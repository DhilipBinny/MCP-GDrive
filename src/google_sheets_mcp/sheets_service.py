"""Google Sheets API wrapper — create, read, write, format, and manage spreadsheets."""

from __future__ import annotations

from googleapiclient.discovery import build

from shared.auth import get_credentials
from shared.utils import (
    execute_with_retry, hex_to_rgb, parse_a1_range,
    parse_values, resolve_sheet_id, quote_sheet_name, index_to_col,
)

_service = None


def _get_service():
    global _service
    if _service is None:
        creds = get_credentials()
        _service = build("sheets", "v4", credentials=creds)
    return _service


def create_spreadsheet(title: str, sheet_names: list[str] | None = None) -> dict:
    service = _get_service()
    body: dict = {"properties": {"title": title}}
    if sheet_names:
        body["sheets"] = [{"properties": {"title": name}} for name in sheet_names]
    spreadsheet = execute_with_retry(service.spreadsheets().create(body=body))
    return {
        "spreadsheet_id": spreadsheet["spreadsheetId"],
        "title": spreadsheet["properties"]["title"],
        "url": spreadsheet["spreadsheetUrl"],
        "sheets": [
            {"title": s["properties"]["title"], "sheet_id": s["properties"]["sheetId"]}
            for s in spreadsheet.get("sheets", [])
        ],
    }


def get_info(spreadsheet_id: str) -> dict:
    service = _get_service()
    spreadsheet = execute_with_retry(
        service.spreadsheets().get(spreadsheetId=spreadsheet_id)
    )
    sheets = []
    for s in spreadsheet.get("sheets", []):
        props = s["properties"]
        grid = props.get("gridProperties", {})
        chart_ids = [c["chartId"] for c in s.get("charts", [])]
        sheets.append({
            "title": props["title"],
            "sheet_id": props["sheetId"],
            "index": props["index"],
            "row_count": grid.get("rowCount", 0),
            "column_count": grid.get("columnCount", 0),
            "hidden": props.get("hidden", False),
            "chart_ids": chart_ids,
        })
    return {
        "spreadsheet_id": spreadsheet_id,
        "title": spreadsheet["properties"]["title"],
        "url": spreadsheet.get("spreadsheetUrl", ""),
        "sheets": sheets,
    }


def read_range(
    spreadsheet_id: str,
    range_str: str,
    value_render_option: str = "FORMATTED_VALUE",
) -> dict:
    service = _get_service()
    result = execute_with_retry(
        service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_str,
            valueRenderOption=value_render_option,
        )
    )
    values = result.get("values", [])
    return {
        "range": result.get("range", range_str),
        "values": values,
        "total_rows": len(values),
    }


def write_range(
    spreadsheet_id: str,
    range_str: str,
    values: list[list],
    value_input_option: str = "USER_ENTERED",
    date_format: str | None = None,
) -> dict:
    """Write values to a range, optionally applying a date number format.

    Args:
        spreadsheet_id: The spreadsheet ID.
        range_str: A1 notation range (e.g. "Sheet1!A2:A5").
        values: 2D array of values to write.
        value_input_option: "USER_ENTERED" or "RAW".
        date_format: Optional date format pattern (e.g. "yyyy-MM-dd").
            When provided, a number format of type DATE with this pattern
            is applied to the written range after writing values.
    """
    service = _get_service()
    values = parse_values(values)
    result = execute_with_retry(
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=range_str,
            valueInputOption=value_input_option,
            body={"values": values},
        )
    )

    if date_format:
        sheet_name = None
        if "!" in range_str:
            sheet_name = range_str.split("!")[0].strip("'")
        sheet_id, _ = resolve_sheet_id(service, spreadsheet_id, sheet_name)
        grid_range = parse_a1_range(range_str, sheet_id)

        execute_with_retry(
            service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"requests": [{
                    "repeatCell": {
                        "range": grid_range,
                        "cell": {
                            "userEnteredFormat": {
                                "numberFormat": {
                                    "type": "DATE",
                                    "pattern": date_format,
                                }
                            }
                        },
                        "fields": "userEnteredFormat.numberFormat",
                    }
                }]},
            )
        )

    return {
        "updated_range": result.get("updatedRange", ""),
        "updated_rows": result.get("updatedRows", 0),
        "updated_cells": result.get("updatedCells", 0),
    }


