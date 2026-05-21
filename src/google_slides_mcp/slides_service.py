"""Google Slides API wrapper — create, read, and build presentations."""

from __future__ import annotations

import uuid
from googleapiclient.discovery import build

from shared.auth import get_credentials
from shared.utils import execute_with_retry

_service = None
_deck_themes: dict[str, str] = {}
_deck_footers: dict[str, str] = {}

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


def set_deck_theme(presentation_id: str, theme: str) -> dict:
    from .design import PALETTES
    if theme not in PALETTES:
        raise ValueError(f"Unknown theme: {theme}. Available: {list(PALETTES.keys())}")
    _deck_themes[presentation_id] = theme
    return {"presentation_id": presentation_id, "theme": theme}


def get_deck_theme(presentation_id: str) -> str:
    from .design import DEFAULT_PALETTE
    return _deck_themes.get(presentation_id, DEFAULT_PALETTE)


def set_deck_footer(presentation_id: str, footer: str) -> dict:
    _deck_footers[presentation_id] = footer
    return {"presentation_id": presentation_id, "footer": footer}


def _resolve_theme(presentation_id: str, theme: str | None) -> str:
    from .design import DEFAULT_PALETTE
    if theme is not None:
        return theme
    return _deck_themes.get(presentation_id, DEFAULT_PALETTE)


def _header_bar_reqs(slide_id: str, pal: dict) -> list[dict]:
    """Full-width colored header bar behind the title (McKinsey pattern)."""
    from .design import LAYOUT
    from shared.utils import hex_to_rgb
    L = LAYOUT["header_bar"]
    bid = _new_id()
    return [
        {"createShape": {
            "objectId": bid, "shapeType": "RECTANGLE",
            "elementProperties": {
                "pageObjectId": slide_id,
                "size": _emu_size(L["w"], L["h"]),
                "transform": _emu_transform(L["x"], L["y"]),
            },
        }},
        {"updateShapeProperties": {
            "objectId": bid,
            "shapeProperties": {
                "shapeBackgroundFill": {"solidFill": {"color": {"rgbColor": hex_to_rgb(pal["accent"])}, "alpha": 1.0}},
                "outline": {"propertyState": "NOT_RENDERED"},
            },
            "fields": "shapeBackgroundFill,outline",
        }},
        {"updatePageElementsZOrder": {
            "pageElementObjectIds": [bid],
            "operation": "SEND_TO_BACK",
        }},
    ]


def _footer_line_reqs(slide_id: str, pal: dict) -> list[dict]:
    """Thin horizontal divider line above the footer area."""
    from .design import LAYOUT
    from shared.utils import hex_to_rgb
    lid = _new_id()
    x = LAYOUT["content"]["title"]["x"]
    w = LAYOUT["content"]["title"]["w"]
    y = LAYOUT["footer_line_y"]
    return [
        {"createLine": {
            "objectId": lid, "category": "STRAIGHT",
            "elementProperties": {
                "pageObjectId": slide_id,
                "size": _emu_size(w, 0),
                "transform": _emu_transform(x, y),
            },
        }},
        {"updateLineProperties": {
            "objectId": lid,
            "lineProperties": {
                "lineFill": {"solidFill": {"color": {"rgbColor": hex_to_rgb(pal["divider"])}}},
                "weight": {"magnitude": 0.75, "unit": "PT"},
            },
            "fields": "lineFill,weight",
        }},
    ]


def _page_number_reqs(slide_id: str, pal: dict, number: int) -> list[dict]:
    from .design import LAYOUT, FONTS, FONT_SIZES
    pn = LAYOUT["page_number"]
    sid = _new_id()
    return _text_box_reqs(sid, slide_id, str(number), pn,
        font=FONTS["body"], size=FONT_SIZES["page_number"],
        color=pal["page_number"], alignment="END")


def _footer_reqs(slide_id: str, pal: dict, presentation_id: str) -> list[dict]:
    footer = _deck_footers.get(presentation_id, "")
    if not footer:
        return []
    from .design import LAYOUT, FONTS, FONT_SIZES
    fid = _new_id()
    return _text_box_reqs(fid, slide_id, footer, LAYOUT["footer"],
        font=FONTS["body"], size=FONT_SIZES["page_number"],
        color=pal["page_number"], alignment="START")


def _get_slide_count(service, presentation_id: str) -> int:
    pres = execute_with_retry(
        service.presentations().get(presentationId=presentation_id, fields="slides.objectId"))
    return len(pres.get("slides", []))


def _polish_reqs(slide_id: str, pal: dict, presentation_id: str, service) -> list[dict]:
    """Add footer line + page number + footer text to a content slide."""
    reqs = []
    reqs.extend(_footer_line_reqs(slide_id, pal))
    slide_num = _get_slide_count(service, presentation_id) + 1
    reqs.extend(_page_number_reqs(slide_id, pal, slide_num))
    reqs.extend(_footer_reqs(slide_id, pal, presentation_id))
    return reqs


def _auto_column_widths(headers: list[str], table_w: int) -> list[int]:
    MIN_COL = 600_000  # ~0.66 inches — prevents unreadably narrow columns
    n = len(headers)
    if n == 0:
        return []
    lengths = [max(len(h), 4) for h in headers]
    total = sum(lengths)
    widths = [max(MIN_COL, int(table_w * l / total)) for l in lengths]
    # Ensure widths sum exactly to table_w (absorb rounding into widest column)
    diff = table_w - sum(widths)
    if diff != 0:
        widest = max(range(n), key=lambda i: widths[i])
        widths[widest] += diff
    return widths


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


