"""Google Docs MCP Server — consolidated tools for create, read, write, and edit documents."""

from __future__ import annotations

import sys
import logging
import functools
from typing import Literal

logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from googleapiclient.errors import HttpError

from . import docs_service, formatter
from .markdown_parser import markdown_to_requests
from shared import drive_service


def _safe_insert_index(document_id: str, content_end: int, body: dict | None = None) -> int:
    """Return content_end - 1 unless that points inside a table, in which case return content_end."""
    candidate = content_end - 1
    if candidate < 1:
        return content_end
    if body is None:
        doc = docs_service.read_document_raw(document_id)
        tabs = doc.get("tabs", [])
        body = tabs[0].get("documentTab", {}).get("body", {}) if tabs else doc.get("body", {})
    for elem in body.get("content", []):
        table = elem.get("table")
        if not table:
            continue
        t_start = elem.get("startIndex", 0)
        t_end = elem.get("endIndex", 0)
        if t_start < candidate < t_end:
            return content_end
    return candidate

mcp = FastMCP(
    "google-docs-mcp",
    instructions="""MCP server for Google Docs — create, read, write, and edit formatted documents.

WORKFLOW FOR CREATING DOCUMENTS:
1. gdocs_create — create new blank doc (optionally in a folder)
2. gdocs_write(action="write_markdown") — write full content with Markdown formatting
3. gdocs_edit(action="cleanup") — fix formatting issues
4. gdocs_edit(action="audit") — verify quality

WORKFLOW FOR EDITING EXISTING DOCS:
1. gdocs_read(action="structure") — see document outline with headings
2. gdocs_read(action="section", heading_text="...") — read specific sections
3. gdocs_write — insert, append, replace, or delete content
4. gdocs_edit — highlight, cleanup, audit, adjust page setup, or edit tables

MARKDOWN FORMATTING RULES:
- Headings: # through ###### (H1-H6)
- Inline: **bold**, *italic*, ~~strikethrough~~, `code`, [links](url)
- Lists: bullet (- or *) and numbered (1.) with nesting via indentation
- Tables: | col1 | col2 | with |---| separator row
- Code blocks: triple backticks with optional language tag
- Horizontal rules: --- on its own line

CONTENT BEST PRACTICES:
- Use heading hierarchy consistently (H1 for title, H2 for sections, H3 for subsections)
- Keep table cells concise — long text wraps poorly in narrow columns
- Use write_markdown to replace all content; use append_markdown to add to the end
- Use insert_at_section to surgically add content at a specific location
- Always read the doc structure before making targeted edits
- Run audit after major changes to catch formatting inconsistencies
""",
)