def append_rows(
    spreadsheet_id: str,
    range_str: str,
    values: list[list],
    value_input_option: str = "USER_ENTERED",
) -> dict:
    service = _get_service()
    values = parse_values(values)
    result = execute_with_retry(
        service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=range_str,
            valueInputOption=value_input_option,
            insertDataOption="INSERT_ROWS",
            body={"values": values},
        )
    )
    updates = result.get("updates", {})
    return {
        "updated_range": updates.get("updatedRange", ""),
        "updated_rows": updates.get("updatedRows", 0),
        "updated_cells": updates.get("updatedCells", 0),
    }


def clear_range(spreadsheet_id: str, range_str: str) -> dict:
    service = _get_service()
    execute_with_retry(
        service.spreadsheets().values().clear(
            spreadsheetId=spreadsheet_id,
            range=range_str,
            body={},
        )
    )
    return {"cleared_range": range_str}


def find_in_sheet(
    spreadsheet_id: str,
    query: str,
    sheet_name: str | None = None,
    match_case: bool = False,
    max_rows: int = 200000,
) -> list[dict]:
    service = _get_service()
    info = get_info(spreadsheet_id)
    matches = []

    sheets_to_search = info["sheets"]
    if sheet_name:
        sheets_to_search = [s for s in sheets_to_search if s["title"] == sheet_name]
        if not sheets_to_search:
            raise ValueError(f"Sheet '{sheet_name}' not found")

    for sheet in sheets_to_search:
        qname = quote_sheet_name(sheet["title"])
        result = execute_with_retry(
            service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id,
                range=f"{qname}!A1:ZZ{max_rows}",
                valueRenderOption="FORMATTED_VALUE",
            )
        )
        values = result.get("values", [])
        q = query if match_case else query.lower()
        for r_idx, row in enumerate(values):
            for c_idx, cell in enumerate(row):
                cell_str = str(cell)
                compare = cell_str if match_case else cell_str.lower()
                if q in compare:
                    col_letter = index_to_col(c_idx)
                    matches.append({
                        "sheet": sheet["title"],
                        "cell": f"{col_letter}{r_idx + 1}",
                        "value": cell_str,
                    })
    return matches


def format_cells(
    spreadsheet_id: str,
    range_str: str,
    bold: bool | None = None,
    italic: bool | None = None,
    font_size: int | None = None,
    font_family: str | None = None,
    foreground_color: str | None = None,
    background_color: str | None = None,
    horizontal_alignment: str | None = None,
    vertical_alignment: str | None = None,
    wrap_strategy: str | None = None,
    number_format_type: str | None = None,
    number_format_pattern: str | None = None,
) -> dict:
    service = _get_service()

    # Resolve sheet — strip quotes from sheet name (e.g. 'Q2 Data'!A1 → Q2 Data)
    sheet_name = None
    if "!" in range_str:
        sheet_name = range_str.split("!")[0].strip("'")
    sheet_id, _ = resolve_sheet_id(service, spreadsheet_id, sheet_name)
    grid_range = parse_a1_range(range_str, sheet_id)

    cell_format: dict = {}
    fields = []

    text_format: dict = {}
    if bold is not None:
        text_format["bold"] = bold
        fields.append("userEnteredFormat.textFormat.bold")
    if italic is not None:
        text_format["italic"] = italic
        fields.append("userEnteredFormat.textFormat.italic")
    if font_size is not None:
        text_format["fontSize"] = font_size
        fields.append("userEnteredFormat.textFormat.fontSize")
    if font_family is not None:
        text_format["fontFamily"] = font_family
        fields.append("userEnteredFormat.textFormat.fontFamily")
    if foreground_color is not None:
        text_format["foregroundColorStyle"] = {"rgbColor": hex_to_rgb(foreground_color)}
        fields.append("userEnteredFormat.textFormat.foregroundColorStyle")
    if text_format:
        cell_format["textFormat"] = text_format

    if background_color is not None:
        cell_format["backgroundColorStyle"] = {"rgbColor": hex_to_rgb(background_color)}
        fields.append("userEnteredFormat.backgroundColorStyle")
    if horizontal_alignment is not None:
        cell_format["horizontalAlignment"] = horizontal_alignment.upper()
        fields.append("userEnteredFormat.horizontalAlignment")
    if vertical_alignment is not None:
        cell_format["verticalAlignment"] = vertical_alignment.upper()
        fields.append("userEnteredFormat.verticalAlignment")
    if wrap_strategy is not None:
        cell_format["wrapStrategy"] = wrap_strategy.upper()
        fields.append("userEnteredFormat.wrapStrategy")
    if number_format_type is None and number_format_pattern is not None:
        number_format_type = "NUMBER"
    if number_format_type is not None:
        nf = {"type": number_format_type.upper()}
        if number_format_pattern:
            nf["pattern"] = number_format_pattern
        cell_format["numberFormat"] = nf
        fields.append("userEnteredFormat.numberFormat")

    if not fields:
        raise ValueError("At least one formatting option must be specified")

    requests = [{
        "repeatCell": {
            "range": grid_range,
            "cell": {"userEnteredFormat": cell_format},
            "fields": ",".join(fields),
        }
    }]

    execute_with_retry(
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": requests},
        )
    )
    return {"formatted_range": range_str, "fields_applied": len(fields)}


