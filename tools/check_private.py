"""Keeps project data out of this public repo.

The foundry is used by private projects. Their names, paths, recipes, catalogs, people and
emails must never land here. This check scans files (the tracked tree, or what's staged for
a commit) and fails on:

- an absolute home-folder path (C:\\Users\\<name>\\..., /home/<name>/..., /Users/<name>/...)
- an email address, except no-reply ones (users.noreply.github.com, noreply@anthropic.com)
  and example ones (example.com / .org)
- a file type that holds project output: .blend, .glb (outside docs/), .fbx, .obj, catalog
  files (verdicts.json, lineage.json, round.json, collection.json), or anything under out/
- any word from your private list: one word or phrase per line in the file named by
  $FOUNDRY_PRIVATE_WORDS, else ~/.config/asset-foundry/private-words.txt. That file lives
  outside the repo, so the words themselves are never published. Matching ignores case.

Used by the pre-commit hook (`--staged`, also checks the commit author's email), the
commit-msg hook (`--message <file>`) and the tests (the whole tree; the private list is skipped where it doesn't exist, e.g. in CI).
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Not text-scanned: vendored third-party code (unmodified), and this check's own patterns and
# test samples (made-up paths and addresses on purpose; review changes to them by hand).
SKIP_TEXT = ("foundry/review/static/vendor/", "tools/check_private.py", "tests/test_private.py")
HOME_PATH = re.compile(r"(?i)(?:[a-z]:[\\/]+users[\\/]+(?!public\b|default\b|<)[^\\/\s\"'`<>]+|/home/(?!runner\b|<)[^/\s\"'`<>]+|/users/(?!shared\b|<)[^/\s\"'`<>]+)")
EMAIL = re.compile(r"[\w.+-]+@[A-Za-z][\w-]*(?:\.[A-Za-z][\w-]*)+")  # domains start with a letter, so pkg@1.2.3 isn't one
ALLOWED_EMAIL = re.compile(r"(?i)@users\.noreply\.github\.com$|^noreply@anthropic\.com$|@example\.(?:com|org)$")
BLOCKED_NAMES = {"verdicts.json", "lineage.json", "round.json", "collection.json"}
BLOCKED_SUFFIXES = {".blend", ".blend1", ".fbx", ".obj", ".glb", ".gltf"}


def private_words() -> list[str]:
    path = Path(os.environ.get("FOUNDRY_PRIVATE_WORDS") or Path.home() / ".config" / "asset-foundry" / "private-words.txt")
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [w.strip().lower() for w in lines if w.strip() and not w.strip().startswith("#")]


def check_file(rel: str, data: bytes, words: list[str]) -> list[str]:
    problems = []
    p = Path(rel)
    if rel.startswith("out/") or "/out/" in rel:
        problems.append(f"{rel}: run output (out/) is never committed")
    if p.name in BLOCKED_NAMES:
        problems.append(f"{rel}: a catalog file; catalogs belong to the project using the foundry")
    if p.suffix.lower() in BLOCKED_SUFFIXES and not rel.startswith("docs/"):
        problems.append(f"{rel}: a model file; build examples from recipes instead of committing meshes")
    if rel.startswith(SKIP_TEXT):
        return problems
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return problems  # binary (images): names and paths can't be read from them here
    for n, line in enumerate(text.splitlines(), 1):
        for m in HOME_PATH.finditer(line):
            problems.append(f"{rel}:{n}: home-folder path {m.group(0)!r}; use a relative path or a placeholder")
        for m in EMAIL.finditer(line):
            if not ALLOWED_EMAIL.search(m.group(0)):
                problems.append(f"{rel}:{n}: email address {m.group(0)!r}; use a no-reply or example.com address")
        low = line.lower()
        for w in words:
            if w in low:
                problems.append(f"{rel}:{n}: a word from your private list ({w!r})")
    return problems


def git(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=True).stdout


def tracked() -> list[tuple[str, bytes]]:
    names = git("ls-files", "-z").decode("utf-8").split("\0")
    return [(n, (ROOT / n).read_bytes()) for n in names if n and (ROOT / n).is_file()]


def staged() -> list[tuple[str, bytes]]:
    names = git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z").decode("utf-8").split("\0")
    return [(n, git("show", f":{n}")) for n in names if n]


def author_problems() -> list[str]:
    email = os.environ.get("GIT_AUTHOR_EMAIL") or git("config", "user.email").decode().strip()
    if not ALLOWED_EMAIL.search(email):
        return [f"commit author email {email!r} would be public; set a no-reply one: "
                "git config user.email <id>+<user>@users.noreply.github.com"]
    return []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--staged", action="store_true", help="check what is staged, and the author email")
    ap.add_argument("--message", help="check a commit message file (the commit-msg hook)")
    args = ap.parse_args(argv)
    words = private_words()
    if args.message:
        files = [("commit message", Path(args.message).read_bytes())]
    else:
        files = staged() if args.staged else tracked()
    problems = [p for rel, data in files for p in check_file(rel, data, words)]
    if args.staged:
        problems += author_problems()
    for p in problems:
        print(f"private-data: {p}")
    if problems:
        print("Blocked: this repo is public. Remove project data, then commit again (CONTRIBUTING.md rule 1).")
        return 1
    if not words:
        print("private-data: no private word list found; only paths, emails and file types were checked")
    return 0


if __name__ == "__main__":
    sys.exit(main())
