"""Google Slides API wrapper — create, read, and build presentations."""

from __future__ import annotations

import uuid
from googleapiclient.discovery import build

from shared.auth import get_credentials
from shared.utils import execute_with_retry

_service = None

EMU_PER_INCH = 914400
SLIDE_WIDTH = 9144000
SLIDE_HEIGHT = 5143500

POSITIONS = {
    "title": {"x": 311700, "y": 292925, "w": 8520300, "h": 572700},
    "subtitle": {"x": 311700, "y": 897225, "w": 8520300, "h": 400050},
    "body_full": {"x": 311700, "y": 1333500, "w": 8520300, "h": 3530600},
    "table_centered": {"x": 672000, "y": 1500000, "w": 7800000, "h": 3600000},
    "image_centered": {"x": 457200, "y": 914400, "w": 8229600, "h": 3314700},
}


def _get_service():
    global _service
    if _service is None:
        creds = get_credentials()
        _service = build("slides", "v1", credentials=creds)
    return _service


def _new_id() -> str:
    return "g" + uuid.uuid4().hex[:12]


def _emu_size(w: int, h: int) -> dict:
    return {"width": {"magnitude": w, "unit": "EMU"}, "height": {"magnitude": h, "unit": "EMU"}}


def _emu_transform(x: int, y: int) -> dict:
    return {"scaleX": 1, "scaleY": 1, "translateX": x, "translateY": y, "unit": "EMU"}


def create_presentation(title: str) -> dict:
    service = _get_service()
    pres = execute_with_retry(
        service.presentations().create(body={"title": title})
    )
    return {
        "presentation_id": pres["presentationId"],
        "title": pres["title"],
        "slides": [_summarize_slide(s) for s in pres.get("slides", [])],
    }


def get_presentation(presentation_id: str) -> dict:
    service = _get_service()
    pres = execute_with_retry(
        service.presentations().get(presentationId=presentation_id)
    )
    return {
        "presentation_id": pres["presentationId"],
        "title": pres["title"],
        "total_slides": len(pres.get("slides", [])),
        "slides": [_summarize_slide(s) for s in pres.get("slides", [])],
    }


def add_slide(
    presentation_id: str,
    title: str,
    body: str = "",
    layout: str = "TITLE_AND_BODY",
    speaker_notes: str = "",
) -> dict:
    service = _get_service()
    slide_id = _new_id()
    title_id = _new_id()
    body_id = _new_id()

    no_title_layouts = {"BLANK", "CAPTION_ONLY"}
    no_body_layouts = {"SECTION_HEADER", "TITLE_ONLY", "BLANK", "MAIN_POINT", "BIG_NUMBER", "CAPTION_ONLY"}
    has_title_placeholder = layout not in no_title_layouts
    has_body_placeholder = layout not in no_body_layouts

    mappings = []
    if has_title_placeholder:
        mappings.append({"layoutPlaceholder": {"type": "TITLE", "index": 0}, "objectId": title_id})
    if has_body_placeholder:
        mappings.append({"layoutPlaceholder": {"type": "BODY", "index": 0}, "objectId": body_id})

    requests: list[dict] = [{
        "createSlide": {
            "objectId": slide_id,
            "slideLayoutReference": {"predefinedLayout": layout},
            "placeholderIdMappings": mappings,
        }
    }]

    if title and has_title_placeholder:
        requests.append({"insertText": {"objectId": title_id, "text": title}})
    if body and has_body_placeholder:
        requests.append({"insertText": {"objectId": body_id, "text": body}})

    if body and has_body_placeholder and "\n" in body:
        requests.append({
            "createParagraphBullets": {
                "objectId": body_id,
                "textRange": {"type": "ALL"},
                "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE",
            }
        })

    execute_with_retry(
        service.presentations().batchUpdate(
            presentationId=presentation_id,
            body={"requests": requests},
        )
    )

    # Speaker notes require a second pass — need the notesPage objectId
    if speaker_notes:
        _set_speaker_notes(service, presentation_id, slide_id, speaker_notes)

    return {"slide_id": slide_id, "title": title, "layout": layout}


def add_table_slide(
    presentation_id: str,
    title: str,
    headers: list[str],
    rows: list[list[str]],
) -> dict:
    service = _get_service()
    slide_id = _new_id()
    title_id = _new_id()
    table_id = _new_id()

    num_rows = len(rows) + 1
    num_cols = len(headers)
    table_height = min(num_rows * 370000 + 200000, POSITIONS["table_centered"]["h"])

    requests: list[dict] = [
        {
            "createSlide": {
                "objectId": slide_id,
                "slideLayoutReference": {"predefinedLayout": "TITLE_ONLY"},
                "placeholderIdMappings": [
                    {"layoutPlaceholder": {"type": "TITLE", "index": 0}, "objectId": title_id},
                ],
            }
        },
        {"insertText": {"objectId": title_id, "text": title}},
        {
            "createTable": {
                "objectId": table_id,
                "elementProperties": {
                    "pageObjectId": slide_id,
                    "size": _emu_size(POSITIONS["table_centered"]["w"], table_height),
                    "transform": _emu_transform(
                        POSITIONS["table_centered"]["x"], POSITIONS["table_centered"]["y"]
                    ),
                },
                "rows": num_rows,
                "columns": num_cols,
            }
        },
    ]

    for c_idx, header in enumerate(headers):
        requests.append({
            "insertText": {
                "objectId": table_id,
                "cellLocation": {"rowIndex": 0, "columnIndex": c_idx},
                "text": header,
            }
        })

    for r_idx, row in enumerate(rows):
        for c_idx, cell in enumerate(row):
            if c_idx < num_cols:
                requests.append({
                    "insertText": {
                        "objectId": table_id,
                        "cellLocation": {"rowIndex": r_idx + 1, "columnIndex": c_idx},
                        "text": str(cell),
                    }
                })

    # Bold header row
    for c_idx in range(num_cols):
        requests.append({
            "updateTextStyle": {
                "objectId": table_id,
                "cellLocation": {"rowIndex": 0, "columnIndex": c_idx},
                "style": {"bold": True},
                "textRange": {"type": "ALL"},
                "fields": "bold",
            }
        })

    execute_with_retry(
        service.presentations().batchUpdate(
            presentationId=presentation_id,
            body={"requests": requests},
        )
    )
    return {"slide_id": slide_id, "title": title, "table": f"{num_rows}x{num_cols}"}


def add_image_slide(
    presentation_id: str,
    image_url: str,
    title: str = "",
    as_background: bool = False,
) -> dict:
    service = _get_service()
    slide_id = _new_id()
    title_id = _new_id()
    image_id = _new_id()

    layout = "TITLE_ONLY" if title else "BLANK"
    mappings = []
    if title:
        mappings.append({"layoutPlaceholder": {"type": "TITLE", "index": 0}, "objectId": title_id})

    requests: list[dict] = [{
        "createSlide": {
            "objectId": slide_id,
            "slideLayoutReference": {"predefinedLayout": layout},
            "placeholderIdMappings": mappings,
        }
    }]

    if title:
        requests.append({"insertText": {"objectId": title_id, "text": title}})

    if as_background:
        requests.append({
            "updatePageProperties": {
                "objectId": slide_id,
                "pageProperties": {
                    "pageBackgroundFill": {
                        "stretchedPictureFill": {"contentUrl": image_url}
                    }
                },
                "fields": "pageBackgroundFill",
            }
        })
    else:
        pos = POSITIONS["image_centered"]
        requests.append({
            "createImage": {
                "objectId": image_id,
                "url": image_url,
                "elementProperties": {
                    "pageObjectId": slide_id,
                    "size": _emu_size(pos["w"], pos["h"]),
                    "transform": _emu_transform(pos["x"], pos["y"]),
                },
            }
        })

    execute_with_retry(
        service.presentations().batchUpdate(
            presentationId=presentation_id,
            body={"requests": requests},
        )
    )
    return {"slide_id": slide_id, "title": title or "(image)", "background": as_background}


