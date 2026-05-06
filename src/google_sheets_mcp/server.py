"""Google Sheets MCP Server — read, write, format, and manage spreadsheets."""

from __future__ import annotations

import sys
import logging
import functools
from typing import Literal

logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)

from mcp.server.fastmcp import FastMCP
from googleapiclient.errors import HttpError

from . import sheets_service
from shared import drive_service

mcp = FastMCP(
    "google-sheets-mcp",
    instructions="MCP server for Google Sheets — read, write, format, and manage spreadsheets",
)


def _handle_errors(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except HttpError as e:
            status = e.resp.status
            if status == 404:
                return "ERROR: Spreadsheet or sheet not found. Check the ID is correct."
            elif status == 403:
                return "ERROR: Permission denied. You may not have access to this spreadsheet."
            elif status == 429:
                return "ERROR: Google API rate limit exceeded. Wait a moment and try again."
            else:
                return f"ERROR: Google API returned {status}: {e._get_reason()}"
        except RuntimeError as e:
            return f"ERROR: {e}"
        except (FileNotFoundError, ValueError) as e:
            return f"ERROR: {e}"
        except Exception as e:
            return f"ERROR: Unexpected — {type(e).__name__}: {e}"
    return wrapper


# ── Sheets Tools ───────────────────────────────────────────────────


@mcp.tool()
@_handle_errors
def gsheets_create(
    title: str,
    sheet_names: list[str] | None = None,
    folder_id: str | None = None,
) -> str:
    """Create a new Google Spreadsheet.

    Args:
        title: Spreadsheet title
        sheet_names: Optional list of tab names (default: one "Sheet1" tab)
        folder_id: Optional Drive folder ID to place it in
    """
    result = sheets_service.create_spreadsheet(title, sheet_names)
    if folder_id:
        drive_service.move_file(result["spreadsheet_id"], folder_id)
    tabs = ", ".join(s["title"] for s in result["sheets"])
    return f"Created: **{result['title']}**\n- ID: `{result['spreadsheet_id']}`\n- Tabs: {tabs}\n- URL: {result['url']}"


@mcp.tool()
@_handle_errors
def gsheets_get_info(spreadsheet_id: str) -> str:
    """Get metadata about a spreadsheet — title, tabs, row/column counts.

    Args:
        spreadsheet_id: The spreadsheet ID
    """
    result = sheets_service.get_info(spreadsheet_id)
    lines = [f"# {result['title']}\n- ID: `{result['spreadsheet_id']}`\n- URL: {result['url']}\n"]
    for s in result["sheets"]:
        hidden = " (hidden)" if s["hidden"] else ""
        lines.append(f"- **{s['title']}** — {s['row_count']} rows x {s['column_count']} cols{hidden}")
    return "\n".join(lines)


@mcp.tool()
@_handle_errors
def gsheets_read(
    spreadsheet_id: str,
    range: str = "A1:Z1000",
    render: Literal["formatted", "raw", "formula"] = "formatted",
) -> str:
    """Read cell values from a spreadsheet range.

    Args:
        spreadsheet_id: The spreadsheet ID
        range: A1 notation range (e.g. "A1:D10", "Sheet1!A1:D10", "A:A", "1:1")
        render: Value rendering — "formatted" ($1,234.56), "raw" (1234.56), or "formula" (=SUM(A1:A5))
    """
    render_map = {"formatted": "FORMATTED_VALUE", "raw": "UNFORMATTED_VALUE", "formula": "FORMULA"}
    result = sheets_service.read_range(spreadsheet_id, range, render_map.get(render, "FORMATTED_VALUE"))

    values = result["values"]
    if not values:
        return f"Range `{result['range']}` is empty."

    def _escape(val: str) -> str:
        return val.replace("|", "\\|")

    # Format as markdown table
    headers = [_escape(str(h)) for h in values[0]]
    col_widths = [len(h) for h in headers]
    for row in values[1:]:
        for i, cell in enumerate(row):
            if i < len(col_widths):
                col_widths[i] = max(col_widths[i], len(_escape(str(cell))))

    lines = [f"Range: `{result['range']}` ({result['total_rows']} rows)\n"]
    lines.append("| " + " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers)) + " |")
    lines.append("| " + " | ".join("-" * w for w in col_widths) + " |")
    for row in values[1:]:
        cells = []
        for i in range(len(headers)):
            val = _escape(str(row[i])) if i < len(row) else ""
            cells.append(val.ljust(col_widths[i]) if i < len(col_widths) else val)
        lines.append("| " + " | ".join(cells) + " |")

    return "\n".join(lines)


@mcp.tool()
@_handle_errors
def gsheets_write(
    spreadsheet_id: str,
    range: str,
    values: list[list],
    input_mode: Literal["user", "raw"] = "user",
) -> str:
    """Write values to a spreadsheet range, overwriting existing data.

    With input_mode="user", formulas (=SUM), dates, and currencies are parsed.
    With input_mode="raw", values are stored as literal strings.

    Args:
        spreadsheet_id: The spreadsheet ID
        range: A1 notation range (e.g. "Sheet1!A1:C3")
        values: 2D array of values — [[row1col1, row1col2], [row2col1, row2col2]]
        input_mode: "user" (parse formulas/dates) or "raw" (literal strings)
    """
    option = "USER_ENTERED" if input_mode == "user" else "RAW"
    result = sheets_service.write_range(spreadsheet_id, range, values, option)
    return f"Wrote {result['updated_cells']} cells to `{result['updated_range']}`"


@mcp.tool()
@_handle_errors
def gsheets_append(
    spreadsheet_id: str,
    range: str,
    values: list[list],
) -> str:
    """Append rows after the last row of data in a range.

    Args:
        spreadsheet_id: The spreadsheet ID
        range: A1 notation range to append to (e.g. "Sheet1!A1")
        values: 2D array of rows to append — [[val1, val2], [val3, val4]]
    """
    result = sheets_service.append_rows(spreadsheet_id, range, values)
    return f"Appended {result['updated_rows']} row(s) to `{result['updated_range']}`"


@mcp.tool()
@_handle_errors
def gsheets_clear(spreadsheet_id: str, range: str) -> str:
    """Clear all values in a range. Formatting is preserved.

    Args:
        spreadsheet_id: The spreadsheet ID
        range: A1 notation range to clear
    """
    result = sheets_service.clear_range(spreadsheet_id, range)
    return f"Cleared `{result['cleared_range']}`"


@mcp.tool()
@_handle_errors
def gsheets_find(
    spreadsheet_id: str,
    query: str,
    sheet_name: str | None = None,
    match_case: bool = False,
) -> str:
    """Search for text across all cells in a spreadsheet.

    Args:
        spreadsheet_id: The spreadsheet ID
        query: Text to search for
        sheet_name: Optional — limit search to a specific tab
        match_case: Case-sensitive search (default false)
    """
    matches = sheets_service.find_in_sheet(spreadsheet_id, query, sheet_name, match_case)
    if not matches:
        return f"No matches found for: {query}"
    lines = [f"Found {len(matches)} match(es) for \"{query}\":\n"]
    for m in matches[:50]:
        lines.append(f"- `{m['sheet']}!{m['cell']}` = {m['value']}")
    if len(matches) > 50:
        lines.append(f"\n... and {len(matches) - 50} more")
    return "\n".join(lines)


@mcp.tool()
@_handle_errors
def gsheets_format(
    spreadsheet_id: str,
    range: str,
    bold: bool | None = None,
    italic: bool | None = None,
    font_size: int | None = None,
    font_family: str | None = None,
    foreground_color: str | None = None,
    background_color: str | None = None,
    horizontal_alignment: Literal["LEFT", "CENTER", "RIGHT"] | None = None,
    number_format: str | None = None,
    number_format_pattern: str | None = None,
) -> str:
    """Format cells — bold, colors, alignment, number format.

    Args:
        spreadsheet_id: The spreadsheet ID
        range: A1 notation range to format
        bold: Set bold
        italic: Set italic
        font_size: Font size in points
        font_family: Font name (e.g. "Arial", "Courier New")
        foreground_color: Text color as hex "#RRGGBB"
        background_color: Cell background as hex "#RRGGBB"
        horizontal_alignment: LEFT, CENTER, or RIGHT
        number_format: Format type — NUMBER, CURRENCY, PERCENT, DATE, TIME, TEXT
        number_format_pattern: Optional pattern (e.g. "$#,##0.00", "yyyy-MM-dd", "0.00%")
    """
    result = sheets_service.format_cells(
        spreadsheet_id, range,
        bold=bold, italic=italic, font_size=font_size, font_family=font_family,
        foreground_color=foreground_color, background_color=background_color,
        horizontal_alignment=horizontal_alignment,
        number_format_type=number_format, number_format_pattern=number_format_pattern,
    )
    return f"Formatted `{result['formatted_range']}` ({result['fields_applied']} properties applied)"


@mcp.tool()
@_handle_errors
def gsheets_add_sheet(spreadsheet_id: str, title: str) -> str:
    """Add a new sheet (tab) to an existing spreadsheet.

    Args:
        spreadsheet_id: The spreadsheet ID
        title: Name for the new tab
    """
    result = sheets_service.add_sheet(spreadsheet_id, title)
    return f"Added sheet **{result['title']}** (ID: {result['sheet_id']})"


@mcp.tool()
@_handle_errors
def gsheets_delete_sheet(spreadsheet_id: str, sheet_name: str) -> str:
    """Delete a sheet (tab) from a spreadsheet. Cannot be undone.

    Args:
        spreadsheet_id: The spreadsheet ID
        sheet_name: Name of the tab to delete
    """
    result = sheets_service.delete_sheet(spreadsheet_id, sheet_name)
    return f"Deleted sheet **{result['deleted']}**"


@mcp.tool()
@_handle_errors
def gsheets_freeze(
    spreadsheet_id: str,
    sheet_name: str | None = None,
    rows: int = 1,
    columns: int = 0,
    auto_resize: bool = True,
) -> str:
    """Freeze header rows/columns and optionally auto-resize columns to fit content.

    Args:
        spreadsheet_id: The spreadsheet ID
        sheet_name: Tab name (default: first tab)
        rows: Number of rows to freeze (default 1 for header)
        columns: Number of columns to freeze (default 0)
        auto_resize: Auto-fit column widths (default true)
    """
    result = sheets_service.freeze_rows_columns(
        spreadsheet_id, sheet_name, rows, columns, auto_resize
    )
    parts = []
    if result["frozen_rows"]:
        parts.append(f"{result['frozen_rows']} row(s)")
    if result["frozen_columns"]:
        parts.append(f"{result['frozen_columns']} column(s)")
    msg = f"Froze {' and '.join(parts)}" if parts else "Cleared freeze"
    if result["auto_resized"]:
        msg += " + auto-resized columns"
    return msg


@mcp.tool()
@_handle_errors
def gsheets_add_chart(
    spreadsheet_id: str,
    chart_type: Literal["BAR", "COLUMN", "LINE", "AREA", "SCATTER", "PIE", "DONUT"],
    data_range: str,
    title: str | None = None,
    sheet_name: str | None = None,
) -> str:
    """Insert a chart from spreadsheet data.

    For PIE/DONUT: first column = labels, second = values.
    For all others: first column = X axis, remaining = data series.

    Args:
        spreadsheet_id: The spreadsheet ID
        chart_type: Chart type — BAR, COLUMN, LINE, AREA, SCATTER, PIE, or DONUT
        data_range: A1 notation of the data (include headers)
        title: Optional chart title
        sheet_name: Tab containing the data (default: first tab)
    """
    result = sheets_service.add_chart(
        spreadsheet_id, chart_type, data_range, title, sheet_name
    )
    return f"Added {result['chart_type']} chart (ID: {result['chart_id']})"


@mcp.tool()
@_handle_errors
def gsheets_delete_chart(spreadsheet_id: str, chart_id: int) -> str:
    """Delete a chart by its ID (found in gsheets_get_info or returned by gsheets_add_chart).

    Args:
        spreadsheet_id: The spreadsheet ID
        chart_id: The chart ID to delete
    """
    result = sheets_service.delete_chart(spreadsheet_id, chart_id)
    return f"Deleted chart {result['deleted_chart_id']}"


@mcp.tool()
@_handle_errors
def gsheets_rename_sheet(spreadsheet_id: str, sheet_name: str, new_name: str) -> str:
    """Rename a sheet (tab).

    Args:
        spreadsheet_id: The spreadsheet ID
        sheet_name: Current tab name
        new_name: New tab name
    """
    result = sheets_service.rename_sheet(spreadsheet_id, sheet_name, new_name)
    return f"Renamed **{result['old_name']}** → **{result['new_name']}**"


@mcp.tool()
@_handle_errors
def gsheets_sort(
    spreadsheet_id: str,
    range: str,
    sort_column: str,
    ascending: bool = True,
    sheet_name: str | None = None,
) -> str:
    """Sort data in a range by a column.

    Note: the range should NOT include the header row — only the data rows.

    Args:
        spreadsheet_id: The spreadsheet ID
        range: A1 notation of data rows to sort (exclude header)
        sort_column: Column letter to sort by (e.g. "B", "D")
        ascending: Sort ascending (default true)
        sheet_name: Tab name (default: auto-detect from range)
    """
    result = sheets_service.sort_range(spreadsheet_id, range, sort_column, ascending, sheet_name)
    direction = "ascending" if result["ascending"] else "descending"
    return f"Sorted `{result['sorted_range']}` by column {result['sort_column']} ({direction})"


# ── Google Drive Tools (shared) ────────────────────────────────────


@mcp.tool()
@_handle_errors
def gdrive_search(query: str, max_results: int = 20) -> str:
    """Search for files in Google Drive.

    Args:
        query: Search query
        max_results: Maximum results (default 20)
    """
    results = drive_service.search_files(query, max_results=max_results)
    if not results:
        return f"No files found for: {query}"
    lines = [f"Found {len(results)} file(s):\n"]
    for f in results:
        lines.append(f"- **{f['name']}** (`{f['id']}`)\n  {f['mime_type']} | {f['modified']}\n  {f['url']}")
    return "\n".join(lines)


@mcp.tool()
@_handle_errors
def gdrive_list_folder(folder_id: str | None = None, max_results: int = 50) -> str:
    """List files in a Google Drive folder.

    Args:
        folder_id: Folder ID (omit for root)
        max_results: Maximum results (default 50)
    """
    results = drive_service.list_folder(folder_id=folder_id, max_results=max_results)
    if not results:
        return "Folder is empty"
    label = f"folder `{folder_id}`" if folder_id else "My Drive"
    lines = [f"Contents of {label} ({len(results)} items):\n"]
    for f in results:
        lines.append(f"- **{f['name']}** (`{f['id']}`)\n  {f['mime_type']} | {f['modified']}")
    return "\n".join(lines)


@mcp.tool()
@_handle_errors
def gdrive_move(file_id: str, folder_id: str) -> str:
    """Move a file to a different Drive folder.

    Args:
        file_id: The file ID
        folder_id: Target folder ID
    """
    result = drive_service.move_file(file_id, folder_id)
    return f"Moved **{result['name']}** to folder `{folder_id}`"


@mcp.tool()
@_handle_errors
def gdrive_delete(file_id: str, confirm: bool = False) -> str:
    """DESTRUCTIVE: Move a file to trash (recoverable 30 days). Requires confirm=true.

    Args:
        file_id: The file ID to delete
        confirm: Must be true to proceed
    """
    if not confirm:
        return "REFUSED: confirm must be true. Ask the user first."
    result = drive_service.trash_file(file_id)
    return f"Trashed **{result['name']}** (`{result['id']}`)"


# ── Entry Point ────────────────────────────────────────────────────


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "auth":
        from shared.auth import run_auth_flow
        run_auth_flow()
        return
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