def list_layouts(presentation_id: str) -> list[dict]:
    """List all available layouts in a presentation (from its master)."""
    service = _get_service()
    pres = execute_with_retry(service.presentations().get(presentationId=presentation_id))
    layouts = []
    for layout in pres.get("layouts", []):
        props = layout.get("layoutProperties", {})
        placeholders = []
        for elem in layout.get("pageElements", []):
            ph = elem.get("shape", {}).get("placeholder", {})
            if ph:
                placeholders.append({"type": ph.get("type", ""), "index": ph.get("index", 0)})
        layouts.append({
            "layout_id": layout["objectId"],
            "name": props.get("displayName", props.get("name", "")),
            "placeholders": placeholders,
        })
    return layouts


def create_from_template(
    template_id: str, title: str, folder_id: str | None = None,
) -> dict:
    """Copy a template presentation, clear its content, return a clean deck with the theme."""
    from shared import drive_service
    result = drive_service.copy_file(template_id, title, folder_id)
    new_id = result["id"]

    # Delete all slides except the first (to keep at least one for layout reference)
    pres = get_presentation(new_id)
    for s in pres["slides"][1:]:
        delete_slide(new_id, s["slide_id"])
    # Delete the last remaining slide
    if pres["slides"]:
        delete_slide(new_id, pres["slides"][0]["slide_id"])

    return {
        "presentation_id": new_id,
        "title": title,
        "url": result.get("url", ""),
        "layouts": list_layouts(new_id),
    }


def add_slide_from_layout(
    presentation_id: str, layout_id: str, texts: dict[str, str] | None = None,
) -> dict:
    """Create a slide using a specific layout ID, then fill placeholders.

    texts: dict mapping "PLACEHOLDER_TYPE_INDEX" to text content.
    E.g. {"TITLE_0": "My Title", "BODY_0": "Body text", "SUBTITLE_0": "Sub"}
    """
    service = _get_service()
    slide_id = _new_id()

    execute_with_retry(service.presentations().batchUpdate(
        presentationId=presentation_id,
        body={"requests": [{"createSlide": {
            "objectId": slide_id,
            "slideLayoutReference": {"layoutId": layout_id},
        }}]},
    ))

    if texts:
        # Read back to find placeholder object IDs
        pres = execute_with_retry(service.presentations().get(presentationId=presentation_id))
        slide = next((s for s in pres["slides"] if s["objectId"] == slide_id), None)
        if slide:
            insert_reqs = []
            for elem in slide.get("pageElements", []):
                ph = elem.get("shape", {}).get("placeholder", {})
                if not ph:
                    continue
                key = f"{ph.get('type', '')}_{ph.get('index', 0)}"
                if key in texts:
                    insert_reqs.append({"insertText": {
                        "objectId": elem["objectId"],
                        "text": texts[key],
                    }})
            if insert_reqs:
                execute_with_retry(service.presentations().batchUpdate(
                    presentationId=presentation_id,
                    body={"requests": insert_reqs},
                ))

    return {"slide_id": slide_id}


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
    theme: str | None = None,
) -> dict:
    from .design import FONTS, FONT_SIZES, get_palette
    from shared.utils import hex_to_rgb
    service = _get_service()
    pal = get_palette(_resolve_theme(presentation_id, theme))
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
        requests.append({"updateTextStyle": {
            "objectId": title_id,
            "style": {
                "fontFamily": FONTS["heading"],
                "fontSize": {"magnitude": FONT_SIZES["slide_title"], "unit": "PT"},
                "foregroundColor": {"opaqueColor": {"rgbColor": hex_to_rgb(pal["primary_text"])}},
                "bold": True,
            },
            "textRange": {"type": "ALL"},
            "fields": "fontFamily,fontSize,foregroundColor,bold",
        }})

    if body and has_body_placeholder:
        requests.append({"insertText": {"objectId": body_id, "text": body}})
        requests.append({"updateTextStyle": {
            "objectId": body_id,
            "style": {
                "fontFamily": FONTS["body"],
                "fontSize": {"magnitude": FONT_SIZES["body"], "unit": "PT"},
                "foregroundColor": {"opaqueColor": {"rgbColor": hex_to_rgb(pal["primary_text"])}},
            },
            "textRange": {"type": "ALL"},
            "fields": "fontFamily,fontSize,foregroundColor",
        }})

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
    theme: str | None = None,
) -> dict:
    """Legacy table slide — now redirects to styled table with design system."""
    return add_styled_table_slide(
        presentation_id, title, headers, rows,
        _resolve_theme(presentation_id, theme))


def add_image_slide(
    presentation_id: str,
    image_url: str,
    title: str = "",
    as_background: bool = False,
    theme: str | None = None,
) -> dict:
    from .design import FONTS, FONT_SIZES, get_palette
    from shared.utils import hex_to_rgb
    service = _get_service()
    pal = get_palette(_resolve_theme(presentation_id, theme))
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
        requests.append({"updateTextStyle": {
            "objectId": title_id,
            "style": {
                "fontFamily": FONTS["heading"],
                "fontSize": {"magnitude": FONT_SIZES["slide_title"], "unit": "PT"},
                "foregroundColor": {"opaqueColor": {"rgbColor": hex_to_rgb(pal["primary_text"])}},
                "bold": True,
            },
            "textRange": {"type": "ALL"},
            "fields": "fontFamily,fontSize,foregroundColor,bold",
        }})

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


