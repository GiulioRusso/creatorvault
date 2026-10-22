#!/usr/bin/env python3
"""
Generates the synthetic archive fixtures in tests/fixtures/archive/.

Everything here is invented: no real export or insights data. Rerun after
changing it and commit both this script and its output:

    python tests/fixtures/make_fixtures.py

Posts (UTC) and what each one exercises:
  p1  2024-06-10 16:00  single image
  p2  2024-07-04 18:30  carousel (3 images)
  p3  2024-09-15 20:00  video, stored outside its declared uri (rglob fallback)
  p4  2024-11-20 17:00  mojibake caption, insights row duplicated across files
  p5  2025-02-14 21:00  emoji caption already in correct UTF-8
  p6  2025-04-01 15:00  missing caption
  p7  2023-05-05 12:00  outside the insights window
  p8  2025-06-20 16:00  ambiguous pair with p9 (30 min apart)
  p9  2025-06-20 16:30
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from openpyxl import Workbook

OUT = Path(__file__).parent / "archive"
ZIP_DATE = (2025, 1, 1, 0, 0, 0)


def ts(*args: int) -> int:
    return int(datetime(*args, tzinfo=UTC).timestamp())


def mojibake(s: str) -> str:
    """What Instagram's export does to UTF-8 text."""
    return s.encode("utf-8").decode("latin-1")


# (key, timestamp, caption, [(uri, stored_at or None)])
POSTS = [
    (
        "p1",
        ts(2024, 6, 10, 16),
        "Apollo 11 lands on the Moon\nThe Eagle has landed. #apollo #space",
        [("media/posts/202406/p1.jpg", None)],
    ),
    (
        "p2",
        ts(2024, 7, 4, 18, 30),
        "Saturn V on the pad\nThree frames from the rollout. #nasa",
        [(f"media/posts/202407/p2_{i}.jpg", None) for i in (1, 2, 3)],
    ),
    (
        "p3",
        ts(2024, 9, 15, 20),
        "Countdown footage from Gemini 4",
        [("media/reels/202409/p3.mp4", "your_instagram_activity/media/reels/202409/p3.mp4")],
    ),
    (
        "p4",
        ts(2024, 11, 20, 17),
        mojibake("L'equipaggio è tornato a casa 🚀\nRientro dell'Apollo 13."),
        [("media/posts/202411/p4.jpg", None)],
    ),
    (
        "p5",
        ts(2025, 2, 14, 21),
        "🚀🌕 Happy Valentine's from the Moon",
        [("media/posts/202502/p5.png", None)],
    ),
    ("p6", ts(2025, 4, 1, 15), "", [("media/posts/202504/p6.jpg", None)]),
    ("p7", ts(2023, 5, 5, 12), "Voyager 1 golden record", [("media/posts/202305/p7.jpg", None)]),
    ("p8", ts(2025, 6, 20, 16), "Skylab day one launch", [("media/posts/202506/p8.jpg", None)]),
    (
        "p9",
        ts(2025, 6, 20, 16, 30),
        "Skylab day two crew portrait",
        [("media/posts/202506/p9.jpg", None)],
    ),
]


def posts_json() -> list[dict]:
    entries = []
    for _key, t, caption, media in POSTS:
        if len(media) > 1:
            entries.append(
                {
                    "media": [{"uri": u, "creation_timestamp": t, "title": ""} for u, _ in media],
                    "title": caption,
                    "creation_timestamp": t,
                }
            )
        else:
            entries.append(
                {"media": [{"uri": media[0][0], "creation_timestamp": t, "title": caption}]}
            )
    # An entry with no media is skipped by the parser
    entries.append({"media": [], "title": "empty", "creation_timestamp": ts(2024, 1, 1)})
    return entries


def write_zip(path: Path) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:

        def add(name: str, data: bytes) -> None:
            zf.writestr(zipfile.ZipInfo(name, ZIP_DATE), data)

        add(
            "your_instagram_activity/content/posts_1.json",
            json.dumps(posts_json(), indent=2).encode("utf-8"),
        )
        for key, _t, _c, media in POSTS:
            for uri, stored_at in media:
                add(stored_at or uri, f"fake-media-{key}-{Path(uri).name}".encode())


