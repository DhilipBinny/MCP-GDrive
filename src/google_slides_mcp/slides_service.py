"""Google Slides API wrapper — create, read, and build presentations."""

from __future__ import annotations

import uuid
from googleapiclient.discovery import build

from shared.auth import get_credentials
from shared.utils import execute_with_retry

_service = None
_service_creds = None
_deck_themes: dict[str, str] = {}
_deck_footers: dict[str, str] = {}

EMU_PER_INCH = 914400
SLIDE_WIDTH = 9144000
SLIDE_HEIGHT = 5143500


def _get_service():
    global _service, _service_creds
    creds = get_credentials()
    if _service is None or creds is not _service_creds:
        _service = build("slides", "v1", credentials=creds)
        _service_creds = creds
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
        from .design import CONTENT
        pos = CONTENT
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
    """Import a draw.io diagram (mxGraph XML) as native Slides shapes.

    Uses BLANK layout + custom title text box for consistent positioning
    and maximum diagram space (no fixed-height TITLE placeholder).
    """
    from .design import LAYOUT, FONTS, FONT_SIZES
    from shared.utils import hex_to_rgb
    service = _get_service()
    slide_id = _new_id()
    title_id = _new_id()
    pal = _resolve_palette(presentation_id)

    create_reqs: list[dict] = [{
        "createSlide": {
            "objectId": slide_id,
            "slideLayoutReference": {"predefinedLayout": "BLANK"},
        }
    }]

    if title:
        L = LAYOUT["content"]["title"]
        create_reqs.append({
            "createShape": {
                "objectId": title_id, "shapeType": "TEXT_BOX",
                "elementProperties": {
                    "pageObjectId": slide_id,
                    "size": _emu_size(L["w"], L["h"]),
                    "transform": _emu_transform(L["x"], L["y"]),
                },
            }
        })
        create_reqs.append({"insertText": {"objectId": title_id, "text": title}})
        create_reqs.append({
            "updateTextStyle": {
                "objectId": title_id,
                "style": {
                    "fontFamily": FONTS["heading"],
                    "fontSize": {"magnitude": FONT_SIZES["slide_title"], "unit": "PT"},
                    "foregroundColor": {"opaqueColor": {"rgbColor": hex_to_rgb(pal["primary_text"])}},
                    "bold": True,
                },
                "textRange": {"type": "ALL"},
                "fields": "fontFamily,fontSize,foregroundColor,bold",
            }
        })

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


def _resolve_palette(presentation_id: str) -> dict:
    from .design import get_palette
    return get_palette(_resolve_theme(presentation_id, None))


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
            elements.append({"type": "table", "rows": table.get("rows", 0), "columns": table.get("columns", 0), "data": rows_data, "object_id": elem["objectId"]})
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
            font=FONTS["body"], size=18, color=pal["white"],
            alignment="START", line_spacing=115))

    tid = _new_id()
    reqs.extend(_text_box_reqs(tid, slide_id, title, L["title"],
        font=FONTS["heading"], size=FONT_SIZES["section_title"],
        color=pal["white"], bold=True, alignment="START", line_spacing=115))

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
    title: str = "", linked: bool = True, theme: str | None = None,
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


CODE_STYLES = {
    "dark": {"bg": "#1E1E1E", "text": "#D4D4D4", "label": "#555555", "outline": None},
    "terminal": {"bg": "#0D1117", "text": "#58A6FF", "label": "#8B949E", "outline": None},
    "light": {"bg": "#F6F8FA", "text": "#24292F", "label": "#656D76", "outline": "#D0D7DE"},
    "notebook": {"bg": "#FFFFFF", "text": "#333333", "label": "#6E7781", "outline": "#E1E4E8"},
}

