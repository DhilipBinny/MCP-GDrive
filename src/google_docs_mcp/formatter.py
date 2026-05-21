"""Document formatting utilities — cleanup, audit, and highlight."""

from __future__ import annotations

from shared.utils import utf16_len
from . import docs_service


def _search_text_runs(paragraphs: list[dict], search_text: str) -> list[tuple[int, int]]:
    """Search text runs in paragraph elements, return list of (doc_start, doc_end) hits."""
    hits = []
    for para in paragraphs:
        for pe in para.get("elements", []):
            tr = pe.get("textRun")
            if not tr:
                continue
            content = tr.get("content", "")
            elem_start = pe.get("startIndex", 0)
            pos = 0
            while True:
                idx = content.find(search_text, pos)
                if idx == -1:
                    break
                doc_start = elem_start + idx
                doc_end = doc_start + utf16_len(search_text)
                hits.append((doc_start, doc_end))
                pos = idx + len(search_text)
    return hits


def highlight_text(document_id: str, search_text: str, color: dict) -> dict:
    """Find text in doc (paragraphs + table cells) and apply background highlight."""
    doc_data = docs_service.read_document_raw(document_id)
    tabs = doc_data.get("tabs", [])
    body = tabs[0].get("documentTab", {}).get("body", {}) if tabs else doc_data.get("body", {})

    all_hits = []
    for elem in body.get("content", []):
        if "paragraph" in elem:
            all_hits.extend(_search_text_runs([elem["paragraph"]], search_text))
        elif "table" in elem:
            for row in elem["table"].get("tableRows", []):
                for cell in row.get("tableCells", []):
                    for ce in cell.get("content", []):
                        if "paragraph" in ce:
                            all_hits.extend(_search_text_runs([ce["paragraph"]], search_text))

    requests = []
    for doc_start, doc_end in all_hits:
        requests.append({
            "updateTextStyle": {
                "range": {"startIndex": doc_start, "endIndex": doc_end},
                "textStyle": {"backgroundColor": {"color": {"rgbColor": color}}},
                "fields": "backgroundColor",
            }
        })

    if requests:
        docs_service.batch_update(document_id, requests)

    return {"occurrences_highlighted": len(all_hits)}


def cleanup_document(document_id: str) -> dict:
    """Fix formatting issues: blank paragraphs, style inheritance, table fonts, bold leaks."""
    doc_data = docs_service.read_document_raw(document_id)
    tabs = doc_data.get("tabs", [])
    body = tabs[0].get("documentTab", {}).get("body", {}) if tabs else doc_data.get("body", {})

    requests = []
    fixes = {"blank_paragraphs": 0, "style_resets": 0, "table_fonts": 0, "bold_resets": 0}
    content = body.get("content", [])
    prev_was_empty = False
    heading_styles = {"HEADING_1", "HEADING_2", "HEADING_3", "HEADING_4", "HEADING_5", "HEADING_6"}

    for elem in reversed(content):
        para = elem.get("paragraph")
        if not para:
            prev_was_empty = False
            continue

        style = para.get("paragraphStyle", {}).get("namedStyleType", "NORMAL_TEXT")
        text = ""
        all_bold = True
        has_text_run = False
        for pe in para.get("elements", []):
            tr = pe.get("textRun")
            if tr:
                text += tr.get("content", "")
                has_text_run = True
                ts = tr.get("textStyle", {})
                if not ts.get("bold"):
                    all_bold = False

        text_stripped = text.strip()
        is_empty = text_stripped == ""
        start = elem.get("startIndex", 0)
        end = elem.get("endIndex", 0)

        # Fix 1: Remove consecutive blank paragraphs
        if is_empty and prev_was_empty:
            if start > 0 and end > start:
                requests.append({"deleteContentRange": {"range": {"startIndex": start, "endIndex": end}}})
                fixes["blank_paragraphs"] += 1

        # Fix 2: Body text with heading style (long text, no section numbering pattern)
        if style in heading_styles and text_stripped and len(text_stripped) > 80:
            requests.append({
                "updateParagraphStyle": {
                    "range": {"startIndex": start, "endIndex": end},
                    "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                    "fields": "namedStyleType",
                }
            })
            fixes["style_resets"] += 1

        # Fix 3: Entirely bold body text (inheritance leak)
        if style == "NORMAL_TEXT" and all_bold and has_text_run and not is_empty and len(text_stripped) > 20:
            requests.append({
                "updateTextStyle": {
                    "range": {"startIndex": start, "endIndex": end},
                    "textStyle": {"bold": False},
                    "fields": "bold",
                }
            })
            fixes["bold_resets"] += 1

        prev_was_empty = is_empty

    # Fix 4: Table cells with wrong font size
    for elem in content:
        table = elem.get("table")
        if not table:
            continue
        for r_idx, row in enumerate(table.get("tableRows", [])):
            for cell in row.get("tableCells", []):
                for ce in cell.get("content", []):
                    cp = ce.get("paragraph")
                    if not cp:
                        continue
                    for pe in cp.get("elements", []):
                        tr = pe.get("textRun")
                        if not tr:
                            continue
                        ts = tr.get("textStyle", {})
                        fs = ts.get("fontSize", {})
                        magnitude = fs.get("magnitude", 11) if fs else 11
                        if magnitude != 11:
                            requests.append({
                                "updateTextStyle": {
                                    "range": {"startIndex": pe["startIndex"], "endIndex": pe["endIndex"]},
                                    "textStyle": {"fontSize": {"magnitude": 11, "unit": "PT"}},
                                    "fields": "fontSize",
                                }
                            })
                            fixes["table_fonts"] += 1

    if requests:
        docs_service.batch_update(document_id, requests)

    total = sum(fixes.values())
    parts = [f"{v} {k.replace('_', ' ')}" for k, v in fixes.items() if v > 0]
    return {"issues_fixed": total, "details": parts}


