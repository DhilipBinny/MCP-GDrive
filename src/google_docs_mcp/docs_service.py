"""Google Docs API wrapper — create, read, write, and inspect documents."""

from __future__ import annotations

from googleapiclient.discovery import build

from shared.auth import get_credentials
from shared.utils import execute_with_retry, batch_update as _batch_update

_service = None


def _get_service():
    global _service
    if _service is None:
        creds = get_credentials()
        _service = build("docs", "v1", credentials=creds)
    return _service


def create_document(title: str) -> dict:
    service = _get_service()
    doc = execute_with_retry(service.documents().create(body={"title": title}))
    return {"document_id": doc["documentId"], "title": doc["title"]}


def read_document(document_id: str, as_markdown: bool = False) -> dict:
    service = _get_service()
    doc = execute_with_retry(
        service.documents().get(documentId=document_id, includeTabsContent=True)
    )
    title = doc.get("title", "")

    tabs = doc.get("tabs", [])
    if tabs:
        body = tabs[0].get("documentTab", {}).get("body", {})
    else:
        body = doc.get("body", {})

    if as_markdown:
        text = _body_to_markdown(body)
    else:
        text = _body_to_text(body)

    return {"document_id": document_id, "title": title, "content": text}


def read_document_raw(document_id: str) -> dict:
    """Return the raw Google Docs API response (for internal use by formatter)."""
    service = _get_service()
    return execute_with_retry(
        service.documents().get(documentId=document_id, includeTabsContent=True)
    )


def get_document_structure(document_id: str) -> dict:
    service = _get_service()
    doc = execute_with_retry(
        service.documents().get(documentId=document_id, includeTabsContent=True)
    )
    tabs = doc.get("tabs", [])
    structure = {
        "title": doc.get("title", ""),
        "document_id": document_id,
        "tabs": [],
    }
    for tab in tabs:
        dt = tab.get("documentTab", {})
        body = dt.get("body", {})
        elements = _summarize_elements(body.get("content", []))
        structure["tabs"].append({
            "tab_id": tab.get("tabProperties", {}).get("tabId", ""),
            "title": tab.get("tabProperties", {}).get("title", ""),
            "elements": elements,
        })
    return structure


def get_end_index(document_id: str) -> int:
    service = _get_service()
    doc = execute_with_retry(
        service.documents().get(documentId=document_id, includeTabsContent=True)
    )
    tabs = doc.get("tabs", [])
    if tabs:
        body = tabs[0].get("documentTab", {}).get("body", {})
    else:
        body = doc.get("body", {})
    content = body.get("content", [])
    if content:
        return content[-1].get("endIndex", 1)
    return 1


def batch_update(document_id: str, requests: list[dict], preserve_order: bool = False) -> dict:
    service = _get_service()
    return _batch_update(service, document_id, requests, preserve_order=preserve_order)


def insert_inline_image(
    document_id: str,
    image_url: str,
    index: int | None = None,
    width_pt: float | None = None,
    height_pt: float | None = None,
) -> dict:
    """Insert an inline image from a public URL."""
    service = _get_service()
    req: dict = {"uri": image_url}

    if index is not None:
        req["location"] = {"index": index}
    else:
        req["endOfSegmentLocation"] = {"segmentId": ""}

    if width_pt or height_pt:
        size = {}
        if width_pt:
            size["width"] = {"magnitude": width_pt, "unit": "PT"}
        if height_pt:
            size["height"] = {"magnitude": height_pt, "unit": "PT"}
        req["objectSize"] = size

    result = execute_with_retry(
        service.documents().batchUpdate(
            documentId=document_id,
            body={"requests": [{"insertInlineImage": req}]},
        )
    )
    obj_id = result.get("replies", [{}])[0].get("insertInlineImage", {}).get("objectId", "")
    return {"object_id": obj_id}


def update_document_style(
    document_id: str,
    margin_top: float | None = None,
    margin_bottom: float | None = None,
    margin_left: float | None = None,
    margin_right: float | None = None,
) -> dict:
    """Update document margins (in points, 72pt = 1 inch)."""
    style: dict = {}
    fields = []
    if margin_top is not None:
        style["marginTop"] = {"magnitude": margin_top, "unit": "PT"}
        fields.append("marginTop")
    if margin_bottom is not None:
        style["marginBottom"] = {"magnitude": margin_bottom, "unit": "PT"}
        fields.append("marginBottom")
    if margin_left is not None:
        style["marginLeft"] = {"magnitude": margin_left, "unit": "PT"}
        fields.append("marginLeft")
    if margin_right is not None:
        style["marginRight"] = {"magnitude": margin_right, "unit": "PT"}
        fields.append("marginRight")

    if not fields:
        return {}

    service = _get_service()
    execute_with_retry(
        service.documents().batchUpdate(
            documentId=document_id,
            body={"requests": [{"updateDocumentStyle": {"documentStyle": style, "fields": ",".join(fields)}}]},
        )
    )
    return {"updated_fields": fields}