def delete_slide(presentation_id: str, slide_id: str) -> dict:
    service = _get_service()
    execute_with_retry(
        service.presentations().batchUpdate(
            presentationId=presentation_id,
            body={"requests": [{"deleteObject": {"objectId": slide_id}}]},
        )
    )
    return {"deleted": slide_id}


def replace_text(presentation_id: str, find: str, replace: str) -> dict:
    service = _get_service()
    result = execute_with_retry(
        service.presentations().batchUpdate(
            presentationId=presentation_id,
            body={"requests": [{
                "replaceAllText": {
                    "containsText": {"text": find, "matchCase": True},
                    "replaceText": replace,
                }
            }]},
        )
    )
    count = 0
    for reply in result.get("replies", []):
        count += reply.get("replaceAllText", {}).get("occurrencesChanged", 0)
    return {"occurrences_replaced": count}


def replace_image(presentation_id: str, placeholder_text: str, image_url: str) -> dict:
    service = _get_service()
    result = execute_with_retry(
        service.presentations().batchUpdate(
            presentationId=presentation_id,
            body={"requests": [{
                "replaceAllShapesWithImage": {
                    "imageUrl": image_url,
                    "replaceMethod": "CENTER_INSIDE",
                    "containsText": {"text": placeholder_text, "matchCase": True},
                }
            }]},
        )
    )
    count = 0
    for reply in result.get("replies", []):
        count += reply.get("replaceAllShapesWithImage", {}).get("occurrencesChanged", 0)
    return {"occurrences_replaced": count}


def set_speaker_notes(presentation_id: str, slide_id: str, notes: str) -> dict:
    service = _get_service()
    _set_speaker_notes(service, presentation_id, slide_id, notes)
    return {"slide_id": slide_id, "notes_set": True}


def _set_speaker_notes(service, presentation_id: str, slide_id: str, notes: str) -> None:
    pres = execute_with_retry(
        service.presentations().get(presentationId=presentation_id)
    )
    notes_id = None
    for slide in pres.get("slides", []):
        if slide["objectId"] == slide_id:
            notes_page = slide.get("slideProperties", {}).get("notesPage", {})
            notes_id = notes_page.get("notesProperties", {}).get("speakerNotesObjectId")
            break

    if not notes_id:
        raise ValueError(f"Could not find speaker notes for slide {slide_id}")

    execute_with_retry(
        service.presentations().batchUpdate(
            presentationId=presentation_id,
            body={"requests": [{"insertText": {"objectId": notes_id, "text": notes}}]},
        )
    )


def duplicate_slide(presentation_id: str, slide_id: str) -> dict:
    service = _get_service()
    new_id = _new_id()
    execute_with_retry(
        service.presentations().batchUpdate(
            presentationId=presentation_id,
            body={"requests": [{
                "duplicateObject": {"objectId": slide_id, "objectIds": {slide_id: new_id}}
            }]},
        )
    )
    return {"original": slide_id, "duplicate": new_id}


SHAPE_ALIASES = {
    "rectangle": "RECTANGLE", "box": "RECTANGLE",
    "rounded": "ROUND_RECTANGLE", "rounded_rectangle": "ROUND_RECTANGLE",
    "circle": "ELLIPSE", "oval": "ELLIPSE",
    "diamond": "DIAMOND", "decision": "FLOW_CHART_DECISION",
    "process": "FLOW_CHART_PROCESS", "terminator": "FLOW_CHART_TERMINATOR",
    "cylinder": "CAN", "database": "CAN",
    "cloud": "CLOUD", "hexagon": "HEXAGON",
    "arrow_right": "RIGHT_ARROW", "arrow_down": "DOWN_ARROW",
    "document": "FLOW_CHART_DOCUMENT", "text": "TEXT_BOX",
    "chevron": "CHEVRON", "parallelogram": "PARALLELOGRAM",
    "cube": "CUBE", "star": "STAR_5",
}

SIDE_MAP = {"top": 0, "right": 1, "bottom": 2, "left": 3}

PALETTES = {
    "corporate": ["#4285F4", "#34A853", "#FBBC04", "#EA4335", "#5F6368", "#1A73E8"],
    "tech": ["#E94560", "#0F3460", "#533483", "#16213E", "#1A1A2E", "#950740"],
    "minimal": ["#FFFFFF", "#F1F3F4", "#E8EAED", "#DADCE0", "#BDC1C6", "#9AA0A6"],
    "colorful": ["#4285F4", "#EA4335", "#FBBC04", "#34A853", "#FF6D01", "#46BDC6"],
}


def _inches(val: float) -> int:
    return int(val * EMU_PER_INCH)


def _resolve_shape_type(name: str) -> str:
    return SHAPE_ALIASES.get(name.lower(), name)


def _shape_requests(sid: str, slide_id: str, shape: dict) -> list[dict]:
    """Build all requests for a single shape: create + fill + text style + alignment."""
    from shared.utils import hex_to_rgb
    shape_type = _resolve_shape_type(shape.get("type", shape.get("shape_type", "rounded")))
    x = _inches(shape.get("x", 0))
    y = _inches(shape.get("y", 0))
    w = _inches(shape.get("w", 2.0))
    h = _inches(shape.get("h", 0.7))

    reqs: list[dict] = [{
        "createShape": {
            "objectId": sid,
            "shapeType": shape_type,
            "elementProperties": {
                "pageObjectId": slide_id,
                "size": _emu_size(w, h),
                "transform": _emu_transform(x, y),
            },
        }
    }]

    has_text = bool(shape.get("text") or shape.get("label"))
    if has_text:
        reqs.append({"insertText": {"objectId": sid, "text": shape.get("text") or shape.get("label", "")}})

    fill = shape.get("fill_color") or shape.get("color")
    if fill:
        reqs.append({
            "updateShapeProperties": {
                "objectId": sid,
                "shapeProperties": {
                    "shapeBackgroundFill": {"solidFill": {"color": {"rgbColor": hex_to_rgb(fill)}, "alpha": 1.0}},
                    "contentAlignment": "MIDDLE",
                },
                "fields": "shapeBackgroundFill,contentAlignment",
            }
        })
    else:
        reqs.append({
            "updateShapeProperties": {
                "objectId": sid,
                "shapeProperties": {"contentAlignment": "MIDDLE"},
                "fields": "contentAlignment",
            }
        })

    outline = shape.get("outline_color")
    if outline:
        reqs.append({
            "updateShapeProperties": {
                "objectId": sid,
                "shapeProperties": {
                    "outline": {
                        "outlineFill": {"solidFill": {"color": {"rgbColor": hex_to_rgb(outline)}, "alpha": 1.0}},
                        "weight": {"magnitude": shape.get("outline_weight", 1.5), "unit": "PT"},
                    }
                },
                "fields": "outline",
            }
        })

    if has_text:
        font_color = shape.get("font_color", shape.get("text_color", "#FFFFFF"))
        font_size = shape.get("font_size", 10)
        text_style: dict = {
            "fontSize": {"magnitude": font_size, "unit": "PT"},
            "foregroundColor": {"opaqueColor": {"rgbColor": hex_to_rgb(font_color)}},
            "bold": shape.get("bold", False),
        }
        fields = "fontSize,foregroundColor,bold"
        if shape.get("font_family"):
            text_style["fontFamily"] = shape["font_family"]
            fields += ",fontFamily"
        reqs.append({
            "updateTextStyle": {
                "objectId": sid,
                "style": text_style,
                "textRange": {"type": "ALL"},
                "fields": fields,
            }
        })
        reqs.append({
            "updateParagraphStyle": {
                "objectId": sid,
                "style": {"alignment": "CENTER"},
                "textRange": {"type": "ALL"},
                "fields": "alignment",
            }
        })
    return reqs


