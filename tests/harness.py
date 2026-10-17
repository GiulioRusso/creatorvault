"""Shared helpers for the golden test: fixture configs and a mock Ollama server."""

from __future__ import annotations

import copy
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator

import yaml

TESTS = Path(__file__).parent
FIXTURES = TESTS / "fixtures" / "archive"
GOLDEN = TESTS / "golden"
MOCK_MODEL = "mock-model:1b"

# Two golden runs that between them hit both tier scopes, both metrics,
# only_top on/off and tagging on/off.
RUNS: dict[str, dict] = {
    "no_tags": {
        "tiers": {"metric": "engagement", "top_percentile": 25},
        "tagging": {"enabled": False},
        "advanced": {"tier_scope": "year", "only_top": True},
    },
    "tags": {
        "tiers": {"metric": "engagement_rate", "top_percentile": 50},
        "tagging": {"enabled": True, "model": MOCK_MODEL},
        "advanced": {"tier_scope": "global", "only_top": False, "batch_size": 4},
    },
}


def write_config(run: str, tmp: Path) -> Path:
    cfg = copy.deepcopy(RUNS[run])
    cfg["paths"] = {
        "ig_export": str(FIXTURES / "instagram-export.zip"),
        "insights_dir": str(FIXTURES / "insights"),
        "out": str(tmp / "vault"),
        "taxonomy": str(FIXTURES / "taxonomy.json"),
    }
    path = tmp / "config.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return path


def run_dir(tmp: Path) -> Path:
    """The timestamped output folder of the single run made in tmp."""
    (found,) = tmp.glob("vault-*")
    return found


def snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


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
def mock_ollama(taxonomy_path: Path = FIXTURES / "taxonomy.json") -> Iterator[str]:
    """Serves /api/chat and /api/tags on a free port; yields the host URL."""
    taxonomy = json.loads(taxonomy_path.read_text(encoding="utf-8"))

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
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
