"""A project's profile (TOML): where Blender is, its families and their budgets, round
sizes, the reference model, view distances, extra builders and hooks. The foundry knows
nothing about any game beyond what a profile says. Paths are relative to the profile file.
"""

from __future__ import annotations

import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_FAMILY = {
    "tri_budget": None,
    "sockets": [],
    "allow_open": False,
    "extent": None,
    "round_first": 8,
    "round_next": 4,
    "reference_offset": [0.8, 0.0, 0.0],
    "region_tints": {},
}

DEFAULT_TINTS = {
    "metal": [0.72, 0.74, 0.78], "trim": [0.62, 0.52, 0.36], "wrap": [0.32, 0.26, 0.22],
    "base": [0.6, 0.6, 0.6], "stone": [0.55, 0.55, 0.52], "wood": [0.5, 0.38, 0.26],
    "cloth": [0.45, 0.42, 0.5], "skin": [0.7, 0.58, 0.5], "glow": [0.85, 0.85, 0.6],
}

DEFAULT_VIEWS = {"near": {"distance": 3.0, "fov": 60.0, "screen_h": 1080}}


@dataclass
class Profile:
    root: Path
    blender: str | None = None
    catalog: Path | None = None
    parallel: int = 4
    parts: list[str] = field(default_factory=list)
    reference: Path | None = None
    views: dict = field(default_factory=lambda: dict(DEFAULT_VIEWS))
    families: dict[str, dict] = field(default_factory=dict)
    hooks: dict[str, str] = field(default_factory=dict)
    path: Path | None = None

    def family(self, name: str) -> dict:
        fam = {**DEFAULT_FAMILY, **self.families.get(name, {})}
        fam["region_tints"] = {**DEFAULT_TINTS, **fam.get("region_tints", {})}
        return fam


def load(path: str | Path | None) -> Profile:
    if path is None:
        return Profile(root=Path.cwd(), catalog=Path.cwd() / "out" / "catalog")
    path = Path(path).resolve()
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    root = path.parent
    top = data.get("foundry", {})
    base = Path(top.get("root", ".")) if Path(top.get("root", ".")).is_absolute() else (root / top.get("root", ".")).resolve()
    prof = Profile(
        root=base,
        blender=top.get("blender"),
        catalog=(base / top.get("catalog", "out/catalog")).resolve(),
        parallel=int(top.get("parallel", 4)),
        parts=list(top.get("parts", [])),
        reference=(base / top["reference"]).resolve() if top.get("reference") else None,
        views=data.get("views", dict(DEFAULT_VIEWS)),
        families=data.get("family", {}),
        hooks=data.get("hooks", {}),
        path=path,
    )
    parts_dir = top.get("parts_path")
    if parts_dir:
        p = str((root / parts_dir).resolve())
        if p not in sys.path:
            sys.path.insert(0, p)
    return prof
