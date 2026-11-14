"""Recipes: load, check every key, and assemble the parts into one mesh plus what the
review and the agents need to name places on it (parts, anchors, spans, sockets).

Errors say what was wrong and what is allowed; nothing unknown is ignored.
"""

from __future__ import annotations

import json
import random
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import parts as registry
from .geom import Mesh
from .vec import IDENTITY, Frame, Vec

TOP_KEYS = {"family", "name", "seed", "parts", "sockets", "origin", "reference", "brief", "note", "lineage"}
REQUIRED_TOP = ("family", "name", "parts")
PLACEMENT_KEYS = {"id", "part", "at", "offset", "turn", "region", "mirror", "note"}


class RecipeError(ValueError):
    """A recipe that cannot build; the message says where and how to fix it."""


@dataclass
class PlacedPart:
    id: str
    part: str
    region: str
    frame: Frame
    faces: range
    spans: dict[str, tuple[float, float]]
    anchors: dict[str, Frame]
    params: dict


@dataclass
class Assembly:
    name: str
    family: str
    mesh: Mesh
    parts: list[PlacedPart] = field(default_factory=list)
    sockets: dict[str, Frame] = field(default_factory=dict)

    def parts_json(self) -> dict:
        """parts.json: where each part is, in the exported model's space."""
        out = []
        for p in self.parts:
            spec = registry.REGISTRY[p.part]
            sub = Mesh(self.mesh.verts, [self.mesh.faces[i] for i in p.faces], [])
            lo, hi = _bounds(sub)
            out.append({
                "id": p.id, "part": p.part, "region": p.region,
                "faces": [p.faces.start, p.faces.stop],
                "bounds": [list(lo), list(hi)],
                "frame": p.frame.as_lists(),
                "anchors": {k: f.as_lists() for k, f in p.anchors.items()},
                "axes": [{"name": a.name, "along": a.along, "param": a.param, "doc": a.doc,
                          "span": list(p.spans.get(a.name, (0.0, 0.0)))} for a in spec.frame],
                "params": p.params,
            })
        return {"name": self.name, "family": self.family, "mesh_hash": self.mesh.hash(),
                "parts": out, "sockets": {k: f.as_lists() for k, f in self.sockets.items()}}


