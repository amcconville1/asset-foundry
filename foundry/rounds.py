"""Building rounds and reading their feedback: the agent's side of the round loop (2.1)."""

from __future__ import annotations

import subprocess
from . import build as builder
from .catalog import Catalog, CatalogError, failed_rules, parse_round, read, write
from .profile import Profile


def build_round(cat: Catalog, profile: Profile, name: str, n: int, only: list[str] | None = None) -> list[dict]:
    """Builds the round's variants in parallel; the round is `built` when every one has a report."""
    data = cat.round(name, n)
    if data["status"] not in ("building", "built"):
        raise CatalogError(f"round {n} is {data['status']}; a submitted round doesn't rebuild")
    ids = [v for v in data["variants"] if not only or v in only]
    jobs = [(read(cat.variant_dir(name, v) / "recipe.json"), cat.variant_dir(name, v)) for v in ids]
    reports = builder.build_many(jobs, profile)
    if all((cat.variant_dir(name, v) / "report.json").exists() for v in data["variants"]):
        cat.set_status(name, n, "built")
    return [{"id": v, **r} for v, r in zip(ids, reports)]


def replace_recipe(cat: Catalog, name: str, vid: str, recipe: dict) -> None:
    """A fixed recipe for a variant before submission; its lineage stays."""
    data = cat.round(name, parse_round(vid))
    if data["status"] not in ("building", "built"):
        raise CatalogError(f"{vid}: round is {data['status']}; start a new round instead")
    recipe.pop("lineage", None)
    write(cat.variant_dir(name, vid) / "recipe.json", recipe)


def notify(profile: Profile, event: str, name: str, n: int) -> str | None:
    """Runs the profile's hook for `event` (e.g. hooks.ready = "python notify.py {collection} {round}")."""
    template = profile.hooks.get(event)
    if not template:
        return None
    cmd = template.format(collection=name, round=n, catalog=profile.catalog)
    proc = subprocess.run(cmd, shell=True, cwd=profile.root, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return f"hook {event}: exit {proc.returncode} {proc.stdout.strip()[-300:]} {proc.stderr.strip()[-300:]}".strip()


def feedback(cat: Catalog, name: str, n: int | None = None) -> dict:
    """The last reviewed round (or round n) in the form an agent plans the next round from."""
    col = cat.collection(name)
    rounds = cat.rounds(name)
    if n is None:
        reviewed = [r for r in rounds if cat.round(name, r)["status"] == "reviewed"]
        if not reviewed:
            raise CatalogError(f"{name}: no reviewed round yet (rounds: {rounds})")
        n = reviewed[-1]
    r = cat.round(name, n)
    groups: dict[str, list] = {"use": [], "like": [], "cut": [], "none": []}
    for vid in r["variants"]:
        d = cat.variant_dir(name, vid)
        verdicts = read(d / "verdicts.json", {})
        lineage = read(d / "lineage.json", {})
        entry = {
            "id": vid,
            "recipe": str(d / "recipe.json"),
            "sheet": str(d / "sheet.png"),
            "brief": lineage.get("brief", ""),
            "parents": lineage.get("parents", []),
            "reviews": [{"by": by, **v} for by, v in sorted(verdicts.items())],
        }
        groups[_strongest([v.get("verdict") for v in verdicts.values()])].append(entry)
    return {"collection": name, "family": col["family"], "ask": col["ask"], "round": n,
            "status": r["status"], "round_notes": r.get("notes", {}), **groups}


def _strongest(verdicts: list) -> str:
    """Several reviewers: use beats like beats cut; no verdict at all is 'none'."""
    for v in ("use", "like", "cut"):
        if v in verdicts:
            return v
    return "none"


def feedback_text(fb: dict) -> str:
    lines = [f"{fb['collection']} ({fb['family']}), round {fb['round']} [{fb['status']}]", f"ask: {fb['ask']}"]
    for by, note in fb["round_notes"].items():
        if note.strip():
            lines.append(f"round note ({by}): {note.strip()}")
    titles = {"use": "USE (done: take these to the game)", "like": "LIKED (answer every comment and mark in the next round)",
              "cut": "CUT (don't bring these back; read why)", "none": "NO VERDICT"}
    for key in ("use", "like", "cut", "none"):
        if not fb[key]:
            continue
        lines.append("")
        lines.append(titles[key])
        for e in fb[key]:
            parents = f" from {', '.join(e['parents'])}" if e["parents"] else ""
            lines.append(f"  {e['id']}{parents}: {e['brief']}")
            for rv in e["reviews"]:
                if rv.get("comment"):
                    lines.append(f"    {rv['by']}: \"{rv['comment']}\"")
                for m in rv.get("marks", []):
                    lines.append(f"    {rv['by']} mark {m.get('n', '?')} ({m.get('kind')}, {_where(m)}): \"{m.get('note', '')}\"")
            lines.append(f"    recipe: {e['recipe']}")
    return "\n".join(lines)


def _where(mark: dict) -> str:
    if mark.get("kind") == "area":
        return "parts " + ", ".join(mark.get("parts", []))
    part = mark.get("part", "?")
    at = mark.get("at") or {}
    extra = ", ".join(f"{k} {v:.2f}" if isinstance(v, (int, float)) else f"{k} {v}" for k, v in at.items())
    if mark.get("kind") == "drag" and mark.get("axis"):
        param = f" (changes {mark['param']})" if mark.get("param") else ""
        extra = (extra + "; " if extra else "") + f"arrow {mark.get('metres', 0):+.3f} m along {mark['axis']}{param}"
    return part + (f": {extra}" if extra else "")


def status_text(cat: Catalog, name: str) -> str:
    col = cat.collection(name)
    lines = [f"{name} ({col['family']}, {col['status']}): {col['ask']}"]
    for n in cat.rounds(name):
        r = cat.round(name, n)
        counts = {"use": 0, "like": 0, "cut": 0}
        bad = []
        for vid in r["variants"]:
            d = cat.variant_dir(name, vid)
            for v in read(d / "verdicts.json", {}).values():
                if v.get("verdict") in counts:
                    counts[v["verdict"]] += 1
            rep = read(d / "report.json")
            if rep is not None and not rep.get("ok"):
                bad.append(f"{vid} ({', '.join(failed_rules(rep)) or 'error'})")
        verdicts = ", ".join(f"{k} {c}" for k, c in counts.items() if c)
        lines.append(f"  round {n}: {r['status']}, {len(r['variants'])} variants"
                     + (f"; {verdicts}" if verdicts else "") + (f"; failing: {'; '.join(bad)}" if bad else ""))
    return "\n".join(lines)
