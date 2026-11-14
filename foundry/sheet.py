"""sheet.png: one picture per variant, laid out from the raw renders (contract 2.4).

Row 1: front, side, back, three-quarter, top. Row 2: wireframe, beside the reference
model, and the silhouette at each of the profile's view distances, at the size it has on
screen (actual pixels, then enlarged 4x so it can be read).
"""

from __future__ import annotations

import math
from pathlib import Path

CELL = 300
LABEL_H = 22
BG = (36, 38, 42)
FG = (230, 230, 230)
BAD = (240, 110, 100)
GOOD = (140, 210, 140)


def screen_pixels(size_m: float, distance: float, fov_deg: float, screen_h: int) -> float:
    """How many pixels `size_m` metres covers on a screen `screen_h` tall, seen from
    `distance` metres with a vertical field of view `fov_deg`."""
    return size_m * screen_h / (2.0 * distance * math.tan(math.radians(fov_deg) / 2.0))


def silhouette_scale(extent_m: float, render_px: int, distance: float, fov_deg: float, screen_h: int) -> float:
    """Factor that shrinks an orthographic render covering `extent_m` metres over
    `render_px` pixels to its on-screen size at that distance."""
    return screen_pixels(extent_m, distance, fov_deg, screen_h) / render_px


def compose(out_dir: Path, report: dict, family: dict, views: dict) -> Path:
    from PIL import Image, ImageDraw

    renders = Path(out_dir) / "renders"
    row1 = ["front", "side", "back", "three_quarter", "top"]
    sil = Image.open(renders / "silhouette.png").convert("L")
    extent = family.get("extent") or _extent_from_stats(report)
    sil_cells = []
    for name, v in views.items():
        f = silhouette_scale(extent, sil.width, v["distance"], v["fov"], v["screen_h"])
        w = max(1, round(sil.width * f))
        on_screen = sil.resize((w, w), Image.Resampling.BOX)
        sil_cells.append((name, v, on_screen))
    width = CELL * 5
    height = LABEL_H * 2 + (CELL + LABEL_H) * 2 + 40
    sheet = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(sheet)
    _header(draw, report, family, width)
    y = LABEL_H * 2
    for i, name in enumerate(row1):
        _cell(sheet, draw, renders / f"{name}.png", name.replace("_", " "), i * CELL, y)
    y += CELL + LABEL_H
    _cell(sheet, draw, renders / "wire.png", "wire", 0, y)
    _cell(sheet, draw, renders / "scale.png", "beside reference", CELL, y)
    x = CELL * 2
    for name, v, on_screen in sil_cells:
        if x >= width:
            break
        tall = _ink_height(on_screen)
        shown, zoom = _fit(on_screen)
        draw.text((x + 4, y + 2), f"{name} {v['distance']:g} m: {tall} px tall" + (f" (shown x{zoom})" if zoom > 1 else ""), fill=FG)
        cell = Image.new("L", (CELL, CELL), 255)
        cell.paste(shown, ((CELL - shown.width) // 2, (CELL - shown.height) // 2))
        sheet.paste(cell.convert("RGB"), (x, y + LABEL_H))
        x += CELL
    path = Path(out_dir) / "sheet.png"
    sheet.save(path, optimize=True)
    return path


def _fit(img):
    """The on-screen silhouette for a cell: cropped to its ink, enlarged by a whole factor
    (pixels kept square) when small, shrunk to fit when bigger. Returns (image, zoom)."""
    from PIL import Image

    box = Image.eval(img, lambda v: 255 - v).getbbox()
    if box:
        img = img.crop(box)
    zoom = max(1, min(8, (CELL - 8) // max(img.width, img.height, 1)))
    if zoom > 1:
        return img.resize((img.width * zoom, img.height * zoom), Image.Resampling.NEAREST), zoom
    if max(img.width, img.height) > CELL - 8:
        img = img.copy()
        img.thumbnail((CELL - 8, CELL - 8), Image.Resampling.BOX)
    return img, 1


def _ink_height(img) -> int:
    from PIL import Image

    box = Image.eval(img, lambda v: 255 - v).getbbox()
    return 0 if not box else box[3] - box[1]


def _extent_from_stats(report: dict) -> float:
    return max(report["stats"]["size"]) * 1.15


def _header(draw, report: dict, family: dict, width: int) -> None:
    st = report["stats"]
    budget = family.get("tri_budget")
    tris = f"{st['tris']} tris" + (f" / {budget}" if budget else "")
    size = " x ".join(f"{v:.2f}" for v in st["size"]) + " m"
    failed = [r["rule"] for r in report["rules"] if not r["ok"]]
    draw.text((8, 4), f"{report['name']}   {report['family']}   {tris}   {size}", fill=FG)
    draw.text((8, 4 + LABEL_H), "rules: all pass" if not failed else "FAILED: " + ", ".join(failed), fill=GOOD if not failed else BAD)


def _cell(sheet, draw, path: Path, label: str, x: int, y: int) -> None:
    from PIL import Image

    draw.text((x + 4, y + 2), label, fill=FG)
    if path.exists():
        img = Image.open(path).convert("RGB").resize((CELL, CELL), Image.Resampling.LANCZOS)
        sheet.paste(img, (x, y + LABEL_H))