def audit_document(document_id: str) -> dict:
    """Check document for formatting issues and return a detailed report."""
    doc_data = docs_service.read_document_raw(document_id)
    tabs = doc_data.get("tabs", [])
    body = tabs[0].get("documentTab", {}).get("body", {}) if tabs else doc_data.get("body", {})

    issues = []
    content = body.get("content", [])
    consecutive_empty = 0
    heading_count = {"HEADING_1": 0, "HEADING_2": 0, "HEADING_3": 0}
    heading_styles = {"HEADING_1", "HEADING_2", "HEADING_3", "HEADING_4", "HEADING_5", "HEADING_6"}
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
            all_bold = True
            has_text_run = False
            has_bullet = para.get("bullet") is not None
            for pe in para.get("elements", []):
                tr = pe.get("textRun")
                if tr:
                    text += tr.get("content", "")
                    has_text_run = True
                    ts = tr.get("textStyle", {})
                    font = ts.get("weightedFontFamily", {}).get("fontFamily")
                    if font:
                        fonts_used.add(font)
                    if not ts.get("bold"):
                        all_bold = False

            text_stripped = text.strip()
            start_idx = elem.get("startIndex", "?")

            if text_stripped == "":
                consecutive_empty += 1
                if consecutive_empty >= 3:
                    issues.append(f"3+ blank paragraphs at index {start_idx}")
            else:
                consecutive_empty = 0

            # Body text with heading style (likely inheritance)
            if named in heading_styles and text_stripped and len(text_stripped) > 80:
                issues.append(f"Body text has {named} style at index {start_idx}: '{text_stripped[:60]}...'")

            # Entirely bold body text (inheritance leak)
            if named == "NORMAL_TEXT" and all_bold and has_text_run and text_stripped and len(text_stripped) > 20:
                issues.append(f"All-bold body text at index {start_idx}: '{text_stripped[:50]}...'")

            # Bullets on headings
            if named in heading_styles and has_bullet:
                issues.append(f"Heading has bullet at index {start_idx}: '{text_stripped[:40]}'")

        if "table" in elem:
            total_tables += 1
            table = elem["table"]
            for r_idx, row in enumerate(table.get("tableRows", [])):
                row_empty = True
                for cell in row.get("tableCells", []):
                    for ce in cell.get("content", []):
                        cp = ce.get("paragraph")
                        if not cp:
                            continue
                        for pe in cp.get("elements", []):
                            tr = pe.get("textRun")
                            if not tr:
                                continue
                            if tr.get("content", "").strip():
                                row_empty = False
                            ts = tr.get("textStyle", {})
                            fs = ts.get("fontSize", {})
                            magnitude = fs.get("magnitude", 11) if fs else 11
                            if magnitude != 11 and magnitude != 0:
                                issues.append(f"Table cell [{r_idx}] has {magnitude}pt font (expected 11pt) at index {pe.get('startIndex', '?')}")
                if row_empty and r_idx > 0:
                    issues.append(f"Empty table row at row {r_idx} in table at index {elem.get('startIndex', '?')}")

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
