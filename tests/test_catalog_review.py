"""Catalog, rounds, feedback and the review server, on a throwaway catalog (no Blender)."""

import json
import threading
import urllib.error
import urllib.request

import pytest

from foundry import rounds
from foundry.catalog import Catalog, CatalogError, letters, read, write
from foundry.profile import Profile
from foundry.review.server import serve


def recipe(name, brief="", parents=()):
    return {"family": "weapon", "name": name, "brief": brief,
            "parts": [{"id": "b", "part": "block"}], "lineage": {"parents": list(parents), "answers": []}}


def fake_build(cat, name, vid, ok=True):
    d = cat.variant_dir(name, vid)
    write(d / "report.json", {"ok": ok, "stats": {"tris": 12, "size": [0.5, 0.5, 0.5]},
                              "rules": [{"rule": "tri_budget", "ok": ok}]})
    (d / "sheet.png").write_bytes(b"\x89PNG fake")


@pytest.fixture
def cat(tmp_path):
    c = Catalog(tmp_path / "catalog")
    c.create("swords", "weapon", "heavy swords")
    return c


def ready_round(cat, n_variants=3):
    data = cat.new_round("swords", "first takes", [recipe(f"v{i}", f"take {i}") for i in range(n_variants)])
    for vid in data["variants"]:
        fake_build(cat, "swords", vid)
    cat.submit("swords", data["n"])
    return data


def test_letters_run_past_z():
    assert [letters(i) for i in (0, 25, 26, 27)] == ["A", "Z", "AA", "AB"]


def test_a_round_gets_lettered_variants_with_lineage(cat):
    data = cat.new_round("swords", "b", [recipe("a", "wide", ["r0-A"]), recipe("b")])
    assert data["variants"] == ["r1-A", "r1-B"] and data["status"] == "building"
    assert read(cat.variant_dir("swords", "r1-A") / "lineage.json")["parents"] == ["r0-A"]
    assert "lineage" not in read(cat.variant_dir("swords", "r1-A") / "recipe.json")


def test_submit_refuses_a_failing_or_unbuilt_variant(cat):
    data = cat.new_round("swords", "b", [recipe("a"), recipe("b"), recipe("c")])
    fake_build(cat, "swords", "r1-A")
    fake_build(cat, "swords", "r1-B", ok=False)
    with pytest.raises(CatalogError) as e:
        cat.submit("swords", 1)
    assert "r1-B: failed (tri_budget)" in str(e.value) and "r1-C: not built" in str(e.value)


def test_next_round_waits_for_the_review(cat):
    ready_round(cat)
    with pytest.raises(CatalogError, match="not reviewed"):
        cat.new_round("swords", "again", [recipe("x")])
    cat.mark_reviewed("swords", 1)
    assert cat.new_round("swords", "again", [recipe("x")])["variants"] == ["r2-A"]


def test_drop_only_before_submission(cat):
    data = cat.new_round("swords", "b", [recipe("a"), recipe("b")])
    assert cat.drop("swords", "r1-B")["variants"] == ["r1-A"]
    fake_build(cat, "swords", "r1-A")
    cat.submit("swords", 1)
    with pytest.raises(CatalogError):
        cat.drop("swords", "r1-A")


def test_verdicts_are_kept_per_reviewer(cat):
    ready_round(cat)
    cat.set_verdict("swords", "r1-A", "ana", "like", "the weight")
    cat.set_verdict("swords", "r1-A", "sam", "cut", "too plain")
    v = read(cat.variant_dir("swords", "r1-A") / "verdicts.json")
    assert v["ana"]["verdict"] == "like" and v["sam"]["verdict"] == "cut"
    with pytest.raises(CatalogError):
        cat.set_verdict("swords", "r1-A", "ana", "love")


def test_feedback_groups_by_the_strongest_verdict(cat):
    ready_round(cat, 4)
    write(cat.variant_dir("swords", "r1-A") / "parts.json", sword_parts())
    tip_r = next(p for p in sword_parts()["parts"] if p["id"] == "guard")["anchors"]["tip_r"]["origin"]
    cat.set_verdict("swords", "r1-A", "ana", "like", "blade weight", [{"kind": "pin", "n": 1, "part": "guard", "point": gl(tip_r), "note": "curl"}])
    cat.set_verdict("swords", "r1-A", "sam", "cut", "")
    cat.set_verdict("swords", "r1-B", "ana", "cut", "too thin")
    cat.set_verdict("swords", "r1-C", "ana", "use", "this one")
    cat.set_round_note("swords", 1, "ana", "all a bit thin")
    cat.mark_reviewed("swords", 1)
    fb = rounds.feedback(cat, "swords")
    assert [e["id"] for e in fb["like"]] == ["r1-A"]
    assert [e["id"] for e in fb["cut"]] == ["r1-B"]
    assert [e["id"] for e in fb["use"]] == ["r1-C"]
    assert [e["id"] for e in fb["none"]] == ["r1-D"]
    text = rounds.feedback_text(fb)
    assert "round note (ana): all a bit thin" in text
    assert 'ana: "blade weight"' in text and 'mark 1 (pin, guard: along_span 1.00' in text and '"curl"' in text


def test_feedback_needs_a_reviewed_round(cat):
    ready_round(cat)
    with pytest.raises(CatalogError, match="no reviewed round"):
        rounds.feedback(cat, "swords")


def test_bad_names_are_refused(cat):
    with pytest.raises(CatalogError):
        cat.create("../escape", "weapon", "x")


# --- the server ------------------------------------------------------------

@pytest.fixture
def server(cat):
    ready_round(cat)
    srv = serve(cat, Profile(root=cat.root), 0, "ana")
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def get(url):
    with urllib.request.urlopen(url) as r:
        return r.status, r.read()


