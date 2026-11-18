"""Local review decisions are cached, validated and constrained by real source evidence."""

import json
from datetime import UTC, datetime, timedelta

import pytest
import yaml
from harness import write_config

from creatorvault import cli
from creatorvault.dedup import DedupConfig, pub_ref
from creatorvault.join import join_posts
from creatorvault.models import Content, Publication
from creatorvault.review import ReviewConfig, Reviewer, check_local, review_duplicates, review_joins
from creatorvault.tagging import ollama


def reviewer(tmp_path, monkeypatch, answers):
    calls = []
    replies = iter(answers)
    monkeypatch.setattr(ollama, "check_model", lambda _: "ok")
    monkeypatch.setattr(ollama, "OLLAMA_HOST", "http://localhost:11434")

    def chat(model, system, user, schema):
        calls.append(json.loads(user))
        answer = next(replies)
        return answer if isinstance(answer, str) else json.dumps(answer)

    monkeypatch.setattr(ollama, "ollama_chat", chat)
    return Reviewer(ReviewConfig(enabled=True), tmp_path / "reviews.json"), calls


def decision(action="merge", target=None, confidence=0.95):
    return {
        "action": action,
        "target": target,
        "confidence": confidence,
        "reason": "Evidence supports the decision.",
    }


def pub(n, **kwargs):
    return Publication(str(n), datetime(2024, 1, n, tzinfo=UTC), f"Synthetic caption {n}", **kwargs)


def test_cached_decisions_reapply_current_confidence_threshold(tmp_path, monkeypatch):
    worker, calls = reviewer(tmp_path, monkeypatch, [decision(confidence=0.8)])
    evidence = {"reference": "pair", "a": "caption", "b": "same content"}
    assert worker.decide("dedup", evidence, ["merge", "separate"], [])["action"] == "defer"
    fresh = Reviewer(ReviewConfig(enabled=True, min_confidence=0.7), worker.path)
    assert fresh.decide("dedup", evidence, ["merge", "separate"], [])["action"] == "merge"
    assert len(calls) == 1 and fresh.audit[0]["reference"] == "pair"


def test_malformed_or_invented_targets_are_never_applied(tmp_path, monkeypatch):
    worker, calls = reviewer(tmp_path, monkeypatch, ["not JSON", decision("match", "invented")])
    result = worker.decide("join", {"reference": "row"}, ["match", "unmatched"], ["real-id"])
    assert result["action"] == "defer" and len(calls) == 2


def test_only_local_models_are_used(monkeypatch):
    monkeypatch.setattr(ollama, "OLLAMA_HOST", "https://remote.example.com")
    with pytest.raises(SystemExit, match="local model"):
        check_local("llama3.2:3b")
    monkeypatch.setattr(ollama, "OLLAMA_HOST", "http://localhost:11434")
    with pytest.raises(SystemExit, match="local model"):
        check_local("model-cloud")


def test_join_resolution_copies_only_source_metrics_without_overwriting(tmp_path, monkeypatch):
    a, b = pub(1), pub(1, content_type="reels")
    b.key = "reel-1"
    row = {
        "publish_time": a.timestamp,
        "description": a.caption,
        "permalink": "https://example.com/post",
        "metrics": {"reach": 123},
        "content_type": "posts",
    }
    a.metrics = {"reach": 99}
    rows = [{"insight_index": 0, "issue": "post already matched"}]
    worker, calls = reviewer(tmp_path, monkeypatch, [decision("unmatched")])
    review_joins([a, b], [row], rows, worker)
    assert a.metrics == {"reach": 99} and b.metrics == {}
    assert calls[0]["candidates"] == []
    a.metrics = {}
    worker, _ = reviewer(tmp_path, monkeypatch, [decision("match", "1")])
    review_joins([a, b], [row], rows, worker)
    assert a.metrics == row["metrics"] and a.metrics is not row["metrics"]
    assert a.permalink == row["permalink"]


def test_distant_repost_cannot_receive_another_publications_metrics(tmp_path, monkeypatch):
    a = pub(1)
    rec = {
        "publish_time": a.timestamp + timedelta(days=20),
        "description": a.caption,
        "permalink": None,
        "metrics": {"reach": 1},
    }
    rows = join_posts([a], [rec], 90)
    worker, calls = reviewer(tmp_path, monkeypatch, [decision("unmatched")])
    review_joins([a], [rec], rows, worker)
    assert calls[0]["candidates"] == [] and not a.metrics