def add_code_slide(
    presentation_id: str, title: str, code: str,
    language: str = "", theme: str | None = None,
    code_style: str = "dark",
) -> dict:
    """Create a slide with a styled code block.

    code_style: "dark" (VS Code), "terminal" (GitHub dark), "light" (GitHub light), "notebook" (Jupyter)
    """
    from .design import LAYOUT, FONTS, FONT_SIZES, get_palette
    from shared.utils import hex_to_rgb
    service = _get_service()
    pal = get_palette(_resolve_theme(presentation_id, theme))
    cs = CODE_STYLES.get(code_style, CODE_STYLES["dark"])
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
    shape_props: dict = {
        "shapeBackgroundFill": {"solidFill": {"color": {"rgbColor": hex_to_rgb(cs["bg"])}}},
        "contentAlignment": "TOP",
    }
    shape_fields = "shapeBackgroundFill,contentAlignment"
    if cs["outline"]:
        shape_props["outline"] = {
            "outlineFill": {"solidFill": {"color": {"rgbColor": hex_to_rgb(cs["outline"])}}},
            "weight": {"magnitude": 1.0, "unit": "PT"},
        }
        shape_fields += ",outline"
    else:
        shape_props["outline"] = {"propertyState": "NOT_RENDERED"}
        shape_fields += ",outline"
    reqs.append({"updateShapeProperties": {
        "objectId": code_bg_id, "shapeProperties": shape_props, "fields": shape_fields,
    }})

    if language:
        lang_id = _new_id()
        lang_pos = {
            "x": code_area["x"] + code_area["w"] - 900_000,
            "y": code_area["y"] + 76_200,
            "w": 800_000, "h": 254_000,
        }
        reqs.extend(_text_box_reqs(lang_id, slide_id, language, lang_pos,
            font=FONTS["mono"], size=9, color=cs["label"], alignment="END"))

    code_id = _new_id()
    pad = 152_400
    code_text_area = {
        "x": code_area["x"] + pad,
        "y": code_area["y"] + pad,
        "w": code_area["w"] - 2 * pad,
        "h": code_area["h"] - 2 * pad,
    }
    reqs.extend(_text_box_reqs(code_id, slide_id, code, code_text_area,
        font=FONTS["mono"], size=13, color=cs["text"],
        alignment="START", line_spacing=130))

    reqs.extend(_polish_reqs(slide_id, pal, presentation_id, service))
    execute_with_retry(service.presentations().batchUpdate(
        presentationId=presentation_id, body={"requests": reqs}))
    return {"slide_id": slide_id, "title": title, "code_style": code_style}


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
    from shared.utils import estimate_text_width_pt
    service = _get_service()
    pres = execute_with_retry(service.presentations().get(presentationId=presentation_id))

    fonts = {}
    sizes = {}
    colors = {}
    tables = []
    overflow_shapes = []
    misaligned_slides = []
    slide_count = len(pres.get("slides", []))

    title_positions = []
    slides_without_title = []
    empty_slides = []
    title_fonts = {}
    title_sizes = {}
    page_num_slides = set()
    footer_slides = set()

    from .design import CANVAS_W, CANVAS_H, CONTENT, EMU_PER_PT
    SHAPE_INSET_EMU = int(0.05 * EMU_PER_INCH)
    TITLE_Y_THRESHOLD = CANVAS_H * 0.40

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
            text_runs: list[tuple[str, float]] = []

            for te in shape.get("text", {}).get("textElements", []):
                tr = te.get("textRun", {})
                content = tr.get("content", "") if tr else ""
                stripped = content.strip()
                if not stripped:
                    continue
                has_content = True
                elem_text += stripped + "\n"
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
                    text_runs.append((stripped, fs))
                    if fs <= 9 and len(stripped) <= 4 and stripped.isdigit():
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

                # Text overflow — check each text run against shape width
                elem_size = elem.get("size", {})
                scale_x = abs(transform.get("scaleX", 1))
                shape_w_emu = elem_size.get("width", {}).get("magnitude", 0) * scale_x
                if shape_w_emu > 0 and text_runs:
                    text_area_w_pt = max(0, (shape_w_emu - 2 * SHAPE_INSET_EMU)) / EMU_PER_PT
                    for run_text, run_font in text_runs:
                        run_w = estimate_text_width_pt(run_text, run_font)
                        if run_w > text_area_w_pt > 0:
                            overflow_shapes.append({
                                "slide": slide_num, "id": obj_id,
                                "text": run_text[:30],
                                "font_pt": int(run_font),
                                "text_w_pt": int(run_w),
                                "shape_w_pt": int(text_area_w_pt),
                            })
                            break

            if table:
                has_content = True
                has_header_bg = False
                first_row = table.get("tableRows", [{}])[0] if table.get("tableRows") else {}
                for cell in first_row.get("tableCells", []):
                    bg = cell.get("tableCellProperties", {}).get("tableCellBackgroundFill", {})
                    if bg.get("solidFill"):
                        has_header_bg = True
                        break
                col_widths = [
                    col.get("columnWidth", {}).get("magnitude", 0)
                    for col in table.get("tableColumns", [])
                ]
                table_w_emu = sum(col_widths) if col_widths else (
                    elem.get("size", {}).get("width", {}).get("magnitude", 0)
                    * abs(transform.get("scaleX", 1))
                )
                width_pct = (table_w_emu / CONTENT["w"] * 100) if CONTENT["w"] else 0
                tables.append({
                    "slide": slide_num,
                    "object_id": obj_id,
                    "rows": table.get("rows", 0),
                    "columns": table.get("columns", 0),
                    "has_styled_header": has_header_bg,
                    "width_pct": round(width_pct),
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

        # Alignment check: find elements at similar Y that aren't exactly aligned
        elem_ys = []
        for elem in slide.get("pageElements", []):
            t = elem.get("transform", {})
            ey = t.get("translateY", 0)
            if ey > 0:
                elem_ys.append(ey)
        if len(elem_ys) >= 3:
            near_threshold = CANVAS_H * 0.03
            exact_threshold = CANVAS_H * 0.002
            elem_ys.sort()
            for i in range(len(elem_ys)):
                for j in range(i + 1, len(elem_ys)):
                    diff = abs(elem_ys[i] - elem_ys[j])
                    if exact_threshold < diff < near_threshold:
                        misaligned_slides.append(slide_num)
                        break
                else:
                    continue
                break

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

    if overflow_shapes:
        overflow_by_slide: dict[int, int] = {}
        for ov in overflow_shapes:
            overflow_by_slide[ov["slide"]] = overflow_by_slide.get(ov["slide"], 0) + 1
        overflow_summary = ", ".join(f"slide {s} ({c} shapes)" for s, c in sorted(overflow_by_slide.items())[:8])
        issues.append(f"Text overflow in {len(overflow_shapes)} shapes: {overflow_summary}")

    if misaligned_slides:
        unique_mis = sorted(set(misaligned_slides))
        if len(unique_mis) <= 5:
            issues.append(f"Near-misaligned elements on slides: {', '.join(str(s) for s in unique_mis)}")
        else:
            issues.append(f"Near-misaligned elements on {len(unique_mis)} slides (first 5: {', '.join(str(s) for s in unique_mis[:5])})")

    narrow_tables = [t for t in tables if t.get("width_pct", 100) < 85]
    if narrow_tables:
        for t in narrow_tables:
            issues.append(f"Slide {t['slide']}: table only {t['width_pct']}% of content width — may look unbalanced")

    return {
        "slides": slide_count,
        "fonts": dict(sorted(fonts.items(), key=lambda x: -x[1])),
        "font_sizes": dict(sorted(sizes.items(), key=lambda x: -x[1])),
        "text_colors": dict(sorted(colors.items(), key=lambda x: -x[1])[:8]),
        "tables": tables,
        "overflow": overflow_shapes[:10] if overflow_shapes else [],
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


def align_elements(
    presentation_id: str, slide_id: str,
    mode: str = "auto",
) -> dict:
    """Align and distribute elements on a slide.

    Modes:
      "auto" — detect rows/columns, snap Y within rows, distribute X evenly
      "align_left" / "align_center" / "align_right" — horizontal alignment
      "align_top" / "align_middle" / "align_bottom" — vertical alignment
      "distribute_h" — equal horizontal spacing
      "distribute_v" — equal vertical spacing
    """
    from .design import CANVAS_H, CANVAS_W
    service = _get_service()
    pres = execute_with_retry(service.presentations().get(presentationId=presentation_id))

    slide = None
    for s in pres.get("slides", []):
        if s["objectId"] == slide_id:
            slide = s
            break
    if not slide:
        return {"error": f"Slide {slide_id} not found"}

    elements = []
    for elem in slide.get("pageElements", []):
        t = elem.get("transform", {})
        s = elem.get("size", {})
        sx = t.get("scaleX", 1)
        sy = t.get("scaleY", 1)
        w = s.get("width", {}).get("magnitude", 0) * abs(sx)
        h = s.get("height", {}).get("magnitude", 0) * abs(sy)
        x = t.get("translateX", 0)
        y = t.get("translateY", 0)
        if w < 50000 or h < 50000:
            continue
        elements.append({
            "id": elem["objectId"], "x": x, "y": y, "w": w, "h": h,
            "cx": x + w / 2, "cy": y + h / 2,
            "transform": t,
        })

    if len(elements) < 2:
        return {"aligned": 0, "mode": mode, "total_elements": len(elements)}

    reqs: list[dict] = []
    adjusted = 0

    if mode == "auto":
        row_tolerance = CANVAS_H * 0.03
        sorted_elems = sorted(elements, key=lambda e: e["cy"])
        rows: list[list] = [[sorted_elems[0]]]
        for e in sorted_elems[1:]:
            if abs(e["cy"] - rows[-1][-1]["cy"]) <= row_tolerance:
                rows[-1].append(e)
            else:
                rows.append([e])

        for row_elems in rows:
            if len(row_elems) < 2:
                continue
            median_y = sorted(e["y"] for e in row_elems)[len(row_elems) // 2]
            for e in row_elems:
                if abs(e["y"] - median_y) > 1000:
                    new_t = dict(e["transform"])
                    new_t["translateY"] = median_y
                    reqs.append({"updatePageElementTransform": {
                        "objectId": e["id"],
                        "transform": {**new_t, "unit": "EMU"},
                        "applyMode": "ABSOLUTE",
                    }})
                    adjusted += 1

            row_elems.sort(key=lambda e: e["x"])
            if len(row_elems) >= 3:
                left = row_elems[0]["x"]
                right = row_elems[-1]["x"] + row_elems[-1]["w"]
                total_elem_w = sum(e["w"] for e in row_elems)
                total_gap = (right - left) - total_elem_w
                if total_gap > 0:
                    gap = total_gap / (len(row_elems) - 1)
                    cx = left
                    for e in row_elems:
                        if abs(e["x"] - cx) > 5000:
                            new_t = dict(e["transform"])
                            new_t["translateX"] = cx
                            reqs.append({"updatePageElementTransform": {
                                "objectId": e["id"],
                                "transform": {**new_t, "unit": "EMU"},
                                "applyMode": "ABSOLUTE",
                            }})
                            adjusted += 1
                        cx += e["w"] + gap

    elif mode.startswith("align_"):
        direction = mode.split("_", 1)[1]
        if direction == "left":
            target = min(e["x"] for e in elements)
            for e in elements:
                if abs(e["x"] - target) > 1000:
                    new_t = dict(e["transform"])
                    new_t["translateX"] = target
                    reqs.append({"updatePageElementTransform": {
                        "objectId": e["id"],
                        "transform": {**new_t, "unit": "EMU"},
                        "applyMode": "ABSOLUTE",
                    }})
                    adjusted += 1
        elif direction == "center":
            target_cx = sum(e["cx"] for e in elements) / len(elements)
            for e in elements:
                new_x = target_cx - e["w"] / 2
                if abs(e["x"] - new_x) > 1000:
                    new_t = dict(e["transform"])
                    new_t["translateX"] = new_x
                    reqs.append({"updatePageElementTransform": {
                        "objectId": e["id"],
                        "transform": {**new_t, "unit": "EMU"},
                        "applyMode": "ABSOLUTE",
                    }})
                    adjusted += 1
        elif direction == "right":
            target_r = max(e["x"] + e["w"] for e in elements)
            for e in elements:
                new_x = target_r - e["w"]
                if abs(e["x"] - new_x) > 1000:
                    new_t = dict(e["transform"])
                    new_t["translateX"] = new_x
                    reqs.append({"updatePageElementTransform": {
                        "objectId": e["id"],
                        "transform": {**new_t, "unit": "EMU"},
                        "applyMode": "ABSOLUTE",
                    }})
                    adjusted += 1
        elif direction == "top":
            target = min(e["y"] for e in elements)
            for e in elements:
                if abs(e["y"] - target) > 1000:
                    new_t = dict(e["transform"])
                    new_t["translateY"] = target
                    reqs.append({"updatePageElementTransform": {
                        "objectId": e["id"],
                        "transform": {**new_t, "unit": "EMU"},
                        "applyMode": "ABSOLUTE",
                    }})
                    adjusted += 1
        elif direction == "middle":
            target_cy = sum(e["cy"] for e in elements) / len(elements)
            for e in elements:
                new_y = target_cy - e["h"] / 2
                if abs(e["y"] - new_y) > 1000:
                    new_t = dict(e["transform"])
                    new_t["translateY"] = new_y
                    reqs.append({"updatePageElementTransform": {
                        "objectId": e["id"],
                        "transform": {**new_t, "unit": "EMU"},
                        "applyMode": "ABSOLUTE",
                    }})
                    adjusted += 1
        elif direction == "bottom":
            target_b = max(e["y"] + e["h"] for e in elements)
            for e in elements:
                new_y = target_b - e["h"]
                if abs(e["y"] - new_y) > 1000:
                    new_t = dict(e["transform"])
                    new_t["translateY"] = new_y
                    reqs.append({"updatePageElementTransform": {
                        "objectId": e["id"],
                        "transform": {**new_t, "unit": "EMU"},
                        "applyMode": "ABSOLUTE",
                    }})
                    adjusted += 1

    elif mode == "distribute_h":
        elements.sort(key=lambda e: e["x"])
        if len(elements) >= 3:
            left = elements[0]["x"]
            right = elements[-1]["x"] + elements[-1]["w"]
            total_w = sum(e["w"] for e in elements)
            gap = ((right - left) - total_w) / (len(elements) - 1)
            cx = left
            for e in elements:
                if abs(e["x"] - cx) > 5000:
                    new_t = dict(e["transform"])
                    new_t["translateX"] = cx
                    reqs.append({"updatePageElementTransform": {
                        "objectId": e["id"],
                        "transform": {**new_t, "unit": "EMU"},
                        "applyMode": "ABSOLUTE",
                    }})
                    adjusted += 1
                cx += e["w"] + gap

    elif mode == "distribute_v":
        elements.sort(key=lambda e: e["y"])
        if len(elements) >= 3:
            top = elements[0]["y"]
            bottom = elements[-1]["y"] + elements[-1]["h"]
            total_h = sum(e["h"] for e in elements)
            gap = ((bottom - top) - total_h) / (len(elements) - 1)
            cy = top
            for e in elements:
                if abs(e["y"] - cy) > 5000:
                    new_t = dict(e["transform"])
                    new_t["translateY"] = cy
                    reqs.append({"updatePageElementTransform": {
                        "objectId": e["id"],
                        "transform": {**new_t, "unit": "EMU"},
                        "applyMode": "ABSOLUTE",
                    }})
                    adjusted += 1
                cy += e["h"] + gap

    if reqs:
        execute_with_retry(service.presentations().batchUpdate(
            presentationId=presentation_id, body={"requests": reqs}))

    return {"aligned": adjusted, "mode": mode, "total_elements": len(elements)}


def get_image_url(presentation_id: str, element_id: str) -> dict:
    """Extract the image URL from an image element or shape with image fill."""
    service = _get_service()
    pres = execute_with_retry(service.presentations().get(presentationId=presentation_id))
    for slide in pres.get("slides", []):
        for elem in slide.get("pageElements", []):
            if elem["objectId"] != element_id:
                continue
            result: dict = {"element_id": element_id}
            img = elem.get("image", {})
            if img:
                if img.get("sourceUrl"):
                    result["source_url"] = img["sourceUrl"]
                if img.get("contentUrl"):
                    result["content_url"] = img["contentUrl"]
                    result["content_url_note"] = "Temporary (30 min). Use source_url for permanence."
                s = elem.get("size", {})
                result["width_emu"] = s.get("width", {}).get("magnitude", 0)
                result["height_emu"] = s.get("height", {}).get("magnitude", 0)
                return result
            shape = elem.get("shape", {})
            bg = shape.get("shapeProperties", {}).get("shapeBackgroundFill", {})
            fill = bg.get("stretchedPictureFill", {})
            if fill.get("contentUrl"):
                result["content_url"] = fill["contentUrl"]
                result["content_url_note"] = "Temporary (30 min). Re-host for permanence."
                return result
            return {"error": f"Element {element_id} is not an image"}
    return {"error": f"Element {element_id} not found"}


def _read_element(pres: dict, element_id: str) -> dict | None:
    """Find a PageElement by ID across all slides in a presentation."""
    for slide in pres.get("slides", []):
        for elem in slide.get("pageElements", []):
            if elem["objectId"] == element_id:
                return elem
    return None


def _recreate_element(
    elem: dict, slide_id: str, offset_x: int = 0, offset_y: int = 0,
) -> list[dict]:
    """Build API requests to recreate a PageElement on a target slide."""
    from shared.utils import hex_to_rgb
    reqs: list[dict] = []
    new_id = _new_id()
    t = elem.get("transform", {})
    s = elem.get("size", {})

    tx = t.get("translateX", 0) + offset_x
    ty = t.get("translateY", 0) + offset_y

    base_transform = {
        "scaleX": t.get("scaleX", 1), "scaleY": t.get("scaleY", 1),
        "shearX": t.get("shearX", 0), "shearY": t.get("shearY", 0),
        "translateX": tx, "translateY": ty, "unit": "EMU",
    }
    base_size = {
        "width": s.get("width", {"magnitude": 914400, "unit": "EMU"}),
        "height": s.get("height", {"magnitude": 914400, "unit": "EMU"}),
    }

    img = elem.get("image", {})
    shape = elem.get("shape", {})
    line = elem.get("line", {})
    table = elem.get("table", {})

    if img:
        url = img.get("sourceUrl") or img.get("contentUrl", "")
        if url:
            reqs.append({"createImage": {
                "objectId": new_id, "url": url,
                "elementProperties": {
                    "pageObjectId": slide_id,
                    "size": base_size,
                    "transform": base_transform,
                },
            }})
    elif shape:
        shape_type = shape.get("shapeType", "RECTANGLE")
        if shape_type == "TEXT_BOX":
            reqs.append({"createShape": {
                "objectId": new_id, "shapeType": "TEXT_BOX",
                "elementProperties": {
                    "pageObjectId": slide_id,
                    "size": base_size, "transform": base_transform,
                },
            }})
        else:
            reqs.append({"createShape": {
                "objectId": new_id, "shapeType": shape_type,
                "elementProperties": {
                    "pageObjectId": slide_id,
                    "size": base_size, "transform": base_transform,
                },
            }})

        sp = shape.get("shapeProperties", {})
        props: dict = {}
        fields: list[str] = []

        bg_fill = sp.get("shapeBackgroundFill", {})
        if bg_fill.get("solidFill"):
            props["shapeBackgroundFill"] = bg_fill
            fields.append("shapeBackgroundFill")
        elif bg_fill.get("propertyState") == "NOT_RENDERED":
            props["shapeBackgroundFill"] = {"propertyState": "NOT_RENDERED"}
            fields.append("shapeBackgroundFill")

        outline = sp.get("outline", {})
        if outline:
            props["outline"] = outline
            fields.append("outline")

        ca = sp.get("contentAlignment")
        if ca:
            props["contentAlignment"] = ca
            fields.append("contentAlignment")

        if fields:
            reqs.append({"updateShapeProperties": {
                "objectId": new_id, "shapeProperties": props,
                "fields": ",".join(fields),
            }})

        text_content = shape.get("text", {})
        full_text = ""
        for te in text_content.get("textElements", []):
            tr = te.get("textRun", {})
            if tr.get("content"):
                full_text += tr["content"]
        if full_text.rstrip("\n"):
            reqs.append({"insertText": {"objectId": new_id, "text": full_text.rstrip("\n")}})

            for te in text_content.get("textElements", []):
                tr = te.get("textRun", {})
                if not tr.get("content"):
                    continue
                ts = tr.get("style", {})
                start = te.get("startIndex", 0)
                end = te.get("endIndex", start + len(tr["content"]))
                style_update: dict = {}
                style_fields: list[str] = []
                if ts.get("fontFamily"):
                    style_update["fontFamily"] = ts["fontFamily"]
                    style_fields.append("fontFamily")
                if ts.get("fontSize"):
                    style_update["fontSize"] = ts["fontSize"]
                    style_fields.append("fontSize")
                if ts.get("bold") is not None:
                    style_update["bold"] = ts["bold"]
                    style_fields.append("bold")
                if ts.get("italic") is not None:
                    style_update["italic"] = ts["italic"]
                    style_fields.append("italic")
                fg = ts.get("foregroundColor")
                if fg:
                    style_update["foregroundColor"] = fg
                    style_fields.append("foregroundColor")
                if style_fields:
                    reqs.append({"updateTextStyle": {
                        "objectId": new_id,
                        "style": style_update,
                        "textRange": {"type": "FIXED_RANGE", "startIndex": start, "endIndex": end},
                        "fields": ",".join(style_fields),
                    }})

            for te in text_content.get("textElements", []):
                pp = te.get("paragraphMarker", {})
                ps = pp.get("style", {})
                if ps.get("alignment"):
                    idx = te.get("startIndex", 0)
                    reqs.append({"updateParagraphStyle": {
                        "objectId": new_id,
                        "style": {"alignment": ps["alignment"]},
                        "textRange": {"type": "FIXED_RANGE", "startIndex": idx, "endIndex": idx + 1},
                        "fields": "alignment",
                    }})

    elif line:
        line_type = line.get("lineCategory", line.get("lineType", "STRAIGHT_CONNECTOR_1"))
        category = "STRAIGHT"
        if "CURVE" in str(line_type).upper():
            category = "CURVED"
        elif "BENT" in str(line_type).upper():
            category = "BENT"
        reqs.append({"createLine": {
            "objectId": new_id, "category": category,
            "elementProperties": {
                "pageObjectId": slide_id,
                "size": base_size, "transform": base_transform,
            },
        }})
        lp = line.get("lineProperties", {})
        if lp:
            lp_clean = {k: v for k, v in lp.items() if k not in ("startConnection", "endConnection")}
            if lp_clean:
                reqs.append({"updateLineProperties": {
                    "objectId": new_id, "lineProperties": lp_clean,
                    "fields": ",".join(lp_clean.keys()),
                }})

    return reqs


def clone_slide(
    source_presentation_id: str, source_slide_id: str,
    target_presentation_id: str | None = None, position: int = -1,
) -> dict:
    """Clone a slide. Same-deck uses native duplicate. Cross-deck recreates elements."""
    service = _get_service()

    if not target_presentation_id or target_presentation_id == source_presentation_id:
        new_id = _new_id()
        reqs = [{"duplicateObject": {
            "objectId": source_slide_id,
            "objectIds": {source_slide_id: new_id},
        }}]
        if position >= 0:
            reqs.append({"updateSlidesPosition": {
                "slideObjectIds": [new_id], "insertionIndex": position,
            }})
        execute_with_retry(service.presentations().batchUpdate(
            presentationId=source_presentation_id, body={"requests": reqs}))
        return {"slide_id": new_id, "method": "duplicate", "presentation_id": source_presentation_id}

    source_pres = execute_with_retry(service.presentations().get(presentationId=source_presentation_id))
    source_slide = None
    for slide in source_pres.get("slides", []):
        if slide["objectId"] == source_slide_id:
            source_slide = slide
            break
    if not source_slide:
        return {"error": f"Slide {source_slide_id} not found in source presentation"}

    new_slide_id = _new_id()
    create_reqs: list[dict] = [{"createSlide": {
        "objectId": new_slide_id,
        "slideLayoutReference": {"predefinedLayout": "BLANK"},
    }}]
    if position >= 0:
        create_reqs.append({"updateSlidesPosition": {
            "slideObjectIds": [new_slide_id], "insertionIndex": position,
        }})

    bg = source_slide.get("slideProperties", {}).get("pageBackgroundFill", {})
    if bg.get("solidFill"):
        create_reqs.append({"updatePageProperties": {
            "objectId": new_slide_id,
            "pageProperties": {"pageBackgroundFill": bg},
            "fields": "pageBackgroundFill",
        }})

    execute_with_retry(service.presentations().batchUpdate(
        presentationId=target_presentation_id, body={"requests": create_reqs}))

    elem_reqs: list[dict] = []
    for elem in source_slide.get("pageElements", []):
        elem_reqs.extend(_recreate_element(elem, new_slide_id))

    if elem_reqs:
        for i in range(0, len(elem_reqs), 50):
            batch = elem_reqs[i:i + 50]
            execute_with_retry(service.presentations().batchUpdate(
                presentationId=target_presentation_id, body={"requests": batch}))

    element_count = len(source_slide.get("pageElements", []))
    return {
        "slide_id": new_slide_id, "method": "recreate",
        "elements_copied": element_count,
        "presentation_id": target_presentation_id,
    }


def copy_element(
    source_presentation_id: str, element_id: str,
    target_presentation_id: str, target_slide_id: str,
    x: float | None = None, y: float | None = None,
) -> dict:
    """Copy a specific element from one presentation to another at optional x/y (inches)."""
    service = _get_service()
    source_pres = execute_with_retry(service.presentations().get(presentationId=source_presentation_id))
    elem = _read_element(source_pres, element_id)
    if not elem:
        return {"error": f"Element {element_id} not found"}

    offset_x = 0
    offset_y = 0
    if x is not None:
        orig_x = elem.get("transform", {}).get("translateX", 0)
        offset_x = _inches(x) - orig_x
    if y is not None:
        orig_y = elem.get("transform", {}).get("translateY", 0)
        offset_y = _inches(y) - orig_y

    reqs = _recreate_element(elem, target_slide_id, offset_x, offset_y)
    if not reqs:
        return {"error": f"Element {element_id} type not supported for copy"}

    execute_with_retry(service.presentations().batchUpdate(
        presentationId=target_presentation_id, body={"requests": reqs}))
    return {"copied": element_id, "to_slide": target_slide_id, "requests": len(reqs)}


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


def parse_video_url(url: str) -> tuple[str, str]:
    """Extract video ID and source from a YouTube or Google Drive URL.

    Returns (video_id, source) where source is 'YOUTUBE' or 'DRIVE'.
    Raises ValueError if the URL cannot be parsed.
    """
    import re

    # YouTube patterns
    yt_patterns = [
        r'(?:youtube\.com/watch\?.*v=|youtu\.be/|youtube\.com/embed/|youtube\.com/v/)([a-zA-Z0-9_-]{11})',
    ]
    for pattern in yt_patterns:
        m = re.search(pattern, url)
        if m:
            return m.group(1), "YOUTUBE"

    # Google Drive patterns: drive.google.com/file/d/FILE_ID/...
    drive_pattern = r'drive\.google\.com/file/d/([a-zA-Z0-9_-]+)'
    m = re.search(drive_pattern, url)
    if m:
        return m.group(1), "DRIVE"

    raise ValueError(f"Cannot parse video URL: {url}. Provide a YouTube or Google Drive URL, or use video_id directly.")


def create_video(
    presentation_id: str,
    slide_id: str,
    video_id: str,
    source: str = "YOUTUBE",
) -> dict:
    """Embed a YouTube or Google Drive video on a slide.

    Centers the video on the slide at 60% of canvas width.
    """
    from .design import CANVAS_W, CANVAS_H

    service = _get_service()

    # Size: 60% of canvas width, 16:9 aspect ratio
    video_w = int(CANVAS_W * 0.6)
    video_h = int(video_w * 9 / 16)

    # Center on slide
    x = (CANVAS_W - video_w) // 2
    y = (CANVAS_H - video_h) // 2

    vid_obj_id = _new_id()
    reqs = [{
        "createVideo": {
            "objectId": vid_obj_id,
            "source": source.upper(),
            "id": video_id,
            "elementProperties": {
                "pageObjectId": slide_id,
                "size": _emu_size(video_w, video_h),
                "transform": _emu_transform(x, y),
            },
        }
    }]

    execute_with_retry(service.presentations().batchUpdate(
        presentationId=presentation_id, body={"requests": reqs}))

    return {"slide_id": slide_id, "video_id": vid_obj_id}
