"""Document formatting utilities — cleanup, audit, and highlight."""

from __future__ import annotations

from shared.utils import utf16_len
from . import docs_service


def highlight_text(document_id: str, search_text: str, color: dict) -> dict:
    """Find text in doc and apply background highlight color.

    Uses actual document element indices instead of string.find() to correctly
    handle documents with tables (which occupy index space).
    """
    doc_data = docs_service.read_document_raw(document_id)
    tabs = doc_data.get("tabs", [])
    body = tabs[0].get("documentTab", {}).get("body", {}) if tabs else doc_data.get("body", {})

    requests = []
    count = 0

    for elem in body.get("content", []):
        para = elem.get("paragraph")
        if not para:
            continue
        for pe in para.get("elements", []):
            tr = pe.get("textRun")
            if not tr:
                continue
            content = tr.get("content", "")
            elem_start = pe.get("startIndex", 0)
            start = 0
            while True:
                idx = content.find(search_text, start)
                if idx == -1:
                    break
                doc_start = elem_start + idx
                doc_end = doc_start + utf16_len(search_text)
                requests.append({
                    "updateTextStyle": {
                        "range": {"startIndex": doc_start, "endIndex": doc_end},
                        "textStyle": {
                            "backgroundColor": {"color": {"rgbColor": color}}
                        },
                        "fields": "backgroundColor",
                    }
                })
                count += 1
                start = idx + len(search_text)

    if requests:
        docs_service.batch_update(document_id, requests)

    return {"occurrences_highlighted": count}


def cleanup_document(document_id: str) -> dict:
    """Fix common formatting issues: remove consecutive blank paragraphs."""
    doc_data = docs_service.read_document_raw(document_id)
    tabs = doc_data.get("tabs", [])
    body = tabs[0].get("documentTab", {}).get("body", {}) if tabs else doc_data.get("body", {})

    requests = []
    issues_fixed = 0
    content = body.get("content", [])
    prev_was_empty = False

    for elem in reversed(content):
        para = elem.get("paragraph")
        if not para:
            prev_was_empty = False
            continue

        text = ""
        for pe in para.get("elements", []):
            tr = pe.get("textRun")
            if tr:
                text += tr.get("content", "")

        is_empty = text.strip() == ""

        if is_empty and prev_was_empty:
            start = elem.get("startIndex", 0)
            end = elem.get("endIndex", 0)
            if start > 0 and end > start:
                requests.append({
                    "deleteContentRange": {
                        "range": {"startIndex": start, "endIndex": end}
                    }
                })
                issues_fixed += 1

        prev_was_empty = is_empty

    if requests:
        docs_service.batch_update(document_id, requests)

    return {"issues_fixed": issues_fixed}


def audit_document(document_id: str) -> dict:
    """Check document for formatting issues and return a report."""
    doc_data = docs_service.read_document_raw(document_id)
    tabs = doc_data.get("tabs", [])
    body = tabs[0].get("documentTab", {}).get("body", {}) if tabs else doc_data.get("body", {})

    issues = []
    content = body.get("content", [])
    consecutive_empty = 0
    heading_count = {"HEADING_1": 0, "HEADING_2": 0, "HEADING_3": 0}
    fonts_used = set()
    total_paragraphs = 0
    total_tables = 0

    for elem in content:
        para = elem.get("paragraph")
        if para:
            total_paragraphs += 1
            style = para.get("paragraphStyle", {})
            named = style.get("namedStyleType", "NORMAL_TEXT")
            if named in heading_count:
                heading_count[named] += 1

            text = ""
            for pe in para.get("elements", []):
                tr = pe.get("textRun")
                if tr:
                    text += tr.get("content", "")
                    ts = tr.get("textStyle", {})
                    font = ts.get("weightedFontFamily", {}).get("fontFamily")
                    if font:
                        fonts_used.add(font)

            if text.strip() == "":
                consecutive_empty += 1
                if consecutive_empty >= 3:
                    issues.append(f"3+ consecutive blank paragraphs at index {elem.get('startIndex', '?')}")
            else:
                consecutive_empty = 0

        if "table" in elem:
            total_tables += 1

    if len(fonts_used) > 3:
        issues.append(f"Too many fonts ({len(fonts_used)}): {', '.join(sorted(fonts_used))}")

    return {
        "document_id": document_id,
        "total_paragraphs": total_paragraphs,
        "total_tables": total_tables,
        "headings": heading_count,
        "fonts_used": sorted(fonts_used),
        "issues": issues if issues else ["No issues found"],
    }
