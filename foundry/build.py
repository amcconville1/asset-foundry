"""One variant: recipe in; model, parts map, report and sheet out (contract 2.4)."""

from __future__ import annotations

import json
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import blender_run, geom, parts as registry, recipe as rec, rules, sheet, stats
from .profile import Profile

VIEWS = [
    {"name": "front", "dir": [0, -1, 0], "kind": "shaded"},
    {"name": "side", "dir": [-1, 0, 0], "kind": "shaded"},
    {"name": "back", "dir": [0, 1, 0], "kind": "shaded"},
    {"name": "three_quarter", "dir": [-0.55, -0.75, -0.35], "kind": "shaded"},
    {"name": "top", "dir": [0, 0, -1], "kind": "shaded"},
    {"name": "wire", "dir": [-0.55, -0.75, -0.35], "kind": "wire"},
    {"name": "scale", "dir": [0, -1, 0], "kind": "scale"},
    {"name": "silhouette", "dir": [0, -1, 0], "kind": "silhouette"},
]
RENDER_SIZE = 512


def build(recipe: dict, out_dir: Path, profile: Profile, render: bool = True, blender: str | None = None) -> dict:
    """Builds one variant into `out_dir` and returns its report (also written as report.json)."""
    started = time.monotonic()
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "recipe.json").write_text(json.dumps(recipe, indent=2), encoding="utf-8")
    specs = registry.load(profile.parts)
    report: dict = {"name": recipe.get("name"), "family": recipe.get("family"), "ok": False}
    errors = rec.check(recipe, specs)
    if errors:
        report["errors"] = errors
        return _finish(report, out_dir, started)
    try:
        asm = rec.assemble(recipe, specs)
    except (ValueError, KeyError, IndexError, ZeroDivisionError) as e:
        report["errors"] = [f"a builder failed: {e}"]
        return _finish(report, out_dir, started)
    family = profile.family(asm.family)
    st = stats.mesh_stats(asm)
    results = rules.check(st, family)
    report.update(stats=st, rules=rules.as_json(results), mesh_hash=st["mesh_hash"])
    (out_dir / "parts.json").write_text(json.dumps(asm.parts_json(), indent=1), encoding="utf-8")
    if render:
        _blender(asm, out_dir, profile, family, report, blender)
        if report.get("blender_ok"):
            sheet.compose(out_dir, report, family, profile.views)
            report["sheet"] = "sheet.png"
    report["ok"] = rules.passed(results) and (not render or report.get("blender_ok", False))
    return _finish(report, out_dir, started)


def _blender(asm, out_dir: Path, profile: Profile, family: dict, report: dict, blender: str | None) -> None:
    work = out_dir / "_work"
    work.mkdir(exist_ok=True)
    mesh = asm.mesh
    data = {"name": asm.name, "verts": mesh.verts, "faces": mesh.faces, "regions": mesh.regions,
            "uvs": geom.box_uvs(mesh), "parts": [{"id": p.id, "faces": [p.faces.start, p.faces.stop]} for p in asm.parts],
            "sockets": {k: f.as_lists() for k, f in asm.sockets.items()}}
    (work / "mesh.json").write_text(json.dumps(data), encoding="utf-8")
    job = {"mesh": str(work / "mesh.json"), "out_dir": str(out_dir), "views": VIEWS, "size": RENDER_SIZE,
           "extent": family.get("extent"), "region_tints": family["region_tints"],
           "reference": str(profile.reference) if profile.reference else None,
           "reference_offset": family["reference_offset"]}
    (work / "job.json").write_text(json.dumps(job), encoding="utf-8")
    exe = blender or blender_run.find(profile.blender)
    proc = blender_run.run_job(exe, work / "job.json")
    result_path = out_dir / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else {"ok": False}
    report["blender_ok"] = bool(result.get("ok"))
    report["uv"] = result.get("uv_layers", 0) > 0
    report["files"] = result.get("files", [])
    if not result.get("ok"):
        report.setdefault("errors", []).append("blender: " + (result.get("error") or proc.stdout[-2000:]))
    result_path.unlink(missing_ok=True)
    shutil.rmtree(work, ignore_errors=True)


def _finish(report: dict, out_dir: Path, started: float) -> dict:
    report["seconds"] = round(time.monotonic() - started, 2)
    (out_dir / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    return report


def build_many(jobs: list[tuple[dict, Path]], profile: Profile, render: bool = True) -> list[dict]:
    """Builds variants in parallel, `profile.parallel` Blender processes at a time."""
    exe = blender_run.find(profile.blender) if render else None
    with ThreadPoolExecutor(max_workers=max(1, profile.parallel)) as pool:
        return list(pool.map(lambda j: build(j[0], j[1], profile, render, exe), jobs))