def freeze_rows_columns(
    spreadsheet_id: str,
    sheet_name: str | None = None,
    frozen_rows: int = 0,
    frozen_columns: int = 0,
    auto_resize: bool = True,
) -> dict:
    service = _get_service()
    sheet_id, resolved_name = resolve_sheet_id(service, spreadsheet_id, sheet_name)

    requests = [{
        "updateSheetProperties": {
            "properties": {
                "sheetId": sheet_id,
                "gridProperties": {
                    "frozenRowCount": frozen_rows,
                    "frozenColumnCount": frozen_columns,
                },
            },
            "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount",
        }
    }]

    if auto_resize:
        requests.append({
            "autoResizeDimensions": {
                "dimensions": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                }
            }
        })

    execute_with_retry(
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": requests},
        )
    )
    return {"frozen_rows": frozen_rows, "frozen_columns": frozen_columns, "auto_resized": auto_resize}


def auto_resize_columns(
    spreadsheet_id: str,
    sheet_name: str | None = None,
) -> dict:
    """Auto-resize all columns to fit content."""
    service = _get_service()
    sheet_id, resolved_name = resolve_sheet_id(service, spreadsheet_id, sheet_name)

    requests = [{
        "autoResizeDimensions": {
            "dimensions": {
                "sheetId": sheet_id,
                "dimension": "COLUMNS",
            }
        }
    }]

    execute_with_retry(
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": requests},
        )
    )
    return {"sheet_name": resolved_name, "auto_resized": True}


def add_sheet(spreadsheet_id: str, title: str) -> dict:
    service = _get_service()
    result = execute_with_retry(
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": title}}}]},
        )
    )
    props = result["replies"][0]["addSheet"]["properties"]
    return {"title": props["title"], "sheet_id": props["sheetId"]}


def delete_sheet(spreadsheet_id: str, sheet_name: str) -> dict:
    service = _get_service()
    sheet_id, title = resolve_sheet_id(service, spreadsheet_id, sheet_name)
    execute_with_retry(
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"deleteSheet": {"sheetId": sheet_id}}]},
        )
    )
    return {"deleted": title}


def rename_sheet(spreadsheet_id: str, sheet_name: str, new_name: str) -> dict:
    service = _get_service()
    sheet_id, old_title = resolve_sheet_id(service, spreadsheet_id, sheet_name)
    execute_with_retry(
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{
                "updateSheetProperties": {
                    "properties": {"sheetId": sheet_id, "title": new_name},
                    "fields": "title",
                }
            }]},
        )
    )
    return {"old_name": old_title, "new_name": new_name}