def _connector_requests(lid: str, slide_id: str, from_id: str, to_id: str, conn: dict, auto_route: bool = False) -> list[dict]:
    """Build requests for a connector line between two shapes."""
    from shared.utils import hex_to_rgb
    connector_type = conn.get("connector_type", conn.get("type", "CURVED")).upper()
    from_side = conn.get("from_side", "bottom")
    to_side = conn.get("to_side", "top")

    reqs: list[dict] = [{
        "createLine": {
            "objectId": lid,
            "category": connector_type,
            "elementProperties": {
                "pageObjectId": slide_id,
                "size": _emu_size(1, 1),
                "transform": _emu_transform(0, 0),
            },
        }
    }, {
        "updateLineProperties": {
            "objectId": lid,
            "lineProperties": {
                "startConnection": {"connectedObjectId": from_id, "connectionSiteIndex": SIDE_MAP.get(from_side, 0)},
                "endConnection": {"connectedObjectId": to_id, "connectionSiteIndex": SIDE_MAP.get(to_side, 0)},
            },
            "fields": "startConnection,endConnection",
        }
    }]

    if auto_route:
        reqs.append({"rerouteLine": {"objectId": lid}})

    color = conn.get("color", "#80868B")
    weight = conn.get("weight", 2)
    end_arrow = conn.get("end_arrow", "OPEN_ARROW")
    dash = conn.get("dash_style", "SOLID")

    reqs.append({
        "updateLineProperties": {
            "objectId": lid,
            "lineProperties": {
                "lineFill": {"solidFill": {"color": {"rgbColor": hex_to_rgb(color)}, "alpha": 1.0}},
                "weight": {"magnitude": weight, "unit": "PT"},
                "endArrow": end_arrow,
                "dashStyle": dash,
            },
            "fields": "lineFill,weight,endArrow,dashStyle",
        }
    })
    return reqs


def add_shape(
    presentation_id: str,
    slide_id: str,
    shape_type: str = "rounded",
    x: float = 1.0, y: float = 1.0,
    width: float = 2.0, height: float = 0.7,
    text: str = "",
    fill_color: str = "#4285F4",
    text_color: str = "#FFFFFF",
    font_size: int = 10,
    bold: bool = False,
    outline_color: str | None = None,
) -> dict:
    service = _get_service()
    sid = _new_id()
    shape = {
        "type": shape_type, "x": x, "y": y, "w": width, "h": height,
        "text": text, "fill_color": fill_color, "font_color": text_color,
        "font_size": font_size, "bold": bold, "outline_color": outline_color,
    }
    reqs = _shape_requests(sid, slide_id, shape)
    execute_with_retry(
        service.presentations().batchUpdate(presentationId=presentation_id, body={"requests": reqs})
    )
    return {"shape_id": sid, "text": text}


def add_connector(
    presentation_id: str,
    slide_id: str,
    from_shape_id: str,
    to_shape_id: str,
    from_side: str = "bottom",
    to_side: str = "top",
    connector_type: str = "STRAIGHT",
    color: str = "#80868B",
    weight: float = 2.0,
    end_arrow: str = "OPEN_ARROW",
) -> dict:
    service = _get_service()
    lid = _new_id()
    conn = {
        "connector_type": connector_type, "from_side": from_side, "to_side": to_side,
        "color": color, "weight": weight, "end_arrow": end_arrow,
    }
    reqs = _connector_requests(lid, slide_id, from_shape_id, to_shape_id, conn)
    execute_with_retry(
        service.presentations().batchUpdate(presentationId=presentation_id, body={"requests": reqs})
    )
    return {"connector_id": lid, "from": from_shape_id, "to": to_shape_id}


def add_text_box(
    presentation_id: str,
    slide_id: str,
    text: str,
    x: float = 1.0, y: float = 1.0,
    width: float = 2.0, height: float = 0.5,
    font_size: int = 9,
    font_color: str = "#5F6368",
    bold: bool = False,
    alignment: str = "CENTER",
) -> dict:
    service = _get_service()
    sid = _new_id()
    from shared.utils import hex_to_rgb
    reqs = [
        {
            "createShape": {
                "objectId": sid, "shapeType": "TEXT_BOX",
                "elementProperties": {
                    "pageObjectId": slide_id,
                    "size": _emu_size(_inches(width), _inches(height)),
                    "transform": _emu_transform(_inches(x), _inches(y)),
                },
            }
        },
        {"insertText": {"objectId": sid, "text": text}},
        {
            "updateTextStyle": {
                "objectId": sid,
                "style": {
                    "fontSize": {"magnitude": font_size, "unit": "PT"},
                    "foregroundColor": {"opaqueColor": {"rgbColor": hex_to_rgb(font_color)}},
                    "bold": bold,
                },
                "textRange": {"type": "ALL"},
                "fields": "fontSize,foregroundColor,bold",
            }
        },
        {
            "updateParagraphStyle": {
                "objectId": sid,
                "style": {"alignment": alignment.upper()},
                "textRange": {"type": "ALL"},
                "fields": "alignment",
            }
        },
    ]
    execute_with_retry(
        service.presentations().batchUpdate(presentationId=presentation_id, body={"requests": reqs})
    )
    return {"text_box_id": sid, "text": text}