def _inches(val: float) -> int:
    return int(val * EMU_PER_INCH)


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
    author: str = "", theme: str | None = None,
    title_font: str | None = None, title_size: float | None = None,
    subtitle_font: str | None = None, subtitle_size: float | None = None,
    title_color: str | None = None, subtitle_color: str | None = None,
    bg_color: str | None = None,
) -> dict:
    """Create a title slide. All styling optional — defaults from theme."""
    from .design import LAYOUT, FONTS, FONT_SIZES, get_palette
    from shared.utils import hex_to_rgb
    service = _get_service()
    pal = get_palette(_resolve_theme(presentation_id, theme))
    slide_id = _new_id()
    L = LAYOUT["title_slide"]

    reqs: list[dict] = [{"createSlide": {
        "objectId": slide_id,
        "slideLayoutReference": {"predefinedLayout": "BLANK"},
    }}]
    if bg_color:
        reqs.append({"updatePageProperties": {
            "objectId": slide_id,
            "pageProperties": {"pageBackgroundFill": {"solidFill": {"color": {"rgbColor": hex_to_rgb(bg_color)}}}},
            "fields": "pageBackgroundFill",
        }})
    else:
        reqs.extend(_set_bg_reqs(slide_id, pal))

    tid = _new_id()
    reqs.extend(_text_box_reqs(tid, slide_id, title, L["title"],
        font=title_font or FONTS["heading"],
        size=title_size or FONT_SIZES["slide_title"],
        color=title_color or pal["primary_text"],
        bold=True, alignment="CENTER", line_spacing=115))

    if subtitle:
        sid = _new_id()
        reqs.extend(_text_box_reqs(sid, slide_id, subtitle, L["subtitle"],
            font=subtitle_font or FONTS["body"],
            size=subtitle_size or FONT_SIZES["subtitle"],
            color=subtitle_color or pal["secondary_text"],
            alignment="CENTER"))

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
    theme: str | None = None,
) -> dict:
    """Create a section divider slide with accent background."""
    from .design import LAYOUT, FONTS, FONT_SIZES, CANVAS_W, CANVAS_H, get_palette
    from shared.utils import hex_to_rgb
    service = _get_service()
    pal = get_palette(_resolve_theme(presentation_id, theme))
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
        color=pal["primary_text"], bold=True, alignment="START", line_spacing=115))

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
    speaker_notes: str = "", theme: str | None = None,
    title_font: str | None = None, title_size: float | None = None,
    body_font: str | None = None, body_size: float | None = None,
    title_color: str | None = None, body_color: str | None = None,
    line_spacing: float | None = None, bg_color: str | None = None,
) -> dict:
    """Create a content slide. All styling is optional — defaults from theme."""
    from .design import LAYOUT, FONTS, FONT_SIZES, LINE_SPACING, get_palette
    from shared.utils import hex_to_rgb
    service = _get_service()
    pal = get_palette(_resolve_theme(presentation_id, theme))
    slide_id = _new_id()
    L = LAYOUT["content"]

    reqs: list[dict] = [{"createSlide": {
        "objectId": slide_id,
        "slideLayoutReference": {"predefinedLayout": "BLANK"},
    }}]
    if bg_color:
        reqs.append({"updatePageProperties": {
            "objectId": slide_id,
            "pageProperties": {"pageBackgroundFill": {"solidFill": {"color": {"rgbColor": hex_to_rgb(bg_color)}}}},
            "fields": "pageBackgroundFill",
        }})
    else:
        reqs.extend(_set_bg_reqs(slide_id, pal))

    tid = _new_id()
    reqs.extend(_text_box_reqs(tid, slide_id, title, L["title"],
        font=title_font or FONTS["heading"],
        size=title_size or FONT_SIZES["slide_title"],
        color=title_color or pal["primary_text"],
        bold=True, alignment="START"))

    if body:
        bid = _new_id()
        reqs.extend(_text_box_reqs(bid, slide_id, body, L["body"],
            font=body_font or FONTS["body"],
            size=body_size or FONT_SIZES["body"],
            color=body_color or pal["primary_text"],
            alignment="START",
            line_spacing=line_spacing or LINE_SPACING["body"],
            space_below=6))
    else:
        bid = None

    if bid and "\n" in body:
        reqs.append({"createParagraphBullets": {
            "objectId": bid,
            "textRange": {"type": "ALL"},
            "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE",
        }})

    reqs.extend(_polish_reqs(slide_id, pal, presentation_id, service))
    execute_with_retry(service.presentations().batchUpdate(
        presentationId=presentation_id, body={"requests": reqs}))

    if speaker_notes:
        _set_speaker_notes(service, presentation_id, slide_id, speaker_notes)

    return {"slide_id": slide_id, "title": title}


def add_two_column_slide(
    presentation_id: str, title: str, col1: str, col2: str,
    col1_title: str = "", col2_title: str = "", theme: str | None = None,
) -> dict:
    """Create a two-column content slide."""
    from .design import LAYOUT, FONTS, FONT_SIZES, GUTTER, get_palette
    service = _get_service()
    pal = get_palette(_resolve_theme(presentation_id, theme))
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

    reqs.extend(_polish_reqs(slide_id, pal, presentation_id, service))
    execute_with_retry(service.presentations().batchUpdate(
        presentationId=presentation_id, body={"requests": reqs}))
    return {"slide_id": slide_id, "title": title}


def add_image_text_slide(
    presentation_id: str, title: str, image_url: str, text: str,
    image_side: str = "left", theme: str | None = None,
) -> dict:
    """Create an image + text slide (image left or right)."""
    from .design import LAYOUT, FONTS, FONT_SIZES, get_palette
    service = _get_service()
    pal = get_palette(_resolve_theme(presentation_id, theme))
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

    reqs.extend(_polish_reqs(slide_id, pal, presentation_id, service))
    execute_with_retry(service.presentations().batchUpdate(
        presentationId=presentation_id, body={"requests": reqs}))
    return {"slide_id": slide_id, "title": title, "image_side": image_side}


def add_quote_slide(
    presentation_id: str, quote: str, attribution: str = "",
    theme: str | None = None,
) -> dict:
    """Create a quote slide with accent bar."""
    from .design import LAYOUT, FONTS, FONT_SIZES, get_palette
    from shared.utils import hex_to_rgb
    service = _get_service()
    pal = get_palette(_resolve_theme(presentation_id, theme))
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
    theme: str | None = None,
) -> dict:
    """Create a big-numbers metrics slide. metrics: [{"value": "98%", "label": "Uptime"}, ...]"""
    from .design import LAYOUT, FONTS, FONT_SIZES, CONTENT, GUTTER, get_palette
    from shared.utils import hex_to_rgb
    service = _get_service()
    pal = get_palette(_resolve_theme(presentation_id, theme))
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

    reqs.extend(_polish_reqs(slide_id, pal, presentation_id, service))
    execute_with_retry(service.presentations().batchUpdate(
        presentationId=presentation_id, body={"requests": reqs}))
    return {"slide_id": slide_id, "title": title, "metrics_count": n}