def sort_range(
    spreadsheet_id: str,
    range_str: str,
    sort_column: str,
    ascending: bool = True,
    sheet_name: str | None = None,
) -> dict:
    service = _get_service()
    if sheet_name is None and "!" in range_str:
        sheet_name = range_str.split("!")[0].strip("'")
    sheet_id, _ = resolve_sheet_id(service, spreadsheet_id, sheet_name)
    grid_range = parse_a1_range(range_str, sheet_id)

    from shared.utils import col_to_index
    sort_col_idx = col_to_index(sort_column.upper())

    execute_with_retry(
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{
                "sortRange": {
                    "range": grid_range,
                    "sortSpecs": [{
                        "dimensionIndex": sort_col_idx,
                        "sortOrder": "ASCENDING" if ascending else "DESCENDING",
                    }],
                }
            }]},
        )
    )
    return {"sorted_range": range_str, "sort_column": sort_column, "ascending": ascending}


def delete_chart(spreadsheet_id: str, chart_id: int) -> dict:
    service = _get_service()
    execute_with_retry(
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"deleteEmbeddedObject": {"objectId": chart_id}}]},
        )
    )
    return {"deleted_chart_id": chart_id}


def add_chart(
    spreadsheet_id: str,
    chart_type: str,
    data_range: str,
    title: str | None = None,
    sheet_name: str | None = None,
    header_row: bool = True,
    stacked: str = "NOT_STACKED",
    anchor_row: int = 0,
    anchor_column: int = 0,
    width_pixels: int = 600,
    height_pixels: int = 400,
) -> dict:
    service = _get_service()
    sheet_id, resolved_name = resolve_sheet_id(service, spreadsheet_id, sheet_name)

    full_range = f"{quote_sheet_name(resolved_name)}!{data_range}" if "!" not in data_range else data_range
    grid_range = parse_a1_range(full_range, sheet_id)

    chart_type_upper = chart_type.upper()

    # Split range into single-column ranges: first col = labels/domain, rest = data/series
    start_col = grid_range.get("startColumnIndex", 0)
    end_col = grid_range.get("endColumnIndex", start_col + 2)
    base = {k: v for k, v in grid_range.items() if k not in ("startColumnIndex", "endColumnIndex")}

    domain_range = {**base, "startColumnIndex": start_col, "endColumnIndex": start_col + 1}
    series_col_range = {**base, "startColumnIndex": start_col + 1, "endColumnIndex": start_col + 2}

    if chart_type_upper in ("PIE", "DONUT"):
        chart_spec = {
            "title": title or "",
            "pieChart": {
                "legendPosition": "RIGHT_LEGEND",
                "domain": {"sourceRange": {"sources": [domain_range]}},
                "series": {"sourceRange": {"sources": [series_col_range]}},
                "threeDimensional": False,
            },
        }
        if chart_type_upper == "DONUT":
            chart_spec["pieChart"]["pieHole"] = 0.5
    else:
        series_list = []
        for col in range(start_col + 1, end_col):
            col_range = {**base, "startColumnIndex": col, "endColumnIndex": col + 1}
            series_list.append({"series": {"sourceRange": {"sources": [col_range]}}})

        basic_chart: dict = {
            "chartType": chart_type_upper,
            "legendPosition": "BOTTOM_LEGEND",
            "domains": [{"domain": {"sourceRange": {"sources": [domain_range]}}}],
            "series": series_list,
            "headerCount": 1 if header_row else 0,
        }
        # stackedType not supported for LINE and SCATTER
        if chart_type_upper not in ("LINE", "SCATTER"):
            basic_chart["stackedType"] = stacked.upper()

        chart_spec = {"title": title or "", "basicChart": basic_chart}

    request = {
        "addChart": {
            "chart": {
                "spec": chart_spec,
                "position": {
                    "overlayPosition": {
                        "anchorCell": {
                            "sheetId": sheet_id,
                            "rowIndex": anchor_row,
                            "columnIndex": anchor_column,
                        },
                        "widthPixels": width_pixels,
                        "heightPixels": height_pixels,
                    }
                },
            }
        }
    }

    result = execute_with_retry(
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [request]},
        )
    )
    chart_id = result["replies"][0]["addChart"]["chart"]["chartId"]
    return {"chart_id": chart_id, "chart_type": chart_type_upper, "title": title or ""}


