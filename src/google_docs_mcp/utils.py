"""Index management, batch helpers, and retry logic for Google Docs API."""

import random
import time
import sys
from typing import Any

from googleapiclient.errors import HttpError


def utf16_len(text: str) -> int:
    """Google Docs uses UTF-16 code units for indices."""
    return len(text.encode("utf-16-le")) // 2


def reverse_requests(requests: list[dict]) -> list[dict]:
    """Sort batchUpdate requests by startIndex descending to avoid index shifts."""
    def _get_index(req: dict) -> int:
        for key, val in req.items():
            if isinstance(val, dict):
                loc = val.get("location", {})
                if "index" in loc:
                    return loc["index"]
                rng = val.get("range", {})
                if "startIndex" in rng:
                    return rng["startIndex"]
        return 0
    return sorted(requests, key=_get_index, reverse=True)


def execute_with_retry(request, max_retries: int = 5) -> Any:
    """Execute a Google API request with exponential backoff on 429/5xx."""
    for attempt in range(max_retries + 1):
        try:
            return request.execute()
        except HttpError as e:
            if e.resp.status in (429, 500, 503) and attempt < max_retries:
                wait = min(((2 ** attempt) + random.random()), 64)
                print(f"API error {e.resp.status}, retrying in {wait:.1f}s...", file=sys.stderr)
                time.sleep(wait)
            else:
                raise


def batch_update(docs_service, document_id: str, requests: list[dict], preserve_order: bool = False) -> dict:
    """Send a batchUpdate.

    By default, reverses request order by index (safe for modify-only operations).
    Set preserve_order=True when requests contain inserts followed by formatting
    (e.g., from markdown_to_requests) — these must execute in the given order.
    """
    if not requests:
        return {}
    reqs = requests if preserve_order else reverse_requests(requests)
    return execute_with_retry(
        docs_service.documents().batchUpdate(
            documentId=document_id,
            body={"requests": reqs},
        )
    )