# Insights rows are in America/Los_Angeles local time, like Meta's export.
CSV_2024 = [
    # (publish time, permalink, description, reach, likes, comments, shares, saves, follows)
    (
        "2024-06-10 09:05",
        "https://example.com/p/p1",
        "Apollo 11 lands on the Moon",
        12000,
        900,
        40,
        30,
        120,
        15,
    ),
    (
        "2024-07-04 11:30",
        "https://example.com/p/p2",
        "Saturn V on the pad",
        8000,
        400,
        10,
        5,
        60,
        4,
    ),
    (
        "09/15/2024 13:00",
        "https://example.com/p/p3",
        "Countdown footage",
        20000,
        1500,
        80,
        200,
        300,
        40,
    ),
    (
        "2024-11-20 09:00",
        "https://example.com/p/p4",
        "Rientro dell'Apollo 13",
        5000,
        150,
        5,
        2,
        10,
        1,
    ),
    (
        "2024-12-25 10:00",
        "https://example.com/p/ghost",
        "No post matches this row",
        1000,
        10,
        0,
        0,
        0,
        0,
    ),
]

XLSX_2025 = [
    # (publish time, permalink, description, reach, likes, comments, shares, saves, engagement)
    (
        datetime(2024, 11, 20, 9, 0),
        "https://example.com/p/p4",
        "Rientro dell'Apollo 13",
        5000,
        150,
        5,
        2,
        10,
        167,
    ),
    (
        datetime(2025, 2, 14, 13, 0),
        "https://example.com/p/p5",
        "Happy Valentine's",
        9000,
        700,
        30,
        20,
        50,
        800,
    ),
    (datetime(2025, 4, 1, 8, 0), "https://example.com/p/p6", "", 3000, 90, 2, 1, 4, 97),
    (datetime(2025, 6, 20, 9, 15), "https://example.com/p/p8", "", 4000, 200, 8, 3, 9, 220),
    (
        datetime(2025, 6, 20, 9, 30),
        "https://example.com/p/p9",
        "Skylab day two crew portrait",
        4500,
        260,
        9,
        4,
        12,
        285,
    ),
]


def write_csv(path: Path) -> None:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["Instagram posts export", "", "", "", "", "", "", "", ""])
    w.writerow(
        [
            "Publish time",
            "Permalink",
            "Description",
            "Reach",
            "Likes",
            "Comments",
            "Shares",
            "Saves",
            "Follows",
        ]
    )
    w.writerows(CSV_2024)
    path.write_text(buf.getvalue(), encoding="utf-8-sig")


def write_xlsx(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.append(
        [
            "Ora di pubblicazione",
            "Link permanente",
            "Descrizione",
            "Copertura",
            "Mi piace",
            "Commenti",
            "Condivisioni",
            "Salvataggi",
            "Interazioni",
        ]
    )
    for row in XLSX_2025:
        ws.append(list(row))
    wb.properties.created = wb.properties.modified = datetime(2025, 1, 1)
    wb.save(path)


TAXONOMY = {
    "_instructions": [
        "You are an archivist cataloguing posts from a page about space exploration.",
        "For each caption, assign the correct values for every axis of the taxonomy below.",
    ],
    "program": {
        "multi": False,
        "description": "Space program the post is about",
        "values": ["apollo", "gemini", "saturn", "skylab", "voyager"],
    },
    "angle": {
        "multi": True,
        "description": "Storytelling angle",
        "values": ["anecdote", "photo", "video", "quote"],
    },
}


def main() -> None:
    (OUT / "insights").mkdir(parents=True, exist_ok=True)
    write_zip(OUT / "instagram-export.zip")
    write_csv(OUT / "insights" / "2024.csv")
    write_xlsx(OUT / "insights" / "2025.xlsx")
    (OUT / "taxonomy.json").write_text(json.dumps(TAXONOMY, indent=2) + "\n", encoding="utf-8")
    print(f"Fixtures written to {OUT}")


if __name__ == "__main__":
    main()
