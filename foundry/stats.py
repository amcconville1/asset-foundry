"""Mesh numbers the rules read: counts, bounds, closedness, winding."""

from __future__ import annotations

from collections import Counter

from . import vec
from .geom import Mesh
from .recipe import Assembly


def signed_volume(mesh: Mesh, faces) -> float:
    """Positive when the faces enclose space with outward normals."""
    total = 0.0
    for i in faces:
        a, b, c = (mesh.verts[k] for k in mesh.faces[i])
        total += vec.dot(a, vec.cross(b, c)) / 6.0
    return total


def mesh_stats(asm: Assembly) -> dict:
    mesh = asm.mesh
    edges: Counter = Counter()
    degenerate = 0
    for a, b, c in mesh.faces:
        for u, v in ((a, b), (b, c), (c, a)):
            edges[(min(u, v), max(u, v))] += 1
        pa, pb, pc = mesh.verts[a], mesh.verts[b], mesh.verts[c]
        if vec.length(vec.cross(vec.sub(pb, pa), vec.sub(pc, pa))) < 1e-12:
            degenerate += 1
    used = {i for f in mesh.faces for i in f}
    lo, hi = mesh.bounds() if mesh.verts else ((0, 0, 0), (0, 0, 0))
    inside_out = [p.id for p in asm.parts if signed_volume(mesh, p.faces) < 0]
    return {
        "tris": len(mesh.faces),
        "verts": len(used),
        "bounds_min": [round(v, 4) for v in lo],
        "bounds_max": [round(v, 4) for v in hi],
        "size": [round(h - l, 4) for l, h in zip(lo, hi)],
        "regions": sorted(set(mesh.regions)),
        "open_edges": sum(1 for n in edges.values() if n == 1),
        "nonmanifold_edges": sum(1 for n in edges.values() if n > 2),
        "loose_verts": len(mesh.verts) - len(used),
        "degenerate_tris": degenerate,
        "inside_out_parts": inside_out,
        "sockets": sorted(asm.sockets),
        "parts": len(asm.parts),
        "mesh_hash": mesh.hash(),
    }