def post(url, body):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def test_server_lists_and_serves(server):
    cols = json.loads(get(server + "/api/collections")[1])
    assert cols[0]["name"] == "swords" and cols[0]["waiting"] == 1
    view = json.loads(get(server + "/api/collection/swords")[1])
    assert [v["id"] for v in view["rounds"][0]["variants"]] == ["r1-A", "r1-B", "r1-C"]
    assert get(server + "/files/swords/round-1/r1-A/sheet.png")[1].startswith(b"\x89PNG")
    assert b"Foundry review" in get(server + "/")[1]
    assert get(server + "/static/vendor/three.module.min.js")[0] == 200


def test_server_refuses_paths_outside_the_catalog(server):
    for bad in ("/files/../../etc/passwd.json", "/files/swords/round-1/r1-A/recipe.py", "/static/../server.py"):
        with pytest.raises(urllib.error.HTTPError) as e:
            get(server + bad)
        assert e.value.code in (403, 404)


def test_server_saves_verdicts_notes_and_the_review(server, cat):
    post(server + "/api/verdict", {"collection": "swords", "variant": "r1-B", "by": "ana", "verdict": "like", "comment": "nice"})
    post(server + "/api/round-note", {"collection": "swords", "round": 1, "by": "ana", "note": "wider"})
    out = post(server + "/api/reviewed", {"collection": "swords", "round": 1})
    assert out["status"] == "reviewed"
    assert read(cat.variant_dir("swords", "r1-B") / "verdicts.json")["ana"]["comment"] == "nice"
    assert cat.round("swords", 1)["notes"]["ana"] == "wider"


def test_server_reports_bad_input(server):
    with pytest.raises(urllib.error.HTTPError) as e:
        post(server + "/api/verdict", {"collection": "swords", "variant": "r1-A", "verdict": "love"})
    assert e.value.code == 400


# --- marks -------------------------------------------------------------------

from foundry import marks as mk, recipe as rec  # noqa: E402

SWORD = json.loads((__import__("pathlib").Path(__file__).parent.parent / "examples" / "weapon" / "greatsword.json").read_text(encoding="utf-8"))


def gl(p):
    """foundry (x, y fwd, z up) -> glTF (x, y up, z back), as the page sends points."""
    return [p[0], p[2], -p[1]]


def sword_parts():
    return rec.assemble(SWORD).parts_json()


def test_a_pin_at_the_tip_is_the_end_of_the_blade():
    pj = sword_parts()
    tip = next(p for p in pj["parts"] if p["id"] == "blade")["anchors"]["tip"]["origin"]
    m = mk.resolve({"kind": "pin", "n": 1, "part": "blade", "point": gl(tip), "note": "x"}, pj)
    assert m["at"]["to_tip"] == pytest.approx(1.0, abs=1e-3)
    assert m["at"]["across"] == pytest.approx(0.5, abs=1e-3)  # on the centre line


def test_an_arrow_up_the_blade_is_a_length_change_in_metres():
    pj = sword_parts()
    tip = next(p for p in pj["parts"] if p["id"] == "blade")["anchors"]["tip"]["origin"]
    end = [tip[0] + 0.01, tip[1], tip[2] + 0.23]
    m = mk.resolve({"kind": "drag", "n": 2, "part": "blade", "from": gl(tip), "to": gl(end)}, pj)
    assert m["axis"] == "to_tip" and m["param"] == "length"
    assert m["metres"] == pytest.approx(0.23, abs=1e-3)
    assert m["to_at"]["to_tip"] == pytest.approx(1 + 0.23 / 1.9, abs=1e-3)


def test_an_arrow_across_the_guard_reads_as_span():
    pj = sword_parts()
    g = next(p for p in pj["parts"] if p["id"] == "guard")
    right = g["anchors"]["tip_r"]["origin"]
    out = [right[0] + 0.1, right[1], right[2]]
    m = mk.resolve({"kind": "drag", "n": 1, "part": "guard", "from": gl(right), "to": gl(out)}, pj)
    assert m["axis"] == "along_span" and m["param"] == "span" and m["metres"] == pytest.approx(0.1, abs=1e-3)
    assert m["at"]["along_span"] == pytest.approx(1.0, abs=1e-2)


def test_a_lasso_keeps_only_real_parts():
    m = mk.resolve({"kind": "area", "n": 3, "parts": ["grip", "pommel", "nope"]}, sword_parts())
    assert m["parts"] == ["grip", "pommel"]


def test_marks_on_an_unknown_part_or_kind_are_refused():
    with pytest.raises(mk.MarkError):
        mk.resolve({"kind": "pin", "part": "hilt", "point": [0, 0, 0]}, sword_parts())
    with pytest.raises(mk.MarkError):
        mk.resolve({"kind": "circle"}, sword_parts())


def test_verdicts_store_resolved_marks_and_feedback_reads_them(cat):
    ready_round(cat, 1)
    write(cat.variant_dir("swords", "r1-A") / "parts.json", sword_parts())
    tip = next(p for p in sword_parts()["parts"] if p["id"] == "blade")["anchors"]["tip"]["origin"]
    cat.set_verdict("swords", "r1-A", "ana", "like", "", [
        {"kind": "drag", "n": 1, "part": "blade", "from": gl(tip), "to": gl([tip[0], tip[1], tip[2] + 0.2]), "note": "longer, to here"}])
    cat.mark_reviewed("swords", 1)
    text = rounds.feedback_text(rounds.feedback(cat, "swords"))
    assert "arrow +0.200 m along to_tip (changes length)" in text and '"longer, to here"' in text
