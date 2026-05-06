"""Search the curated draw.io shape library (58 generic presentation shapes)."""

from __future__ import annotations

import json
from pathlib import Path

_index: list[dict] | None = None
_INDEX_PATH = Path(__file__).parent / "shape-index.json"


def _load_index() -> list[dict]:
    global _index
    if _index is None:
        with open(_INDEX_PATH) as f:
            _index = json.load(f)
    return _index


def search_shapes(query: str, max_results: int = 10) -> list[dict]:
    """Search for draw.io shapes by keyword."""
    index = _load_index()
    query_lower = query.lower()
    terms = query_lower.split()

    scored: list[tuple[int, dict]] = []
    for item in index:
        title = (item.get("title") or "").lower()
        tags = (item.get("tags") or "").lower()
        searchable = title + " " + tags

        score = 0
        for term in terms:
            if term in title:
                score += 10
            if term in tags:
                score += 5
            if term == title:
                score += 20

        if score > 0:
            scored.append((score, item))

    scored.sort(key=lambda x: -x[0])
    return [
        {
            "title": item["title"],
            "style": item["style"],
            "width": item.get("w", 120),
            "height": item.get("h", 60),
        }
        for _, item in scored[:max_results]
    ]