def add_styled_table_slide(
    presentation_id: str, title: str, headers: list[str],
    rows: list[list[str]], theme: str | None = None,
) -> dict:
    """Create a table slide with professional styling: colored header, alternating rows, borders."""
    from .design import LAYOUT, FONTS, FONT_SIZES, get_palette
    from shared.utils import hex_to_rgb
    service = _get_service()
    pal = get_palette(_resolve_theme(presentation_id, theme))
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

    # Table borders — horizontal rules only (modern style, no outer border)
    for pos in ("INNER_HORIZONTAL", "BOTTOM", "TOP"):
        reqs.append({"updateTableBorderProperties": {
            "objectId": table_id,
            "borderPosition": pos,
            "tableBorderProperties": {
                "tableBorderFill": {"solidFill": {"color": {"rgbColor": hex_to_rgb(pal["table_border"])}}},
                "weight": {"magnitude": 0.5, "unit": "PT"},
                "dashStyle": "SOLID",
            },
            "fields": "tableBorderFill,weight,dashStyle",
        }})

    # Auto-size columns proportionally
    col_widths = _auto_column_widths(headers, L["table"]["w"])
    for c, width in enumerate(col_widths):
        reqs.append({"updateTableColumnProperties": {
            "objectId": table_id,
            "columnIndices": [c],
            "tableColumnProperties": {"columnWidth": {"magnitude": width, "unit": "EMU"}},
            "fields": "columnWidth",
        }})

    reqs.extend(_polish_reqs(slide_id, pal, presentation_id, service))
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
    pal = get_palette(_resolve_theme(presentation_id, theme))
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

    reqs.extend(_polish_reqs(slide_id, pal, presentation_id, service))
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
    language: str = "", theme: str | None = None,
) -> dict:
    """Create a slide with a styled code block (dark background, mono font)."""
    from .design import LAYOUT, FONTS, FONT_SIZES, get_palette
    from shared.utils import hex_to_rgb
    service = _get_service()
    pal = get_palette(_resolve_theme(presentation_id, theme))
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

    reqs.extend(_polish_reqs(slide_id, pal, presentation_id, service))
    execute_with_retry(service.presentations().batchUpdate(
        presentationId=presentation_id, body={"requests": reqs}))
    return {"slide_id": slide_id, "title": title}


def update_table_columns(
    presentation_id: str, table_id: str, column_widths: list[float],
) -> dict:
    """Set column widths for a table. Widths in inches."""
    service = _get_service()
    reqs = []
    for c, w in enumerate(column_widths):
        reqs.append({"updateTableColumnProperties": {
            "objectId": table_id,
            "columnIndices": [c],
            "tableColumnProperties": {"columnWidth": {"magnitude": _inches(w), "unit": "EMU"}},
            "fields": "columnWidth",
        }})
    execute_with_retry(service.presentations().batchUpdate(
        presentationId=presentation_id, body={"requests": reqs}))
    return {"table_id": table_id, "columns": len(column_widths)}


def update_text_style(
    presentation_id: str,
    element_id: str,
    font_family: str | None = None,
    font_size: float | None = None,
    bold: bool | None = None,
    italic: bool | None = None,
    color: str | None = None,
    start_index: int | None = None,
    end_index: int | None = None,
) -> dict:
    """Update text style on an existing element (shape, text box, table cell)."""
    from shared.utils import hex_to_rgb
    service = _get_service()
    style: dict = {}
    fields = []

    if font_family:
        style["fontFamily"] = font_family
        fields.append("fontFamily")
    if font_size is not None:
        style["fontSize"] = {"magnitude": font_size, "unit": "PT"}
        fields.append("fontSize")
    if bold is not None:
        style["bold"] = bold
        fields.append("bold")
    if italic is not None:
        style["italic"] = italic
        fields.append("italic")
    if color:
        style["foregroundColor"] = {"opaqueColor": {"rgbColor": hex_to_rgb(color)}}
        fields.append("foregroundColor")

    if not fields:
        return {"element_id": element_id, "updated": False}

    text_range = {"type": "ALL"}
    if start_index is not None and end_index is not None:
        text_range = {"type": "FIXED_RANGE", "startIndex": start_index, "endIndex": end_index}

    execute_with_retry(service.presentations().batchUpdate(
        presentationId=presentation_id,
        body={"requests": [{"updateTextStyle": {
            "objectId": element_id,
            "style": style,
            "textRange": text_range,
            "fields": ",".join(fields),
        }}]},
    ))
    return {"element_id": element_id, "updated": True, "fields": fields}


