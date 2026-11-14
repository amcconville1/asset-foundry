"""Shapes, recipes, stats and rules: everything that runs without Blender."""

import copy
import json
import math
from pathlib import Path

import pytest

from foundry import geom, parts, recipe as rec, rules, sheet, stats
from foundry.vec import Frame

EXAMPLE = Path(__file__).parent.parent / "examples" / "weapon" / "greatsword.json"
WEAPON = {"tri_budget": 500, "sockets": ["grip"], "size_min": 0.3, "size_max": 3.0}


def sword() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def built(recipe: dict) -> dict:
    return stats.mesh_stats(rec.assemble(recipe))


def failing(recipe: dict, family: dict = WEAPON) -> list[str]:
    return [r.rule for r in rules.check(built(recipe), family) if not r.ok]


# --- shapes ---------------------------------------------------------------

@pytest.mark.parametrize("name", ["lathe", "block", "loft", "blade", "guard", "grip"])
def test_every_builder_makes_a_closed_outward_mesh_from_its_defaults(name):
    spec = parts.load()[name]
    out = spec.build(spec.defaults(), parts.Ctx(__import__("random").Random(0), spec.region))
    asm = rec.Assembly("t", "any", out.mesh, [rec.PlacedPart("p", name, spec.region, Frame(), range(len(out.mesh.faces)), {}, {}, {})])
    st = stats.mesh_stats(asm)
    assert st["open_edges"] == 0 and st["nonmanifold_edges"] == 0
    assert st["inside_out_parts"] == [] and st["degenerate_tris"] == 0


def test_a_section_shrunk_to_a_point_is_a_tip_not_a_cap():
    stations = [geom.Station(Frame(origin=(0, 0, 0)), geom.rect(1, 1)), geom.Station(Frame(origin=(0, 0, 1)), [(0, 0)] * 4)]
    mesh = geom.sweep(stations, "r")
    assert len(mesh.verts) == 4 + 1 + 1  # base ring, apex, base cap centre
    assert len(mesh.faces) == 4 + 4  # sides to the apex, base cap fan


def test_signed_volume_of_a_unit_cube_is_one():
    mesh = geom.sweep([geom.Station(Frame(origin=(0, 0, 0)), geom.rect(1, 1)), geom.Station(Frame(origin=(0, 0, 1)), geom.rect(1, 1))], "r")
    assert stats.signed_volume(mesh, range(len(mesh.faces))) == pytest.approx(1.0)


# --- recipes --------------------------------------------------------------

def test_same_recipe_and_seed_build_the_same_mesh():
    assert built(sword())["mesh_hash"] == built(sword())["mesh_hash"]


def test_a_changed_parameter_changes_the_mesh():
    r = sword()
    r["parts"][0]["length"] = 1.5
    assert built(r)["mesh_hash"] != built(sword())["mesh_hash"]


def test_the_example_sword_has_its_recipe_dimensions():
    st = built(sword())
    assert st["size"][0] == pytest.approx(0.58)  # guard span
    assert st["size"][2] == pytest.approx(1.9 + 0.1 + 0.55 + 0.1)  # blade + guard + grip + pommel


def test_origin_moves_the_named_socket_to_zero():
    asm = rec.assemble(sword())
    assert asm.sockets["grip"].origin == pytest.approx((0.0, 0.0, 0.0))


def test_unknown_parameter_lists_the_valid_ones():
    r = sword()
    r["parts"][0]["lenght"] = 2
    errors = rec.check(r)
    assert len(errors) == 1 and "'lenght'" in errors[0] and "'length'" in errors[0]


def test_unknown_part_lists_known_parts():
    r = sword()
    r["parts"][1]["part"] = "crossguard"
    assert any("known:" in e and "'guard'" in e for e in rec.check(r))


def test_bad_anchor_names_the_anchors_that_exist():
    r = sword()
    r["parts"][1]["at"] = "blade.bottom"
    assert any("'base'" in e and "'tip'" in e for e in rec.check(r))


def test_at_may_only_name_an_earlier_part():
    r = sword()
    r["parts"][1]["at"] = "grip.end"
    assert any("not an earlier part" in e for e in rec.check(r))