def replace_all_text(document_id: str, find: str, replace: str) -> dict:
    service = _get_service()
    requests = [{
        "replaceAllText": {
            "containsText": {"text": find, "matchCase": True},
            "replaceText": replace,
        }
    }]
    result = execute_with_retry(
        service.documents().batchUpdate(
            documentId=document_id,
            body={"requests": requests},
        )
    )
    replies = result.get("replies", [{}])
    count = replies[0].get("replaceAllText", {}).get("occurrencesChanged", 0) if replies else 0
    return {"occurrences_replaced": count}


def get_section_boundaries(document_id: str, heading_text: str) -> dict | None:
    """Find a section by its heading text.

    Returns dict with: heading_start, heading_end, content_start, content_end, heading_level
    Or None if heading not found. Supports partial match (e.g. "4.3" matches "4.3 Estimated Cost").
    """
    doc = read_document_raw(document_id)
    tabs = doc.get("tabs", [])
    body = tabs[0].get("documentTab", {}).get("body", {}) if tabs else doc.get("body", {})
    content = body.get("content", [])

    heading_styles = {"HEADING_1": 1, "HEADING_2": 2, "HEADING_3": 3,
                      "HEADING_4": 4, "HEADING_5": 5, "HEADING_6": 6}

    # Find the target heading
    target_elem = None
    target_level = None
    target_idx = None

    for i, elem in enumerate(content):
        para = elem.get("paragraph")
        if not para:
            continue
        style = para.get("paragraphStyle", {}).get("namedStyleType", "NORMAL_TEXT")
        if style not in heading_styles:
            continue
        text = ""
        for pe in para.get("elements", []):
            tr = pe.get("textRun")
            if tr:
                text += tr.get("content", "")
        text = text.strip()
        if text == heading_text or heading_text in text or text.startswith(heading_text):
            target_elem = elem
            target_level = heading_styles[style]
            target_idx = i
            break

    if target_elem is None:
        return None

    heading_start = target_elem.get("startIndex", 0)
    heading_end = target_elem.get("endIndex", 0)
    content_start = heading_end

    # Find where section ends: next heading of same or higher level, or end of document
    content_end = content[-1].get("endIndex", heading_end) if content else heading_end
    for elem in content[target_idx + 1:]:
        para = elem.get("paragraph")
        if not para:
            continue
        style = para.get("paragraphStyle", {}).get("namedStyleType", "NORMAL_TEXT")
        if style in heading_styles and heading_styles[style] <= target_level:
            content_end = elem.get("startIndex", content_end)
            break

    return {
        "heading_start": heading_start,
        "heading_end": heading_end,
        "content_start": content_start,
        "content_end": content_end,
        "heading_level": target_level,
    }


def find_tables(document_id: str) -> list[dict]:
    """Return all tables in the document with their indices and content."""
    doc = read_document_raw(document_id)
    tabs = doc.get("tabs", [])
    body = tabs[0].get("documentTab", {}).get("body", {}) if tabs else doc.get("body", {})

    tables = []
    for elem in body.get("content", []):
        table = elem.get("table")
        if not table:
            continue
        rows_data = []
        for row in table.get("tableRows", []):
            cells = []
            for cell in row.get("tableCells", []):
                cell_text = ""
                cell_start = None
                cell_end = None
                for ce in cell.get("content", []):
                    if cell_start is None:
                        cell_start = ce.get("startIndex", 0)
                    cell_end = ce.get("endIndex", 0)
                    cp = ce.get("paragraph")
                    if cp:
                        for cpe in cp.get("elements", []):
                            ctr = cpe.get("textRun")
                            if ctr:
                                cell_text += ctr.get("content", "")
                cells.append({"text": cell_text.strip(), "start": cell_start, "end": cell_end})
            rows_data.append(cells)
        tables.append({
            "start_index": elem.get("startIndex", 0),
            "end_index": elem.get("endIndex", 0),
            "rows": len(rows_data),
            "columns": table.get("columns", 0),
            "data": rows_data,
        })
    return tables


def read_section(document_id: str, heading_text: str, as_markdown: bool = False) -> dict | None:
    """Read content from a specific section only."""
    boundaries = get_section_boundaries(document_id, heading_text)
    if not boundaries:
        return None

    doc = read_document_raw(document_id)
    tabs = doc.get("tabs", [])
    body = tabs[0].get("documentTab", {}).get("body", {}) if tabs else doc.get("body", {})
    content = body.get("content", [])

    section_elements = []
    for elem in content:
        elem_start = elem.get("startIndex", 0)
        elem_end = elem.get("endIndex", 0)
        if elem_start >= boundaries["heading_start"] and elem_end <= boundaries["content_end"]:
            section_elements.append(elem)

    section_body = {"content": section_elements}
    if as_markdown:
        return {"content": _body_to_markdown(section_body), "boundaries": boundaries}
    return {"content": _body_to_text(section_body), "boundaries": boundaries}