def add_conditional_format(
    spreadsheet_id: str,
    range_str: str,
    rule_type: str,
    values: list[str] | None = None,
    bg_color: str | None = None,
    text_color: str | None = None,
    bold: bool = False,
    sheet_name: str | None = None,
    custom_formula: str | None = None,
) -> dict:
    """Add a conditional formatting rule."""
    service = _get_service()
    if sheet_name is None and "!" in range_str:
        sheet_name = range_str.split("!")[0].strip("'")
    sheet_id, _ = resolve_sheet_id(service, spreadsheet_id, sheet_name)
    grid_range = parse_a1_range(range_str, sheet_id)

    rule_type_upper = rule_type.upper()
    if rule_type_upper == "CUSTOM_FORMULA" and custom_formula:
        condition = {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": custom_formula}]}
    else:
        condition = {"type": rule_type_upper}
        if values:
            condition["values"] = [{"userEnteredValue": v} for v in values]

    fmt: dict = {}
    if bg_color:
        fmt["backgroundColor"] = hex_to_rgb(bg_color)
    if text_color or bold:
        text_fmt: dict = {}
        if text_color:
            text_fmt["foregroundColor"] = hex_to_rgb(text_color)
        if bold:
            text_fmt["bold"] = True
        fmt["textFormat"] = text_fmt

    request = {
        "addConditionalFormatRule": {
            "rule": {
                "ranges": [grid_range],
                "booleanRule": {"condition": condition, "format": fmt},
            },
            "index": 0,
        }
    }
    execute_with_retry(
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": [request]},
        )
    )
    return {"rule_type": rule_type_upper, "range": range_str}


def set_data_validation(
    spreadsheet_id: str,
    range_str: str,
    rule_type: str,
    values: list[str] | None = None,
    strict: bool = True,
    input_message: str | None = None,
    sheet_name: str | None = None,
) -> dict:
    """Set data validation on a range (dropdown, number range, etc.)."""
    service = _get_service()
    if sheet_name is None and "!" in range_str:
        sheet_name = range_str.split("!")[0].strip("'")
    sheet_id, _ = resolve_sheet_id(service, spreadsheet_id, sheet_name)
    grid_range = parse_a1_range(range_str, sheet_id)

    rule_type_upper = rule_type.upper()
    condition: dict = {"type": rule_type_upper}
    if values:
        condition["values"] = [{"userEnteredValue": v} for v in values]

    rule: dict = {
        "condition": condition,
        "strict": strict,
        "showCustomUi": rule_type_upper in ("ONE_OF_LIST", "ONE_OF_RANGE"),
    }
    if input_message:
        rule["inputMessage"] = input_message

    request = {"setDataValidation": {"range": grid_range, "rule": rule}}
    execute_with_retry(
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": [request]},
        )
    )
    return {"rule_type": rule_type_upper, "range": range_str}


def merge_cells(
    spreadsheet_id: str,
    range_str: str,
    merge_type: str = "MERGE_ALL",
    sheet_name: str | None = None,
) -> dict:
    """Merge cells in a range."""
    service = _get_service()
    if sheet_name is None and "!" in range_str:
        sheet_name = range_str.split("!")[0].strip("'")
    sheet_id, _ = resolve_sheet_id(service, spreadsheet_id, sheet_name)
    grid_range = parse_a1_range(range_str, sheet_id)

    request = {"mergeCells": {"range": grid_range, "mergeType": merge_type.upper()}}
    execute_with_retry(
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": [request]},
        )
    )
    return {"merged_range": range_str, "merge_type": merge_type.upper()}


