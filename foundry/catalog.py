"""The catalog (contract 2.6): collections of rounds of variants, as plain files.

    <root>/<collection>/collection.json     the ask, family, status
    <root>/<collection>/round-<n>/round.json brief, status, variant ids, round notes
    <root>/<collection>/round-<n>/<id>/      the variant's build outputs (build.py) plus
        lineage.json   parents and the notes this variant answers
        verdicts.json  {reviewer: {verdict, comment, marks, at}}

Statuses: a round is `building` -> `built` (every variant built) -> `ready` (submitted
for review; every variant passed) -> `reviewed`. A collection is `open` or `done`.
"""

from __future__ import annotations

import json
import re
import string
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import marks as mk

VERDICTS = ("like", "cut", "use")
NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class CatalogError(ValueError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def write(path: Path, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    tmp.replace(path)  # a reader never sees half a file


def letters(i: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    out = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        out = string.ascii_uppercase[r] + out
    return out


@dataclass
class Catalog:
    root: Path

    # --- collections ---------------------------------------------------------

    def collection_dir(self, name: str) -> Path:
        if not NAME.match(name):
            raise CatalogError(f"collection name {name!r}: lowercase letters, digits, - and _ only")
        return self.root / name

    def create(self, name: str, family: str, ask: str) -> dict:
        d = self.collection_dir(name)
        if (d / "collection.json").exists():
            raise CatalogError(f"collection {name!r} already exists")
        data = {"name": name, "family": family, "ask": ask, "status": "open", "created": now()}
        write(d / "collection.json", data)
        return data

    def collection(self, name: str) -> dict:
        data = read(self.collection_dir(name) / "collection.json")
        if data is None:
            raise CatalogError(f"no collection {name!r}; have: {self.names()}")
        return data

    def names(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(p.name for p in self.root.iterdir() if (p / "collection.json").exists())

    # --- rounds --------------------------------------------------------------

    def round_dir(self, name: str, n: int) -> Path:
        return self.collection_dir(name) / f"round-{n}"

    def rounds(self, name: str) -> list[int]:
        d = self.collection_dir(name)
        nums = [int(p.name.split("-")[1]) for p in d.glob("round-*") if p.name.split("-")[1].isdigit()]
        return sorted(nums)

    def round(self, name: str, n: int) -> dict:
        data = read(self.round_dir(name, n) / "round.json")
        if data is None:
            raise CatalogError(f"{name}: no round {n}; rounds: {self.rounds(name)}")
        return data

    def save_round(self, name: str, data: dict) -> None:
        write(self.round_dir(name, data["n"]) / "round.json", data)

    def new_round(self, name: str, brief: str, recipes: list[dict]) -> dict:
        """Opens the next round with one variant per recipe. The previous round must be
        reviewed first, so every round answers feedback."""
        self.collection(name)
        existing = self.rounds(name)
        if existing:
            last = self.round(name, existing[-1])
            if last["status"] != "reviewed":
                raise CatalogError(f"{name}: round {last['n']} is {last['status']}, not reviewed; "
                                   "a new round answers the last one's feedback")
        n = (existing[-1] if existing else 0) + 1
        ids = []
        for i, recipe in enumerate(recipes):
            vid = f"r{n}-{letters(i)}"
            vdir = self.round_dir(name, n) / vid
            lineage = recipe.pop("lineage", {}) or {}
            write(vdir / "recipe.json", recipe)
            write(vdir / "lineage.json", {"brief": recipe.get("brief", ""), "parents": lineage.get("parents", []),
                                          "answers": lineage.get("answers", [])})
            ids.append(vid)
        data = {"n": n, "brief": brief, "status": "building", "variants": ids, "notes": {}, "created": now()}
        self.save_round(name, data)
        return data

    def variant_dir(self, name: str, vid: str) -> Path:
        n = parse_round(vid)
        return self.round_dir(name, n) / vid

    def set_status(self, name: str, n: int, status: str) -> dict:
        data = self.round(name, n)
        data["status"] = status
        data[f"{status}_at"] = now()
        self.save_round(name, data)
        return data

    def submit(self, name: str, n: int) -> dict:
        """Marks a round ready for review; refuses unless every variant passed and has a sheet."""
        data = self.round(name, n)
        problems = []
        for vid in data["variants"]:
            report = read(self.variant_dir(name, vid) / "report.json")
            if report is None:
                problems.append(f"{vid}: not built")
            elif not report.get("ok"):
                problems.append(f"{vid}: failed ({', '.join(failed_rules(report)) or 'errors'})")
            elif not (self.variant_dir(name, vid) / "sheet.png").exists():
                problems.append(f"{vid}: no sheet")
        if problems:
            raise CatalogError("round not ready: " + "; ".join(problems))
        return self.set_status(name, n, "ready")

    def drop(self, name: str, vid: str) -> dict:
        """Removes a variant from its round's list (its files stay, for the record)."""
        n = parse_round(vid)
        data = self.round(name, n)
        if data["status"] not in ("building", "built"):
            raise CatalogError(f"{vid}: round {n} is {data['status']}; only an unsubmitted round can drop variants")
        data["variants"] = [v for v in data["variants"] if v != vid]
        data.setdefault("dropped", []).append(vid)
        self.save_round(name, data)
        return data

    # --- review --------------------------------------------------------------

    def set_verdict(self, name: str, vid: str, by: str, verdict: str | None, comment: str = "",
                    marks: list | None = None) -> dict:
        if verdict not in (*VERDICTS, None):
            raise CatalogError(f"verdict {verdict!r}: use one of {VERDICTS} or none")
        if not by.strip():
            raise CatalogError("a verdict needs a reviewer name")
        path = self.variant_dir(name, vid) / "verdicts.json"
        if not path.parent.exists():
            raise CatalogError(f"no variant {vid} in {name}")
        placed = mk.resolve_all(marks or [], read(path.parent / "parts.json"))
        all_ = read(path, {})
        all_[by] = {"verdict": verdict, "comment": comment, "marks": placed, "at": now()}
        write(path, all_)
        return all_[by]

    def set_round_note(self, name: str, n: int, by: str, note: str) -> dict:
        data = self.round(name, n)
        data.setdefault("notes", {})[by] = note
        self.save_round(name, data)
        return data

    def mark_reviewed(self, name: str, n: int) -> dict:
        data = self.round(name, n)
        if data["status"] not in ("ready", "reviewed"):
            raise CatalogError(f"round {n} is {data['status']}; only a submitted round can be reviewed")
        return self.set_status(name, n, "reviewed")

    def view(self, name: str) -> dict:
        """Everything the review page shows for one collection."""
        col = self.collection(name)
        rounds = []
        for n in self.rounds(name):
            r = self.round(name, n)
            variants = []
            for vid in r["variants"]:
                d = self.variant_dir(name, vid)
                report = read(d / "report.json", {})
                variants.append({
                    "id": vid,
                    "lineage": read(d / "lineage.json", {}),
                    "verdicts": read(d / "verdicts.json", {}),
                    "ok": report.get("ok", False),
                    "stats": report.get("stats", {}),
                    "failed": failed_rules(report),
                    "files": {f: (d / f).exists() for f in ("sheet.png", "model.glb", "parts.glb", "parts.json")},
                })
            rounds.append({**r, "variants": variants})
        return {**col, "rounds": rounds}


def parse_round(vid: str) -> int:
    m = re.match(r"^r(\d+)-[A-Z]+$", vid)
    if not m:
        raise CatalogError(f"variant id {vid!r} should look like r2-C")
    return int(m.group(1))


def failed_rules(report: dict) -> list[str]:
    return [r["rule"] for r in report.get("rules", []) if not r.get("ok")]
