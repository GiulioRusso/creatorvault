"""compress: real ffmpeg encode on a synthetic clip, plus the error paths."""

from __future__ import annotations

import shutil
import subprocess

import pytest

from creatorvault import cli, compress

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


def make_clip(path, size="1080x1920", rate="20M"):
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s={size}:d=2:r=60",
         "-f", "lavfi", "-i", "sine=d=2", "-c:v", "libx264", "-b:v", rate, "-shortest", str(path)],
        check=True,
    )  # fmt: skip


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
         "stream=width,height,codec_name", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    return out.stdout.strip()


@needs_ffmpeg
def test_compress_shrinks_mp4_in_place_and_mov_to_sibling(tmp_path, capsys):
    big = tmp_path / "pool" / "a" / "01.mp4"
    big.parent.mkdir(parents=True)
    make_clip(big)
    mov = tmp_path / "pool" / "b.mov"
    make_clip(mov, size="1920x1080")
    before = big.stat().st_size

    cli.main(["compress", str(tmp_path / "pool")])

    assert big.stat().st_size < before
    assert probe(big) == "h264,720,1280"
    assert mov.exists() and probe(mov.with_suffix(".mp4")) == "h264,720,406"
    assert "2 video(s)" in capsys.readouterr().out


@needs_ffmpeg
def test_compress_keeps_files_already_small(tmp_path, capsys):
    small = tmp_path / "small.mp4"
    make_clip(small, size="320x568", rate="100k")
    data = small.read_bytes()
    compress.compress([small])
    assert small.read_bytes() == data
    assert "kept" in capsys.readouterr().out


def test_compress_errors(tmp_path, monkeypatch):
    with pytest.raises(SystemExit, match="Not found"):
        compress.find_videos([tmp_path / "missing.mp4"])
    monkeypatch.setattr(shutil, "which", lambda _: "/bin/ffmpeg")
    with pytest.raises(SystemExit, match="No videos"):
        compress.compress([tmp_path])
    monkeypatch.setattr(shutil, "which", lambda _: None)
    with pytest.raises(SystemExit, match="ffmpeg not found"):
        compress.compress([tmp_path])