def test_unknown_top_level_key_is_an_error():
    r = sword()
    r["colour"] = "red"
    assert any("'colour'" in e for e in rec.check(r))


def test_out_of_range_value_says_the_limit():
    r = sword()
    r["parts"][3]["sides"] = 200
    assert any("maximum 64" in e for e in rec.check(r))


def test_parts_json_names_axes_with_real_spans():
    pj = rec.assemble(sword()).parts_json()
    blade = next(p for p in pj["parts"] if p["id"] == "blade")
    to_tip = next(a for a in blade["axes"] if a["name"] == "to_tip")
    assert to_tip["span"] == [0.0, 1.9] and to_tip["param"] == "length"
    assert blade["faces"][0] == 0 and blade["faces"][1] > 0


def test_mirror_adds_a_mirrored_copy():
    r = {"family": "x", "name": "m", "parts": [{"id": "a", "part": "block", "size": [0.1, 0.1, 0.1], "offset": [0.5, 0, 0]}]}
    plain = built(r)
    r["parts"][0]["mirror"] = True
    both = built(r)
    assert both["tris"] == 2 * plain["tris"]
    assert both["bounds_min"][0] == pytest.approx(-plain["bounds_max"][0])
    assert both["inside_out_parts"] == []


@pytest.mark.parametrize("path", sorted((Path(__file__).parent.parent / "examples").glob("*/*.json")))
def test_every_example_recipe_builds_closed(path):
    st = built(json.loads(path.read_text(encoding="utf-8")))
    assert st["open_edges"] == 0 and st["inside_out_parts"] == [] and st["degenerate_tris"] == 0


# --- rules: one broken recipe per rule ------------------------------------

def test_a_clean_sword_passes_every_rule():
    assert failing(sword()) == []


def test_tri_budget_fails_with_a_fix():
    r = sword()
    r["parts"][3]["sides"] = 64
    res = {x.rule: x for x in rules.check(built(r), {**WEAPON, "tri_budget": 200})}
    assert not res["tri_budget"].ok and "sides" in res["tri_budget"].fix


def test_missing_socket_fails_naming_it():
    r = sword()
    del r["sockets"]["grip"]
    del r["origin"]
    res = {x.rule: x for x in rules.check(built(r), WEAPON)}
    assert not res["sockets"].ok and "grip" in res["sockets"].fix


def test_degenerate_faces_fail():
    r = sword()
    r["parts"][3]["profile"] = [[0.05, 0], [0.05, 0], [0, 0.1]]
    assert "no_degenerate" in failing(r) or "manifold" in failing(r)


def test_inside_out_fails():
    r = {"family": "x", "name": "neg", "parts": [{"id": "a", "part": "block", "size": [0.2, 0.2, 0.2]}]}
    st = built(r)
    st["inside_out_parts"] = ["a"]  # a builder bug can't be made from valid params; the rule still has to fire
    assert not {x.rule: x for x in rules.check(st, {})}["normals_out"].ok


def test_open_mesh_fails_unless_the_family_allows_it():
    st = built(sword())
    st["open_edges"] = 3
    assert "closed" in [r.rule for r in rules.check(st, WEAPON) if not r.ok]
    assert "closed" not in [r.rule for r in rules.check(st, {**WEAPON, "allow_open": True}) if not r.ok]


def test_size_limits():
    assert "size_max" in failing(sword(), {**WEAPON, "size_max": 2.0})
    assert "size_min" in failing(sword(), {**WEAPON, "size_min": 3.0})


# --- sheet arithmetic -----------------------------------------------------

def test_screen_pixels_matches_the_pinhole_formula():
    # 2.65 m at 30 m, 70 degree vertical fov, 1080 p
    assert sheet.screen_pixels(2.65, 30, 70, 1080) == pytest.approx(2.65 * 1080 / (60 * math.tan(math.radians(35))))


def test_silhouette_scale_halves_with_twice_the_distance():
    a = sheet.silhouette_scale(3.0, 512, 8, 70, 1080)
    b = sheet.silhouette_scale(3.0, 512, 16, 70, 1080)
    assert a == pytest.approx(2 * b)
