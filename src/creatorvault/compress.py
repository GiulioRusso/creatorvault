"""Shrink videos to the size of the reels Meta serves back (720x1280, H.264, ~0.8 Mbps).

Two-pass ffmpeg encode. An .mp4 is replaced in place; any other video gets a sibling .mp4 and
stays untouched. A file is kept as is when the encode would not make it smaller."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

VIDEO_EXT = {".mp4", ".mov", ".m4v"}


def find_videos(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        if p.is_dir():
            out += sorted(f for f in p.rglob("*") if f.suffix.lower() in VIDEO_EXT)
        elif p.is_file():
            out.append(p)
        else:
            raise SystemExit(f"[!] Not found: {p}")
    return out


def encode(src: Path, dst: Path, bitrate: str, audio: str, workdir: Path) -> None:
    video = [
        "-vf",
        "scale=w=720:h=1280:force_original_aspect_ratio=decrease:force_divisible_by=2",
        "-fpsmax", "30",
        "-c:v", "libx264", "-preset", "slow", "-b:v", bitrate, "-pix_fmt", "yuv420p",
        "-passlogfile", str(workdir / "pass"),
    ]  # fmt: skip
    base = ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(src), *video]
    subprocess.run([*base, "-pass", "1", "-an", "-f", "mp4", "/dev/null"], check=True)
    subprocess.run(
        [*base, "-pass", "2", "-c:a", "aac", "-b:a", audio, "-movflags", "+faststart", str(dst)],
        check=True,
    )


def compress(paths: list[Path], bitrate: str = "750k", audio: str = "64k") -> None:
    if not shutil.which("ffmpeg"):
        raise SystemExit("[!] ffmpeg not found. Install it (macOS: brew install ffmpeg).")
    videos = find_videos(paths)
    if not videos:
        raise SystemExit("[!] No videos found (.mp4, .mov, .m4v).")
    saved = 0
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        for src in videos:
            dst = src.with_suffix(".mp4")
            out = work / "out.mp4"
            try:
                encode(src, out, bitrate, audio, work)
            except subprocess.CalledProcessError:
                print(f"[!] failed   {src}")
                continue
            before, after = src.stat().st_size, out.stat().st_size
            if after >= before:
                print(f"[i] kept     {src} (already {before / 1e6:.1f} MB)")
                continue
            if dst.exists() and dst != src:
                print(f"[!] skipped  {src}: {dst.name} already exists")
                continue
            shutil.move(out, dst)
            saved += before - after
            print(f"[OK] {before / 1e6:6.1f} MB -> {after / 1e6:5.1f} MB  {dst}")
    print(f"[OK] {len(videos)} video(s), {saved / 1e6:.1f} MB saved")
