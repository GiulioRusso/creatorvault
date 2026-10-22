"""Tagging: schema generation, answer parsing, retry, cache, Ollama errors."""

from __future__ import annotations

import json
import socket
from datetime import UTC, datetime

import pytest
from harness import FIXTURES, mock_ollama

from creatorvault.models import Post
from creatorvault.tagging import ollama
from creatorvault.tagging.taxonomy import build_tagging_prompt, response_schema

TAXONOMY = json.loads((FIXTURES / "taxonomy.json").read_text(encoding="utf-8"))


def posts() -> list[Post]:
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    return [
        Post(key="1", timestamp=ts, caption="Apollo 11 #moon"),
        Post(key="2", timestamp=ts, caption="Gemini 4 spacewalk"),
        Post(key="3", timestamp=ts, caption="#onlyhashtags"),
    ]


def test_schema_from_taxonomy():
    schema = response_schema(TAXONOMY)
    item = schema["properties"]["posts"]["items"]
    assert item["required"] == ["id", "program", "angle"]
    assert item["properties"]["program"]["items"]["enum"] == TAXONOMY["program"]["values"]
    assert item["properties"]["program"]["maxItems"] == 1  # multi: false
    assert "maxItems" not in item["properties"]["angle"]  # multi: true


def test_prompt_lists_axes_and_format():
    prompt = build_tagging_prompt(TAXONOMY)
    assert "- program (at most one value)" in prompt
    assert "- angle (multiple values allowed)" in prompt
    assert '{"posts": [{"id": "<received id>", "program": [], "angle": []}]}' in prompt


@pytest.mark.parametrize(
    "text",
    [
        '{"posts": [{"id": "a"}]}',
        '[{"id": "a"}]',
        '```json\n[{"id": "a"}]\n```',
    ],
)
def test_parse_answer(text):
    assert ollama.parse_answer(text) == [{"id": "a"}]


@pytest.mark.parametrize("text", ["not json", '{"other": 1}', "42"])
def test_parse_answer_rejects(text):
    with pytest.raises(ValueError):
        ollama.parse_answer(text)


class FakeChat:
    """Replays canned replies; answers with valid tags once they run out."""

    def __init__(self, *replies: str):
        self.replies = list(replies)
        self.calls: list[dict | None] = []

    def __call__(self, model, system, user, schema=None):
        self.calls.append(schema)
        if self.replies:
            return self.replies.pop(0)
        items = json.loads(user)
        return json.dumps(
            {
                "posts": [
                    {"id": i["id"], "program": ["apollo", "gemini"], "angle": ["photo", "x"]}
                    for i in items
                ]
            }
        )


def test_tags_validated_and_cached(tmp_path, monkeypatch):
    chat = FakeChat()
    monkeypatch.setattr(ollama, "ollama_chat", chat)
    cache = tmp_path / "cache.json"

    first = posts()
    ollama.tag_posts(first, TAXONOMY, "llama3.2:3b", 10, cache)
    assert len(chat.calls) == 1 and chat.calls[0] == response_schema(TAXONOMY)
    # Single-value axis truncated, unknown values dropped, empty caption skipped
    assert first[0].tags == {"program": ["apollo"], "angle": ["photo"]}
    assert first[2].tags == {}

    second = posts()
    ollama.tag_posts(second, TAXONOMY, "llama3.2:3b", 10, cache)
    assert len(chat.calls) == 1  # all from cache
    assert second[1].tags == first[1].tags


def test_cloud_model_gets_no_schema(tmp_path, monkeypatch):
    chat = FakeChat()
    monkeypatch.setattr(ollama, "ollama_chat", chat)
    ollama.tag_posts(posts(), TAXONOMY, "qwen3:235b-cloud", 10, tmp_path / "c.json")
    assert chat.calls == [None]


def test_retry_once_on_malformed_json(tmp_path, monkeypatch):
    chat = FakeChat("oops, not json")
    monkeypatch.setattr(ollama, "ollama_chat", chat)
    p = posts()
    ollama.tag_posts(p, TAXONOMY, "m", 10, tmp_path / "c.json")
    assert len(chat.calls) == 2 and p[0].tags["program"] == ["apollo"]


def test_batch_skipped_after_two_failures(tmp_path, monkeypatch):
    chat = FakeChat("bad", "still bad")
    monkeypatch.setattr(ollama, "ollama_chat", chat)
    p = posts()
    ollama.tag_posts(p, TAXONOMY, "m", 10, tmp_path / "c.json")
    assert len(chat.calls) == 2 and p[0].tags == {}


def test_ollama_chat_against_mock_server(monkeypatch):
    with mock_ollama() as host:
        monkeypatch.setattr(ollama, "OLLAMA_HOST", host)
        monkeypatch.setattr(ollama, "OLLAMA_API_KEY", "secret")
        text = ollama.ollama_chat("m", "sys", json.dumps([{"id": "ab", "caption": "x"}]), {})
    assert ollama.parse_answer(text)[0]["id"] == "ab"


def test_ollama_unreachable_is_a_clean_error(monkeypatch):
    with socket.socket() as s:  # grab a free port, then close it
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setattr(ollama, "OLLAMA_HOST", f"http://127.0.0.1:{port}")
    with pytest.raises(SystemExit, match="Can't reach Ollama"):
        ollama.ollama_chat("m", "sys", "[]")
