"""The part registry: every builder a recipe can name, with its parameters, defaults,
anchors and parameter frame, all readable without Blender (`foundry parts` prints it).

A builder makes its part in its own frame: the attach point at the origin, +z pointing
away from the part it hangs on. It returns the mesh and named anchor frames; a recipe's
`at` puts another part's origin on one of those anchors.
"""

from __future__ import annotations

import importlib
import random
from dataclasses import dataclass, field
from typing import Any, Callable

from ..geom import Mesh
from ..vec import Frame


@dataclass(frozen=True)
class Param:
    name: str
    default: Any
    doc: str
    kind: str = "float"  # float | int | points | str | vec
    min: float | None = None
    max: float | None = None


@dataclass(frozen=True)
class Axis:
    """One axis of the parameter frame: how a point or a drag on the part maps to a
    parameter. `along` is the part's local axis; `param` is what a drag along it changes.
    The builder reports the axis's real span (start, end) for each build in `Built.spans`."""

    name: str
    along: str  # "x" | "y" | "z"
    param: str | None
    doc: str


@dataclass
class Built:
    mesh: Mesh
    anchors: dict[str, Frame] = field(default_factory=dict)
    spans: dict[str, tuple[float, float]] = field(default_factory=dict)  # axis name -> (start, end)


@dataclass
class Ctx:
    rng: random.Random
    region: str


@dataclass(frozen=True)
class PartSpec:
    name: str
    family: str
    doc: str
    params: tuple[Param, ...]
    anchors: dict[str, str]
    frame: tuple[Axis, ...]
    region: str
    build: Callable[[dict, Ctx], Built]

    def defaults(self) -> dict:
        return {p.name: p.default for p in self.params}

    def describe(self) -> dict:
        return {
            "part": self.name,
            "family": self.family,
            "doc": self.doc,
            "region": self.region,
            "params": [
                {"name": p.name, "default": p.default, "kind": p.kind, "min": p.min, "max": p.max, "doc": p.doc}
                for p in self.params
            ],
            "anchors": self.anchors,
            "frame": [a.__dict__ for a in self.frame],
        }


REGISTRY: dict[str, PartSpec] = {}


def part(name: str, family: str, doc: str, params: list[Param], anchors: dict[str, str],
         frame: list[Axis] | None = None, region: str = "base"):
    """Registers a builder. `anchors` maps each anchor name to what it is for."""

    def register(fn: Callable[[dict, Ctx], Built]) -> Callable[[dict, Ctx], Built]:
        if name in REGISTRY:
            raise ValueError(f"part {name!r} is registered twice")
        REGISTRY[name] = PartSpec(name, family, doc, tuple(params), dict(anchors), tuple(frame or ()), region, fn)
        return fn

    return register


_LOADED: set[str] = set()


def load(modules: list[str] | tuple[str, ...] = ()) -> dict[str, PartSpec]:
    """Imports the foundry's own builders plus any a profile names (module paths)."""
    for module in ("foundry.parts.primitives", "foundry.parts.weapon", *modules):
        if module not in _LOADED:
            importlib.import_module(module)
            _LOADED.add(module)
    return REGISTRY
