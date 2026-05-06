"""Google Docs MCP Server — FastMCP server with stdio transport."""

from __future__ import annotations

import sys
import logging
import functools
from typing import Literal

logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)

from mcp.server.fastmcp import FastMCP
from googleapiclient.errors import HttpError

from . import docs_service, drive_service, formatter
from .markdown_parser import markdown_to_requests

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
) -> str:
    """Create a formatted table with headers and data rows in a Google Doc.

    Appends the table at the end of the document. Header row is bolded.

    Args:
        document_id: The Google Doc ID
        headers: Column header labels
        rows: List of rows, each a list of cell values
    """
    md_rows = [headers] + rows
    md_lines = []
    for i, row in enumerate(md_rows):
        md_lines.append("| " + " | ".join(row) + " |")
        if i == 0:
            md_lines.append("| " + " | ".join(["---"] * len(row)) + " |")
    table_md = "\n".join(md_lines)

    end_idx = docs_service.get_end_index(document_id)
    start = end_idx - 1 if end_idx > 1 else 1

    md_requests = markdown_to_requests(table_md, start_index=start)
    docs_service.batch_update(document_id, md_requests, preserve_order=True)

    return f"Added {len(md_rows[0])}-column table with {len(rows)} data rows"


@mcp.tool()
@_handle_errors
def gdocs_replace(document_id: str, find: str, replace: str) -> str:
    """Find and replace text in a Google Doc (case-sensitive).

    Args:
        document_id: The Google Doc ID
        find: Text to search for
        replace: Replacement text
    """
    result = docs_service.replace_all_text(document_id, find, replace)
    return f"Replaced {result['occurrences_replaced']} occurrence(s) of `{find}`"


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

    Removes consecutive blank paragraphs, normalizes spacing.

    Args:
        document_id: The Google Doc ID
    """
    result = formatter.cleanup_document(document_id)
    return f"Fixed {result['issues_fixed']} formatting issue(s)"


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
        from .auth import run_auth_flow
        run_auth_flow()
        return
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
