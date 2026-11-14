"""The review page's server (contract 2.7): stdlib only, localhost only.

GET  /                                   the page
GET  /static/<path>                      page assets (vendored three.js)
GET  /api/collections                    [{name, family, ask, status, rounds, waiting}]
GET  /api/collection/<name>              catalog.view(name)
GET  /files/<name>/<round-n>/<id>/<file> a variant's sheet, renders, model
POST /api/verdict     {collection, variant, by, verdict, comment, marks}
POST /api/round-note  {collection, round, by, note}
POST /api/reviewed    {collection, round}       round -> reviewed, runs hooks.reviewed
"""

from __future__ import annotations

import json
import mimetypes
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .. import rounds
from ..catalog import Catalog, CatalogError
from ..profile import Profile

STATIC = Path(__file__).parent / "static"
SERVED = {".png", ".glb", ".json", ".jpg", ".webp"}
mimetypes.add_type("model/gltf-binary", ".glb")
mimetypes.add_type("text/javascript", ".js")


def make_handler(cat: Catalog, profile: Profile, default_reviewer: str):
    lock = threading.Lock()  # one writer at a time; files are small

    class Handler(BaseHTTPRequestHandler):
        server_version = "foundry-review"

        def log_message(self, fmt, *args):  # quiet: the terminal is the user's
            pass

        def do_GET(self):
            path = unquote(urlparse(self.path).path)
            try:
                if path == "/":
                    return self._file(STATIC / "index.html")
                if path.startswith("/static/"):
                    return self._file(_inside(STATIC, path[len("/static/"):]))
                if path == "/api/collections":
                    return self._json(_collections(cat))
                if path == "/api/config":
                    return self._json({"reviewer": default_reviewer, "views": profile.views, "tints": _tints(profile)})
                if path.startswith("/api/collection/"):
                    return self._json(cat.view(path[len("/api/collection/"):]))
                if path.startswith("/files/"):
                    target = _inside(cat.root, path[len("/files/"):])
                    if target.suffix.lower() not in SERVED:
                        return self._error(HTTPStatus.FORBIDDEN, "not a served file type")
                    return self._file(target)
                return self._error(HTTPStatus.NOT_FOUND, "no such page")
            except CatalogError as e:
                return self._error(HTTPStatus.NOT_FOUND, str(e))
            except PermissionError as e:
                return self._error(HTTPStatus.FORBIDDEN, str(e))

        def do_POST(self):
            path = urlparse(self.path).path
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                with lock:
                    if path == "/api/verdict":
                        out = cat.set_verdict(body["collection"], body["variant"], body.get("by") or default_reviewer,
                                              body.get("verdict"), body.get("comment", ""), body.get("marks"))
                    elif path == "/api/round-note":
                        out = cat.set_round_note(body["collection"], int(body["round"]), body.get("by") or default_reviewer,
                                                 body.get("note", ""))
                    elif path == "/api/reviewed":
                        out = cat.mark_reviewed(body["collection"], int(body["round"]))
                        out["hook"] = rounds.notify(profile, "reviewed", body["collection"], int(body["round"]))
                    else:
                        return self._error(HTTPStatus.NOT_FOUND, "no such action")
                return self._json(out)
            except (CatalogError, KeyError, ValueError) as e:
                return self._error(HTTPStatus.BAD_REQUEST, str(e))

        def _json(self, data):
            raw = json.dumps(data).encode()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _file(self, path: Path):
            if not path.is_file():
                return self._error(HTTPStatus.NOT_FOUND, f"missing {path.name}")
            raw = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _error(self, status, message):
            raw = json.dumps({"error": message}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    return Handler


def _inside(root: Path, rel: str) -> Path:
    """`rel` under `root`, refusing anything that climbs out."""
    target = (root / rel).resolve()
    if root.resolve() not in target.parents and target != root.resolve():
        raise PermissionError("outside the served folder")
    return target


def _collections(cat: Catalog) -> list[dict]:
    out = []
    for name in cat.names():
        col = cat.collection(name)
        rs = [cat.round(name, n) for n in cat.rounds(name)]
        out.append({**col, "rounds": len(rs), "waiting": sum(1 for r in rs if r["status"] == "ready"),
                    "last_status": rs[-1]["status"] if rs else None})
    return out


def _tints(profile: Profile) -> dict:
    """Region colours per family, so the 3D view shows the same tints as the sheet."""
    out = {fam: profile.family(fam)["region_tints"] for fam in profile.families}
    out["_default"] = profile.family("_default")["region_tints"]
    return out


def serve(cat: Catalog, profile: Profile, port: int, reviewer: str) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(cat, profile, reviewer))
