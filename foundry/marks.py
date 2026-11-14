"""Marks (contract 2.5): turning a click, an arrow or a lasso on the model into part terms.

The review page sends points in the exported model's glTF space (Y up). This module turns
them into what a recipe can act on: which part, where along each of its parameter axes
(0 at the axis's start, 1 at its end), and for an arrow, which axis it runs along and how
many metres, signed so + means toward the axis's end.

    pin   {"kind": "pin",  "n", "part", "point": [x, y, z], "note"}
    drag  {"kind": "drag", "n", "part", "from": [x, y, z], "to": [x, y, z], "note"}
    area  {"kind": "area", "n", "parts": [...], "note"}
"""

from __future__ import annotations

from . import vec

KINDS = ("pin", "drag", "area")


class MarkError(ValueError):
    pass


def from_gltf(p) -> vec.Vec:
    """glTF (x right, y up, z back) to foundry space (x right, y forward, z up)."""
    return (float(p[0]), -float(p[2]), float(p[1]))


def _part(parts_json: dict, pid: str) -> dict:
    for part in parts_json.get("parts", []):
        if part["id"] == pid:
            return part
    raise MarkError(f"no part {pid!r}; parts: {[p['id'] for p in parts_json.get('parts', [])]}")


def _axis_vector(part: dict, along: str) -> vec.Vec:
    return tuple(part["frame"][along])


def _local(part: dict, p: vec.Vec) -> dict[str, float]:
    d = vec.sub(p, tuple(part["frame"]["origin"]))
    return {k: vec.dot(d, tuple(part["frame"][k])) for k in ("x", "y", "z")}


def place(part: dict, p: vec.Vec) -> dict[str, float]:
    """Where a point sits along each of the part's axes, 0 at the start and 1 at the end."""
    loc = _local(part, p)
    out = {}
    for axis in part.get("axes", []):
        start, end = axis["span"]
        if abs(end - start) > 1e-9:
            out[axis["name"]] = round((loc[axis["along"]] - start) / (end - start), 3)
    return out


def drag(part: dict, a: vec.Vec, b: vec.Vec) -> dict:
    """The axis an arrow runs along most, and how far along it, in metres."""
    delta = vec.sub(b, a)
    best = None
    for axis in part.get("axes", []):
        start, end = axis["span"]
        direction = 1.0 if end >= start else -1.0
        metres = vec.dot(delta, _axis_vector(part, axis["along"])) * direction
        if best is None or abs(metres) > abs(best["metres"]):
            best = {"axis": axis["name"], "param": axis.get("param"), "metres": round(metres, 4)}
    sideways = vec.length(delta) - abs(best["metres"]) if best else vec.length(delta)
    return {**(best or {"axis": None, "param": None, "metres": 0.0}), "length": round(vec.length(delta), 4),
            "off_axis": round(max(sideways, 0.0), 4)}


def resolve(mark: dict, parts_json: dict) -> dict:
    """The mark with its part terms added; the raw points are kept so the page can redraw it."""
    kind = mark.get("kind")
    if kind not in KINDS:
        raise MarkError(f"mark kind {kind!r}: use one of {KINDS}")
    out = dict(mark)
    if kind == "area":
        known = {p["id"] for p in parts_json.get("parts", [])}
        out["parts"] = [p for p in mark.get("parts", []) if p in known]
        return out
    part = _part(parts_json, mark.get("part"))
    if kind == "pin":
        out["at"] = place(part, from_gltf(mark["point"]))
        return out
    a, b = from_gltf(mark["from"]), from_gltf(mark["to"])
    out["at"] = place(part, a)
    out["to_at"] = place(part, b)
    out.update(drag(part, a, b))
    return out


def resolve_all(marks: list, parts_json: dict | None) -> list:
    if not marks:
        return []
    if parts_json is None:
        raise MarkError("this variant has no parts.json, so marks can't be placed on its parts")
    return [resolve(m, parts_json) for m in marks]
