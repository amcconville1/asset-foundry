"""Builders for held weapons. Blades run up +z from the guard; guards and grips hang
below them (each part's +z points away from the part it attaches to)."""

from __future__ import annotations

from .. import geom
from ..geom import Station
from ..vec import Frame, frame_from_z, norm
from . import Axis, Built, Ctx, Param, part
from .primitives import DOWN

SECTIONS = ("diamond", "hexagonal", "flat")


def blade_section(kind: str, w: float, d: float, flat: float) -> list[tuple[float, float]]:
    """A blade's cross-section, edges at +-x. `flat` is the ridge's share of the width."""
    if kind == "diamond":
        return geom.lens(w, d)
    if kind == "hexagonal":
        f = max(min(flat, 0.95), 0.05) * w / 2
        return [(w / 2, 0.0), (f, d / 2), (-f, d / 2), (-w / 2, 0.0), (-f, -d / 2), (f, -d / 2)]
    if kind == "flat":
        return geom.rect(w, d)
    raise ValueError(f"blade section {kind!r}: use one of {list(SECTIONS)}")


@part("blade", "weapon", "A blade from its base (at the guard) up to the tip, shaped by an outline.",
      [Param("length", 1.0, "base to tip, metres", "float", 0.01),
       Param("width", 0.08, "edge to edge at the base, metres", "float", 0.001),
       Param("thickness", 0.02, "ridge to ridge at the base, metres", "float", 0.001),
       Param("outline", [[0.0, 1.0], [0.8, 0.9], [1.0, 0.0]],
             "[[t, width factor], ...], t from base (0) to tip (1); a last factor of 0 is a point", "points"),
       Param("taper", 0.5, "thickness at the tip as a fraction of the base", "float", 0.0, 2.0),
       Param("section", "diamond", "cross-section: diamond | hexagonal | flat", "str"),
       Param("flat", 0.4, "hexagonal only: the flat ridge's share of the width", "float", 0.05, 0.95),
       Param("curve", 0.0, "sideways bow of the tip (+x), metres; a sabre's sweep", "float")],
      {"base": "the blade's root, facing down (a guard hangs here)", "tip": "the point, facing up"},
      [Axis("to_tip", "z", "length", "base (0) to tip (1)"), Axis("across", "x", "width", "edge to edge")],
      region="metal")
def blade(p: dict, ctx: Ctx) -> Built:
    length, outline = p["length"], p["outline"]
    ts = sorted({float(t) for t, _ in outline})
    count = len(blade_section(p["section"], 1.0, 1.0, p["flat"]))
    stations = []
    for t in ts:
        w = p["width"] * geom.curve_at(outline, t)
        d = p["thickness"] * (1.0 + (p["taper"] - 1.0) * t)
        x = p["curve"] * t * t
        sec = blade_section(p["section"], w, d, p["flat"]) if w > 1e-6 and d > 1e-6 else [(0.0, 0.0)] * count
        stations.append(Station(Frame(origin=(x, 0.0, t * length)), sec))
    tip_dir = norm((2 * p["curve"], 0.0, length)) if p["curve"] else (0.0, 0.0, 1.0)
    anchors = {
        "base": frame_from_z((0.0, 0.0, 0.0), DOWN),
        "tip": frame_from_z((p["curve"], 0.0, length), tip_dir),
    }
    return Built(geom.sweep(stations, ctx.region), anchors,
                 {"to_tip": (0.0, length), "across": (-p["width"] / 2, p["width"] / 2)})


@part("guard", "weapon", "A crossguard across x; its blade side at z=0, the grip side at z=depth.",
      [Param("span", 0.3, "tip to tip, metres", "float", 0.01),
       Param("depth", 0.04, "along the blade axis, metres", "float", 0.005),
       Param("thickness", 0.05, "front to back (y), metres", "float", 0.005),
       Param("curve", 0.0, "how far the tips bend toward the blade, metres (negative: toward the grip)", "float"),
       Param("taper", 1.0, "tip size as a fraction of the middle", "float", 0.0, 3.0),
       Param("segments", 6, "stations tip to tip", "int", 2, 32)],
      {"front": "the blade side, facing up", "back": "the grip side, facing down (a grip hangs here)",
       "tip_l": "the left tip, facing out", "tip_r": "the right tip, facing out"},
      [Axis("along_span", "x", "span", "left tip (0) to right tip (1)")],
      region="trim")
def guard(p: dict, ctx: Ctx) -> Built:
    span, depth, n = p["span"], p["depth"], p["segments"]
    stations = []
    for i in range(n + 1):
        u = i / n
        x = (u - 0.5) * span
        k = 2 * x / span
        z = depth / 2 - p["curve"] * k * k
        dz = -p["curve"] * 8 * x / (span * span)
        s = 1.0 + (p["taper"] - 1.0) * abs(2 * u - 1)
        sec = geom.rect(depth * s, p["thickness"] * s) if s > 1e-6 else [(0.0, 0.0)] * 4
        stations.append(Station(frame_from_z((x, 0.0, z), (1.0, 0.0, dz), (0.0, 0.0, 1.0)), sec))
    end_z = depth / 2 - p["curve"]
    anchors = {
        "front": Frame(origin=(0.0, 0.0, 0.0), z=(0.0, 0.0, -1.0), x=(1.0, 0.0, 0.0), y=(0.0, -1.0, 0.0)),
        "back": Frame(origin=(0.0, 0.0, depth)),
        "tip_l": frame_from_z((-span / 2, 0.0, end_z), (-1.0, 0.0, 0.0)),
        "tip_r": frame_from_z((span / 2, 0.0, end_z), (1.0, 0.0, 0.0)),
    }
    return Built(geom.sweep(stations, ctx.region), anchors, {"along_span": (-span / 2, span / 2)})


@part("grip", "weapon", "A round grip from z=0 (the guard) to z=length (the pommel end).",
      [Param("length", 0.15, "metres", "float", 0.01),
       Param("radius", 0.016, "at the guard end, metres", "float", 0.003),
       Param("flare", 1.0, "radius at the pommel end as a fraction of the guard end", "float", 0.1, 3.0),
       Param("waist", 1.0, "radius at the middle as a fraction (below 1 pinches it)", "float", 0.1, 3.0),
       Param("sides", 8, "sides round the axis", "int", 3, 32)],
      {"end": "the pommel end, facing down the grip (a pommel hangs here)", "mid": "half way"},
      [Axis("along", "z", "length", "guard end (0) to pommel end (1)")],
      region="wrap")
def grip(p: dict, ctx: Ctx) -> Built:
    r, n = p["radius"], p["sides"]
    rows = [(0.0, 1.0), (0.5, p["waist"]), (1.0, p["flare"])]
    stations = [Station(Frame(origin=(0.0, 0.0, t * p["length"])), geom.circle(r * k, n)) for t, k in rows]
    anchors = {"end": Frame(origin=(0.0, 0.0, p["length"])), "mid": Frame(origin=(0.0, 0.0, p["length"] / 2))}
    return Built(geom.sweep(stations, ctx.region), anchors, {"along": (0.0, p["length"])})
