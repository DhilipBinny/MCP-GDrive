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
        sheets.append({
            "title": props["title"],
            "sheet_id": props["sheetId"],
            "index": props["index"],
            "row_count": grid.get("rowCount", 0),
            "column_count": grid.get("columnCount", 0),
            "hidden": props.get("hidden", False),
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
) -> dict:
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
                range=f"{qname}!A1:ZZ",
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