def _handle_errors(func):
    """Wrap MCP tools with user-friendly error handling."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except HttpError as e:
            status = e.resp.status
            if status == 404:
                return "ERROR: Document or file not found. Check the ID is correct."
            elif status == 403:
                return "ERROR: Permission denied. You may not have access to this document."
            elif status == 429:
                return "ERROR: Google API rate limit exceeded. Wait a moment and try again."
            else:
                return f"ERROR: Google API returned {status}: {e._get_reason()}"
        except RuntimeError as e:
            return f"ERROR: {e}"
        except FileNotFoundError as e:
            return f"ERROR: {e}"
        except Exception as e:
            return f"ERROR: Unexpected error — {type(e).__name__}: {e}"
    return wrapper


# ═══════════════════════════════════════════════════════════════
# TOOL 1: CREATE
# ═══════════════════════════════════════════════════════════════

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True))
@_handle_errors
def gdocs_create(title: str, folder_id: str | None = None) -> str:
    """Create a new Google Doc. Optionally place it in a specific Drive folder.

    WORKFLOW: create -> write_markdown -> edit(cleanup/audit).

    Args:
        title: Document title
        folder_id: Optional Google Drive folder ID to place the doc in
    """
    result = docs_service.create_document(title)
    if folder_id:
        drive_service.create_in_folder(result["document_id"], folder_id)
    url = f"https://docs.google.com/document/d/{result['document_id']}/edit"
    return f"Created: **{result['title']}**\n- ID: `{result['document_id']}`\n- URL: {url}"


# ═══════════════════════════════════════════════════════════════
# TOOL 2: READ (all read operations via `action` parameter)
# ═══════════════════════════════════════════════════════════════

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True))
@_handle_errors
def gdocs_read(
    document_id: str,
    action: str = "full",
    heading_text: str = "",
    format: Literal["text", "markdown"] = "markdown",
) -> str:
    """Read content from a Google Doc. The `action` parameter selects what to read.

    WORKFLOW: Always read structure first to understand the document layout,
    then read specific sections for targeted edits.

    ACTIONS:
    - "full" — read the entire document (uses: format)
    - "section" — read a specific section by heading (uses: heading_text, format)
    - "structure" — document outline with headings, tables, and index ranges

    Args:
        document_id: The Google Doc ID
        action: Read mode (see above)
        heading_text: Section heading text for action="section" (supports partial match, e.g. "4.3" matches "4.3 Estimated Cost")
        format: Output format — "text" (plain) or "markdown" (with formatting). Used by "full" and "section" actions.
    """
    a = action.lower()

    if a == "full":
        as_md = format == "markdown"
        result = docs_service.read_document(document_id, as_markdown=as_md)
        return f"# {result['title']}\n\n{result['content']}"

    elif a == "section":
        if not heading_text:
            return "ERROR: heading_text is required for action='section'"
        result = docs_service.read_section(document_id, heading_text, as_markdown=(format == "markdown"))
        if not result:
            return f"ERROR: Section with heading '{heading_text}' not found"
        return result["content"]

    elif a == "structure":
        result = docs_service.get_document_structure(document_id)
        parts = [f"# {result['title']}\n"]
        for tab in result["tabs"]:
            parts.append(f"\n## Tab: {tab['title'] or '(default)'}\n")
            for elem in tab["elements"]:
                if elem["type"] == "paragraph":
                    parts.append(f"- [{elem['style']}] {elem['preview']} ({elem['startIndex']}-{elem['endIndex']})")
                elif elem["type"] == "table":
                    parts.append(f"- [TABLE {elem['rows']}x{elem['columns']}] ({elem['startIndex']}-{elem['endIndex']})")
        return "\n".join(parts)

    else:
        return f"ERROR: Unknown action '{action}'. Use: full, section, structure"


# ═══════════════════════════════════════════════════════════════
# TOOL 3: WRITE (all content-writing operations via `action`)
# ═══════════════════════════════════════════════════════════════

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True))
@_handle_errors
def gdocs_write(
    document_id: str,
    action: str,
    markdown: str = "",
    find: str = "",
    replace: str = "",
    scope: Literal["all", "first", "section"] = "all",
    section_heading: str | None = None,
    heading_text: str = "",
    text: str = "",
    level: int = 2,
    headers: list[str] | None = None,
    rows: list[list[str]] | None = None,
    before_heading: str | None = None,
    after_heading: str | None = None,
    image_url: str = "",
    width_pt: float | None = None,
    height_pt: float | None = None,
) -> str:
    """Write, insert, or modify content in a Google Doc. The `action` parameter selects the operation.

    GUIDELINES:
    - Use "write_markdown" to create a full document from scratch (replaces all content)
    - Use "append_markdown" to add content to the end of an existing document
    - Use "insert_at_section" for surgical inserts at a specific heading location
    - Use "replace" for find/replace — supports scoping to first occurrence or a section
    - Use "delete_section" to remove an entire section (heading + content)
    - Use "add_heading" to insert a new heading at a specific position
    - Use "add_table" to insert a formatted table at a specific position
    - Use "insert_image" for inline images from public URLs

    ACTIONS:
    - "write_markdown" — replace entire doc with Markdown content (uses: markdown)
    - "append_markdown" — append Markdown content at end (uses: markdown)
    - "insert_at_section" — insert Markdown at a heading position (uses: markdown, before_heading or after_heading)
    - "replace" — find and replace text (uses: find, replace, scope, section_heading)
    - "delete_section" — delete a section by heading (uses: heading_text)
    - "add_heading" — insert a heading (uses: text, level, before_heading or after_heading)
    - "add_table" — insert a formatted table (uses: headers, rows, before_heading or after_heading)
    - "insert_image" — insert inline image (uses: image_url, width_pt, height_pt, before_heading)

    Args:
        document_id: The Google Doc ID
        action: Write operation (see above)
        markdown: Markdown-formatted content (for write_markdown, append_markdown, insert_at_section)
        find: Text to search for (replace action)
        replace: Replacement text (replace action)
        scope: "all" (replace all), "first" (first only), or "section" (within a section) — for replace action
        section_heading: Required when scope="section" — heading text of target section (replace action)
        heading_text: Section heading to delete (delete_section action)
        text: Heading text to insert (add_heading action)
        level: Heading level 1-6 (add_heading action, default 2)
        headers: Column header labels (add_table action)
        rows: List of rows, each a list of cell values (add_table action)
        before_heading: Insert before this heading (insert_at_section, add_heading, add_table)
        after_heading: Insert after this heading's section content (insert_at_section, add_heading, add_table)
        image_url: Publicly accessible image URL (insert_image action)
        width_pt: Image width in points, 72pt = 1 inch (insert_image action)
        height_pt: Image height in points (insert_image action)
    """
    a = action.lower()

    if a == "write_markdown":
        if not markdown:
            return "ERROR: markdown is required for write_markdown action"
        end_idx = docs_service.get_end_index(document_id)
        clear_requests = []
        if end_idx > 2:
            clear_requests.append({
                "deleteContentRange": {
                    "range": {"startIndex": 1, "endIndex": end_idx - 1}
                }
            })
        clear_requests.append({
            "deleteParagraphBullets": {
                "range": {"startIndex": 1, "endIndex": 2}
            }
        })
        docs_service.batch_update(document_id, clear_requests, preserve_order=True)
        md_requests = markdown_to_requests(markdown, start_index=1)
        docs_service.batch_update(document_id, md_requests, preserve_order=True)
        return f"Wrote {len(md_requests)} formatting operations to `{document_id}`"

    elif a == "append_markdown":
        if not markdown:
            return "ERROR: markdown is required for append_markdown action"
        end_idx = docs_service.get_end_index(document_id)
        start = end_idx - 1 if end_idx > 1 else 1
        md_requests = markdown_to_requests(markdown, start_index=start)
        docs_service.batch_update(document_id, md_requests, preserve_order=True)
        return f"Appended {len(md_requests)} formatting operations to `{document_id}`"

    elif a == "insert_at_section":
        if not markdown:
            return "ERROR: markdown is required for insert_at_section action"
        if not before_heading and not after_heading:
            return "ERROR: Provide either before_heading or after_heading"
        target = before_heading or after_heading
        boundaries = docs_service.get_section_boundaries(document_id, target)
        if not boundaries:
            return f"ERROR: Heading '{target}' not found in document"
        if before_heading:
            insert_at = boundaries["heading_start"]
        else:
            insert_at = _safe_insert_index(document_id, boundaries["content_end"])
        md_requests = markdown_to_requests(markdown, start_index=insert_at)
        docs_service.batch_update(document_id, md_requests, preserve_order=True)
        return f"Inserted content {'before' if before_heading else 'after'} section '{target}'"

    elif a == "replace":
        if not find:
            return "ERROR: find is required for replace action"
        if scope == "all":
            result = docs_service.replace_all_text(document_id, find, replace)
            return f"Replaced {result['occurrences_replaced']} occurrence(s) of `{find}`"

        if scope == "section" and not section_heading:
            return "ERROR: section_heading is required when scope='section'"

        doc = docs_service.read_document_raw(document_id)
        tabs = doc.get("tabs", [])
        body = tabs[0].get("documentTab", {}).get("body", {}) if tabs else doc.get("body", {})

        range_start = 0
        range_end = float("inf")
        if scope == "section":
            boundaries = docs_service.get_section_boundaries(document_id, section_heading)
            if not boundaries:
                return f"ERROR: Heading '{section_heading}' not found in document"
            range_start = boundaries["heading_start"]
            range_end = boundaries["content_end"]

        from shared.utils import utf16_len

        def _find_in_paragraphs(paragraphs):
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
                        idx = content.find(find, pos)
                        if idx == -1:
                            break
                        doc_start = elem_start + utf16_len(content[:idx])
                        doc_end = doc_start + utf16_len(find)
                        if doc_start >= range_start and doc_end <= range_end:
                            hits.append((doc_start, doc_end))
                        pos = idx + len(find)
            return hits

        all_hits = []
        for elem in body.get("content", []):
            if "paragraph" in elem:
                all_hits.extend(_find_in_paragraphs([elem["paragraph"]]))
            elif "table" in elem:
                for row in elem["table"].get("tableRows", []):
                    for cell in row.get("tableCells", []):
                        for ce in cell.get("content", []):
                            if "paragraph" in ce:
                                all_hits.extend(_find_in_paragraphs([ce["paragraph"]]))

        if scope == "first" and all_hits:
            all_hits = [all_hits[0]]

        requests = []
        count = len(all_hits)
        for doc_start, doc_end in all_hits:
            requests.append({"deleteContentRange": {"range": {"startIndex": doc_start, "endIndex": doc_end}}})
            requests.append({"insertText": {"location": {"index": doc_start}, "text": replace}})

        if requests:
            pair_requests = []
            for i in range(0, len(requests), 2):
                pair_requests.append((requests[i], requests[i + 1]))
            pair_requests.reverse()
            flat = []
            for delete, insert in pair_requests:
                flat.append(delete)
                flat.append(insert)
            docs_service.batch_update(document_id, flat, preserve_order=True)

        scope_desc = f" in section '{section_heading}'" if scope == "section" else " (first only)" if scope == "first" else ""
        return f"Replaced {count} occurrence(s) of `{find}`{scope_desc}"

    elif a == "delete_section":
        if not heading_text:
            return "ERROR: heading_text is required for delete_section action"
        boundaries = docs_service.get_section_boundaries(document_id, heading_text)
        if not boundaries:
            return f"ERROR: Section with heading '{heading_text}' not found"
        start = boundaries["heading_start"]
        end = boundaries["content_end"]
        if end <= start:
            return "Section is empty, nothing to delete"
        requests = [{"deleteContentRange": {"range": {"startIndex": start, "endIndex": end}}}]
        docs_service.batch_update(document_id, requests)
        return f"Section (heading + content) deleted for '{heading_text}'"

    elif a == "add_heading":
        if not text:
            return "ERROR: text is required for add_heading action"
        level_clamped = max(1, min(level, 6))
        style_map = {1: "HEADING_1", 2: "HEADING_2", 3: "HEADING_3", 4: "HEADING_4", 5: "HEADING_5", 6: "HEADING_6"}
        named_style = style_map[level_clamped]

        if before_heading:
            boundaries = docs_service.get_section_boundaries(document_id, before_heading)
            if not boundaries:
                return f"ERROR: Heading '{before_heading}' not found"
            insert_at = boundaries["heading_start"]
        elif after_heading:
            boundaries = docs_service.get_section_boundaries(document_id, after_heading)
            if not boundaries:
                return f"ERROR: Heading '{after_heading}' not found"
            insert_at = _safe_insert_index(document_id, boundaries["content_end"])
        else:
            end_idx = docs_service.get_end_index(document_id)
            insert_at = end_idx - 1 if end_idx > 1 else 1

        from shared.utils import utf16_len
        full_text = text + "\n"
        end = insert_at + utf16_len(full_text)

        requests = [
            {"insertText": {"location": {"index": insert_at}, "text": full_text}},
            {"updateParagraphStyle": {
                "range": {"startIndex": insert_at, "endIndex": end},
                "paragraphStyle": {"namedStyleType": named_style},
                "fields": "namedStyleType",
            }},
        ]
        docs_service.batch_update(document_id, requests, preserve_order=True)

        pos = "before " + before_heading if before_heading else "after " + after_heading if after_heading else "at end"
        return f"Added H{level_clamped} heading '{text}' {pos}"

    elif a == "add_table":
        if not headers:
            return "ERROR: headers is required for add_table action"
        if not rows:
            return "ERROR: rows is required for add_table action"
        md_rows = [headers] + rows
        md_lines = []
        for i, row in enumerate(md_rows):
            md_lines.append("| " + " | ".join(row) + " |")
            if i == 0:
                md_lines.append("| " + " | ".join(["---"] * len(row)) + " |")
        table_md = "\n".join(md_lines)

        if before_heading:
            boundaries = docs_service.get_section_boundaries(document_id, before_heading)
            if not boundaries:
                return f"ERROR: Heading '{before_heading}' not found in document"
            start = boundaries["heading_start"]
        elif after_heading:
            boundaries = docs_service.get_section_boundaries(document_id, after_heading)
            if not boundaries:
                return f"ERROR: Heading '{after_heading}' not found in document"
            start = _safe_insert_index(document_id, boundaries["content_end"])
        else:
            end_idx = docs_service.get_end_index(document_id)
            start = end_idx - 1 if end_idx > 1 else 1

        md_requests = markdown_to_requests(table_md, start_index=start)
        docs_service.batch_update(document_id, md_requests, preserve_order=True)
        return f"Added {len(headers)}-column table with {len(rows)} data rows"

    elif a == "insert_image":
        if not image_url:
            return "ERROR: image_url is required for insert_image action"
        index = None
        heading = before_heading or after_heading
        if heading:
            boundaries = docs_service.get_section_boundaries(document_id, heading)
            if not boundaries:
                return f"ERROR: Heading '{heading}' not found"
            index = boundaries["heading_start"] if before_heading else _safe_insert_index(document_id, boundaries["content_end"])
        result = docs_service.insert_inline_image(document_id, image_url, index, width_pt, height_pt)
        return f"Inserted image (object: `{result['object_id']}`)"

    else:
        return f"ERROR: Unknown action '{action}'. Use: write_markdown, append_markdown, insert_at_section, replace, delete_section, add_heading, add_table, insert_image"


# ═══════════════════════════════════════════════════════════════
# TOOL 4: EDIT (formatting, auditing, table editing)
# ═══════════════════════════════════════════════════════════════

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True))
@_handle_errors
def gdocs_edit(
    document_id: str,
    action: str,
    text: str = "",
    color: Literal["yellow", "green", "blue", "red", "orange", "purple"] = "yellow",
    table_index: int = 0,
    row_index: int = 0,
    col: int = 0,
    margin_top: float | None = None,
    margin_bottom: float | None = None,
    margin_left: float | None = None,
    margin_right: float | None = None,
) -> str:
    """Edit formatting, audit quality, or modify tables in a Google Doc. The `action` parameter selects the operation.

    GUIDELINES:
    - Run "audit" first to understand the document's formatting state
    - Use "cleanup" to auto-fix common formatting issues
    - Use "highlight" to mark text for review or emphasis
    - Use "page_setup" to adjust margins (72pt = 1 inch, narrow = 36pt)
    - Use "delete_table_row" and "update_table_cell" for table edits

    ACTIONS:
    - "highlight" — highlight all occurrences of text with a color (uses: text, color)
    - "cleanup" — auto-fix formatting issues: duplicate blank lines, heading style leaks, bold inheritance, table font sizes
    - "audit" — generate a quality report: paragraph count, table count, heading structure, font consistency, issues
    - "page_setup" — update document margins (uses: margin_top, margin_bottom, margin_left, margin_right — values in points)
    - "delete_table_row" — delete a row from a table (uses: table_index, row_index)
    - "update_table_cell" — update text in a specific table cell (uses: table_index, row_index, col, text)

    Args:
        document_id: The Google Doc ID
        action: Edit operation (see above)
        text: Text to highlight (highlight action) or new cell content (update_table_cell action)
        color: Highlight color — yellow, green, blue, red, orange, purple (highlight action)
        table_index: Which table, 0-based (delete_table_row, update_table_cell actions)
        row_index: Which row, 0-based (delete_table_row, update_table_cell actions)
        col: Column index, 0-based (update_table_cell action)
        margin_top: Top margin in points (page_setup action)
        margin_bottom: Bottom margin in points (page_setup action)
        margin_left: Left margin in points (page_setup action)
        margin_right: Right margin in points (page_setup action)
    """
    a = action.lower()

    if a == "highlight":
        if not text:
            return "ERROR: text is required for highlight action"
        color_map = {
            "yellow": {"red": 1.0, "green": 0.95, "blue": 0.0},
            "green": {"red": 0.71, "green": 0.93, "blue": 0.71},
            "blue": {"red": 0.68, "green": 0.85, "blue": 1.0},
            "red": {"red": 1.0, "green": 0.71, "blue": 0.71},
            "orange": {"red": 1.0, "green": 0.85, "blue": 0.56},
            "purple": {"red": 0.85, "green": 0.71, "blue": 1.0},
        }
        rgb = color_map.get(color, color_map["yellow"])
        result = formatter.highlight_text(document_id, text, rgb)
        return f"Highlighted {result['occurrences_highlighted']} occurrence(s) in {color}"

    elif a == "cleanup":
        result = formatter.cleanup_document(document_id)
        details = result.get("details", [])
        summary = ", ".join(details) if details else "nothing to fix"
        return f"Fixed {result['issues_fixed']} issue(s): {summary}"

    elif a == "audit":
        result = formatter.audit_document(document_id)
        parts = [
            f"# Audit: {result['document_id']}",
            f"- Paragraphs: {result['total_paragraphs']}",
            f"- Tables: {result['total_tables']}",
            f"- Headings: H1={result['headings']['HEADING_1']}, H2={result['headings']['HEADING_2']}, H3={result['headings']['HEADING_3']}",
            f"- Fonts: {', '.join(result['fonts_used']) or 'default only'}",
            "",
            "## Issues",
        ]
        for issue in result["issues"]:
            parts.append(f"- {issue}")
        return "\n".join(parts)

    elif a == "page_setup":
        result = docs_service.update_document_style(
            document_id, margin_top, margin_bottom, margin_left, margin_right
        )
        if not result:
            return "ERROR: No margin values provided"
        return f"Updated margins: {', '.join(result['updated_fields'])}"

    elif a == "delete_table_row":
        tables = docs_service.find_tables(document_id)
        if table_index >= len(tables):
            return f"ERROR: Document has {len(tables)} table(s), index {table_index} is out of range"
        table = tables[table_index]
        if row_index >= table["rows"]:
            return f"ERROR: Table has {table['rows']} row(s), row {row_index} is out of range"
        if table["rows"] <= 1:
            return "ERROR: Cannot delete the last remaining row"
        requests = [{"deleteTableRow": {
            "tableCellLocation": {
                "tableStartLocation": {"index": table["start_index"]},
                "rowIndex": row_index,
                "columnIndex": 0,
            }
        }}]
        docs_service.batch_update(document_id, requests)
        return f"Deleted row {row_index} from table {table_index}"

    elif a == "update_table_cell":
        tables = docs_service.find_tables(document_id)
        if table_index >= len(tables):
            return f"ERROR: Document has {len(tables)} table(s), index {table_index} is out of range"
        table = tables[table_index]
        if row_index >= table["rows"] or col >= table["columns"]:
            return f"ERROR: Cell [{row_index},{col}] is out of range (table is {table['rows']}x{table['columns']})"
        cell = table["data"][row_index][col]
        cell_start = cell["start"]

        from shared.utils import utf16_len
        requests = []

        old_text = cell["text"]
        if old_text:
            # Use raw_text (includes trailing newline) to compute correct range
            raw_text = cell.get("raw_text", old_text)
            content_end = cell_start + utf16_len(raw_text.rstrip('\n'))
            requests.append({"deleteContentRange": {"range": {"startIndex": cell_start, "endIndex": content_end}}})

        if text:
            requests.append({"insertText": {"location": {"index": cell_start}, "text": text}})
            requests.append({"updateTextStyle": {
                "range": {"startIndex": cell_start, "endIndex": cell_start + utf16_len(text)},
                "textStyle": {"fontSize": {"magnitude": 11, "unit": "PT"}, "bold": False},
                "fields": "fontSize,bold",
            }})

        if requests:
            docs_service.batch_update(document_id, requests, preserve_order=True)
        return f"Updated cell [{row_index},{col}] in table {table_index} to '{text}'"

    else:
        return f"ERROR: Unknown action '{action}'. Use: highlight, cleanup, audit, page_setup, delete_table_row, update_table_cell"


# ═══════════════════════════════════════════════════════════════
# DRIVE TOOLS (shared)
# ═══════════════════════════════════════════════════════════════

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True))
@_handle_errors
def gdrive_search(query: str, max_results: int = 20) -> str:
    """Search for files in Google Drive by name or content.

    USE FOR: Finding document IDs, template files, images to insert.
    Returns file IDs needed by other tools (gdocs_read, gdrive_ops, etc.).

    Args:
        query: Search query (searches file names and content)
        max_results: Maximum results (default 20)
    """
    results = drive_service.search_files(query, max_results=max_results)
    if not results:
        return f"No files found for: {query}"
    lines = [f"Found {len(results)} file(s):\n"]
    for f in results:
        lines.append(f"- **{f['name']}** (`{f['id']}`)\n  {f['mime_type']} | {f['modified']}\n  {f['url']}")
    return "\n".join(lines)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True))
@_handle_errors
def gdrive_list_folder(folder_id: str | None = None, max_results: int = 50) -> str:
    """List files in a Google Drive folder.

    USE FOR: Browsing folder contents, finding template files, checking what exists.
    Returns file IDs and types (doc, sheet, slide, folder).

    Args:
        folder_id: Folder ID (omit for root/My Drive)
        max_results: Maximum results (default 50)
    """
    results = drive_service.list_folder(folder_id=folder_id, max_results=max_results)
    if not results:
        return "Folder is empty"
    lines = [f"Contents ({len(results)} items):\n"]
    for f in results:
        lines.append(f"- **{f['name']}** (`{f['id']}`)\n  {f['mime_type']} | {f['modified']}")
    return "\n".join(lines)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True))
@_handle_errors
def gdrive_ops(
    action: str,
    file_id: str = "",
    folder_id: str = "",
    local_path: str = "",
    name: str = "",
    format: str = "pdf",
    output_path: str = "",
    email: str = "",
    role: str = "reader",
    anyone: bool = False,
    confirm: bool = False,
) -> str:
    """Google Drive file operations.

    IMAGE SIDECAR (for inserting private/local images into docs):
    1. action="upload" local image -> get file_id
    2. action="share" with anyone=true -> get public URL
    3. Use the URL in gdocs_write(action="insert_image", image_url=...)
    4. action="share" to revoke (image persists in doc after insertion)

    ACTIONS:
    - "move" — move file (uses: file_id, folder_id)
    - "delete" — trash file (uses: file_id, confirm=true)
    - "rename" — rename file (uses: file_id, name)
    - "copy" — copy file (uses: file_id, name, folder_id)
    - "upload" — upload local file (uses: local_path, folder_id, name)
    - "export" — export as PDF/DOCX/etc (uses: file_id, format, output_path)
    - "share" — share file (uses: file_id, email, role, anyone)
    - "info" — get file metadata (uses: file_id)
    - "create_folder" — create folder (uses: name, folder_id as parent)

    Args:
        action: Operation
        file_id: Target file ID
        folder_id: Target folder ID
        local_path: Local file path (upload)
        name: File/folder name
        format: Export format (pdf, docx, xlsx, pptx, csv, txt, png)
        output_path: Export output path
        email: Email for sharing
        role: Permission role (reader/writer/commenter)
        anyone: Make public
        confirm: Confirm deletion
    """
    a = action.lower()

    if a == "move":
        r = drive_service.move_file(file_id, folder_id)
        return f"Moved **{r['name']}** to `{folder_id}`"
    elif a == "delete":
        if not confirm:
            return "REFUSED: set confirm=true"
        r = drive_service.trash_file(file_id)
        return f"Trashed **{r['name']}**"
    elif a == "rename":
        r = drive_service.rename_file(file_id, name)
        return f"Renamed -> **{r['name']}**"
    elif a == "copy":
        r = drive_service.copy_file(file_id, name, folder_id or None)
        return f"Copied -> **{r['name']}** (`{r['id']}`)"
    elif a == "upload":
        r = drive_service.upload_file(local_path, name or None, folder_id or None)
        return f"Uploaded **{r['name']}** (`{r['id']}`)"
    elif a == "export":
        r = drive_service.export_file(file_id, format, output_path or None)
        return f"Exported -> **{r['path']}** ({r['size']/1024:.1f} KB)"
    elif a == "share":
        r = drive_service.share_file(file_id, email or None, role, anyone)
        return f"Shared with {r['shared_with']} as {r['role']}\nURL: {r['url']}"
    elif a == "info":
        r = drive_service.get_file_info(file_id)
        return f"**{r['name']}**\nType: {r['mime_type']}\nOwner: {', '.join(r['owners'])}\nShared: {r['shared']}\nURL: {r['url']}"
    elif a == "create_folder":
        r = drive_service.create_folder(name, folder_id or None)
        return f"Created **{r['name']}** (`{r['id']}`)"
    else:
        return f"ERROR: Unknown action '{action}'"


# ═══════════════════════════════════════════════════════════════

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "auth":
        from shared.auth import run_auth_flow
        run_auth_flow()
        return
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
