"""Semantic tagging via Ollama's /api/chat, with a caption-hash cache."""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from creatorvault.models import Post, log
from creatorvault.tagging.taxonomy import (
    axis_names,
    axis_values,
    build_tagging_prompt,
    clean_caption,
    response_schema,
)

# Ollama server host. Defaults to the local one; can be pointed elsewhere via
# the OLLAMA_HOST env var. If OLLAMA_API_KEY is set it's sent as a Bearer
# token (only needed if talking directly to Ollama's cloud endpoint instead
# of a local instance that's already done `ollama signin`).
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY")


def ollama_chat(model: str, system: str, user: str, schema: dict[str, Any] | None = None) -> str:
    """Calls Ollama's /api/chat (local or cloud) and returns the response text.

    With a schema, Ollama constrains the output to it (structured outputs).
    """
    request: dict[str, Any] = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if schema:
        request["format"] = schema
    body = json.dumps(request).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if OLLAMA_API_KEY:
        headers["Authorization"] = f"Bearer {OLLAMA_API_KEY}"
    req = urllib.request.Request(
        f"{OLLAMA_HOST}/api/chat", data=body, headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"[!] Can't reach Ollama at {OLLAMA_HOST} ({exc}).\n"
            "    Local: start the server with `ollama serve`.\n"
            "    Cloud: run `ollama signin` (tags with -cloud suffix), "
            "or set OLLAMA_HOST/OLLAMA_API_KEY for the direct cloud endpoint."
        )
    return data["message"]["content"]


def parse_answer(text: str) -> list[Any]:
    """Model reply -> list of per-caption items ({"posts": [...]} or a bare list)."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    parsed = json.loads(text)
    if isinstance(parsed, dict):
        parsed = parsed.get("posts")
    if not isinstance(parsed, list):
        raise ValueError("expected a list of posts")
    return parsed


def tag_posts(
    posts: list[Post], taxonomy: dict[str, Any], model: str, batch_size: int, cache_path: Path
) -> None:
    cache: dict[str, dict[str, list[str]]] = {}
    if cache_path.exists():
        cache = json.loads(cache_path.read_text(encoding="utf-8"))

    axes = axis_names(taxonomy)
    valid = {a: set(axis_values(taxonomy[a])) for a in axes}
    system = build_tagging_prompt(taxonomy)
    # Ollama's cloud models don't support structured outputs yet: they rely on
    # the prompt plus the validation below.
    schema = None if model.endswith("-cloud") else response_schema(taxonomy)

    todo = []
    for p in posts:
        digest = hashlib.sha1(clean_caption(p.caption).encode()).hexdigest()[:16]
        if digest in cache:
            p.tags = cache[digest]
        elif clean_caption(p.caption):
            todo.append((digest, p))

    if not todo:
        log("[i] All tags were already cached.")
        return

    log(f"[i] To tag: {len(todo)} post(s) in {(len(todo) + batch_size - 1) // batch_size} call(s).")

    for start in range(0, len(todo), batch_size):
        batch = todo[start : start + batch_size]
        payload = [{"id": digest, "caption": clean_caption(p.caption)} for digest, p in batch]
        parsed = None
        for attempt in (1, 2):  # one retry on malformed output
            try:
                parsed = parse_answer(
                    ollama_chat(model, system, json.dumps(payload, ensure_ascii=False), schema)
                )
                break
            except SystemExit:
                raise
            except Exception as exc:  # noqa: BLE001
                log(f"[!] Batch {start // batch_size + 1} attempt {attempt} failed ({exc}).")
        if parsed is None:
            log(f"[!] Batch {start // batch_size + 1} skipped.")
            continue

        by_id = {str(item.get("id")): item for item in parsed if isinstance(item, dict)}
        for digest, post in batch:
            item = by_id.get(digest)
            if not item:
                continue
            tags: dict[str, list[str]] = {}
            for axis in axes:
                raw = item.get(axis) or []
                if isinstance(raw, str):
                    raw = [raw]
                kept = [v for v in raw if v in valid[axis]]
                if not taxonomy[axis].get("multi"):
                    kept = kept[:1]
                tags[axis] = kept
            post.tags = tags
            cache[digest] = tags

        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
        log(f"    batch {start // batch_size + 1} ok")