def add_diagram(
    presentation_id: str,
    title: str,
    nodes: list[dict],
    connections: list[dict] | None = None,
    style: str = "corporate",
) -> dict:
    """Create a diagram slide with nodes and connectors in a single batch.

    nodes: [{"id": "n1", "label": "Web App", "type": "rounded", "tier": 1,
             "x": 3.5, "y": 1.5, "w": 2.5, "h": 0.7, "color": "#4285F4"}, ...]
       If x/y omitted, auto-layout by tier.
    connections: [{"from": "n1", "to": "n2", "from_side": "bottom", "to_side": "top", "label": "HTTPS"}, ...]
    """
    service = _get_service()
    slide_id = _new_id()
    title_id = _new_id()
    palette = PALETTES.get(style, PALETTES["corporate"])

    # Auto-layout nodes that don't have explicit x/y
    _auto_layout(nodes, palette)

    # Build node ID mapping
    node_id_map: dict[str, str] = {}
    requests: list[dict] = [
        {
            "createSlide": {
                "objectId": slide_id,
                "slideLayoutReference": {"predefinedLayout": "TITLE_ONLY"},
                "placeholderIdMappings": [
                    {"layoutPlaceholder": {"type": "TITLE", "index": 0}, "objectId": title_id},
                ],
            }
        },
        {"insertText": {"objectId": title_id, "text": title}},
    ]

    for node in nodes:
        sid = _new_id()
        node_id_map[node["id"]] = sid
        shape = {
            "type": node.get("type", "rounded"),
            "x": node["x"], "y": node["y"],
            "w": node.get("w", 2.0), "h": node.get("h", 0.7),
            "fill_color": node.get("color"),
            "font_color": node.get("font_color", "#FFFFFF"),
            "font_size": node.get("font_size", 10),
            "bold": node.get("bold", True),
            "text": node.get("label", node.get("text", "")),
            "outline_color": node.get("outline_color"),
        }
        requests.extend(_shape_requests(sid, slide_id, shape))

    for conn in (connections or []):
        from_id = node_id_map.get(conn["from"])
        to_id = node_id_map.get(conn["to"])
        if from_id and to_id:
            lid = _new_id()
            requests.extend(_connector_requests(lid, slide_id, from_id, to_id, conn, auto_route=True))

    # Add connection labels as text boxes
    for conn in (connections or []):
        if conn.get("label"):
            from_node = next((n for n in nodes if n["id"] == conn["from"]), None)
            to_node = next((n for n in nodes if n["id"] == conn["to"]), None)
            if from_node and to_node:
                lx = (from_node["x"] + from_node.get("w", 2.0) / 2 + to_node["x"] + to_node.get("w", 2.0) / 2) / 2 - 0.4
                ly = (from_node["y"] + from_node.get("h", 0.7) + to_node["y"]) / 2 - 0.15
                lbl_id = _new_id()
                from shared.utils import hex_to_rgb
                requests.extend([
                    {
                        "createShape": {
                            "objectId": lbl_id, "shapeType": "TEXT_BOX",
                            "elementProperties": {
                                "pageObjectId": slide_id,
                                "size": _emu_size(_inches(0.8), _inches(0.3)),
                                "transform": _emu_transform(_inches(lx), _inches(ly)),
                            },
                        }
                    },
                    {"insertText": {"objectId": lbl_id, "text": conn["label"]}},
                    {
                        "updateTextStyle": {
                            "objectId": lbl_id,
                            "style": {
                                "fontSize": {"magnitude": 7, "unit": "PT"},
                                "foregroundColor": {"opaqueColor": {"rgbColor": hex_to_rgb("#80868B")}},
                                "italic": True,
                            },
                            "textRange": {"type": "ALL"},
                            "fields": "fontSize,foregroundColor,italic",
                        }
                    },
                    {
                        "updateParagraphStyle": {
                            "objectId": lbl_id,
                            "style": {"alignment": "CENTER"},
                            "textRange": {"type": "ALL"},
                            "fields": "alignment",
                        }
                    },
                ])

    execute_with_retry(
        service.presentations().batchUpdate(
            presentationId=presentation_id,
            body={"requests": requests},
        )
    )
    return {"slide_id": slide_id, "title": title, "nodes": len(nodes), "connections": len(connections or [])}


def _auto_layout(nodes: list[dict], palette: list[str]) -> None:
    """Assign x/y positions to nodes based on tier, and colors from palette."""
    x_min, x_max = 0.4, 9.6
    y_min, y_max = 1.3, 5.0

    tiers: dict[int, list[dict]] = {}
    for n in nodes:
        t = n.get("tier", 1)
        tiers.setdefault(t, []).append(n)

    num_tiers = len(tiers)
    tier_gap = (y_max - y_min) / max(num_tiers, 1)

    for tier_idx, (tier_num, tier_nodes) in enumerate(sorted(tiers.items())):
        y = y_min + tier_idx * tier_gap + (tier_gap - tier_nodes[0].get("h", 0.7)) / 2
        num_nodes = len(tier_nodes)
        total_width = x_max - x_min
        node_spacing = total_width / max(num_nodes, 1)

        for node_idx, node in enumerate(tier_nodes):
            node_w = node.get("w", 2.0)
            if "x" not in node:
                node["x"] = x_min + node_idx * node_spacing + (node_spacing - node_w) / 2
            if "y" not in node:
                node["y"] = y
            if "color" not in node and not node.get("fill_color"):
                node["color"] = palette[tier_idx % len(palette)]


def import_drawio(
    presentation_id: str,
    drawio_xml: str,
    title: str = "",
) -> dict:
    """Import a draw.io diagram (mxGraph XML) as native Slides shapes."""
    service = _get_service()
    slide_id = _new_id()
    title_id = _new_id()

    create_reqs: list[dict] = [{
        "createSlide": {
            "objectId": slide_id,
            "slideLayoutReference": {"predefinedLayout": "BLANK" if not title else "TITLE_ONLY"},
            "placeholderIdMappings": (
                [{"layoutPlaceholder": {"type": "TITLE", "index": 0}, "objectId": title_id}]
                if title else []
            ),
        }
    }]
    if title:
        create_reqs.append({"insertText": {"objectId": title_id, "text": title}})

    execute_with_retry(
        service.presentations().batchUpdate(
            presentationId=presentation_id,
            body={"requests": create_reqs},
        )
    )

    from .drawio_converter import drawio_xml_to_slides_requests
    shape_reqs, node_map = drawio_xml_to_slides_requests(drawio_xml, slide_id, title=title)

    if shape_reqs:
        execute_with_retry(
            service.presentations().batchUpdate(
                presentationId=presentation_id,
                body={"requests": shape_reqs},
            )
        )

    return {
        "slide_id": slide_id,
        "title": title,
        "shapes": len([r for r in shape_reqs if "createShape" in r]),
        "connectors": len([r for r in shape_reqs if "createLine" in r]),
    }


def _summarize_slide(slide: dict) -> dict:
    slide_id = slide["objectId"]
    elements = []
    for elem in slide.get("pageElements", []):
        shape = elem.get("shape", {})
        table = elem.get("table", {})
        image = elem.get("image", {})
        ph = shape.get("placeholder", {})

        if table:
            rows_data = []
            for row in table.get("tableRows", []):
                cells = []
                for cell in row.get("tableCells", []):
                    text = _extract_text(cell.get("text", {}).get("textElements", []))
                    cells.append(text)
                rows_data.append(cells)
            elements.append({"type": "table", "rows": table.get("rows", 0), "columns": table.get("columns", 0), "data": rows_data})
        elif image:
            elements.append({"type": "image", "url": image.get("contentUrl", ""), "object_id": elem["objectId"]})
        elif shape:
            text = _extract_text(shape.get("text", {}).get("textElements", []))
            ptype = ph.get("type", "SHAPE").lower()
            elements.append({"type": ptype, "text": text, "object_id": elem["objectId"]})

    return {"slide_id": slide_id, "elements": elements}


def get_slide_thumbnail(
    presentation_id: str,
    slide_id: str,
    size: str = "LARGE",
) -> dict:
    """Get a temporary thumbnail URL for a slide (expires in ~30 minutes)."""
    service = _get_service()
    result = execute_with_retry(
        service.presentations().pages().getThumbnail(
            presentationId=presentation_id,
            pageObjectId=slide_id,
            thumbnailProperties_thumbnailSize=size.upper(),
            thumbnailProperties_mimeType="PNG",
        )
    )
    return {
        "url": result["contentUrl"],
        "width": result.get("width", 0),
        "height": result.get("height", 0),
    }


