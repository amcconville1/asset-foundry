"""`foundry` command line. Every command prints a short summary and the paths to look at."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import blender_run, build as builder, parts as registry, profile as prof, recipe as rec, rounds
from .catalog import Catalog, CatalogError, parse_round


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="foundry", description="Recipe-built 3D assets in variant rounds.")
    ap.add_argument("--profile", default=os.environ.get("FOUNDRY_PROFILE"), help="profile .toml (or $FOUNDRY_PROFILE)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="build one recipe: model, parts map, report, sheet")
    b.add_argument("recipe")
    b.add_argument("--out", help="output folder (default: <catalog>/scratch/<name>)")
    b.add_argument("--no-render", action="store_true", help="numbers only, no Blender")

    c = sub.add_parser("check", help="check recipes without building")
    c.add_argument("recipes", nargs="+")

    p = sub.add_parser("parts", help="every builder, its parameters, anchors and axes")
    p.add_argument("name", nargs="?")
    p.add_argument("--json", action="store_true")

    sub.add_parser("doctor", help="Blender, profile and parts found")

    n = sub.add_parser("new", help="start a collection: one asset you want, in rounds")
    n.add_argument("collection")
    n.add_argument("--family", required=True)
    n.add_argument("--ask", required=True, help="what was asked for, in the person's words")

    r = sub.add_parser("round", help="open, build, fix, drop or submit a round")
    rs = r.add_subparsers(dest="action", required=True)
    rn = rs.add_parser("new", help="open the next round from recipe files, then build it")
    rn.add_argument("collection")
    rn.add_argument("recipes", nargs="+", help="one recipe per variant; each may carry brief and lineage")
    rn.add_argument("--brief", required=True, help="what this round tries, in one or two lines")
    rn.add_argument("--no-build", action="store_true")
    rb = rs.add_parser("build", help="(re)build a round's variants in parallel")
    rb.add_argument("collection")
    rb.add_argument("--round", type=int)
    rb.add_argument("--only", nargs="+", help="variant ids")
    rf = rs.add_parser("fix", help="replace one variant's recipe and rebuild it")
    rf.add_argument("collection")
    rf.add_argument("variant")
    rf.add_argument("recipe")
    rd = rs.add_parser("drop", help="take a variant out of an unsubmitted round")
    rd.add_argument("collection")
    rd.add_argument("variant")
    rsub = rs.add_parser("submit", help="send a round for review (every variant must pass)")
    rsub.add_argument("collection")
    rsub.add_argument("--round", type=int)

    s = sub.add_parser("status", help="collections and their rounds")
    s.add_argument("collection", nargs="?")

    f = sub.add_parser("feedback", help="the last reviewed round, ready to plan the next from")
    f.add_argument("collection")
    f.add_argument("--round", type=int)
    f.add_argument("--json", action="store_true")

    v = sub.add_parser("review", help="open the review page")
    v.add_argument("--port", type=int, default=8765)
    v.add_argument("--as", dest="reviewer", default=os.environ.get("FOUNDRY_REVIEWER", ""))
    v.add_argument("--no-open", action="store_true")

    args = ap.parse_args(argv)
    profile = prof.load(args.profile)
    commands = {"build": cmd_build, "check": cmd_check, "parts": cmd_parts, "doctor": cmd_doctor, "new": cmd_new,
                "round": cmd_round, "status": cmd_status, "feedback": cmd_feedback, "review": cmd_review}
    try:
        return commands[args.cmd](args, profile)
    except CatalogError as e:
        print(f"error: {e}")
        return 1


def cmd_build(args, profile) -> int:
    recipe = rec.load(args.recipe)
    out = Path(args.out) if args.out else profile.catalog / "scratch" / str(recipe.get("name", Path(args.recipe).stem))
    report = builder.build(recipe, out, profile, render=not args.no_render)
    print(summary(report, out))
    return 0 if report["ok"] else 1


def summary(report: dict, out: Path) -> str:
    lines = []
    st = report.get("stats")
    head = "PASS" if report["ok"] else "FAIL"
    if st:
        lines.append(f"{head} {report['name']}: {st['tris']} tris, {' x '.join(f'{v:.2f}' for v in st['size'])} m, "
                     f"{report['seconds']} s, hash {st['mesh_hash']}")
    else:
        lines.append(f"{head} {report.get('name')}")
    for r in report.get("rules", []):
        if not r["ok"]:
            lines.append(f"  rule {r['rule']}: {r['value']} (limit {r['limit']}) -> {r.get('fix', '')}")
    for e in report.get("errors", []):
        lines.append(f"  error: {e}")
    lines.append(f"  out: {out}")
    if report.get("sheet"):
        lines.append(f"  look: {out / report['sheet']}")
    return "\n".join(lines)


def cmd_check(args, profile) -> int:
    specs = registry.load(profile.parts)
    bad = 0
    for path in args.recipes:
        errors = rec.check(rec.load(path), specs)
        print(f"{'ok  ' if not errors else 'FAIL'} {path}")
        for e in errors:
            print(f"  {e}")
        bad += bool(errors)
    return 1 if bad else 0


def cmd_parts(args, profile) -> int:
    specs = registry.load(profile.parts)
    chosen = [specs[args.name]] if args.name else [specs[k] for k in sorted(specs)]
    if args.json:
        print(json.dumps([s.describe() for s in chosen], indent=1))
        return 0
    for s in chosen:
        print(f"{s.name} ({s.family}, region {s.region}): {s.doc}")
        for p in s.params:
            rng = "" if p.min is None and p.max is None else f" [{p.min if p.min is not None else ''}..{p.max if p.max is not None else ''}]"
            print(f"    {p.name} = {json.dumps(p.default)}{rng}  {p.doc}")
        print("    anchors: " + "; ".join(f"{k}: {v}" for k, v in s.anchors.items()))
        if s.frame:
            print("    axes: " + "; ".join(f"{a.name} along {a.along} -> {a.param}" for a in s.frame))
    return 0


def cmd_doctor(args, profile) -> int:
    print(f"profile: {profile.path or '(none: defaults)'}")
    print(f"catalog: {profile.catalog}")
    try:
        exe = blender_run.find(profile.blender)
        print(f"blender: {exe} ({blender_run.version(exe)})")
    except blender_run.BlenderMissing as e:
        print(f"blender: MISSING - {e}")
        return 1
    specs = registry.load(profile.parts)
    print(f"parts: {len(specs)} ({', '.join(sorted(specs))})")
    print(f"families: {', '.join(sorted(profile.families)) or '(none)'}")
    return 0


def cmd_new(args, profile) -> int:
    Catalog(profile.catalog).create(args.collection, args.family, args.ask)
    fam = profile.family(args.family)
    print(f"collection {args.collection} ({args.family}): first round {fam['round_first']} variants, "
          f"later rounds {fam['round_next']} (profile sizes; any number is fine)")
    print(f"  folder: {profile.catalog / args.collection}")
    return 0


def _round_n(cat: Catalog, name: str, n: int | None) -> int:
    nums = cat.rounds(name)
    if not nums:
        raise CatalogError(f"{name} has no rounds yet")
    return n if n is not None else nums[-1]


def cmd_round(args, profile) -> int:
    cat = Catalog(profile.catalog)
    if args.action == "new":
        recipes = []
        specs = registry.load(profile.parts)
        for path in args.recipes:
            r = rec.load(path)
            lineage = r.get("lineage")
            errors = rec.check(r, specs)
            if errors:
                print(f"FAIL {path}")
                for e in errors:
                    print(f"  {e}")
                return 1
            r["lineage"] = lineage or {}
            recipes.append(r)
        data = cat.new_round(args.collection, args.brief, recipes)
        print(f"{args.collection} round {data['n']}: {', '.join(data['variants'])}")
        if args.no_build:
            return 0
        return _build(cat, profile, args.collection, data["n"], None)
    if args.action == "build":
        return _build(cat, profile, args.collection, _round_n(cat, args.collection, args.round), args.only)
    if args.action == "fix":
        rounds.replace_recipe(cat, args.collection, args.variant, rec.load(args.recipe))
        return _build(cat, profile, args.collection, parse_round(args.variant), [args.variant])
    if args.action == "drop":
        data = cat.drop(args.collection, args.variant)
        print(f"dropped {args.variant}; round {data['n']}: {', '.join(data['variants'])}")
        return 0
    n = _round_n(cat, args.collection, args.round)
    cat.submit(args.collection, n)
    print(f"{args.collection} round {n} is ready for review: foundry review")
    hook = rounds.notify(profile, "ready", args.collection, n)
    if hook:
        print(f"  {hook}")
    return 0


def _build(cat: Catalog, profile, name: str, n: int, only) -> int:
    reports = rounds.build_round(cat, profile, name, n, only)
    for r in reports:
        st = r.get("stats") or {}
        failed = [x["rule"] for x in r.get("rules", []) if not x["ok"]]
        print(f"  {'PASS' if r['ok'] else 'FAIL'} {r['id']}: {st.get('tris', '?')} tris"
              + (f"; failed {', '.join(failed)}" if failed else "")
              + ("".join(f"; {e[:200]}" for e in r.get("errors", []))))
    print(f"  sheets: {cat.round_dir(name, n) / '<id>' / 'sheet.png'}  (read every one before submitting)")
    return 0 if all(r["ok"] for r in reports) else 1


def cmd_status(args, profile) -> int:
    cat = Catalog(profile.catalog)
    names = [args.collection] if args.collection else cat.names()
    if not names:
        print(f"no collections in {profile.catalog}")
    for name in names:
        print(rounds.status_text(cat, name))
    return 0


def cmd_feedback(args, profile) -> int:
    fb = rounds.feedback(Catalog(profile.catalog), args.collection, args.round)
    print(json.dumps(fb, indent=1) if args.json else rounds.feedback_text(fb))
    return 0


def cmd_review(args, profile) -> int:
    import webbrowser

    from .review.server import serve

    server = serve(Catalog(profile.catalog), profile, args.port, args.reviewer)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"review page: {url}  (Ctrl+C to stop)")
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