def unmerge_cells(
    spreadsheet_id: str,
    range_str: str,
    sheet_name: str | None = None,
) -> dict:
    """Unmerge previously merged cells."""
    service = _get_service()
    if sheet_name is None and "!" in range_str:
        sheet_name = range_str.split("!")[0].strip("'")
    sheet_id, _ = resolve_sheet_id(service, spreadsheet_id, sheet_name)
    grid_range = parse_a1_range(range_str, sheet_id)

    execute_with_retry(
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"unmergeCells": {"range": grid_range}}]},
        )
    )
    return {"unmerged_range": range_str}


def insert_dimension(
    spreadsheet_id: str,
    sheet_name: str | None,
    dimension: str,
    index: int,
    count: int = 1,
) -> dict:
    """Insert empty rows or columns.

    Args:
        dimension: "ROWS" or "COLUMNS"
        index: 0-based index to insert before
        count: number of rows/columns to insert
    """
    service = _get_service()
    sheet_id, resolved_name = resolve_sheet_id(service, spreadsheet_id, sheet_name)

    request = {
        "insertDimension": {
            "range": {
                "sheetId": sheet_id,
                "dimension": dimension.upper(),
                "startIndex": index,
                "endIndex": index + count,
            },
            "inheritFromBefore": index > 0,
        }
    }

    execute_with_retry(
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [request]},
        )
    )
    return {
        "sheet_name": resolved_name,
        "dimension": dimension.upper(),
        "index": index,
        "count": count,
    }


def delete_dimension(
    spreadsheet_id: str,
    sheet_name: str | None,
    dimension: str,
    index: int,
    count: int = 1,
) -> dict:
    """Delete rows or columns.

    Args:
        dimension: "ROWS" or "COLUMNS"
        index: 0-based start index
        count: number of rows/columns to delete
    """
    service = _get_service()
    sheet_id, resolved_name = resolve_sheet_id(service, spreadsheet_id, sheet_name)

    request = {
        "deleteDimension": {
            "range": {
                "sheetId": sheet_id,
                "dimension": dimension.upper(),
                "startIndex": index,
                "endIndex": index + count,
            }
        }
    }

    execute_with_retry(
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [request]},
        )
    )
    return {
        "sheet_name": resolved_name,
        "dimension": dimension.upper(),
        "index": index,
        "count": count,
    }


def add_borders(
    spreadsheet_id: str,
    range_str: str,
    style: str = "SOLID",
    color: str = "#000000",
    width: int = 1,
    edges: str = "all",
    sheet_name: str | None = None,
) -> dict:
    """Add borders to cells. edges: all, outer, top, bottom, left, right, inner_horizontal, inner_vertical."""
    service = _get_service()
    if sheet_name is None and "!" in range_str:
        sheet_name = range_str.split("!")[0].strip("'")
    sheet_id, _ = resolve_sheet_id(service, spreadsheet_id, sheet_name)
    grid_range = parse_a1_range(range_str, sheet_id)

    border = {"style": style.upper(), "color": hex_to_rgb(color), "width": width}

    edge_map = {
        "all": ["top", "bottom", "left", "right", "innerHorizontal", "innerVertical"],
        "outer": ["top", "bottom", "left", "right"],
        "inner": ["innerHorizontal", "innerVertical"],
        "inner_horizontal": ["innerHorizontal"],
        "inner_vertical": ["innerVertical"],
    }
    edge_list = edge_map.get(edges.lower(), [edges.lower()])

    borders_req: dict = {"range": grid_range}
    for e in edge_list:
        borders_req[e] = border

    execute_with_retry(
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"updateBorders": borders_req}]},
        )
    )
    return {"bordered_range": range_str, "edges": edges}


def duplicate_sheet(spreadsheet_id: str, sheet_name: str, new_name: str | None = None) -> dict:
    """Duplicate a sheet (tab)."""
    service = _get_service()
    sheet_id, title = resolve_sheet_id(service, spreadsheet_id, sheet_name)
    body: dict = {"sourceSheetId": sheet_id}
    if new_name:
        body["newSheetName"] = new_name

    result = execute_with_retry(
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"duplicateSheet": body}]},
        )
    )
    props = result["replies"][0]["duplicateSheet"]["properties"]
    return {"title": props["title"], "sheet_id": props["sheetId"]}
