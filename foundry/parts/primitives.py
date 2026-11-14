"""Family-free primitives a recipe can use directly as parts."""

from __future__ import annotations

from .. import geom
from ..geom import Station
from ..vec import Frame, frame_from_z
from . import Axis, Built, Ctx, Param, part

UP = (0.0, 0.0, 1.0)
DOWN = (0.0, 0.0, -1.0)


def ends(height: float) -> dict[str, Frame]:
    """`base` hangs a child below the part, `top` stands one on it."""
    return {
        "base": frame_from_z((0.0, 0.0, 0.0), DOWN),
        "top": Frame(origin=(0.0, 0.0, height)),
        "mid": Frame(origin=(0.0, 0.0, height / 2)),
    }


@part("lathe", "any", "A profile turned round the z axis: pommels, bottles, pots, pillars, rings.",
      [Param("profile", [[0.0, 0.0], [0.05, 0.02], [0.05, 0.08], [0.0, 0.1]],
             "[[radius, height], ...] from the base up; a radius of 0 closes the end to a point", "points"),
       Param("sides", 8, "sides round the axis", "int", 3, 64)],
      {"base": "below the first profile point, facing down", "top": "above the last", "mid": "half height"},
      [Axis("height", "z", None, "base to top")])
def lathe(p: dict, ctx: Ctx) -> Built:
    profile = p["profile"]
    sides = p["sides"]
    stations = [Station(Frame(origin=(0.0, 0.0, h)), geom.circle(max(r, 0.0), sides) if r > 0 else [(0.0, 0.0)] * sides)
                for r, h in profile]
    top = profile[-1][1]
    return Built(geom.sweep(stations, ctx.region), ends(top), {"height": (profile[0][1], top)})


@part("block", "any", "A box from z=0 up, corners optionally chamfered: bricks, slabs, crates, plinths.",
      [Param("size", [0.5, 0.5, 0.5], "[width (x), depth (y), height (z)] metres", "vec", 0.001),
       Param("chamfer", 0.0, "corner cut in metres, round the vertical edges", "float", 0.0),
       Param("taper", 1.0, "top size as a fraction of the bottom", "float", 0.0, 4.0)],
      {"base": "bottom face, facing down", "top": "top face", "mid": "half height"},
      [Axis("height", "z", "size.2", "base to top"), Axis("width", "x", "size.0", "left to right")])
def block(p: dict, ctx: Ctx) -> Built:
    w, d, h = p["size"]
    section = geom.rect(w, d, p["chamfer"])
    top = geom.scaled(section, p["taper"], p["taper"])
    stations = [Station(Frame(origin=(0.0, 0.0, 0.0)), section), Station(Frame(origin=(0.0, 0.0, h)), top)]
    return Built(geom.sweep(stations, ctx.region), ends(h), {"height": (0.0, h), "width": (-w / 2, w / 2)})


SHAPES = {
    "rect": lambda w, d, sides: geom.rect(w, d),
    "lens": lambda w, d, sides: geom.lens(w, d),
    "round": lambda w, d, sides: geom.scaled(geom.circle(1.0, sides), w / 2, d / 2),
}


@part("loft", "any", "Sections stacked up z, each [height, width, depth]; a 0 width closes to a point. "
      "Hafts, posts, tapered columns, horns (straight), crystals.",
      [Param("sections", [[0.0, 0.1, 0.1], [1.0, 0.1, 0.1]], "[[height, width, depth], ...] from the base up", "points"),
       Param("shape", "rect", "section shape: rect | lens | round", "str"),
       Param("sides", 8, "sides for a round shape", "int", 3, 64)],
      {"base": "below the first section, facing down", "top": "above the last", "mid": "half height"},
      [Axis("height", "z", None, "base to top")])
def loft(p: dict, ctx: Ctx) -> Built:
    make = SHAPES.get(p["shape"])
    if make is None:
        raise ValueError(f"loft shape {p['shape']!r}: use one of {sorted(SHAPES)}")
    count = len(make(1.0, 1.0, p["sides"]))
    stations = []
    for h, w, d in p["sections"]:
        sec = make(w, d, p["sides"]) if w > 0 and d > 0 else [(0.0, 0.0)] * count
        stations.append(Station(Frame(origin=(0.0, 0.0, h)), sec))
    first, last = p["sections"][0][0], p["sections"][-1][0]
    return Built(geom.sweep(stations, ctx.region), ends(last), {"height": (first, last)})