def style_existing_table(
    presentation_id: str,
    table_id: str,
    header_bg: str | None = None,
    header_text_color: str = "#FFFFFF",
    alt_row_color: str | None = None,
    border_color: str | None = None,
    header_font_size: float | None = None,
    cell_font_size: float | None = None,
    font_family: str | None = None,
) -> dict:
    """Apply professional styling to an existing table."""
    from shared.utils import hex_to_rgb
    service = _get_service()

    # Read the table to get dimensions
    pres = execute_with_retry(service.presentations().get(presentationId=presentation_id))
    table_data = None
    for slide in pres.get("slides", []):
        for elem in slide.get("pageElements", []):
            if elem["objectId"] == table_id and "table" in elem:
                table_data = elem["table"]
                break
        if table_data:
            break
    if not table_data:
        raise ValueError(f"Table {table_id} not found")

    num_rows = table_data.get("rows", 0)
    num_cols = table_data.get("columns", 0)
    reqs = []

    # Header row background
    if header_bg:
        for c in range(num_cols):
            reqs.append({"updateTableCellProperties": {
                "objectId": table_id,
                "tableRange": {"location": {"rowIndex": 0, "columnIndex": c}, "rowSpan": 1, "columnSpan": 1},
                "tableCellProperties": {
                    "tableCellBackgroundFill": {"solidFill": {"color": {"rgbColor": hex_to_rgb(header_bg)}}},
                },
                "fields": "tableCellBackgroundFill",
            }})
            # Header text color + bold
            reqs.append({"updateTextStyle": {
                "objectId": table_id,
                "cellLocation": {"rowIndex": 0, "columnIndex": c},
                "style": {
                    "foregroundColor": {"opaqueColor": {"rgbColor": hex_to_rgb(header_text_color)}},
                    "bold": True,
                    **({"fontFamily": font_family} if font_family else {}),
                    **({"fontSize": {"magnitude": header_font_size, "unit": "PT"}} if header_font_size else {}),
                },
                "textRange": {"type": "ALL"},
                "fields": "foregroundColor,bold" + (",fontFamily" if font_family else "") + (",fontSize" if header_font_size else ""),
            }})

    # Alternating row backgrounds
    if alt_row_color:
        for r in range(1, num_rows):
            if r % 2 == 0:
                for c in range(num_cols):
                    reqs.append({"updateTableCellProperties": {
                        "objectId": table_id,
                        "tableRange": {"location": {"rowIndex": r, "columnIndex": c}, "rowSpan": 1, "columnSpan": 1},
                        "tableCellProperties": {
                            "tableCellBackgroundFill": {"solidFill": {"color": {"rgbColor": hex_to_rgb(alt_row_color)}}},
                        },
                        "fields": "tableCellBackgroundFill",
                    }})

    # Cell text styling
    if cell_font_size or font_family:
        for r in range(1, num_rows):
            for c in range(num_cols):
                style: dict = {}
                flds = []
                if font_family:
                    style["fontFamily"] = font_family
                    flds.append("fontFamily")
                if cell_font_size:
                    style["fontSize"] = {"magnitude": cell_font_size, "unit": "PT"}
                    flds.append("fontSize")
                if flds:
                    reqs.append({"updateTextStyle": {
                        "objectId": table_id,
                        "cellLocation": {"rowIndex": r, "columnIndex": c},
                        "style": style,
                        "textRange": {"type": "ALL"},
                        "fields": ",".join(flds),
                    }})

    # Borders
    if border_color:
        reqs.append({"updateTableBorderProperties": {
            "objectId": table_id,
            "borderPosition": "INNER_HORIZONTAL",
            "tableBorderProperties": {
                "tableBorderFill": {"solidFill": {"color": {"rgbColor": hex_to_rgb(border_color)}}},
                "weight": {"magnitude": 0.5, "unit": "PT"},
                "dashStyle": "SOLID",
            },
            "fields": "tableBorderFill,weight,dashStyle",
        }})

    if reqs:
        execute_with_retry(service.presentations().batchUpdate(
            presentationId=presentation_id, body={"requests": reqs}))

    return {"table_id": table_id, "rows": num_rows, "cols": num_cols, "requests": len(reqs)}


def normalize_fonts(
    presentation_id: str,
    target_font: str = "Open Sans",
    replace_fonts: list[str] | None = None,
) -> dict:
    """Replace all instances of specified fonts with a target font across the entire deck."""
    service = _get_service()
    pres = execute_with_retry(service.presentations().get(presentationId=presentation_id))
    replace_fonts = replace_fonts or ["Segoe UI", "Calibri", "Times New Roman"]

    reqs = []
    count = 0
    for slide in pres.get("slides", []):
        for elem in slide.get("pageElements", []):
            shape = elem.get("shape", {})
            text_elems = shape.get("text", {}).get("textElements", [])
            for te in text_elems:
                tr = te.get("textRun", {})
                if not tr:
                    continue
                ts = tr.get("style", {})
                ff = ts.get("fontFamily", ts.get("weightedFontFamily", {}).get("fontFamily", ""))
                if ff in replace_fonts:
                    start = te.get("startIndex", 0)
                    end = te.get("endIndex", 0)
                    if end > start:
                        reqs.append({"updateTextStyle": {
                            "objectId": elem["objectId"],
                            "style": {"fontFamily": target_font},
                            "textRange": {"type": "FIXED_RANGE", "startIndex": start, "endIndex": end},
                            "fields": "fontFamily",
                        }})
                        count += 1

    if reqs:
        # Batch in chunks of 100 to avoid API limits
        for i in range(0, len(reqs), 100):
            execute_with_retry(service.presentations().batchUpdate(
                presentationId=presentation_id, body={"requests": reqs[i:i+100]}))

    return {"font_replacements": count, "target_font": target_font}


