"""Shared utilities — retry logic, color parsing, A1 notation, index math."""

import json
import logging
import re
import random
import time
from typing import Any

from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)


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
            if e.resp.status in (429, 500, 502, 503) and attempt < max_retries:
                wait = min(((2 ** attempt) + random.random()), 64)
                logger.debug("API error %s, retrying in %.1fs...", e.resp.status, wait)
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


def hex_to_rgb(hex_color: str) -> dict:
    """Convert '#RRGGBB' or '#RGB' to Google API color format {red, green, blue} (0-1 floats)."""
    h = hex_color.strip().lstrip("#")
    if len(h) == 3:
        h = h[0]*2 + h[1]*2 + h[2]*2
    if len(h) != 6:
        raise ValueError(f"Invalid hex color: {hex_color}")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return {"red": r / 255.0, "green": g / 255.0, "blue": b / 255.0}


def rgb_to_hex(color: dict) -> str:
    """Convert Google API color {red, green, blue} (0-1 floats) to '#RRGGBB' hex string."""
    r = int(round(color.get("red", 0) * 255))
    g = int(round(color.get("green", 0) * 255))
    b = int(round(color.get("blue", 0) * 255))
    return f"#{r:02x}{g:02x}{b:02x}"


NARROW_CHARS = set("iIlj1|!.,;:'`() ")
WIDE_CHARS = set("MWmw@%&ÆŒØQ")

# 15% safety margin — Google Slides renders wider than metrics due to
# kerning, letter-spacing, and anti-aliasing differences across fonts.
_RENDER_SAFETY = 1.15

def estimate_text_width_pt(text: str, font_pt: float) -> float:
    """Estimate rendered text width in points for proportional fonts.

    Uses per-character width classes with a safety margin for rendering.
    Returns width of the longest line if text contains newlines.
    """
    if not text:
        return 0.0
    max_w = 0.0
    for line in text.split("\n"):
        w = 0.0
        for ch in line:
            if ch in NARROW_CHARS:
                w += font_pt * 0.38
            elif ch in WIDE_CHARS:
                w += font_pt * 0.78
            elif ch.isupper():
                w += font_pt * 0.66
            else:
                w += font_pt * 0.55
        max_w = max(max_w, w)
    return max_w * _RENDER_SAFETY


def estimate_text_height_pt(text: str, font_pt: float) -> float:
    """Estimate rendered text height in points (line count × line height)."""
    if not text:
        return 0.0
    num_lines = text.count("\n") + 1
    return num_lines * font_pt * 1.4


def col_to_index(col: str) -> int:
    """Convert column letter to 0-based index: A->0, Z->25, AA->26."""
    result = 0
    for c in col.upper():
        result = result * 26 + (ord(c) - ord("A") + 1)
    return result - 1


def index_to_col(index: int) -> str:
    """Convert 0-based column index to letter: 0->A, 25->Z, 26->AA, 702->AAA."""
    result = ""
    index += 1
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def quote_sheet_name(name: str) -> str:
    """Quote sheet names that contain spaces or special characters for A1 notation."""
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
        return name
    return "'" + name.replace("'", "''") + "'"


def parse_a1_range(range_str: str, sheet_id: int) -> dict:
    """Parse A1 notation to GridRange dict for batchUpdate requests."""
    cell_range = range_str.split("!", 1)[-1] if "!" in range_str else range_str
    parts = cell_range.split(":")
    grid: dict = {"sheetId": sheet_id}

    m = re.match(r"^([A-Z]*)(\d*)$", parts[0].upper())
    if m:
        col, row = m.group(1), m.group(2)
        if col:
            grid["startColumnIndex"] = col_to_index(col)
        if row:
            grid["startRowIndex"] = int(row) - 1

    if len(parts) > 1:
        m = re.match(r"^([A-Z]*)(\d*)$", parts[1].upper())
        if m:
            col, row = m.group(1), m.group(2)
            if col:
                grid["endColumnIndex"] = col_to_index(col) + 1
            if row:
                grid["endRowIndex"] = int(row)

    return grid


def parse_values(values) -> list[list]:
    """Accept values as list[list] or JSON string (LLMs sometimes emit JSON strings)."""
    if isinstance(values, str):
        try:
            values = json.loads(values)
        except json.JSONDecodeError:
            raise ValueError("values must be a 2D array or valid JSON string")
    if not isinstance(values, list) or (values and not isinstance(values[0], list)):
        raise ValueError("values must be a 2D array (list of lists)")
    return values


def resolve_sheet_id(service, spreadsheet_id: str, sheet_name: str | None) -> tuple[int, str]:
    """Resolve sheet name to numeric sheetId. Returns (sheetId, title). Defaults to first sheet."""
    meta = execute_with_retry(
        service.spreadsheets().get(spreadsheetId=spreadsheet_id, fields="sheets.properties")
    )
    sheets = meta.get("sheets", [])
    if not sheets:
        raise ValueError("Spreadsheet has no sheets")
    if sheet_name is None:
        props = sheets[0]["properties"]
        return props["sheetId"], props["title"]
    for s in sheets:
        if s["properties"]["title"] == sheet_name:
            return s["properties"]["sheetId"], s["properties"]["title"]
    available = [s["properties"]["title"] for s in sheets]
    raise ValueError(f"Sheet '{sheet_name}' not found. Available: {available}")
