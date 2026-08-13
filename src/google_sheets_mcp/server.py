"""Google Sheets MCP Server — consolidated tools for create, read, write, format, and manage spreadsheets."""

from __future__ import annotations

import sys
import logging
import functools
from typing import Literal

logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from googleapiclient.errors import HttpError

from . import sheets_service
from shared import drive_service

mcp = FastMCP(
    "google-sheets-mcp",
    instructions="""MCP server for Google Sheets — create, read, write, format, and manage spreadsheets.

WORKFLOW FOR CREATING A SPREADSHEET:
1. gsheets_create — create the spreadsheet with named tabs
2. gsheets_write(action="write") — populate headers and data
3. gsheets_format(action="style") — bold headers, colors, number formats
4. gsheets_manage(action="freeze") — freeze header row + auto-resize columns
5. gsheets_format(action="borders") — add borders to data range
6. gsheets_manage(action="add_chart") — visualize the data

WORKFLOW FOR EDITING EXISTING SHEETS:
1. gsheets_read(action="info") — see tabs, row counts, chart IDs
2. gsheets_read(action="read") — read the data as markdown table
3. gsheets_read(action="find") — locate specific cells
4. gsheets_write/gsheets_format — make changes

DATA FORMATTING BEST PRACTICES:
- Always freeze row 1 (headers) after writing data.
- Bold + background color on header row for scannability.
- Use number_format for currencies ($#,##0.00), percentages (0.00%), dates (yyyy-MM-dd).
- Add borders="outer" on the full data range for clean boundaries.
- Conditional formatting for KPIs: green for good, red for bad.
- Auto-resize columns after writing to fit content.

CHART TYPE SELECTION GUIDE:
- LINE — trends over time (sales by month)
- COLUMN — comparing categories (revenue by region)
- BAR — horizontal comparison, long labels
- PIE/DONUT — parts of a whole (max 6 slices)
- SCATTER — correlation between two variables
- AREA — cumulative trends, stacked contributions
- For PIE/DONUT: first column = labels, second = values
- For all others: first column = X axis, remaining = data series
""",
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


# ═══════════════════════════════════════════════════════════════
# TOOL 1: CREATE
# ═══════════════════════════════════════════════════════════════

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True))
@_handle_errors
def gsheets_create(
    title: str,
    sheet_names: list[str] | None = None,
    folder_id: str | None = None,
) -> str:
    """Create a new Google Spreadsheet.

    WORKFLOW: create -> write headers/data -> format headers -> freeze row 1 -> add borders.

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


# ═══════════════════════════════════════════════════════════════
# TOOL 2: READ (read, info, find)
# ═══════════════════════════════════════════════════════════════

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True))
@_handle_errors
def gsheets_read(
    spreadsheet_id: str,
    action: str = "read",
    cell_range: str = "A1:Z1000",
    render: Literal["formatted", "raw", "formula"] = "formatted",
    query: str = "",
    sheet_name: str | None = None,
    match_case: bool = False,
) -> str:
    """Read data from a spreadsheet — cell values, metadata, or search.

    GUIDELINES:
    - Start with action="info" to understand the spreadsheet structure (tabs, sizes, charts)
    - Use action="read" with a specific range for efficiency — avoid reading entire sheets
    - Use action="find" to locate specific values before editing
    - render="formula" reveals formulas; render="raw" gives unformatted numbers

    ACTIONS:
    - "read" — read cell values as a markdown table (uses: range, render)
    - "info" — get spreadsheet metadata: title, tabs, row/column counts (no extra params)
    - "find" — search for text across cells (uses: query, sheet_name, match_case)

    Args:
        spreadsheet_id: The spreadsheet ID
        action: Operation — "read", "info", or "find"
        range: A1 notation range for read (e.g. "A1:D10", "Sheet1!A1:D10", "A:A")
        render: Value rendering for read — "formatted" ($1,234.56), "raw" (1234.56), or "formula" (=SUM(A1:A5))
        query: Text to search for (find action)
        sheet_name: Limit search to a specific tab (find action)
        match_case: Case-sensitive search (find action, default false)
    """
    a = action.lower()

    if a == "read":
        render_map = {"formatted": "FORMATTED_VALUE", "raw": "UNFORMATTED_VALUE", "formula": "FORMULA"}
        result = sheets_service.read_range(spreadsheet_id, cell_range, render_map.get(render, "FORMATTED_VALUE"))

        values = result["values"]
        if not values:
            return f"Range `{result['range']}` is empty."

        def _escape(val: str) -> str:
            return val.replace("|", "\\|")

        headers = [_escape(str(h)) for h in values[0]]
        if all(h.strip() == "" for h in headers):
            headers = [f"Col{i}" for i in range(len(headers))]
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

    elif a == "info":
        result = sheets_service.get_info(spreadsheet_id)
        lines = [f"# {result['title']}\n- ID: `{result['spreadsheet_id']}`\n- URL: {result['url']}\n"]
        for s in result["sheets"]:
            hidden = " (hidden)" if s["hidden"] else ""
            chart_info = f", charts: {s['chart_ids']}" if s.get("chart_ids") else ""
            lines.append(f"- **{s['title']}** — {s['row_count']} rows x {s['column_count']} cols{hidden}{chart_info}")
        return "\n".join(lines)

    elif a == "find":
        if not query:
            return "ERROR: query is required for find action."
        matches = sheets_service.find_in_sheet(spreadsheet_id, query, sheet_name, match_case)
        if not matches:
            return f"No matches found for: {query}"
        lines = [f"Found {len(matches)} match(es) for \"{query}\":\n"]
        for m in matches[:50]:
            lines.append(f"- `{m['sheet']}!{m['cell']}` = {m['value']}")
        if len(matches) > 50:
            lines.append(f"\n... and {len(matches) - 50} more")
        return "\n".join(lines)

    else:
        return f"ERROR: Unknown action '{action}'. Use: read, info, find"


# ═══════════════════════════════════════════════════════════════
# TOOL 3: WRITE (write, append, clear)
# ═══════════════════════════════════════════════════════════════

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True))
@_handle_errors
def gsheets_write(
    spreadsheet_id: str,
    action: str = "write",
    cell_range: str = "",
    values: list[list] | None = None,
    input_mode: Literal["user", "raw"] = "user",
) -> str:
    """Write, append, or clear data in a spreadsheet.

    GUIDELINES:
    - Use action="write" with input_mode="user" so formulas (=SUM), dates, and currencies are parsed
    - Use action="append" to add rows without overwriting — it finds the last row automatically
    - Use action="clear" to erase values while preserving formatting and borders
    - Always include headers in the first write to a new range

    ACTIONS:
    - "write" — overwrite a range with new values (uses: range, values, input_mode)
    - "append" — append rows after the last data row (uses: range, values)
    - "clear" — clear all values in a range, formatting preserved (uses: range)

    Args:
        spreadsheet_id: The spreadsheet ID
        action: Operation — "write", "append", or "clear"
        range: A1 notation range (e.g. "Sheet1!A1:C3", "A1")
        values: 2D array of values — [[row1col1, row1col2], [row2col1, row2col2]]
        input_mode: For write — "user" (parse formulas/dates) or "raw" (literal strings)
    """
    a = action.lower()

    if a == "write":
        if not cell_range:
            return "ERROR: cell_range is required for write action."
        if not values:
            return "ERROR: values is required for write action."
        option = "USER_ENTERED" if input_mode == "user" else "RAW"
        result = sheets_service.write_range(spreadsheet_id, cell_range, values, option)
        return f"Wrote {result['updated_cells']} cells to `{result['updated_range']}`"

    elif a == "append":
        if not cell_range:
            return "ERROR: cell_range is required for append action."
        if not values:
            return "ERROR: values is required for append action."
        result = sheets_service.append_rows(spreadsheet_id, cell_range, values)
        return f"Appended {result['updated_rows']} row(s) to `{result['updated_range']}`"

    elif a == "clear":
        if not cell_range:
            return "ERROR: cell_range is required for clear action."
        result = sheets_service.clear_range(spreadsheet_id, cell_range)
        return f"Cleared `{result['cleared_range']}`"

    else:
        return f"ERROR: Unknown action '{action}'. Use: write, append, clear"


# ═══════════════════════════════════════════════════════════════
# TOOL 4: FORMAT (style, borders, merge, unmerge,
#                 conditional_format, data_validation)
# ═══════════════════════════════════════════════════════════════

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True))
@_handle_errors
def gsheets_format(
    spreadsheet_id: str,
    action: str = "style",
    cell_range: str = "",
    bold: bool | None = None,
    italic: bool | None = None,
    font_size: int | None = None,
    font_family: str | None = None,
    foreground_color: str | None = None,
    background_color: str | None = None,
    horizontal_alignment: Literal["LEFT", "CENTER", "RIGHT"] | None = None,
    vertical_alignment: Literal["TOP", "MIDDLE", "BOTTOM"] | None = None,
    wrap_strategy: Literal["OVERFLOW_CELL", "LEGACY_WRAP", "CLIP", "WRAP"] | None = None,
    number_format: str | None = None,
    number_format_pattern: str | None = None,
    style: Literal["SOLID", "SOLID_MEDIUM", "SOLID_THICK", "DASHED", "DOTTED", "DOUBLE"] = "SOLID",
    color: str = "#000000",
    edges: str = "all",
    merge_type: Literal["MERGE_ALL", "MERGE_COLUMNS", "MERGE_ROWS"] = "MERGE_ALL",
    rule_type: str = "",
    values: list[str] | None = None,
    bg_color: str | None = None,
    text_color: str | None = None,
    custom_formula: str | None = None,
    strict: bool = True,
    input_message: str | None = None,
) -> str:
    """Format cells — styling, borders, merging, conditional formatting, and data validation.

    GUIDELINES:
    - Bold + background_color on header rows for readability
    - Use number_format for consistent display: CURRENCY ($#,##0.00), PERCENT (0.00%), DATE (yyyy-MM-dd)
    - Add action="borders" with edges="outer" on the full data range for clean boundaries
    - Use action="conditional_format" for KPI highlighting: green bg for targets met, red for missed
    - Use action="data_validation" with rule_type="ONE_OF_LIST" for dropdown menus

    ACTIONS:
    - "style" — cell formatting (uses: range, bold, italic, font_size, font_family, foreground_color, background_color, horizontal_alignment, vertical_alignment, wrap_strategy, number_format, number_format_pattern)
    - "borders" — add borders (uses: range, style, color, edges). Edges: all, outer, inner, top, bottom, left, right
    - "merge" — merge cells (uses: range, merge_type). Types: MERGE_ALL, MERGE_COLUMNS, MERGE_ROWS
    - "unmerge" — unmerge cells (uses: range)
    - "conditional_format" — conditional formatting (uses: range, rule_type, values, bg_color, text_color, bold, custom_formula). Rule types: NUMBER_GREATER, NUMBER_LESS, NUMBER_BETWEEN, TEXT_CONTAINS, TEXT_NOT_CONTAINS, BLANK, NOT_BLANK, CUSTOM_FORMULA
    - "data_validation" — set validation rules (uses: range, rule_type, values, strict, input_message). Rule types: ONE_OF_LIST, NUMBER_BETWEEN, TEXT_IS_EMAIL, DATE_AFTER

    Args:
        spreadsheet_id: The spreadsheet ID
        action: Operation — "style", "borders", "merge", "unmerge", "conditional_format", "data_validation"
        range: A1 notation range to format
        bold: Set bold (style/conditional_format)
        italic: Set italic (style)
        font_size: Font size in points (style)
        font_family: Font name e.g. "Arial" (style)
        foreground_color: Text color hex "#RRGGBB" (style)
        background_color: Cell background hex "#RRGGBB" (style)
        horizontal_alignment: LEFT, CENTER, or RIGHT (style)
        vertical_alignment: TOP, MIDDLE, or BOTTOM (style)
        wrap_strategy: OVERFLOW_CELL, LEGACY_WRAP, CLIP, or WRAP (style)
        number_format: Format type — NUMBER, CURRENCY, PERCENT, DATE, TIME, TEXT (style)
        number_format_pattern: Pattern e.g. "$#,##0.00", "yyyy-MM-dd", "0.00%" (style)
        style: Border style (borders)
        color: Border color hex (borders)
        edges: Border edges — all, outer, inner, top, bottom, left, right (borders)
        merge_type: MERGE_ALL, MERGE_COLUMNS, or MERGE_ROWS (merge)
        rule_type: Condition/validation type (conditional_format/data_validation)
        values: Condition values e.g. ["100"] or dropdown options ["A","B","C"] (conditional_format/data_validation)
        bg_color: Background color hex for matching cells (conditional_format)
        text_color: Text color hex for matching cells (conditional_format)
        custom_formula: Formula for CUSTOM_FORMULA rule e.g. "=$D2<TODAY()" (conditional_format)
        strict: Reject invalid input (data_validation, default true)
        input_message: Tooltip shown to user (data_validation)
    """
    a = action.lower()

    if a == "style":
        if not cell_range:
            return "ERROR: range is required for style action."
        result = sheets_service.format_cells(
            spreadsheet_id, cell_range,
            bold=bold, italic=italic, font_size=font_size, font_family=font_family,
            foreground_color=foreground_color, background_color=background_color,
            horizontal_alignment=horizontal_alignment,
            vertical_alignment=vertical_alignment, wrap_strategy=wrap_strategy,
            number_format_type=number_format, number_format_pattern=number_format_pattern,
        )
        return f"Formatted `{result['formatted_range']}` ({result['fields_applied']} properties applied)"

    elif a == "borders":
        if not cell_range:
            return "ERROR: range is required for borders action."
        result = sheets_service.add_borders(spreadsheet_id, cell_range, style, color, edges=edges)
        return f"Added {edges} borders on `{result['bordered_range']}`"

    elif a == "merge":
        if not cell_range:
            return "ERROR: range is required for merge action."
        result = sheets_service.merge_cells(spreadsheet_id, cell_range, merge_type)
        return f"Merged `{result['merged_range']}` ({result['merge_type']})"

    elif a == "unmerge":
        if not cell_range:
            return "ERROR: range is required for unmerge action."
        result = sheets_service.unmerge_cells(spreadsheet_id, cell_range)
        return f"Unmerged `{result['unmerged_range']}`"

    elif a == "conditional_format":
        if not cell_range:
            return "ERROR: range is required for conditional_format action."
        if not rule_type:
            return "ERROR: rule_type is required for conditional_format action."
        result = sheets_service.add_conditional_format(
            spreadsheet_id, cell_range, rule_type, values, bg_color, text_color, bold, custom_formula=custom_formula,
        )
        return f"Added {result['rule_type']} conditional format on `{result['range']}`"

    elif a == "data_validation":
        if not cell_range:
            return "ERROR: range is required for data_validation action."
        if not rule_type:
            return "ERROR: rule_type is required for data_validation action."
        result = sheets_service.set_data_validation(
            spreadsheet_id, cell_range, rule_type, values, strict, input_message,
        )
        return f"Set {result['rule_type']} validation on `{result['range']}`"

    else:
        return f"ERROR: Unknown action '{action}'. Use: style, borders, merge, unmerge, conditional_format, data_validation"


# ═══════════════════════════════════════════════════════════════
# TOOL 5: MANAGE (add_sheet, delete_sheet, rename_sheet,
#                 duplicate_sheet, freeze, sort, add_chart,
#                 delete_chart)
# ═══════════════════════════════════════════════════════════════

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True))
@_handle_errors
def gsheets_manage(
    spreadsheet_id: str,
    action: str,
    title: str = "",
    sheet_name: str | None = None,
    new_name: str = "",
    rows: int = 1,
    columns: int = 0,
    sort_column: str = "",
    ascending: bool = True,
    chart_type: Literal["BAR", "COLUMN", "LINE", "AREA", "SCATTER", "PIE", "DONUT"] = "COLUMN",
    data_range: str = "",
    chart_id: int | None = None,
    auto_resize: bool = True,
    anchor_row: int = 0,
    anchor_column: int = 0,
) -> str:
    """Manage spreadsheet structure — tabs, freezing, sorting, and charts.

    GUIDELINES:
    - Always freeze headers after writing data: action="freeze" with rows=1
    - Duplicate a sheet before making destructive changes as a backup
    - Sort excludes the header row — provide only the data range
    - For charts, include headers in data_range — first column is the X axis

    ACTIONS:
    - "add_sheet" — add a new tab (uses: title)
    - "delete_sheet" — delete a tab, cannot be undone (uses: sheet_name)
    - "rename_sheet" — rename a tab (uses: sheet_name, new_name)
    - "duplicate_sheet" — clone a tab (uses: sheet_name, new_name)
    - "freeze" — freeze header rows/columns + auto-resize (uses: sheet_name, rows, columns, auto_resize)
    - "auto_resize" — auto-fit column widths to content (uses: sheet_name)
    - "sort" — sort data in a range by column (uses: data_range, sort_column, ascending, sheet_name). Exclude header row from data_range.
    - "add_chart" — insert a chart from data (uses: chart_type, data_range, title, sheet_name, anchor_row, anchor_column)
    - "delete_chart" — remove a chart (uses: chart_id)

    Args:
        spreadsheet_id: The spreadsheet ID
        action: Operation — "add_sheet", "delete_sheet", "rename_sheet", "duplicate_sheet", "freeze", "auto_resize", "sort", "add_chart", "delete_chart"
        title: Name for new tab (add_sheet) or chart title (add_chart)
        sheet_name: Tab name for sheet operations and chart/sort context
        new_name: New name for rename/duplicate
        rows: Rows to freeze (freeze, default 1)
        columns: Columns to freeze (freeze, default 0)
        sort_column: Column letter to sort by e.g. "B" (sort)
        ascending: Sort ascending (sort, default true)
        chart_type: BAR, COLUMN, LINE, AREA, SCATTER, PIE, or DONUT (add_chart)
        data_range: A1 notation of data for sort or chart (include headers for charts)
        chart_id: Chart ID to delete (delete_chart — find via gsheets_read action="info")
        auto_resize: Auto-fit column widths (freeze, default true)
        anchor_row: Row index for chart placement (add_chart, default 0)
        anchor_column: Column index for chart placement (add_chart, default 0)
    """
    a = action.lower()

    if a == "add_sheet":
        if not title:
            return "ERROR: title is required for add_sheet action."
        result = sheets_service.add_sheet(spreadsheet_id, title)
        return f"Added sheet **{result['title']}** (ID: {result['sheet_id']})"

    elif a == "delete_sheet":
        if not sheet_name:
            return "ERROR: sheet_name is required for delete_sheet action."
        result = sheets_service.delete_sheet(spreadsheet_id, sheet_name)
        return f"Deleted sheet **{result['deleted']}**"

    elif a == "rename_sheet":
        if not sheet_name:
            return "ERROR: sheet_name is required for rename_sheet action."
        if not new_name:
            return "ERROR: new_name is required for rename_sheet action."
        result = sheets_service.rename_sheet(spreadsheet_id, sheet_name, new_name)
        return f"Renamed **{result['old_name']}** -> **{result['new_name']}**"

    elif a == "duplicate_sheet":
        if not sheet_name:
            return "ERROR: sheet_name is required for duplicate_sheet action."
        result = sheets_service.duplicate_sheet(spreadsheet_id, sheet_name, new_name or None)
        return f"Duplicated to **{result['title']}** (ID: {result['sheet_id']})"

    elif a == "freeze":
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

    elif a == "auto_resize":
        result = sheets_service.auto_resize_columns(spreadsheet_id, sheet_name)
        return f"Auto-resized columns on **{result['sheet_name']}**"

    elif a == "sort":
        if not data_range:
            return "ERROR: data_range is required for sort action."
        if not sort_column:
            return "ERROR: sort_column is required for sort action."
        result = sheets_service.sort_range(spreadsheet_id, data_range, sort_column, ascending, sheet_name)
        direction = "ascending" if result["ascending"] else "descending"
        return f"Sorted `{result['sorted_range']}` by column {result['sort_column']} ({direction})"

    elif a == "add_chart":
        if not data_range:
            return "ERROR: data_range is required for add_chart action."
        result = sheets_service.add_chart(
            spreadsheet_id, chart_type, data_range, title or None, sheet_name,
            anchor_row=anchor_row, anchor_column=anchor_column,
        )
        return f"Added {result['chart_type']} chart (ID: {result['chart_id']})"

    elif a == "delete_chart":
        if chart_id is None:
            return "ERROR: chart_id is required for delete_chart action."
        result = sheets_service.delete_chart(spreadsheet_id, chart_id)
        return f"Deleted chart {result['deleted_chart_id']}"

    else:
        return f"ERROR: Unknown action '{action}'. Use: add_sheet, delete_sheet, rename_sheet, duplicate_sheet, freeze, auto_resize, sort, add_chart, delete_chart"


# ═══════════════════════════════════════════════════════════════
# DRIVE TOOLS (shared)
# ═══════════════════════════════════════════════════════════════

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True))
@_handle_errors
def gdrive_search(query: str, max_results: int = 20) -> str:
    """Search for files in Google Drive by name or content.

    USE FOR: Finding spreadsheet IDs, template files, data files.
    Returns file IDs needed by other tools.

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

    USE FOR: Browsing folder contents, finding spreadsheets, checking what exists.
    Returns file IDs and types.

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