def audit_styles(presentation_id: str) -> dict:
    """Analyze a deck and report style + layout inconsistencies for LLM-driven fixes."""
    service = _get_service()
    pres = execute_with_retry(service.presentations().get(presentationId=presentation_id))

    fonts = {}
    sizes = {}
    colors = {}
    tables = []
    slide_count = len(pres.get("slides", []))

    title_positions = []
    slides_without_title = []
    empty_slides = []
    title_fonts = {}
    title_sizes = {}
    page_num_slides = set()
    footer_slides = set()

    SLIDE_H_EMU = 5_625_000
    TITLE_Y_THRESHOLD = SLIDE_H_EMU * 0.40

    for s_idx, slide in enumerate(pres.get("slides", [])):
        slide_num = s_idx + 1
        has_title = False
        has_content = False
        has_page_num = False
        has_footer = False

        # Collect text element candidates for multi-signal title detection
        text_candidates = []

        for elem in slide.get("pageElements", []):
            obj_id = elem["objectId"]
            shape = elem.get("shape", {})
            table = elem.get("table", {})
            transform = elem.get("transform", {})
            elem_y = transform.get("translateY", 0)

            is_placeholder = shape.get("placeholder", {}).get("type", "")

            max_font_in_elem = 0
            has_bold = False
            has_heading_font = False
            elem_text = ""

            for te in shape.get("text", {}).get("textElements", []):
                tr = te.get("textRun", {})
                content = tr.get("content", "").strip() if tr else ""
                if not content:
                    continue
                has_content = True
                elem_text += content + " "
                ts = tr.get("style", {})
                ff = ts.get("fontFamily", ts.get("weightedFontFamily", {}).get("fontFamily", ""))
                if ff:
                    fonts[ff] = fonts.get(ff, 0) + 1
                    if ff.lower() in ("montserrat", "roboto slab", "playfair display", "raleway", "poppins"):
                        has_heading_font = True
                fs = ts.get("fontSize", {}).get("magnitude")
                if fs:
                    sizes[fs] = sizes.get(fs, 0) + 1
                    max_font_in_elem = max(max_font_in_elem, fs)
                    if fs <= 9 and len(content) <= 4 and content.isdigit():
                        has_page_num = True
                if ts.get("bold"):
                    has_bold = True
                fg = ts.get("foregroundColor", {}).get("opaqueColor", {}).get("rgbColor", {})
                if fg:
                    r, g, b = fg.get("red", 0), fg.get("green", 0), fg.get("blue", 0)
                    hex_c = f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"
                    colors[hex_c] = colors.get(hex_c, 0) + 1
                if "©" in content or "bsigma" in content.lower():
                    has_footer = True

            if elem_text.strip() and max_font_in_elem > 0:
                score = 0
                if is_placeholder in ("TITLE", "CENTERED_TITLE"):
                    score += 3
                if max_font_in_elem >= 20:
                    score += 2
                if elem_y < TITLE_Y_THRESHOLD:
                    score += 1
                if has_bold:
                    score += 1
                if has_heading_font:
                    score += 1
                text_candidates.append({
                    "id": obj_id, "y": elem_y, "font": max_font_in_elem,
                    "score": score, "placeholder": is_placeholder,
                })

            if table:
                has_content = True
                has_header_bg = False
                first_row = table.get("tableRows", [{}])[0] if table.get("tableRows") else {}
                for cell in first_row.get("tableCells", []):
                    bg = cell.get("tableCellProperties", {}).get("tableCellBackgroundFill", {})
                    if bg.get("solidFill"):
                        has_header_bg = True
                        break
                tables.append({
                    "slide": slide_num,
                    "object_id": obj_id,
                    "rows": table.get("rows", 0),
                    "columns": table.get("columns", 0),
                    "has_styled_header": has_header_bg,
                })

        # Title detection: pick candidate with highest score (needs >=2 signals)
        if text_candidates:
            best = max(text_candidates, key=lambda c: (c["score"], c["font"]))
            if best["score"] >= 2:
                has_title = True
                title_positions.append({"slide": slide_num, "x": 0, "y": best["y"], "id": best["id"]})
                # Track title font/size from the best candidate's element
                for elem in slide.get("pageElements", []):
                    if elem["objectId"] != best["id"]:
                        continue
                    for te in elem.get("shape", {}).get("text", {}).get("textElements", []):
                        tr = te.get("textRun", {})
                        if not tr or not tr.get("content", "").strip():
                            continue
                        ts = tr.get("style", {})
                        tf = ts.get("fontFamily", ts.get("weightedFontFamily", {}).get("fontFamily", ""))
                        if tf:
                            title_fonts[tf] = title_fonts.get(tf, 0) + 1
                        tfs = ts.get("fontSize", {}).get("magnitude")
                        if tfs:
                            title_sizes[tfs] = title_sizes.get(tfs, 0) + 1
                    break

        if not has_title and has_content and slide_num > 1:
            slides_without_title.append(slide_num)
        if not has_content and slide_num > 1:
            empty_slides.append(slide_num)
        if has_page_num:
            page_num_slides.add(slide_num)
        if has_footer:
            footer_slides.add(slide_num)

    issues = []

    if len(fonts) > 2:
        issues.append(f"Too many fonts ({len(fonts)}): {', '.join(sorted(fonts, key=fonts.get, reverse=True))}")
    if len(sizes) > 6:
        issues.append(f"Too many font sizes ({len(sizes)}): inconsistent hierarchy")
    if len(colors) > 6:
        issues.append(f"Too many text colors ({len(colors)}): no consistent palette")
    for t in tables:
        if not t["has_styled_header"]:
            issues.append(f"Slide {t['slide']}: table ({t['rows']}x{t['columns']}) has no styled header — object_id: {t['object_id']}")
    smallest = min(sizes.keys()) if sizes else 0
    if smallest and smallest < 9:
        issues.append(f"Smallest font is {int(smallest)}pt — may be unreadable")

    if len(title_fonts) > 1:
        issues.append(f"Title font inconsistency: {', '.join(f'{f} ({c}x)' for f, c in sorted(title_fonts.items(), key=lambda x: -x[1]))}")
    if len(title_sizes) > 2:
        issues.append(f"Title size inconsistency: {', '.join(f'{int(s)}pt ({c}x)' for s, c in sorted(title_sizes.items(), key=lambda x: -x[1]))}")

    if title_positions:
        y_values = [tp["y"] for tp in title_positions]
        unique_y = set(int(y / 10000) for y in y_values)
        if len(unique_y) > 2:
            issues.append(f"Title Y-position varies across {len(unique_y)} positions — breaks flip test")

    if slides_without_title:
        if len(slides_without_title) <= 5:
            issues.append(f"Slides without title: {', '.join(str(s) for s in slides_without_title)}")
        else:
            issues.append(f"{len(slides_without_title)} slides without title (first 5: {', '.join(str(s) for s in slides_without_title[:5])})")

    if empty_slides:
        issues.append(f"Empty slides: {', '.join(str(s) for s in empty_slides)}")

    missing_pn = [s for s in range(1, slide_count + 1) if s not in page_num_slides]
    content_missing_footer = []
    for s in range(2, slide_count + 1):
        if s not in footer_slides and s in page_num_slides:
            content_missing_footer.append(s)

    return {
        "slides": slide_count,
        "fonts": dict(sorted(fonts.items(), key=lambda x: -x[1])),
        "font_sizes": dict(sorted(sizes.items(), key=lambda x: -x[1])),
        "text_colors": dict(sorted(colors.items(), key=lambda x: -x[1])[:8]),
        "tables": tables,
        "layout": {
            "titles_found": len(title_positions),
            "slides_without_title": slides_without_title,
            "empty_slides": empty_slides,
            "title_fonts": title_fonts,
            "title_sizes": {f"{int(k)}pt": v for k, v in title_sizes.items()},
            "page_numbers_on": len(page_num_slides),
            "footers_on": len(footer_slides),
        },
        "issues": issues,
    }


