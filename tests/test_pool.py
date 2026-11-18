"""Content pool: one folder per content with post.md + media, no publication dates."""

import re
import shutil
from datetime import UTC, datetime

import yaml
from harness import write_config

from creatorvault import cli
from creatorvault.hashtags import HASHTAG, HashtagConfig, ready_caption
from creatorvault.models import Content, Publication
from creatorvault.pool import write_pool


def make_contents(tmp_path):
    image, video = tmp_path / "photo.JPG", tmp_path / "video.mp4"
    image.write_bytes(b"synthetic image")
    video.write_bytes(b"synthetic video")
    hashtags = HashtagConfig(
        strategy="pool", pool=["space", "history", "science", "nasa", "moon", "exploration"]
    )
    contents = []
    for n, media, kind in ((1, [image, video], "posts"), (2, [video], "reels"), (3, [], "posts")):
        caption = f"Jul. 20, 1969: Same title.\n#old #unwanted #too #many #original #tags {n}"
        pub = Publication(
            str(n), datetime(2024, 1, n, tzinfo=UTC), caption, media=media, content_type=kind
        )
        pub.top_percent = 10 * n
        content = Content([pub], tags={"program": ["apollo"]})
        content.ready_caption = ready_caption(caption, content.tags, hashtags)
        contents.append(content)
    return contents


def front(text: str) -> dict:
    return yaml.safe_load(re.match(r"---\n(.*?)\n---\n", text, re.S)[1])


def test_pool_folders_media_and_no_dates(tmp_path):
    out = tmp_path / "pool"
    write_pool(make_contents(tmp_path), out)
    folders = sorted(p.name for p in out.iterdir() if p.is_dir())
    assert folders == [
        "jul-20-1969-same-title",
        "jul-20-1969-same-title-2",
        "jul-20-1969-same-title-3",
    ]
    first = out / folders[0]
    assert sorted(p.name for p in first.iterdir()) == ["01.jpg", "02.mp4", "post.md"]
    text = (first / "post.md").read_text()
    fm = front(text)
    assert fm["origin"] == "archive"
    assert fm["media"] == ["01.jpg", "02.mp4"] and fm["format"] == "carousel"
    assert fm["tags"] == ["program/apollo"] and fm["top_percent"] == 10
    assert fm["content_type"] == "posts"
    assert front((out / folders[1] / "post.md").read_text())["content_type"] == "reels"
    assert "![](01.jpg)" in text and "![](02.mp4)" in text
    description = text.split("```text\n")[1].split("\n```")[0]
    assert len(HASHTAG.findall(description)) == 5 and "#old" not in description
    assert "Jul. 20, 1969" in description  # historical dates belong to the story
    for path in out.rglob("*"):
        if path.is_file():
            assert "2024" not in path.name and "2024" not in path.read_text(errors="ignore")


def test_pool_rebuild_removes_only_stale_generated_files(tmp_path):
    out = tmp_path / "pool"
    contents = make_contents(tmp_path)
    write_pool(contents, out)
    mine = out / "my-idea"
    mine.mkdir()
    (mine / "post.md").write_text("hands off")
    (out / "jul-20-1969-same-title" / "old.jpg").write_bytes(b"stale media")
    write_pool(contents[:1], out)
    assert sorted(p.name for p in out.iterdir() if p.is_dir()) == [
        "jul-20-1969-same-title",
        "my-idea",
    ]
    assert not (out / "jul-20-1969-same-title" / "old.jpg").exists()
    # A hand-written post holding a slug the build wants is never overwritten.
    shutil.rmtree(out / "jul-20-1969-same-title")
    (out / "jul-20-1969-same-title").mkdir()
    (out / "jul-20-1969-same-title" / "post.md").write_text("---\norigin: manual\n---\nmine")
    write_pool(contents[:1], out)
    assert (out / "jul-20-1969-same-title" / "post.md").read_text().endswith("mine")
    assert (out / "jul-20-1969-same-title-2" / "post.md").is_file()


def test_pool_title_never_uses_the_publication_date(tmp_path):
    content = Content([Publication("9", datetime(2024, 3, 3, tzinfo=UTC), "#only #tags")])
    write_pool([content], tmp_path / "pool")
    (note,) = (tmp_path / "pool").glob("*/post.md")
    assert note.parent.name == f"post-{content.id}" and "2024" not in note.read_text()


def test_build_writes_pool_inside_vault(tmp_path):
    path = write_config("tags", tmp_path)
    cfg = yaml.safe_load(path.read_text())
    cfg["tagging"]["enabled"] = False
    path.write_text(yaml.safe_dump(cfg))
    cli.main(["build", "--config", str(path)])
    vault = tmp_path / "vault"
    posts = list((vault / "pool").glob("*/post.md"))
    notes = list((vault / "archive").glob("*.md"))
    assert len(posts) == len(notes) == 9
    # Archive notes embed the pool's media instead of copying them again.
    text = "".join(n.read_text() for n in notes)
    assert "![[pool/" in text and 'pool: "[[pool/' in text
