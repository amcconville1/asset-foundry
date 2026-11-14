"""Triangle meshes in plain Python, and the one shape-making core: the sweep.

Every primitive is a sweep: a 2D section (counter-clockwise, seen from +z of its station)
carried through a list of stations. A section shrunk to one point is an apex (a tip); any
other end is capped. Faces come out as triangles with outward normals, so nothing later
has to triangulate or fix winding.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field

from . import vec
from .vec import Frame, Vec

Point2 = tuple[float, float]
APEX_EPS = 1e-9


@dataclass
class Mesh:
    verts: list[Vec] = field(default_factory=list)
    faces: list[tuple[int, int, int]] = field(default_factory=list)
    regions: list[str] = field(default_factory=list)  # one per face

    def add_vert(self, v: Vec) -> int:
        self.verts.append(v)
        return len(self.verts) - 1

    def add_face(self, a: int, b: int, c: int, region: str) -> None:
        self.faces.append((a, b, c))
        self.regions.append(region)

    def extend(self, other: "Mesh") -> range:
        """Appends `other`; returns the face indices it took."""
        base, first = len(self.verts), len(self.faces)
        self.verts.extend(other.verts)
        self.faces.extend((a + base, b + base, c + base) for a, b, c in other.faces)
        self.regions.extend(other.regions)
        return range(first, len(self.faces))

    def transformed(self, frame: Frame) -> "Mesh":
        return Mesh([frame.point(v) for v in self.verts], list(self.faces), list(self.regions))

    def mirrored_x(self) -> "Mesh":
        """Mirrored across x = 0, winding flipped so normals stay outward."""
        verts = [(-x, y, z) for x, y, z in self.verts]
        return Mesh(verts, [(a, c, b) for a, b, c in self.faces], list(self.regions))

    def bounds(self) -> tuple[Vec, Vec]:
        xs, ys, zs = zip(*self.verts)
        return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))

    def hash(self) -> str:
        data = {
            "v": [[round(c, 5) + 0.0 for c in v] for v in self.verts],
            "f": self.faces,
            "r": self.regions,
        }
        return hashlib.sha256(json.dumps(data, separators=(",", ":")).encode()).hexdigest()[:16]


@dataclass(frozen=True)
class Station:
    frame: Frame
    section: list[Point2]


def is_apex(section: list[Point2]) -> bool:
    return all(abs(x) < APEX_EPS and abs(y) < APEX_EPS for x, y in section)


def sweep(stations: list[Station], region: str) -> Mesh:
    """Skins the stations' sections into one closed mesh."""
    if len(stations) < 2:
        raise ValueError("a sweep needs at least two stations")
    count = len(stations[0].section)
    if count < 3 or any(len(s.section) != count for s in stations):
        raise ValueError("every section needs the same number of points, at least 3")
    mesh = Mesh()
    rings: list[list[int]] = []
    for st in stations:
        if is_apex(st.section):
            rings.append([mesh.add_vert(st.frame.origin)] * count)
        else:
            rings.append([mesh.add_vert(st.frame.point((x, y, 0.0))) for x, y in st.section])
    for lower, upper in zip(rings, rings[1:]):
        _skin(mesh, lower, upper, region)
    _cap(mesh, stations[0], rings[0], region, bottom=True)
    _cap(mesh, stations[-1], rings[-1], region, bottom=False)
    return mesh


def _skin(mesh: Mesh, a: list[int], b: list[int], region: str) -> None:
    n = len(a)
    for i in range(n):
        j = (i + 1) % n
        if a[i] != a[j]:
            mesh.add_face(a[i], a[j], b[j], region)
        if b[i] != b[j]:
            mesh.add_face(a[i], b[j], b[i], region)


def _cap(mesh: Mesh, station: Station, ring: list[int], region: str, bottom: bool) -> None:
    if is_apex(station.section):
        return
    cx = sum(p[0] for p in station.section) / len(station.section)
    cy = sum(p[1] for p in station.section) / len(station.section)
    c = mesh.add_vert(station.frame.point((cx, cy, 0.0)))
    n = len(ring)
    for i in range(n):
        j = (i + 1) % n
        if bottom:
            mesh.add_face(c, ring[j], ring[i], region)
        else:
            mesh.add_face(c, ring[i], ring[j], region)


def straight(heights: list[float]) -> list[Frame]:
    """Station frames along +z."""
    return [Frame(origin=(0.0, 0.0, h)) for h in heights]


def circle(radius: float, sides: int) -> list[Point2]:
    """A regular polygon, a flat side facing +y so a low count still reads square-on."""
    off = math.pi / sides
    return [(radius * math.cos(off + 2 * math.pi * i / sides), radius * math.sin(off + 2 * math.pi * i / sides)) for i in range(sides)]


def rect(w: float, d: float, chamfer: float = 0.0) -> list[Point2]:
    """A w x d rectangle centred on the origin, corners cut by `chamfer` metres."""
    hw, hd = w / 2, d / 2
    if chamfer <= 0:
        return [(hw, -hd), (hw, hd), (-hw, hd), (-hw, -hd)]
    c = min(chamfer, hw * 0.99, hd * 0.99)
    return [(hw, -hd + c), (hw, hd - c), (hw - c, hd), (-hw + c, hd), (-hw, hd - c), (-hw, -hd + c), (-hw + c, -hd), (hw - c, -hd)]


def lens(w: float, d: float) -> list[Point2]:
    """A diamond: edges at +-x, ridges at +-y. A blade's section."""
    return [(w / 2, 0.0), (0.0, d / 2), (-w / 2, 0.0), (0.0, -d / 2)]


def scaled(section: list[Point2], sx: float, sy: float) -> list[Point2]:
    return [(x * sx, y * sy) for x, y in section]


def curve_at(points: list[list[float]], t: float) -> float:
    """Piecewise-linear value at t from [[t, value], ...] sorted by t."""
    if t <= points[0][0]:
        return points[0][1]
    for (t0, v0), (t1, v1) in zip(points, points[1:]):
        if t <= t1:
            return vec.lerp(v0, v1, 0.0 if t1 == t0 else (t - t0) / (t1 - t0))
    return points[-1][1]


def box_uvs(mesh: Mesh) -> list[list[Point2]]:
    """Per-corner UVs, each face projected on the axis plane it faces most."""
    out = []
    for a, b, c in mesh.faces:
        pa, pb, pc = mesh.verts[a], mesh.verts[b], mesh.verts[c]
        n = vec.cross(vec.sub(pb, pa), vec.sub(pc, pa))
        axis = max(range(3), key=lambda k: abs(n[k]))
        keep = [k for k in range(3) if k != axis]
        out.append([(p[keep[0]], p[keep[1]]) for p in (pa, pb, pc)])
    return out