def add_page_numbers(presentation_id: str, theme: str | None = None) -> dict:
    """Add page numbers to all slides (skips slides with colored backgrounds)."""
    from .design import get_palette
    service = _get_service()
    pal = get_palette(_resolve_theme(presentation_id, theme))
    pres = execute_with_retry(service.presentations().get(presentationId=presentation_id))
    slides = pres.get("slides", [])

    all_reqs = []
    numbered = 0
    for i, slide in enumerate(slides):
        slide_id = slide["objectId"]
        # Skip slides with colored backgrounds (section dividers, title slides)
        bg = slide.get("slideProperties", {}).get("pageBackgroundFill", {})
        if bg.get("solidFill") and bg["solidFill"].get("color", {}).get("rgbColor", {}) != {"red": 1, "green": 1, "blue": 1}:
            continue
        numbered += 1
        all_reqs.extend(_page_number_reqs(slide_id, pal, i + 1))

    if all_reqs:
        execute_with_retry(service.presentations().batchUpdate(
            presentationId=presentation_id, body={"requests": all_reqs}))
    return {"slides_numbered": numbered, "total_slides": len(slides)}


def reorder_slides(presentation_id: str, slide_ids: list[str], position: int = 0) -> dict:
    """Move slides to a new position in the deck."""
    service = _get_service()
    execute_with_retry(service.presentations().batchUpdate(
        presentationId=presentation_id,
        body={"requests": [{"updateSlidesPosition": {
            "slideObjectIds": slide_ids,
            "insertionIndex": position,
        }}]},
    ))
    return {"moved": len(slide_ids), "to_position": position}


def delete_element(presentation_id: str, element_id: str) -> dict:
    """Delete any element from a slide."""
    service = _get_service()
    execute_with_retry(service.presentations().batchUpdate(
        presentationId=presentation_id,
        body={"requests": [{"deleteObject": {"objectId": element_id}}]},
    ))
    return {"deleted": element_id}


def add_hyperlink(
    presentation_id: str, element_id: str, url: str,
    start_index: int | None = None, end_index: int | None = None,
) -> dict:
    """Add a hyperlink to text in an existing element."""
    from shared.utils import hex_to_rgb
    service = _get_service()
    text_range = {"type": "ALL"}
    if start_index is not None and end_index is not None:
        text_range = {"type": "FIXED_RANGE", "startIndex": start_index, "endIndex": end_index}
    execute_with_retry(service.presentations().batchUpdate(
        presentationId=presentation_id,
        body={"requests": [{"updateTextStyle": {
            "objectId": element_id,
            "style": {"link": {"url": url}},
            "textRange": text_range,
            "fields": "link",
        }}]},
    ))
    return {"element_id": element_id, "url": url}


def insert_table_rows(
    presentation_id: str, table_id: str, row_index: int, count: int = 1, below: bool = True,
) -> dict:
    """Insert rows into an existing table."""
    service = _get_service()
    execute_with_retry(service.presentations().batchUpdate(
        presentationId=presentation_id,
        body={"requests": [{"insertTableRows": {
            "tableObjectId": table_id,
            "cellLocation": {"rowIndex": row_index},
            "insertBelow": below,
            "number": count,
        }}]},
    ))
    return {"table_id": table_id, "rows_added": count}


def delete_table_row(presentation_id: str, table_id: str, row_index: int) -> dict:
    """Delete a row from an existing table."""
    service = _get_service()
    execute_with_retry(service.presentations().batchUpdate(
        presentationId=presentation_id,
        body={"requests": [{"deleteTableRow": {
            "tableObjectId": table_id,
            "cellLocation": {"rowIndex": row_index},
        }}]},
    ))
    return {"table_id": table_id, "row_deleted": row_index}


def insert_table_columns(
    presentation_id: str, table_id: str, col_index: int, count: int = 1, right: bool = True,
) -> dict:
    """Insert columns into an existing table."""
    service = _get_service()
    execute_with_retry(service.presentations().batchUpdate(
        presentationId=presentation_id,
        body={"requests": [{"insertTableColumns": {
            "tableObjectId": table_id,
            "cellLocation": {"columnIndex": col_index},
            "insertRight": right,
            "number": count,
        }}]},
    ))
    return {"table_id": table_id, "columns_added": count}


def delete_table_column(presentation_id: str, table_id: str, col_index: int) -> dict:
    """Delete a column from an existing table."""
    service = _get_service()
    execute_with_retry(service.presentations().batchUpdate(
        presentationId=presentation_id,
        body={"requests": [{"deleteTableColumn": {
            "tableObjectId": table_id,
            "cellLocation": {"columnIndex": col_index},
        }}]},
    ))
    return {"table_id": table_id, "column_deleted": col_index}


def merge_table_cells(
    presentation_id: str, table_id: str,
    row: int, col: int, row_span: int, col_span: int,
) -> dict:
    """Merge a range of cells in a table."""
    service = _get_service()
    execute_with_retry(service.presentations().batchUpdate(
        presentationId=presentation_id,
        body={"requests": [{"mergeTableCells": {
            "objectId": table_id,
            "tableRange": {
                "location": {"rowIndex": row, "columnIndex": col},
                "rowSpan": row_span, "columnSpan": col_span,
            },
        }}]},
    ))
    return {"table_id": table_id, "merged": f"{row_span}x{col_span} from [{row},{col}]"}


