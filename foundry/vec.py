"""Small vector and frame maths, plain Python so shapes build and test without Blender.

Axes everywhere in the foundry: x = right, y = forward, z = up (metres). In Blender that is
the same x, y, z; a glTF export turns it into a Y-up engine's right, up and forward (-Z).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

Vec = tuple[float, float, float]


def add(a: Vec, b: Vec) -> Vec:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def scale(a: Vec, s: float) -> Vec:
    return (a[0] * s, a[1] * s, a[2] * s)


def dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def length(a: Vec) -> float:
    return math.sqrt(dot(a, a))


def norm(a: Vec) -> Vec:
    n = length(a)
    if n < 1e-12:
        raise ValueError("cannot normalise a zero vector")
    return scale(a, 1.0 / n)


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


@dataclass(frozen=True)
class Frame:
    """An origin and three unit axes. A part is built in its own frame, with its attach
    point at the origin and +z pointing away from whatever it attaches to."""

    origin: Vec = (0.0, 0.0, 0.0)
    x: Vec = (1.0, 0.0, 0.0)
    y: Vec = (0.0, 1.0, 0.0)
    z: Vec = (0.0, 0.0, 1.0)

    def point(self, local: Vec) -> Vec:
        """A point given in this frame, in the parent's space."""
        return add(self.origin, add(scale(self.x, local[0]), add(scale(self.y, local[1]), scale(self.z, local[2]))))

    def direction(self, local: Vec) -> Vec:
        return add(scale(self.x, local[0]), add(scale(self.y, local[1]), scale(self.z, local[2])))

    def compose(self, child: "Frame") -> "Frame":
        """`child` is given in this frame; returns it in this frame's parent space."""
        return Frame(self.point(child.origin), self.direction(child.x), self.direction(child.y), self.direction(child.z))

    def turned(self, degrees: float) -> "Frame":
        """Turned about its own z."""
        a = math.radians(degrees)
        c, s = math.cos(a), math.sin(a)
        x = add(scale(self.x, c), scale(self.y, s))
        y = add(scale(self.x, -s), scale(self.y, c))
        return Frame(self.origin, x, y, self.z)

    def as_lists(self) -> dict:
        return {"origin": list(self.origin), "x": list(self.x), "y": list(self.y), "z": list(self.z)}


def frame_from_z(origin: Vec, z: Vec, x_hint: Vec = (1.0, 0.0, 0.0)) -> Frame:
    """A right-handed frame whose z is `z`, with x as close to `x_hint` as possible."""
    z = norm(z)
    if abs(dot(z, norm(x_hint))) > 0.999:
        x_hint = (0.0, 1.0, 0.0) if abs(z[1]) < 0.9 else (0.0, 0.0, 1.0)
    x = norm(sub(x_hint, scale(z, dot(x_hint, z))))
    y = cross(z, x)
    return Frame(origin, x, y, z)


IDENTITY = Frame()
