"""Shared helpers for the golden test: fixture configs and a mock Ollama server."""

from __future__ import annotations

import copy
import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

TESTS = Path(__file__).parent
FIXTURES = TESTS / "fixtures" / "archive"
GOLDEN = TESTS / "golden"
MOCK_MODEL = "mock-model:1b"
# The synthetic fixtures quote NASA photo codes, as a real space page would.
NASA_PATTERNS = [
    r"AS\d{2}-\d{2,3}-\d{4,5}",
    r"S\d{2}-\d{4,5}(?:_G\d{2}(?:-S)?)?",
    r"GT\d+-\d+-\d+",
    r"STS\d{2,3}-\d+-\d+",
    r"ISS\d{3}-E-\d+",
]
SPACE_HASHTAGS = ["#history", "#space", "#moon", "#exploration", "#science"]
TAXONOMY = yaml.safe_load((FIXTURES / "config.yaml").read_text(encoding="utf-8"))["taxonomy"]

# Two golden runs that between them hit both rank scopes, both metrics,
# top-only vs everything and tagging on/off.
RUNS: dict[str, dict] = {
    "no_tags": {
        "selection": {"metric": "engagement", "top_percentile": 25, "scope": "year"},
        "tagging": {"enabled": False},
        "advanced": {},
    },
    "tags": {
        "selection": {"metric": "engagement_rate", "top_percentile": 100, "scope": "global"},
        "tagging": {"enabled": True, "model": MOCK_MODEL},
        "advanced": {"batch_size": 4},
    },
}


def write_config(run: str, tmp: Path) -> Path:
    cfg = copy.deepcopy(RUNS[run])
    cfg["paths"] = {
        "ig_export": str(FIXTURES / "instagram-export.zip"),
        "insights_dir": str(FIXTURES / "insights"),
        "out": str(tmp / "vault"),
        # Never pick up the developer's own data/ or config/ by default.
        "meta_drafts": str(tmp / "no-drafts"),
    }
    cfg["taxonomy"] = copy.deepcopy(TAXONOMY)
    cfg.setdefault("dedup", {})["overrides"] = str(tmp / "no-overrides.yaml")
    cfg["dedup"]["photo_id_patterns"] = NASA_PATTERNS
    cfg.setdefault("hashtags", {"strategy": "fixed", "fixed": SPACE_HASHTAGS})
    path = tmp / "config.yaml"
    path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    return path


def run_dir(tmp: Path) -> Path:
    """The output vault of the run made in tmp."""
    return tmp / "vault"


def snapshot(root: Path) -> dict[str, bytes]:
    """Every generated file, minus run.log (timestamps, local paths)."""
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.name != "run.log"
    }


def mock_answer(item_id: str, taxonomy: dict) -> dict:
    """Deterministic tags, including values the validator must drop."""
    h = int(item_id, 16)
    program = taxonomy["program"]["values"]
    angle = taxonomy["angle"]["values"]
    return {
        "id": item_id,
        "program": [program[h % len(program)], program[(h + 1) % len(program)]],
        "angle": [angle[h % len(angle)], "not-in-taxonomy"],
    }


@contextmanager
def mock_ollama(taxonomy: dict | None = None) -> Iterator[str]:
    """Serves /api/chat and /api/tags on a free port; yields the host URL."""
    taxonomy = taxonomy or TAXONOMY

    class Handler(BaseHTTPRequestHandler):
        def _send(self, data: dict) -> None:
            body = json.dumps(data).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            self._send({"models": [{"name": MOCK_MODEL}]})

        def do_POST(self) -> None:  # noqa: N802
            req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            items = json.loads(req["messages"][-1]["content"])
            answer = [mock_answer(i["id"], taxonomy) for i in items]
            content = "```json\n" + json.dumps(answer) + "\n```"
            self._send({"message": {"role": "assistant", "content": content}})

        def log_message(self, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