def batch_replace_text(
    presentation_id: str, replacements: dict[str, str],
) -> dict:
    """Replace multiple text placeholders in one call. E.g. {"{{name}}": "John", "{{date}}": "2025-01-15"}"""
    service = _get_service()
    reqs = []
    for find, replace in replacements.items():
        reqs.append({"replaceAllText": {
            "containsText": {"text": find, "matchCase": True},
            "replaceText": replace,
        }})
    result = execute_with_retry(service.presentations().batchUpdate(
        presentationId=presentation_id, body={"requests": reqs}))
    total = sum(
        r.get("replaceAllText", {}).get("occurrencesChanged", 0)
        for r in result.get("replies", []))
    return {"replacements": len(replacements), "total_changed": total}


def update_shape_fill(
    presentation_id: str, element_id: str,
    fill_color: str | None = None, outline_color: str | None = None,
    outline_weight: float | None = None,
) -> dict:
    """Change fill color and/or outline on an existing shape."""
    from shared.utils import hex_to_rgb
    service = _get_service()
    props: dict = {}
    fields = []
    if fill_color:
        props["shapeBackgroundFill"] = {"solidFill": {"color": {"rgbColor": hex_to_rgb(fill_color)}}}
        fields.append("shapeBackgroundFill")
    if outline_color:
        outline: dict = {"outlineFill": {"solidFill": {"color": {"rgbColor": hex_to_rgb(outline_color)}}}}
        if outline_weight:
            outline["weight"] = {"magnitude": outline_weight, "unit": "PT"}
        props["outline"] = outline
        fields.append("outline")
    if not fields:
        return {"element_id": element_id, "updated": False}
    execute_with_retry(service.presentations().batchUpdate(
        presentationId=presentation_id,
        body={"requests": [{"updateShapeProperties": {
            "objectId": element_id, "shapeProperties": props, "fields": ",".join(fields),
        }}]},
    ))
    return {"element_id": element_id, "updated": True}


def apply_brand_kit(
    presentation_id: str,
    heading_font: str,
    body_font: str,
    accent_color: str,
    text_color: str,
    replace_fonts: list[str] | None = None,
) -> dict:
    """Enforce brand consistency: normalize fonts + apply palette across the deck."""
    results = {}
    # Step 1: Normalize fonts
    if replace_fonts:
        r1 = normalize_fonts(presentation_id, body_font, replace_fonts)
        results["font_replacements"] = r1["font_replacements"]
    # Step 2: Style all unstyled tables
    audit = audit_styles(presentation_id)
    for t in audit["tables"]:
        if not t["has_styled_header"]:
            from shared.utils import hex_to_rgb
            style_existing_table(
                presentation_id, t["object_id"],
                header_bg=accent_color, header_text_color="#FFFFFF",
                alt_row_color="#F5F5F5", border_color="#E0E0E0",
                font_family=body_font,
            )
            results.setdefault("tables_styled", 0)
            results["tables_styled"] = results.get("tables_styled", 0) + 1
    results["heading_font"] = heading_font
    results["body_font"] = body_font
    results["accent_color"] = accent_color
    return results


def from_markdown(
    presentation_id: str, markdown: str, theme: str | None = None,
) -> dict:
    """Generate slides from Markdown. # = title slide, ## = section, ### = content slide, ``` = code, > = quote, | = table."""
    slides_created = 0
    lines = markdown.strip().split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if line.startswith("# ") and not line.startswith("## "):
            # Title slide
            title = line[2:].strip()
            subtitle = ""
            if i + 1 < len(lines) and lines[i + 1].strip() and not lines[i + 1].strip().startswith("#"):
                i += 1
                subtitle = lines[i].strip()
            add_title_slide(presentation_id, title, subtitle, theme=theme)
            slides_created += 1

        elif line.startswith("## ") and not line.startswith("### "):
            # Section slide
            add_section_slide(presentation_id, line[3:].strip(), theme=theme)
            slides_created += 1

        elif line.startswith("### "):
            # Content slide — collect body until next heading
            title = line[4:].strip()
            body_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("#"):
                if lines[i].strip():
                    body_lines.append(lines[i].strip())
                i += 1
            i -= 1  # back up for the outer loop
            if body_lines:
                # Check if it's a code block
                if body_lines[0].startswith("```"):
                    lang = body_lines[0][3:].strip()
                    code = "\n".join(body_lines[1:-1] if body_lines[-1] == "```" else body_lines[1:])
                    add_code_slide(presentation_id, title, code, lang, theme=theme)
                # Check if it's a table
                elif "|" in body_lines[0]:
                    rows = []
                    for bl in body_lines:
                        if bl.startswith("|") and "---" not in bl:
                            cells = [c.strip() for c in bl.strip("|").split("|")]
                            rows.append(cells)
                    if len(rows) >= 2:
                        add_styled_table_slide(presentation_id, title, rows[0], rows[1:], theme=theme)
                else:
                    add_content_slide(presentation_id, title, "\n".join(body_lines), theme=theme)
            else:
                add_content_slide(presentation_id, title, "", theme=theme)
            slides_created += 1

        elif line.startswith("> "):
            # Quote slide
            quote = line[2:].strip()
            attribution = ""
            if i + 1 < len(lines) and lines[i + 1].strip().startswith("—"):
                i += 1
                attribution = lines[i].strip()[1:].strip()
            add_quote_slide(presentation_id, quote, attribution, theme=theme)
            slides_created += 1

        i += 1

    return {"slides_created": slides_created}


def _extract_text(text_elements: list) -> str:
    parts = []
    for te in text_elements:
        tr = te.get("textRun", {})
        if tr:
            parts.append(tr.get("content", ""))
    return "".join(parts).strip()