def _text_box_reqs(
    sid: str, slide_id: str, text: str, pos: dict,
    font: str = "Open Sans", size: int = 18, color: str = "#202124",
    bold: bool = False, italic: bool = False, alignment: str = "START",
    line_spacing: float = 140, space_below: float = 0,
) -> list[dict]:
    """Helper: create a text box with styled text at a layout position."""
    from shared.utils import hex_to_rgb
    reqs = [
        {"createShape": {
            "objectId": sid, "shapeType": "TEXT_BOX",
            "elementProperties": {
                "pageObjectId": slide_id,
                "size": _emu_size(pos["w"], pos["h"]),
                "transform": _emu_transform(pos["x"], pos["y"]),
            },
        }},
        {"insertText": {"objectId": sid, "text": text}},
        {"updateTextStyle": {
            "objectId": sid,
            "style": {
                "fontFamily": font,
                "fontSize": {"magnitude": size, "unit": "PT"},
                "foregroundColor": {"opaqueColor": {"rgbColor": hex_to_rgb(color)}},
                "bold": bold, "italic": italic,
            },
            "textRange": {"type": "ALL"},
            "fields": "fontFamily,fontSize,foregroundColor,bold,italic",
        }},
        {"updateParagraphStyle": {
            "objectId": sid,
            "style": {
                "alignment": alignment,
                "lineSpacing": line_spacing,
                **({"spaceBelow": {"magnitude": space_below, "unit": "PT"}} if space_below else {}),
            },
            "textRange": {"type": "ALL"},
            "fields": "alignment,lineSpacing" + (",spaceBelow" if space_below else ""),
        }},
    ]
    # Remove outline for clean text boxes
    reqs.append({"updateShapeProperties": {
        "objectId": sid,
        "shapeProperties": {"outline": {"propertyState": "NOT_RENDERED"}},
        "fields": "outline",
    }})
    return reqs


def _set_bg_reqs(slide_id: str, pal: dict) -> list[dict]:
    """Set slide background from palette (only emits a request if non-white)."""
    from shared.utils import hex_to_rgb
    bg = pal.get("background", "#FFFFFF")
    if bg.upper() in ("#FFFFFF", "#FFF"):
        return []
    return [{"updatePageProperties": {
        "objectId": slide_id,
        "pageProperties": {"pageBackgroundFill": {
            "solidFill": {"color": {"rgbColor": hex_to_rgb(bg)}}}},
        "fields": "pageBackgroundFill",
    }}]


def add_title_slide(
    presentation_id: str, title: str, subtitle: str = "",
    author: str = "", theme: str = "modern",
) -> dict:
    """Create a professional title slide."""
    from .design import LAYOUT, FONTS, FONT_SIZES, get_palette
    service = _get_service()
    pal = get_palette(theme)
    slide_id = _new_id()
    L = LAYOUT["title_slide"]

    reqs: list[dict] = [{"createSlide": {
        "objectId": slide_id,
        "slideLayoutReference": {"predefinedLayout": "BLANK"},
    }}]
    reqs.extend(_set_bg_reqs(slide_id, pal))

    tid = _new_id()
    reqs.extend(_text_box_reqs(tid, slide_id, title, L["title"],
        font=FONTS["heading"], size=FONT_SIZES["slide_title"],
        color=pal["primary_text"], bold=True, alignment="CENTER", line_spacing=115))

    if subtitle:
        sid = _new_id()
        reqs.extend(_text_box_reqs(sid, slide_id, subtitle, L["subtitle"],
            font=FONTS["body"], size=FONT_SIZES["subtitle"],
            color=pal["secondary_text"], alignment="CENTER"))

    if author:
        aid = _new_id()
        reqs.extend(_text_box_reqs(aid, slide_id, author, L["author"],
            font=FONTS["body"], size=FONT_SIZES["author"],
            color=pal["page_number"], alignment="CENTER"))

    execute_with_retry(service.presentations().batchUpdate(
        presentationId=presentation_id, body={"requests": reqs}))
    return {"slide_id": slide_id, "title": title}


def add_section_slide(
    presentation_id: str, title: str, section_number: str = "",
    theme: str = "modern",
) -> dict:
    """Create a section divider slide with accent background."""
    from .design import LAYOUT, FONTS, FONT_SIZES, CANVAS_W, CANVAS_H, get_palette
    from shared.utils import hex_to_rgb
    service = _get_service()
    pal = get_palette(theme)
    slide_id = _new_id()
    L = LAYOUT["section"]

    reqs: list[dict] = [{"createSlide": {
        "objectId": slide_id,
        "slideLayoutReference": {"predefinedLayout": "BLANK"},
    }}]

    # Accent background
    reqs.append({"updatePageProperties": {
        "objectId": slide_id,
        "pageProperties": {"pageBackgroundFill": {
            "solidFill": {"color": {"rgbColor": hex_to_rgb(pal["accent"])}}}},
        "fields": "pageBackgroundFill",
    }})

    if section_number:
        nid = _new_id()
        reqs.extend(_text_box_reqs(nid, slide_id, section_number, L["number"],
            font=FONTS["body"], size=18, color="#B0B0B0",
            alignment="START", line_spacing=115))

    tid = _new_id()
    reqs.extend(_text_box_reqs(tid, slide_id, title, L["title"],
        font=FONTS["heading"], size=FONT_SIZES["section_title"],
        color="#FFFFFF", bold=True, alignment="START", line_spacing=115))

    # Accent underline
    lid = _new_id()
    reqs.append({"createLine": {
        "objectId": lid, "category": "STRAIGHT",
        "elementProperties": {
            "pageObjectId": slide_id,
            "size": _emu_size(L["underline_w"], 0),
            "transform": _emu_transform(L["underline_x"], L["underline_y"]),
        },
    }})
    reqs.append({"updateLineProperties": {
        "objectId": lid,
        "lineProperties": {
            "lineFill": {"solidFill": {"color": {"rgbColor": {"red": 1, "green": 1, "blue": 1}}, "alpha": 0.7}},
            "weight": {"magnitude": 3, "unit": "PT"},
        },
        "fields": "lineFill,weight",
    }})

    execute_with_retry(service.presentations().batchUpdate(
        presentationId=presentation_id, body={"requests": reqs}))
    return {"slide_id": slide_id, "title": title}


def add_content_slide(
    presentation_id: str, title: str, body: str,
    speaker_notes: str = "", theme: str = "modern",
) -> dict:
    """Create a content slide with design-system typography (Montserrat/Open Sans)."""
    from .design import LAYOUT, FONTS, FONT_SIZES, get_palette
    service = _get_service()
    pal = get_palette(theme)
    slide_id = _new_id()
    L = LAYOUT["content"]

    reqs: list[dict] = [{"createSlide": {
        "objectId": slide_id,
        "slideLayoutReference": {"predefinedLayout": "BLANK"},
    }}]
    reqs.extend(_set_bg_reqs(slide_id, pal))

    tid = _new_id()
    reqs.extend(_text_box_reqs(tid, slide_id, title, L["title"],
        font=FONTS["heading"], size=FONT_SIZES["slide_title"],
        color=pal["primary_text"], bold=True, alignment="START"))

    bid = _new_id()
    reqs.extend(_text_box_reqs(bid, slide_id, body, L["body"],
        font=FONTS["body"], size=FONT_SIZES["body"],
        color=pal["primary_text"], alignment="START",
        line_spacing=140, space_below=6))

    # Auto-bullet if multi-line
    if "\n" in body:
        reqs.append({"createParagraphBullets": {
            "objectId": bid,
            "textRange": {"type": "ALL"},
            "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE",
        }})

    execute_with_retry(service.presentations().batchUpdate(
        presentationId=presentation_id, body={"requests": reqs}))

    if speaker_notes:
        _set_speaker_notes(service, presentation_id, slide_id, speaker_notes)

    return {"slide_id": slide_id, "title": title}