def _bounds(mesh: Mesh) -> tuple[Vec, Vec]:
    used = {i for f in mesh.faces for i in f}
    pts = [mesh.verts[i] for i in used]
    xs, ys, zs = zip(*pts)
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def load(path: str | Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise RecipeError(f"{path}: not valid JSON ({e})") from e


def check(recipe: dict, specs: dict[str, registry.PartSpec] | None = None) -> list[str]:
    """Every problem with a recipe, as fix-it sentences; empty when it can build."""
    specs = specs if specs is not None else registry.load()
    errors: list[str] = []
    if not isinstance(recipe, dict):
        return ["a recipe is a JSON object"]
    for key in sorted(set(recipe) - TOP_KEYS):
        errors.append(f"unknown key {key!r}; allowed: {sorted(TOP_KEYS)}")
    for key in REQUIRED_TOP:
        if key not in recipe:
            errors.append(f"missing {key!r}")
    seen: set[str] = set()
    anchors_by_id: dict[str, set[str]] = {}
    for i, entry in enumerate(recipe.get("parts") or []):
        errors.extend(_check_part(i, entry, specs, seen, anchors_by_id))
    if not recipe.get("parts"):
        errors.append("'parts' needs at least one part")
    for name, ref in (recipe.get("sockets") or {}).items():
        errors.extend(_check_ref(f"socket {name!r}", ref, anchors_by_id))
    if "origin" in recipe and recipe["origin"] not in (recipe.get("sockets") or {}):
        errors.append(f"origin {recipe['origin']!r} is not one of the recipe's sockets {sorted(recipe.get('sockets') or {})}")
    return errors


def _check_part(i: int, entry: Any, specs: dict, seen: set[str], anchors_by_id: dict[str, set[str]]) -> list[str]:
    if not isinstance(entry, dict):
        return [f"parts[{i}] is not an object"]
    pid = entry.get("id", f"#{i}")
    where = f"part {pid!r}"
    errors = []
    if "id" not in entry:
        errors.append(f"parts[{i}] needs an 'id'")
    elif pid in seen:
        errors.append(f"{where}: id used twice")
    seen.add(pid)
    spec = specs.get(entry.get("part"))
    if spec is None:
        errors.append(f"{where}: unknown part {entry.get('part')!r}; known: {sorted(specs)}")
        return errors
    names = {p.name: p for p in spec.params}
    for key in sorted(set(entry) - PLACEMENT_KEYS - set(names)):
        errors.append(f"{where}: unknown key {key!r} for part {spec.name!r}; its parameters: {sorted(names)}")
    for key, param in names.items():
        if key in entry:
            problem = _check_value(param, entry[key])
            if problem:
                errors.append(f"{where}.{key}: {problem}")
    if i == 0 and "at" in entry:
        errors.append(f"{where}: the first part is the root and has no 'at'")
    if i > 0:
        if "at" not in entry:
            errors.append(f"{where}: needs 'at' (another part's anchor, e.g. 'blade.base')")
        else:
            errors.extend(_check_ref(where, entry["at"], anchors_by_id))
    anchors_by_id[pid] = set(spec.anchors)
    return errors


def _check_ref(where: str, ref: Any, anchors_by_id: dict[str, set[str]]) -> list[str]:
    if not isinstance(ref, str) or "." not in ref:
        return [f"{where}: {ref!r} should be 'part_id.anchor'"]
    pid, anchor = ref.split(".", 1)
    if pid not in anchors_by_id:
        return [f"{where}: {ref!r} names part {pid!r}, which is not an earlier part; earlier: {sorted(anchors_by_id)}"]
    if anchor not in anchors_by_id[pid]:
        return [f"{where}: part {pid!r} has no anchor {anchor!r}; its anchors: {sorted(anchors_by_id[pid])}"]
    return []


def _check_value(param: registry.Param, value: Any) -> str | None:
    kind = param.kind
    if kind in ("float", "int"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"expected a number, got {value!r}"
        if kind == "int" and not float(value).is_integer():
            return f"expected a whole number, got {value!r}"
        if param.min is not None and value < param.min:
            return f"{value} is below the minimum {param.min}"
        if param.max is not None and value > param.max:
            return f"{value} is above the maximum {param.max}"
    elif kind == "str":
        if not isinstance(value, str):
            return f"expected text, got {value!r}"
    elif kind == "vec":
        if not (isinstance(value, list) and all(isinstance(v, (int, float)) for v in value)):
            return f"expected a list of numbers, got {value!r}"
        if param.min is not None and any(v < param.min for v in value):
            return f"every value must be at least {param.min}"
    elif kind == "points":
        if not (isinstance(value, list) and value and all(isinstance(r, list) and all(isinstance(v, (int, float)) for v in r) for r in value)):
            return f"expected a list of number lists, e.g. {param.default!r}"
    return None


def assemble(recipe: dict, specs: dict[str, registry.PartSpec] | None = None) -> Assembly:
    specs = specs if specs is not None else registry.load()
    errors = check(recipe, specs)
    if errors:
        raise RecipeError("; ".join(errors))
    seed = int(recipe.get("seed", 0))
    asm = Assembly(recipe["name"], recipe["family"], Mesh())
    placed: dict[str, PlacedPart] = {}
    for entry in recipe["parts"]:
        spec = specs[entry["part"]]
        params = {**spec.defaults(), **{k: v for k, v in entry.items() if k not in PLACEMENT_KEYS}}
        region = entry.get("region", spec.region)
        rng = random.Random(seed * 1_000_003 + zlib.crc32(entry["id"].encode()))
        built = spec.build(params, registry.Ctx(rng, region))
        frame = _place(entry, placed)
        world = built.mesh.transformed(frame)
        if entry.get("mirror"):
            world.extend(world.mirrored_x())
        faces = asm.mesh.extend(world)
        anchors = {k: frame.compose(a) for k, a in built.anchors.items()}
        placed[entry["id"]] = PlacedPart(entry["id"], spec.name, region, frame, faces, built.spans, anchors, params)
        asm.parts.append(placed[entry["id"]])
    for name, ref in (recipe.get("sockets") or {}).items():
        pid, anchor = ref.split(".", 1)
        asm.sockets[name] = placed[pid].anchors[anchor]
    if "origin" in recipe:
        _move_origin(asm, asm.sockets[recipe["origin"]].origin)
    return asm


def _place(entry: dict, placed: dict[str, PlacedPart]) -> Frame:
    if "at" not in entry:
        frame = IDENTITY
    else:
        pid, anchor = entry["at"].split(".", 1)
        frame = placed[pid].anchors[anchor]
    if "turn" in entry:
        frame = frame.turned(float(entry["turn"]))
    if "offset" in entry:
        frame = Frame(frame.point(tuple(entry["offset"])), frame.x, frame.y, frame.z)
    return frame


def _move_origin(asm: Assembly, origin: Vec) -> None:
    shift = Frame(origin=(-origin[0], -origin[1], -origin[2]))
    asm.mesh = asm.mesh.transformed(shift)

    def moved(f: Frame) -> Frame:
        return Frame(shift.point(f.origin), f.x, f.y, f.z)

    for p in asm.parts:
        p.frame = moved(p.frame)
        p.anchors = {k: moved(a) for k, a in p.anchors.items()}
    asm.sockets = {k: moved(s) for k, s in asm.sockets.items()}
