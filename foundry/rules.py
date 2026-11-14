"""The checks every variant passes before a person sees it. Pure functions over the stats
dict and the family's settings; each failure carries a `fix` written for the agent who has
to act on it."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class Result:
    rule: str
    ok: bool
    value: object
    limit: object
    fix: str = ""


def check(stats: dict, family: dict) -> list[Result]:
    """`family` comes from the profile: tri_budget, sockets, size_min, size_max, allow_open."""
    out = [
        _tri_budget(stats, family),
        Result("closed", family.get("allow_open", False) or stats["open_edges"] == 0, stats["open_edges"], 0,
               "a part has a hole: a section with fewer than 3 points, or a custom part that doesn't close"),
        Result("manifold", stats["nonmanifold_edges"] == 0, stats["nonmanifold_edges"], 0,
               "an edge is shared by more than two faces: two stations in one sweep at the same place"),
        Result("no_loose_verts", stats["loose_verts"] == 0, stats["loose_verts"], 0,
               "a custom part leaves unused vertices; drop them"),
        Result("no_degenerate", stats["degenerate_tris"] == 0, stats["degenerate_tris"], 0,
               "zero-area faces: two outline or profile points at the same t/height, or a 0 size"),
        Result("normals_out", not stats["inside_out_parts"], stats["inside_out_parts"], [],
               "these parts are inside out: a negative size, or a mirrored custom part"),
        _sockets(stats, family),
    ]
    out.extend(_size(stats, family))
    return out


def _tri_budget(stats: dict, family: dict) -> Result:
    budget = family.get("tri_budget")
    ok = budget is None or stats["tris"] <= budget
    return Result("tri_budget", ok, stats["tris"], budget,
                  "fewer outline/profile points, fewer sides on round parts, or lower 'segments'")


def _sockets(stats: dict, family: dict) -> Result:
    need = sorted(set(family.get("sockets", [])) - set(stats["sockets"]))
    return Result("sockets", not need, stats["sockets"], family.get("sockets", []),
                  f"add to the recipe's 'sockets': {need}" if need else "")


def _size(stats: dict, family: dict) -> list[Result]:
    out = []
    lo, hi = family.get("size_min"), family.get("size_max")
    biggest = max(stats["size"]) if stats["size"] else 0.0
    if lo is not None:
        out.append(Result("size_min", biggest >= lo, biggest, lo, "the asset's longest side is too small for its family"))
    if hi is not None:
        out.append(Result("size_max", biggest <= hi, biggest, hi, "the asset's longest side is too big for its family"))
    return out


def passed(results: list[Result]) -> bool:
    return all(r.ok for r in results)


def as_json(results: list[Result]) -> list[dict]:
    return [{k: v for k, v in asdict(r).items() if not (k == "fix" and r.ok)} for r in results]
