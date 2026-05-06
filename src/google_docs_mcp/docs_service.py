"""Google Docs API wrapper — create, read, write, and inspect documents."""

from __future__ import annotations

from googleapiclient.discovery import build

from .auth import get_credentials
from .utils import execute_with_retry, batch_update as _batch_update

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
