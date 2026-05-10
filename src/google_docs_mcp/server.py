"""Google Docs MCP Server — FastMCP server with stdio transport."""

from __future__ import annotations

import sys
import logging
import functools
from typing import Literal

logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)

from mcp.server.fastmcp import FastMCP
from googleapiclient.errors import HttpError

from . import docs_service, formatter
from .markdown_parser import markdown_to_requests
from shared import drive_service

mcp = FastMCP(
    "google-docs-mcp",
    instructions="MCP server for Google Docs — create, read, and write formatted documents with Markdown",
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
                return f"ERROR: Document or file not found. Check the ID is correct."
            elif status == 403:
                return f"ERROR: Permission denied. You may not have access to this document."
            elif status == 429:
                return f"ERROR: Google API rate limit exceeded. Wait a moment and try again."
            else:
                return f"ERROR: Google API returned {status}: {e._get_reason()}"
        except RuntimeError as e:
            return f"ERROR: {e}"
        except FileNotFoundError as e:
            return f"ERROR: {e}"
        except Exception as e:
            return f"ERROR: Unexpected error — {type(e).__name__}: {e}"
    return wrapper


# ── Google Docs Tools ──────────────────────────────────────────────


@mcp.tool()
@_handle_errors
def gdocs_create(title: str, folder_id: str | None = None) -> str:
    """Create a new Google Doc. Optionally place it in a specific Drive folder.

    Args:
        title: Document title
        folder_id: Optional Google Drive folder ID to place the doc in
    """
    result = docs_service.create_document(title)
    if folder_id:
        drive_service.create_in_folder(result["document_id"], folder_id)
    url = f"https://docs.google.com/document/d/{result['document_id']}/edit"
    return f"Created: **{result['title']}**\n- ID: `{result['document_id']}`\n- URL: {url}"


@mcp.tool()
@_handle_errors
def gdocs_write_markdown(document_id: str, markdown: str) -> str:
    """Write formatted content to a Google Doc using Markdown syntax.

    This is the primary tool for creating formatted documents. Supports:
    headings (#-######), **bold**, *italic*, ~~strikethrough~~, `code`,
    [links](url), bullet lists, numbered lists, nested lists, tables,
    horizontal rules, and code blocks.

    The document's existing content is replaced entirely.

    Args:
        document_id: The Google Doc ID
        markdown: Markdown-formatted content to write
    """
    end_idx = docs_service.get_end_index(document_id)
    clear_requests = []
    if end_idx > 2:
        clear_requests.append({
            "deleteContentRange": {
                "range": {"startIndex": 1, "endIndex": end_idx - 1}
            }
        })
    # Clear any inherited list/bullet formatting from the skeleton paragraph
    clear_requests.append({
        "deleteParagraphBullets": {
            "range": {"startIndex": 1, "endIndex": 2}
        }
    })
    docs_service.batch_update(document_id, clear_requests, preserve_order=True)

    md_requests = markdown_to_requests(markdown, start_index=1)
    docs_service.batch_update(document_id, md_requests, preserve_order=True)

    return f"Wrote {len(md_requests)} formatting operations to `{document_id}`"


@mcp.tool()
@_handle_errors
def gdocs_append_markdown(document_id: str, markdown: str) -> str:
    """Append formatted Markdown content to the end of an existing Google Doc.

    Same Markdown support as gdocs_write_markdown, but appends instead of replacing.

    Args:
        document_id: The Google Doc ID
        markdown: Markdown-formatted content to append
    """
    end_idx = docs_service.get_end_index(document_id)
    start = end_idx - 1 if end_idx > 1 else 1

    md_requests = markdown_to_requests(markdown, start_index=start)
    docs_service.batch_update(document_id, md_requests, preserve_order=True)

    return f"Appended {len(md_requests)} formatting operations to `{document_id}`"


@mcp.tool()
@_handle_errors
def gdocs_read(
    document_id: str,
    format: Literal["text", "markdown", "structure"] = "markdown",
) -> str:
    """Read content from a Google Doc.

    Args:
        document_id: The Google Doc ID
        format: Output format — "text" (plain text), "markdown" (with formatting), or "structure" (document outline)
    """
    if format == "structure":
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

    as_md = format == "markdown"
    result = docs_service.read_document(document_id, as_markdown=as_md)
    return f"# {result['title']}\n\n{result['content']}"


@mcp.tool()
@_handle_errors
def gdocs_add_table(
    document_id: str,
    headers: list[str],
    rows: list[list[str]],
    before_heading: str | None = None,
    after_heading: str | None = None,
) -> str:
    """Create a formatted table with headers and data rows in a Google Doc.

    By default appends at end. Use before_heading/after_heading to position it.

    Args:
        document_id: The Google Doc ID
        headers: Column header labels
        rows: List of rows, each a list of cell values
        before_heading: Insert table before this heading text
        after_heading: Insert table after this heading's section content
    """
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
        start = boundaries["content_end"] - 1
    else:
        end_idx = docs_service.get_end_index(document_id)
        start = end_idx - 1 if end_idx > 1 else 1

    md_requests = markdown_to_requests(table_md, start_index=start)
    docs_service.batch_update(document_id, md_requests, preserve_order=True)

    return f"Added {len(md_rows[0])}-column table with {len(rows)} data rows"


@mcp.tool()
@_handle_errors
def gdocs_replace(
    document_id: str,
    find: str,
    replace: str,
    scope: Literal["all", "first", "section"] = "all",
    section_heading: str | None = None,
) -> str:
    """Find and replace text in a Google Doc (case-sensitive).

    Args:
        document_id: The Google Doc ID
        find: Text to search for
        replace: Replacement text
        scope: "all" (default, replace all), "first" (first occurrence only), or "section" (within a specific section)
        section_heading: Required when scope="section" — heading text of the target section
    """
    if scope == "all":
        result = docs_service.replace_all_text(document_id, find, replace)
        return f"Replaced {result['occurrences_replaced']} occurrence(s) of `{find}`"

    if scope == "section" and not section_heading:
        return "ERROR: section_heading is required when scope='section'"

    # For first/section: use index-based replacement
    doc = docs_service.read_document_raw(document_id)
    tabs = doc.get("tabs", [])
    body = tabs[0].get("documentTab", {}).get("body", {}) if tabs else doc.get("body", {})

    # Determine search range
    range_start = 0
    range_end = float("inf")
    if scope == "section":
        boundaries = docs_service.get_section_boundaries(document_id, section_heading)
        if not boundaries:
            return f"ERROR: Heading '{section_heading}' not found in document"
        range_start = boundaries["heading_start"]
        range_end = boundaries["content_end"]

    # Find occurrences within range — search paragraphs AND table cells
    from shared.utils import utf16_len

    def _find_in_paragraphs(paragraphs):
        """Search text runs in paragraph elements."""
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
                    doc_start = elem_start + idx
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
        # Process in reverse order to maintain indices
        pair_requests = []
        for i in range(0, len(requests), 2):
            pair_requests.append((requests[i], requests[i+1]))
        pair_requests.reverse()
        flat = []
        for delete, insert in pair_requests:
            flat.append(delete)
            flat.append(insert)
        docs_service.batch_update(document_id, flat, preserve_order=True)

    scope_desc = f" in section '{section_heading}'" if scope == "section" else " (first only)" if scope == "first" else ""
    return f"Replaced {count} occurrence(s) of `{find}`{scope_desc}"


@mcp.tool()
@_handle_errors
def gdocs_highlight(
    document_id: str,
    text: str,
    color: Literal["yellow", "green", "blue", "red", "orange", "purple"] = "yellow",
) -> str:
    """Highlight all occurrences of text in a Google Doc with a background color.

    Args:
        document_id: The Google Doc ID
        text: Text to highlight
        color: Highlight color name
    """
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


@mcp.tool()
@_handle_errors
def gdocs_cleanup(document_id: str) -> str:
    """Fix common formatting issues in a Google Doc.

    Fixes: consecutive blank paragraphs, heading style on body text,
    bold inheritance leaks, table cells with wrong font size.

    Args:
        document_id: The Google Doc ID
    """
    result = formatter.cleanup_document(document_id)
    details = result.get("details", [])
    summary = ", ".join(details) if details else "nothing to fix"
    return f"Fixed {result['issues_fixed']} issue(s): {summary}"


@mcp.tool()
@_handle_errors
def gdocs_audit(document_id: str) -> str:
    """Audit a Google Doc's formatting and return a quality report.

    Checks for: excessive blank paragraphs, font inconsistencies,
    heading structure, and more.

    Args:
        document_id: The Google Doc ID
    """
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


@mcp.tool()
@_handle_errors
def gdocs_read_section(
    document_id: str,
    heading_text: str,
    format: Literal["text", "markdown"] = "text",
) -> str:
    """Read content from a specific section of a Google Doc (identified by heading).

    Args:
        document_id: The Google Doc ID
        heading_text: Text of the section heading (supports partial match, e.g. "4.3" matches "4.3 Estimated Cost")
        format: Output format — "text" or "markdown"
    """
    result = docs_service.read_section(document_id, heading_text, as_markdown=(format == "markdown"))
    if not result:
        return f"ERROR: Section with heading '{heading_text}' not found"
    return result["content"]


@mcp.tool()
@_handle_errors
def gdocs_insert_at_section(
    document_id: str,
    markdown: str,
    before_heading: str | None = None,
    after_heading: str | None = None,
) -> str:
    """Insert formatted Markdown content at a specific section position.

    Use before_heading to insert BEFORE a heading, or after_heading to insert
    AFTER a section's content (before the next section starts).

    Args:
        document_id: The Google Doc ID
        markdown: Markdown-formatted content to insert
        before_heading: Insert before this heading text
        after_heading: Insert after this heading's section content
    """
    if not before_heading and not after_heading:
        return "ERROR: Provide either before_heading or after_heading"

    target = before_heading or after_heading
    boundaries = docs_service.get_section_boundaries(document_id, target)
    if not boundaries:
        return f"ERROR: Heading '{target}' not found in document"

    if before_heading:
        insert_at = boundaries["heading_start"]
    else:
        insert_at = boundaries["content_end"] - 1

    md_requests = markdown_to_requests(markdown, start_index=insert_at)
    docs_service.batch_update(document_id, md_requests, preserve_order=True)

    return f"Inserted content {'before' if before_heading else 'after'} section '{target}'"


@mcp.tool()
@_handle_errors
def gdocs_delete_section(
    document_id: str,
    heading_text: str,
    include_heading: bool = True,
) -> str:
    """Delete an entire section from a Google Doc (heading + content until next section).

    Args:
        document_id: The Google Doc ID
        heading_text: Text of the heading to delete
        include_heading: Whether to also delete the heading itself (default True)
    """
    boundaries = docs_service.get_section_boundaries(document_id, heading_text)
    if not boundaries:
        return f"ERROR: Section with heading '{heading_text}' not found"

    start = boundaries["heading_start"] if include_heading else boundaries["content_start"]
    end = boundaries["content_end"]

    if end <= start:
        return "Section is empty, nothing to delete"

    requests = [{"deleteContentRange": {"range": {"startIndex": start, "endIndex": end}}}]
    docs_service.batch_update(document_id, requests)

    what = "Section (heading + content)" if include_heading else "Section content"
    return f"{what} deleted for '{heading_text}'"


@mcp.tool()
@_handle_errors
def gdocs_add_heading(
    document_id: str,
    text: str,
    level: int = 2,
    before_heading: str | None = None,
    after_heading: str | None = None,
) -> str:
    """Insert a heading at a specific position in the document.

    If neither before_heading nor after_heading is specified, appends at end.

    Args:
        document_id: The Google Doc ID
        text: Heading text (e.g., "4.4 Infrastructure Comparison")
        level: Heading level — 1, 2, or 3 (default 2)
        before_heading: Insert before this existing heading text
        after_heading: Insert after this existing heading's section content
    """
    level = max(1, min(level, 6))
    style_map = {1: "HEADING_1", 2: "HEADING_2", 3: "HEADING_3", 4: "HEADING_4", 5: "HEADING_5", 6: "HEADING_6"}
    named_style = style_map[level]

    if before_heading:
        boundaries = docs_service.get_section_boundaries(document_id, before_heading)
        if not boundaries:
            return f"ERROR: Heading '{before_heading}' not found"
        insert_at = boundaries["heading_start"]
    elif after_heading:
        boundaries = docs_service.get_section_boundaries(document_id, after_heading)
        if not boundaries:
            return f"ERROR: Heading '{after_heading}' not found"
        insert_at = boundaries["content_end"] - 1
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
    return f"Added H{level} heading '{text}' {pos}"


@mcp.tool()
@_handle_errors
def gdocs_delete_table_row(
    document_id: str,
    table_index: int,
    row_index: int,
) -> str:
    """Delete a row from a table in a Google Doc.

    Args:
        document_id: The Google Doc ID
        table_index: Which table (0-based, e.g. 0 for first table)
        row_index: Which row to delete (0-based)
    """
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


@mcp.tool()
@_handle_errors
def gdocs_update_table_cell(
    document_id: str,
    table_index: int,
    row: int,
    col: int,
    text: str,
) -> str:
    """Update the text content of a specific table cell.

    Args:
        document_id: The Google Doc ID
        table_index: Which table (0-based)
        row: Row index (0-based)
        col: Column index (0-based)
        text: New text content for the cell
    """
    tables = docs_service.find_tables(document_id)
    if table_index >= len(tables):
        return f"ERROR: Document has {len(tables)} table(s), index {table_index} is out of range"

    table = tables[table_index]
    if row >= table["rows"] or col >= table["columns"]:
        return f"ERROR: Cell [{row},{col}] is out of range (table is {table['rows']}x{table['columns']})"

    cell = table["data"][row][col]
    cell_start = cell["start"]
    cell_end = cell["end"]

    from shared.utils import utf16_len
    requests = []

    # Delete existing content (keep the paragraph marker)
    old_text = cell["text"]
    if old_text:
        # Cell content starts at cell_start, ends before paragraph break
        content_end = cell_start + utf16_len(old_text)
        requests.append({"deleteContentRange": {"range": {"startIndex": cell_start, "endIndex": content_end}}})

    # Insert new text
    if text:
        requests.append({"insertText": {"location": {"index": cell_start}, "text": text}})
        # Set 11pt font explicitly
        requests.append({"updateTextStyle": {
            "range": {"startIndex": cell_start, "endIndex": cell_start + utf16_len(text)},
            "textStyle": {"fontSize": {"magnitude": 11, "unit": "PT"}, "bold": False},
            "fields": "fontSize,bold",
        }})

    if requests:
        docs_service.batch_update(document_id, requests, preserve_order=True)

    return f"Updated cell [{row},{col}] in table {table_index} to '{text}'"


@mcp.tool()
@_handle_errors
def gdrive_move(file_id: str, folder_id: str) -> str:
    """Move a file to a different Drive folder. Works with Docs, Sheets, Slides, or any Drive file.

    Args:
        file_id: The file ID (Google Doc, Sheet, Slide, or any Drive file)
        folder_id: Target folder ID in Google Drive
    """
    result = drive_service.move_file(file_id, folder_id)
    return f"Moved **{result['name']}** to folder `{folder_id}`\n- URL: {result['url']}"


@mcp.tool()
@_handle_errors
def gdrive_delete(file_id: str, confirm: bool = False) -> str:
    """DESTRUCTIVE: Move a file to trash. Works with Docs, Sheets, Slides, or any Drive file.

    The file is moved to Google Drive trash (recoverable for 30 days).
    You MUST set confirm=true to proceed. Always ask the user for
    explicit permission before calling this tool.

    Args:
        file_id: The file ID to delete (Google Doc, Sheet, Slide, or any Drive file)
        confirm: Must be true to proceed — safety guard against accidental deletion
    """
    if not confirm:
        return "REFUSED: confirm must be set to true. Please ask the user to confirm deletion first."
    result = drive_service.trash_file(file_id)
    return f"Trashed **{result['name']}** (`{result['id']}`). Recoverable from Google Drive trash for 30 days."


# ── Google Drive Tools ─────────────────────────────────────────────


@mcp.tool()
@_handle_errors
def gdrive_search(query: str, max_results: int = 20) -> str:
    """Search for files in Google Drive.

    Args:
        query: Search query (searches file names and content)
        max_results: Maximum number of results (default 20)
    """
    results = drive_service.search_files(query, max_results=max_results)
    if not results:
        return f"No files found for: {query}"
    lines = [f"Found {len(results)} file(s):\n"]
    for f in results:
        lines.append(f"- **{f['name']}** (`{f['id']}`)\n  Type: {f['mime_type']} | Modified: {f['modified']}\n  {f['url']}")
    return "\n".join(lines)


@mcp.tool()
@_handle_errors
def gdrive_list_folder(folder_id: str | None = None, max_results: int = 50) -> str:
    """List files in a Google Drive folder.

    Args:
        folder_id: Folder ID (omit for root/My Drive)
        max_results: Maximum number of results (default 50)
    """
    results = drive_service.list_folder(folder_id=folder_id, max_results=max_results)
    if not results:
        return "Folder is empty"
    label = f"folder `{folder_id}`" if folder_id else "My Drive (root)"
    lines = [f"Contents of {label} ({len(results)} items):\n"]
    for f in results:
        icon = "\U0001f4c1" if "folder" in f["mime_type"] else "\U0001f4c4"
        lines.append(f"- {icon} **{f['name']}** (`{f['id']}`)\n  {f['mime_type']} | {f['modified']}")
    return "\n".join(lines)


# ── Entry Point ────────────────────────────────────────────────────


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "auth":
        from shared.auth import run_auth_flow
        run_auth_flow()
        return
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