def add_two_column_slide(
    presentation_id: str, title: str, col1: str, col2: str,
    col1_title: str = "", col2_title: str = "", theme: str = "modern",
) -> dict:
    """Create a two-column content slide."""
    from .design import LAYOUT, FONTS, FONT_SIZES, GUTTER, get_palette
    service = _get_service()
    pal = get_palette(theme)
    slide_id = _new_id()
    L = LAYOUT["two_column"]

    reqs: list[dict] = [{"createSlide": {
        "objectId": slide_id,
        "slideLayoutReference": {"predefinedLayout": "BLANK"},
    }}]
    reqs.extend(_set_bg_reqs(slide_id, pal))

    tid = _new_id()
    reqs.extend(_text_box_reqs(tid, slide_id, title, L["title"],
        font=FONTS["heading"], size=FONT_SIZES["slide_title"],
        color=pal["primary_text"], bold=True, alignment="START"))

    # Column 1
    c1_body = f"{col1_title}\n{col1}" if col1_title else col1
    c1id = _new_id()
    reqs.extend(_text_box_reqs(c1id, slide_id, c1_body, L["col1"],
        font=FONTS["body"], size=FONT_SIZES["body"],
        color=pal["primary_text"], alignment="START", line_spacing=140))

    if col1_title:
        reqs.append({"updateTextStyle": {
            "objectId": c1id,
            "style": {"bold": True, "fontSize": {"magnitude": 20, "unit": "PT"}},
            "textRange": {"type": "FIXED_RANGE", "startIndex": 0, "endIndex": len(col1_title)},
            "fields": "bold,fontSize",
        }})

    # Column 2
    c2_body = f"{col2_title}\n{col2}" if col2_title else col2
    c2id = _new_id()
    reqs.extend(_text_box_reqs(c2id, slide_id, c2_body, L["col2"],
        font=FONTS["body"], size=FONT_SIZES["body"],
        color=pal["primary_text"], alignment="START", line_spacing=140))

    if col2_title:
        reqs.append({"updateTextStyle": {
            "objectId": c2id,
            "style": {"bold": True, "fontSize": {"magnitude": 20, "unit": "PT"}},
            "textRange": {"type": "FIXED_RANGE", "startIndex": 0, "endIndex": len(col2_title)},
            "fields": "bold,fontSize",
        }})

    execute_with_retry(service.presentations().batchUpdate(
        presentationId=presentation_id, body={"requests": reqs}))
    return {"slide_id": slide_id, "title": title}


def add_image_text_slide(
    presentation_id: str, title: str, image_url: str, text: str,
    image_side: str = "left", theme: str = "modern",
) -> dict:
    """Create an image + text slide (image left or right)."""
    from .design import LAYOUT, FONTS, FONT_SIZES, get_palette
    service = _get_service()
    pal = get_palette(theme)
    slide_id = _new_id()
    L = LAYOUT["image_text"]

    reqs: list[dict] = [{"createSlide": {
        "objectId": slide_id,
        "slideLayoutReference": {"predefinedLayout": "BLANK"},
    }}]
    reqs.extend(_set_bg_reqs(slide_id, pal))

    tid = _new_id()
    reqs.extend(_text_box_reqs(tid, slide_id, title, L["title"],
        font=FONTS["heading"], size=FONT_SIZES["slide_title"],
        color=pal["primary_text"], bold=True, alignment="START"))

    img_pos = L["image"] if image_side == "left" else L["text"]
    txt_pos = L["text"] if image_side == "left" else L["image"]

    iid = _new_id()
    reqs.append({"createImage": {
        "objectId": iid, "url": image_url,
        "elementProperties": {
            "pageObjectId": slide_id,
            "size": _emu_size(img_pos["w"], img_pos["h"]),
            "transform": _emu_transform(img_pos["x"], img_pos["y"]),
        },
    }})

    txid = _new_id()
    reqs.extend(_text_box_reqs(txid, slide_id, text, txt_pos,
        font=FONTS["body"], size=FONT_SIZES["body"],
        color=pal["primary_text"], alignment="START", line_spacing=150))

    execute_with_retry(service.presentations().batchUpdate(
        presentationId=presentation_id, body={"requests": reqs}))
    return {"slide_id": slide_id, "title": title, "image_side": image_side}


def add_quote_slide(
    presentation_id: str, quote: str, attribution: str = "",
    theme: str = "modern",
) -> dict:
    """Create a quote slide with accent bar."""
    from .design import LAYOUT, FONTS, FONT_SIZES, get_palette
    from shared.utils import hex_to_rgb
    service = _get_service()
    pal = get_palette(theme)
    slide_id = _new_id()
    L = LAYOUT["quote"]

    reqs: list[dict] = [{"createSlide": {
        "objectId": slide_id,
        "slideLayoutReference": {"predefinedLayout": "BLANK"},
    }}]
    reqs.extend(_set_bg_reqs(slide_id, pal))

    # Accent bar
    bid = _new_id()
    reqs.append({"createShape": {
        "objectId": bid, "shapeType": "RECTANGLE",
        "elementProperties": {
            "pageObjectId": slide_id,
            "size": _emu_size(L["bar"]["w"], L["bar"]["h"]),
            "transform": _emu_transform(L["bar"]["x"], L["bar"]["y"]),
        },
    }})
    reqs.append({"updateShapeProperties": {
        "objectId": bid,
        "shapeProperties": {
            "shapeBackgroundFill": {"solidFill": {"color": {"rgbColor": hex_to_rgb(pal["accent"])}}},
            "outline": {"propertyState": "NOT_RENDERED"},
        },
        "fields": "shapeBackgroundFill,outline",
    }})

    qid = _new_id()
    display_quote = f"“{quote}”"
    quote_size = FONT_SIZES["quote"] if len(quote) < 100 else 22 if len(quote) < 150 else 18
    reqs.extend(_text_box_reqs(qid, slide_id, display_quote, L["text"],
        font=FONTS["body"], size=quote_size,
        color=pal["primary_text"], italic=True, alignment="START", line_spacing=150))

    if attribution:
        aid = _new_id()
        reqs.extend(_text_box_reqs(aid, slide_id, f"— {attribution}", L["attribution"],
            font=FONTS["body"], size=FONT_SIZES["attribution"],
            color=pal["secondary_text"], alignment="START"))

    execute_with_retry(service.presentations().batchUpdate(
        presentationId=presentation_id, body={"requests": reqs}))
    return {"slide_id": slide_id, "quote": quote[:50]}


def add_metrics_slide(
    presentation_id: str, title: str, metrics: list[dict],
    theme: str = "modern",
) -> dict:
    """Create a big-numbers metrics slide. metrics: [{"value": "98%", "label": "Uptime"}, ...]"""
    from .design import LAYOUT, FONTS, FONT_SIZES, CONTENT, GUTTER, get_palette
    from shared.utils import hex_to_rgb
    service = _get_service()
    pal = get_palette(theme)
    slide_id = _new_id()
    L = LAYOUT["metrics"]

    n = min(len(metrics), 4)
    col_w = (CONTENT["w"] - (n - 1) * GUTTER) // n

    reqs: list[dict] = [{"createSlide": {
        "objectId": slide_id,
        "slideLayoutReference": {"predefinedLayout": "BLANK"},
    }}]
    reqs.extend(_set_bg_reqs(slide_id, pal))

    tid = _new_id()
    reqs.extend(_text_box_reqs(tid, slide_id, title, L["title"],
        font=FONTS["heading"], size=FONT_SIZES["slide_title"],
        color=pal["primary_text"], bold=True, alignment="START"))

    for i, m in enumerate(metrics[:4]):
        x = CONTENT["x"] + i * (col_w + GUTTER)

        # Big number
        nid = _new_id()
        num_pos = {"x": x, "y": L["area_y"], "w": col_w, "h": L["number_h"]}
        reqs.extend(_text_box_reqs(nid, slide_id, str(m.get("value", "")), num_pos,
            font=FONTS["heading"], size=FONT_SIZES["metric_number"],
            color=pal["accent"], bold=True, alignment="CENTER"))

        # Label
        lid = _new_id()
        label_pos = {"x": x, "y": L["area_y"] + L["number_h"], "w": col_w, "h": L["label_h"]}
        reqs.extend(_text_box_reqs(lid, slide_id, str(m.get("label", "")), label_pos,
            font=FONTS["body"], size=FONT_SIZES["metric_label"],
            color=pal["secondary_text"], alignment="CENTER"))

    execute_with_retry(service.presentations().batchUpdate(
        presentationId=presentation_id, body={"requests": reqs}))
    return {"slide_id": slide_id, "title": title, "metrics_count": n}