def test_model_cannot_override_nasa_conflicts_or_transitive_splits(tmp_path, monkeypatch):
    contents = [Content([pub(1)], photo_ids=["A"]), Content([pub(2)], photo_ids=["B"])]
    rows = [
        {
            "a_ref": pub_ref(contents[0].first),
            "b_ref": pub_ref(contents[1].first),
            "similarity": "0.8",
        }
    ]
    worker, _ = reviewer(tmp_path, monkeypatch, [decision()])
    cfg = DedupConfig(overrides=tmp_path / "none.yaml")
    assert len(review_duplicates(contents, rows, worker, cfg)) == 2
    assert worker.audit[-1]["action"] == "blocked"

    contents = [Content([pub(n)]) for n in (1, 2, 3)]
    cfg.overrides.write_text(
        yaml.safe_dump({"split": [[pub_ref(contents[0].first), pub_ref(contents[1].first)]]})
    )
    rows = [
        {
            "a_ref": pub_ref(contents[a].first),
            "b_ref": pub_ref(contents[b].first),
            "similarity": "0.8",
        }
        for a, b in ((0, 2), (2, 1))
    ]
    worker, _ = reviewer(tmp_path, monkeypatch, [decision(), decision()])
    merged = review_duplicates(contents, rows, worker, cfg)
    assert sorted(len(c.publications) for c in merged) == [1, 2]
    assert worker.audit[-1]["action"] == "blocked"


def test_reposted_pairs_are_reviewed_once_and_deferred_without_manual_flags(tmp_path, monkeypatch):
    contents = [Content([pub(1)]), Content([pub(2)])]
    row = {
        "a_ref": pub_ref(contents[0].first),
        "b_ref": pub_ref(contents[1].first),
        "similarity": "0.8",
    }
    worker, calls = reviewer(tmp_path, monkeypatch, [decision(confidence=0.1)])
    result = review_duplicates(
        contents, [row, row, row], worker, DedupConfig(overrides=tmp_path / "none")
    )
    assert len(calls) == 1 and len(result) == 2
    assert worker.audit[0]["action"] == "defer" and worker.audit[0]["source_rows"] == 3
    assert worker.audit[0]["outcome"] == "kept_separate"


def test_build_automates_doubts_without_manual_files(tmp_path, monkeypatch):
    worker, _ = reviewer(tmp_path, monkeypatch, [decision("unmatched")] * 20)
    path = write_config("tags", tmp_path)
    cfg = yaml.safe_load(path.read_text())
    cfg["tagging"]["enabled"] = False
    cfg["review"] = {"enabled": True}
    cfg["dedup"]["caption_maybe"] = 0.6
    path.write_text(yaml.safe_dump(cfg))
    cli.main(["build", "--config", str(path)])
    vault = tmp_path / "vault"
    assert not list(vault.glob("*.csv"))  # nothing to review by hand
    assert "## Decisions by the local model\n\n| case |" in (vault / "Review.md").read_text()
    assert all("Needs review" not in n.read_text() for n in (vault / "archive").glob("*.md"))


def test_unavailable_reviewer_degrades_unless_required(tmp_path, monkeypatch, capsys):
    def down(_model):
        raise SystemExit("[!] can't reach Ollama")

    monkeypatch.setattr(ollama, "check_model", down)
    monkeypatch.setattr(ollama, "OLLAMA_HOST", "http://localhost:11434")
    path = write_config("tags", tmp_path)
    cfg = yaml.safe_load(path.read_text())
    cfg["tagging"]["enabled"] = False
    cfg["review"] = {"enabled": True}
    path.write_text(yaml.safe_dump(cfg))
    cli.main(["build", "--config", str(path)])
    assert "Automated review skipped: can't reach Ollama" in capsys.readouterr().err
    cfg["tagging"]["required"] = True
    path.write_text(yaml.safe_dump(cfg))
    with pytest.raises(SystemExit, match="Automated review is required"):
        cli.main(["build", "--config", str(path)])


@pytest.mark.parametrize("raw", [{"min_confidence": 2}, {"enabled": "yes"}, {"unknown": True}])
def test_invalid_review_config(raw):
    with pytest.raises(SystemExit, match="review"):
        ReviewConfig.from_dict(raw, "model")