def _body_to_text(body: dict) -> str:
    parts = []
    for elem in body.get("content", []):
        para = elem.get("paragraph")
        if para:
            for pe in para.get("elements", []):
                tr = pe.get("textRun")
                if tr:
                    parts.append(tr.get("content", ""))
        table = elem.get("table")
        if table:
            for row in table.get("tableRows", []):
                row_texts = []
                for cell in row.get("tableCells", []):
                    cell_text = ""
                    for ce in cell.get("content", []):
                        cp = ce.get("paragraph")
                        if cp:
                            for cpe in cp.get("elements", []):
                                ctr = cpe.get("textRun")
                                if ctr:
                                    cell_text += ctr.get("content", "")
                    row_texts.append(cell_text.strip())
                parts.append(" | ".join(row_texts) + "\n")
    return "".join(parts)


def _body_to_markdown(body: dict) -> str:
    parts = []
    for elem in body.get("content", []):
        para = elem.get("paragraph")
        if para:
            style = para.get("paragraphStyle", {})
            named = style.get("namedStyleType", "NORMAL_TEXT")
            heading_map = {
                "HEADING_1": "# ", "HEADING_2": "## ", "HEADING_3": "### ",
                "HEADING_4": "#### ", "HEADING_5": "##### ", "HEADING_6": "###### ",
                "TITLE": "# ", "SUBTITLE": "## ",
            }
            prefix = heading_map.get(named, "")

            bullet = para.get("bullet")
            if bullet:
                nesting = bullet.get("nestingLevel", 0)
                indent = "  " * nesting
                prefix = f"{indent}- "

            line_parts = []
            for pe in para.get("elements", []):
                tr = pe.get("textRun")
                if tr:
                    content = tr.get("content", "")
                    ts = tr.get("textStyle", {})
                    text = content
                    if ts.get("bold"):
                        text = f"**{text.strip()}**"
                    if ts.get("italic"):
                        text = f"*{text.strip()}*"
                    if ts.get("strikethrough"):
                        text = f"~~{text.strip()}~~"
                    font = ts.get("weightedFontFamily", {}).get("fontFamily", "")
                    if font in ("Courier New", "Consolas", "monospace"):
                        text = f"`{text.strip()}`"
                    link = ts.get("link", {})
                    if link.get("url"):
                        text = f"[{text.strip()}]({link['url']})"
                    line_parts.append(text)

            line = "".join(line_parts).rstrip("\n")
            if line or prefix:
                parts.append(f"{prefix}{line}\n")
            else:
                parts.append("\n")

        table = elem.get("table")
        if table:
            rows = table.get("tableRows", [])
            for r_idx, row in enumerate(rows):
                cells = []
                for cell in row.get("tableCells", []):
                    cell_text = ""
                    for ce in cell.get("content", []):
                        cp = ce.get("paragraph")
                        if cp:
                            for cpe in cp.get("elements", []):
                                ctr = cpe.get("textRun")
                                if ctr:
                                    cell_text += ctr.get("content", "").strip()
                    cells.append(cell_text)
                parts.append("| " + " | ".join(cells) + " |\n")
                if r_idx == 0:
                    parts.append("| " + " | ".join(["---"] * len(cells)) + " |\n")

    return "".join(parts)


def _summarize_elements(content: list[dict]) -> list[dict]:
    summary = []
    for elem in content:
        if "paragraph" in elem:
            para = elem["paragraph"]
            style = para.get("paragraphStyle", {}).get("namedStyleType", "NORMAL_TEXT")
            text = ""
            for pe in para.get("elements", []):
                tr = pe.get("textRun")
                if tr:
                    text += tr.get("content", "")
            text = text.strip()[:100]
            summary.append({
                "type": "paragraph",
                "style": style,
                "preview": text,
                "startIndex": elem.get("startIndex", 0),
                "endIndex": elem.get("endIndex", 0),
            })
        elif "table" in elem:
            table = elem["table"]
            summary.append({
                "type": "table",
                "rows": table.get("rows", 0),
                "columns": table.get("columns", 0),
                "startIndex": elem.get("startIndex", 0),
                "endIndex": elem.get("endIndex", 0),
            })
        elif "sectionBreak" in elem:
            summary.append({"type": "sectionBreak", "startIndex": elem.get("startIndex", 0)})
    return summary