def add_styled_table_slide(
    presentation_id: str, title: str, headers: list[str],
    rows: list[list[str]], theme: str = "modern",
) -> dict:
    """Create a table slide with professional styling: colored header, alternating rows, borders."""
    from .design import LAYOUT, FONTS, FONT_SIZES, get_palette
    from shared.utils import hex_to_rgb
    service = _get_service()
    pal = get_palette(theme)
    slide_id = _new_id()
    title_id = _new_id()
    table_id = _new_id()
    L = LAYOUT["table"]

    num_rows = len(rows) + 1
    num_cols = len(headers)
    row_height = min(370_000, L["table"]["h"] // num_rows)
    table_h = min(num_rows * row_height, L["table"]["h"])

    reqs: list[dict] = [{"createSlide": {
        "objectId": slide_id,
        "slideLayoutReference": {"predefinedLayout": "BLANK"},
    }}]
    reqs.extend(_set_bg_reqs(slide_id, pal))

    # Title
    reqs.extend(_text_box_reqs(title_id, slide_id, title, L["title"],
        font=FONTS["heading"], size=FONT_SIZES["slide_title"],
        color=pal["primary_text"], bold=True, alignment="START"))

    # Table
    reqs.append({"createTable": {
        "objectId": table_id,
        "elementProperties": {
            "pageObjectId": slide_id,
            "size": _emu_size(L["table"]["w"], table_h),
            "transform": _emu_transform(L["table"]["x"], L["table"]["y"]),
        },
        "rows": num_rows, "columns": num_cols,
    }})

    # Insert header text
    for c, header in enumerate(headers):
        reqs.append({"insertText": {
            "objectId": table_id,
            "cellLocation": {"rowIndex": 0, "columnIndex": c},
            "text": header,
        }})

    # Insert data
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            if c < num_cols:
                reqs.append({"insertText": {
                    "objectId": table_id,
                    "cellLocation": {"rowIndex": r + 1, "columnIndex": c},
                    "text": str(cell),
                }})

    # Style header text: white, bold
    for c in range(num_cols):
        reqs.append({"updateTextStyle": {
            "objectId": table_id,
            "cellLocation": {"rowIndex": 0, "columnIndex": c},
            "style": {
                "fontFamily": FONTS["body"],
                "fontSize": {"magnitude": FONT_SIZES["table_header"], "unit": "PT"},
                "foregroundColor": {"opaqueColor": {"rgbColor": hex_to_rgb("#FFFFFF")}},
                "bold": True,
            },
            "textRange": {"type": "ALL"},
            "fields": "fontFamily,fontSize,foregroundColor,bold",
        }})

    # Style data text
    for r in range(len(rows)):
        for c in range(num_cols):
            reqs.append({"updateTextStyle": {
                "objectId": table_id,
                "cellLocation": {"rowIndex": r + 1, "columnIndex": c},
                "style": {
                    "fontFamily": FONTS["body"],
                    "fontSize": {"magnitude": FONT_SIZES["table_value"], "unit": "PT"},
                    "foregroundColor": {"opaqueColor": {"rgbColor": hex_to_rgb(pal["primary_text"])}},
                },
                "textRange": {"type": "ALL"},
                "fields": "fontFamily,fontSize,foregroundColor",
            }})

    # Header background
    for c in range(num_cols):
        reqs.append({"updateTableCellProperties": {
            "objectId": table_id,
            "tableRange": {"location": {"rowIndex": 0, "columnIndex": c}, "rowSpan": 1, "columnSpan": 1},
            "tableCellProperties": {
                "tableCellBackgroundFill": {"solidFill": {"color": {"rgbColor": hex_to_rgb(pal["table_header_bg"])}}},
            },
            "fields": "tableCellBackgroundFill",
        }})

    # Row backgrounds — alternating, plus explicit fill for non-default backgrounds
    surface = pal.get("surface", "#FFFFFF")
    for r in range(len(rows)):
        row_color = pal["table_alt_row"] if r % 2 == 1 else surface
        for c in range(num_cols):
            reqs.append({"updateTableCellProperties": {
                "objectId": table_id,
                "tableRange": {"location": {"rowIndex": r + 1, "columnIndex": c}, "rowSpan": 1, "columnSpan": 1},
                "tableCellProperties": {
                    "tableCellBackgroundFill": {"solidFill": {"color": {"rgbColor": hex_to_rgb(row_color)}}},
                },
                "fields": "tableCellBackgroundFill",
            }})

    # Table borders
    reqs.append({"updateTableBorderProperties": {
        "objectId": table_id,
        "borderPosition": "ALL",
        "tableBorderProperties": {
            "tableBorderFill": {"solidFill": {"color": {"rgbColor": hex_to_rgb(pal["table_border"])}}},
            "weight": {"magnitude": 0.75, "unit": "PT"},
            "dashStyle": "SOLID",
        },
        "fields": "tableBorderFill,weight,dashStyle",
    }})

    execute_with_retry(service.presentations().batchUpdate(
        presentationId=presentation_id, body={"requests": reqs}))
    return {"slide_id": slide_id, "title": title, "table": f"{num_rows}x{num_cols}"}


def add_chart_slide(
    presentation_id: str, spreadsheet_id: str, chart_id: int,
    title: str = "", linked: bool = True,
) -> dict:
    """Embed a Sheets chart onto a slide."""
    from .design import LAYOUT, FONTS, FONT_SIZES, get_palette
    service = _get_service()
    pal = get_palette()
    slide_id = _new_id()
    L = LAYOUT["content"]

    reqs: list[dict] = [{"createSlide": {
        "objectId": slide_id,
        "slideLayoutReference": {"predefinedLayout": "BLANK"},
    }}]
    reqs.extend(_set_bg_reqs(slide_id, pal))

    if title:
        tid = _new_id()
        reqs.extend(_text_box_reqs(tid, slide_id, title, L["title"],
            font=FONTS["heading"], size=FONT_SIZES["slide_title"],
            color=pal["primary_text"], bold=True, alignment="START"))

    chart_obj_id = _new_id()
    reqs.append({"createSheetsChart": {
        "objectId": chart_obj_id,
        "spreadsheetId": spreadsheet_id,
        "chartId": chart_id,
        "linkingMode": "LINKED" if linked else "NOT_LINKED_IMAGE",
        "elementProperties": {
            "pageObjectId": slide_id,
            "size": _emu_size(L["body"]["w"], L["body"]["h"]),
            "transform": _emu_transform(L["body"]["x"], L["body"]["y"]),
        },
    }})

    execute_with_retry(service.presentations().batchUpdate(
        presentationId=presentation_id, body={"requests": reqs}))
    return {"slide_id": slide_id, "title": title, "chart_object_id": chart_obj_id}


def set_slide_background(
    presentation_id: str, slide_id: str,
    color: str | None = None, image_url: str | None = None,
) -> dict:
    """Set slide background to a solid color or image."""
    from shared.utils import hex_to_rgb
    service = _get_service()

    if color:
        fill = {"solidFill": {"color": {"rgbColor": hex_to_rgb(color)}}}
    elif image_url:
        fill = {"stretchedPictureFill": {"contentUrl": image_url}}
    else:
        raise ValueError("Provide either color or image_url")

    execute_with_retry(service.presentations().batchUpdate(
        presentationId=presentation_id,
        body={"requests": [{"updatePageProperties": {
            "objectId": slide_id,
            "pageProperties": {"pageBackgroundFill": fill},
            "fields": "pageBackgroundFill",
        }}]},
    ))
    return {"slide_id": slide_id, "background": "color" if color else "image"}


def update_element(
    presentation_id: str, element_id: str,
    x: float | None = None, y: float | None = None,
    width: float | None = None, height: float | None = None,
) -> dict:
    """Move or resize a page element (shape, image, text box)."""
    service = _get_service()

    # Get current transform to preserve what we don't change
    pres = execute_with_retry(service.presentations().get(presentationId=presentation_id))
    current = None
    for slide in pres.get("slides", []):
        for elem in slide.get("pageElements", []):
            if elem["objectId"] == element_id:
                current = elem
                break
        if current:
            break
    if not current:
        raise ValueError(f"Element {element_id} not found")

    reqs = []
    cur_transform = current.get("transform", {})
    cur_size = current.get("size", {})

    new_transform = {
        "scaleX": cur_transform.get("scaleX", 1),
        "scaleY": cur_transform.get("scaleY", 1),
        "shearX": cur_transform.get("shearX", 0),
        "shearY": cur_transform.get("shearY", 0),
        "translateX": _inches(x) if x is not None else cur_transform.get("translateX", 0),
        "translateY": _inches(y) if y is not None else cur_transform.get("translateY", 0),
        "unit": "EMU",
    }

    if width is not None or height is not None:
        cur_w = cur_size.get("width", {}).get("magnitude", 1)
        cur_h = cur_size.get("height", {}).get("magnitude", 1)
        new_w = _inches(width) if width is not None else cur_w
        new_h = _inches(height) if height is not None else cur_h
        new_transform["scaleX"] = new_w / cur_w if cur_w else 1
        new_transform["scaleY"] = new_h / cur_h if cur_h else 1

    reqs.append({"updatePageElementTransform": {
        "objectId": element_id,
        "transform": new_transform,
        "applyMode": "ABSOLUTE",
    }})

    execute_with_retry(service.presentations().batchUpdate(
        presentationId=presentation_id, body={"requests": reqs}))
    return {"element_id": element_id, "updated": True}


def z_order(
    presentation_id: str, element_ids: list[str], operation: str = "BRING_TO_FRONT",
) -> dict:
    """Change z-order of elements."""
    service = _get_service()
    execute_with_retry(service.presentations().batchUpdate(
        presentationId=presentation_id,
        body={"requests": [{"updatePageElementsZOrder": {
            "pageElementObjectIds": element_ids,
            "operation": operation.upper(),
        }}]},
    ))
    return {"elements": element_ids, "operation": operation}


def group_elements(
    presentation_id: str, element_ids: list[str],
) -> dict:
    """Group elements together."""
    service = _get_service()
    group_id = _new_id()
    result = execute_with_retry(service.presentations().batchUpdate(
        presentationId=presentation_id,
        body={"requests": [{"groupObjects": {
            "groupObjectId": group_id,
            "childrenObjectIds": element_ids,
        }}]},
    ))
    return {"group_id": group_id, "children": element_ids}


def ungroup_elements(presentation_id: str, group_ids: list[str]) -> dict:
    """Ungroup previously grouped elements."""
    service = _get_service()
    execute_with_retry(service.presentations().batchUpdate(
        presentationId=presentation_id,
        body={"requests": [{"ungroupObjects": {"objectIds": group_ids}}]},
    ))
    return {"ungrouped": group_ids}


def add_code_slide(
    presentation_id: str, title: str, code: str,
    language: str = "", theme: str = "modern",
) -> dict:
    """Create a slide with a styled code block (dark background, mono font)."""
    from .design import LAYOUT, FONTS, FONT_SIZES, get_palette
    from shared.utils import hex_to_rgb
    service = _get_service()
    pal = get_palette(theme)
    slide_id = _new_id()
    L = LAYOUT["content"]

    reqs: list[dict] = [{"createSlide": {
        "objectId": slide_id,
        "slideLayoutReference": {"predefinedLayout": "BLANK"},
    }}]
    reqs.extend(_set_bg_reqs(slide_id, pal))

    # Title
    tid = _new_id()
    reqs.extend(_text_box_reqs(tid, slide_id, title, L["title"],
        font=FONTS["heading"], size=FONT_SIZES["slide_title"],
        color=pal["primary_text"], bold=True, alignment="START"))

    # Code block background (dark rounded rectangle)
    code_bg_id = _new_id()
    code_area = {"x": L["body"]["x"], "y": L["body"]["y"], "w": L["body"]["w"], "h": L["body"]["h"]}
    reqs.append({"createShape": {
        "objectId": code_bg_id, "shapeType": "ROUND_RECTANGLE",
        "elementProperties": {
            "pageObjectId": slide_id,
            "size": _emu_size(code_area["w"], code_area["h"]),
            "transform": _emu_transform(code_area["x"], code_area["y"]),
        },
    }})
    reqs.append({"updateShapeProperties": {
        "objectId": code_bg_id,
        "shapeProperties": {
            "shapeBackgroundFill": {"solidFill": {"color": {"rgbColor": hex_to_rgb("#1E1E1E")}}},
            "outline": {"propertyState": "NOT_RENDERED"},
            "contentAlignment": "TOP",
        },
        "fields": "shapeBackgroundFill,outline,contentAlignment",
    }})

    # Language label (top-right corner, as a separate text box)
    if language:
        lang_id = _new_id()
        lang_pos = {
            "x": code_area["x"] + code_area["w"] - 900_000,
            "y": code_area["y"] + 76_200,
            "w": 800_000, "h": 254_000,
        }
        reqs.extend(_text_box_reqs(lang_id, slide_id, language, lang_pos,
            font=FONTS["mono"], size=9, color="#555555", alignment="END"))

    # Code text box (overlaid on the dark background)
    code_id = _new_id()
    code_text_area = {
        "x": code_area["x"] + 152_400,
        "y": code_area["y"] + 152_400,
        "w": code_area["w"] - 304_800,
        "h": code_area["h"] - 304_800,
    }
    reqs.extend(_text_box_reqs(code_id, slide_id, code, code_text_area,
        font=FONTS["mono"], size=13, color="#D4D4D4",
        alignment="START", line_spacing=130))

    execute_with_retry(service.presentations().batchUpdate(
        presentationId=presentation_id, body={"requests": reqs}))
    return {"slide_id": slide_id, "title": title}


def _extract_text(text_elements: list) -> str:
    parts = []
    for te in text_elements:
        tr = te.get("textRun", {})
        if tr:
            parts.append(tr.get("content", ""))
    return "".join(parts).strip()
