"""The private-data check (tools/check_private.py). Made-up words only: the real list lives
outside the repo."""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("check_private", Path(__file__).parent.parent / "tools" / "check_private.py")
cp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cp)


def problems(rel, text, words=()):
    return cp.check_file(rel, text.encode("utf-8") if isinstance(text, str) else text, list(words))


@pytest.mark.parametrize("line", [
    r"profile = 'C:\Users\someone\games\proj\foundry.toml'",
    "root = C:/Users/someone/proj",
    "see /home/someone/proj/recipes",
    "open /Users/someone/Documents/x.json",
])
def test_home_folder_paths_are_caught(line):
    assert any("home-folder path" in p for p in problems("README.md", line))


@pytest.mark.parametrize("line", [
    "relative/path/to/recipe.json",
    "C:/Program Files/Blender Foundation/Blender 5.1/blender.exe",
    r"C:\Users\<you>\recipes",
    "/home/runner/work",  # CI's own home
])
def test_ordinary_paths_pass(line):
    assert problems("README.md", line) == []


def test_real_emails_are_caught_and_no_reply_ones_pass():
    assert problems("a.md", "mail me at someone@mailhost.com")
    assert problems("a.md", "Co-Authored-By: Claude <noreply@anthropic.com>") == []
    assert problems("a.md", "1+someone@users.noreply.github.com") == []
    assert problems("a.md", "ana@example.com") == []
    assert problems("a.md", "three@0.170.0 and pkg@2.1") == []


def test_private_words_are_caught_in_any_case():
    out = problems("examples/x.json", '{"brief": "for the Zorblax arena"}', ["zorblax"])
    assert out and "private list" in out[0]


def test_project_output_files_are_caught():
    assert problems("out/catalog/x/round.json", "{}")
    assert problems("examples/r1-A/verdicts.json", "{}")
    assert problems("examples/sword.glb", b"\x00\x01")
    assert problems("assets/thing.blend", b"\x00")
    assert problems("docs/sheet-example.glb", b"\x00") == []  # docs may hold a sample model


def test_vendored_code_is_not_text_scanned():
    assert problems("foundry/review/static/vendor/x.js", "C:/Users/someone/dev") == []


def test_the_repo_itself_is_clean():
    words = cp.private_words()  # the real list on a maintainer's machine; empty in CI
    found = [p for rel, data in cp.tracked() for p in cp.check_file(rel, data, words)]
    assert found == []


def test_commit_messages_are_checked(tmp_path, monkeypatch, capsys):
    words = tmp_path / "words.txt"
    words.write_text("zorblax\n", encoding="utf-8")
    monkeypatch.setenv("FOUNDRY_PRIVATE_WORDS", str(words))
    bad = tmp_path / "bad.txt"
    bad.write_text("fix(sheet): framing for the Zorblax props\n", encoding="utf-8")
    good = tmp_path / "good.txt"
    good.write_text("fix(sheet): framing for small props\n", encoding="utf-8")
    assert cp.main(["--message", str(bad)]) == 1
    assert cp.main(["--message", str(good)]) == 0
