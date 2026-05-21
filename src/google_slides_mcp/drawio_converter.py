"""Convert draw.io mxGraph XML to Google Slides API requests.

Proportional scaling with accurate text fitting based on Google Slides'
actual shape padding (0.05" per side) and font metrics.
Canvas: 10" × 5.625" (914400 EMU/inch).
"""

from __future__ import annotations

import re
import json
import uuid
import xml.etree.ElementTree as ET

from shared.utils import hex_to_rgb, estimate_text_width_pt, estimate_text_height_pt

EMU_PER_INCH = 914400
SLIDE_W_IN = 10.0
SLIDE_H_IN = 5.625

# Google Slides shape internal text padding (default, per side)
SHAPE_INSET = 0.05  # inches — 3.6pt per side

# Content area matching design.py (TITLE_ONLY layout)
MARGIN_LR = 0.75   # left/right margins
MARGIN_TB = 0.35    # top/bottom margins for diagram
TITLE_RESERVE = 1.0 # space reserved for TITLE_ONLY placeholder

MIN_FONT_PT = 6
MAX_FONT_PT = 14

SHAPE_MAP = {
    "": "ROUND_RECTANGLE", "rhombus": "DIAMOND", "ellipse": "ELLIPSE",
    "cylinder3": "CAN", "hexagon": "HEXAGON", "parallelogram": "PARALLELOGRAM",
    "cloud": "CLOUD", "process": "FLOW_CHART_PROCESS", "cube": "CUBE",
    "document": "FLOW_CHART_DOCUMENT", "step": "CHEVRON", "triangle": "TRIANGLE",
    "mxgraph.flowchart.document": "FLOW_CHART_DOCUMENT",
    "mxgraph.flowchart.decision": "FLOW_CHART_DECISION",
    "mxgraph.flowchart.terminator": "FLOW_CHART_TERMINATOR",
}


def _parse_style(s: str) -> dict:
    d = {}
    for p in (s or "").split(";"):
        p = p.strip()
        if not p: continue
        if "=" in p:
            k, v = p.split("=", 1)
            d[k.strip()] = v.strip()
        else:
            d[p] = True
    return d


def _clean(val: str | None) -> str:
    if not val: return ""
    t = val.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    t = t.replace("&quot;", '"').replace("&#xa;", "\n").replace("&nbsp;", " ")
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.IGNORECASE)
    t = re.sub(r"<[^>]+>", "", t)
    t = t.replace("\\n", "\n")
    return t.strip()


def _shape_type(style: dict) -> str:
    shape = str(style.get("shape", ""))
    for k, v in SHAPE_MAP.items():
        if k and k in shape: return v
    if shape in SHAPE_MAP: return SHAPE_MAP[shape]
    if style.get("ellipse"): return "ELLIPSE"
    if style.get("rhombus"): return "DIAMOND"
    if style.get("rounded"): return "ROUND_RECTANGLE"
    return "ROUND_RECTANGLE"


def _color(c: str | None, default: str = "#666666") -> str:
    if not c or c in ("default", ""): return default
    if c == "none": return "none"
    c = c.strip()
    if not c.startswith("#"): return default
    return c


def _id() -> str:
    return "g" + uuid.uuid4().hex[:12]


def validate_drawio_xml(xml_content: str) -> str:
    content = xml_content.strip()
    for _ in range(4):
        if content.startswith("{") and content.endswith("}"):
            try:
                parsed = json.loads(content)
                if isinstance(parsed, dict):
                    content = str(parsed.get("text", parsed.get("content", parsed.get("xml", ""))))
                    content = content.strip()
                    continue
            except (json.JSONDecodeError, TypeError, AttributeError):
                pass
            break
        else: break

    if not content:
        raise ValueError("Empty XML content")
    if "<mxGraphModel" not in content and "<mxCell" not in content and "<mxfile" not in content:
        raise ValueError("Not valid draw.io XML")
    if "<mxGraphModel" not in content and "<mxfile" not in content:
        content = f'<mxGraphModel><root>{content}</root></mxGraphModel>'

    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        raise ValueError(f"Malformed XML: {e}")

    if root.tag == "mxfile":
        diagrams = root.findall(".//diagram")
        if not diagrams:
            raise ValueError("No diagram in mxfile")
        model = diagrams[0].find(".//mxGraphModel")
        if model is None:
            raise ValueError("No mxGraphModel found")
        root = model
        content = ET.tostring(root, encoding="unicode")

    for cell in root.findall(".//mxCell"):
        if cell.get("edge") == "1" and cell.find("mxGeometry") is None:
            geo = ET.SubElement(cell, "mxGeometry")
            geo.set("relative", "1")
            geo.set("as", "geometry")

    return ET.tostring(root, encoding="unicode")


def drawio_xml_to_slides_requests(
    xml_content: str,
    slide_id: str,
    title: str = "",
) -> tuple[list[dict], dict[str, str]]:
    xml_content = validate_drawio_xml(xml_content)
    root = ET.fromstring(xml_content)
    cells = root.findall(".//mxCell")

    # Find structural IDs (root cells and layer cells)
    structural = set()
    for c in cells:
        if not c.get("parent"):
            structural.add(c.get("id", ""))
    for c in cells:
        if c.get("parent") in structural and not c.get("vertex") and not c.get("edge"):
            structural.add(c.get("id", ""))

    # Parse all vertices and edges
    all_v = []
    edges = []
    for c in cells:
        cid = c.get("id", "")
        if cid in structural: continue

        if c.get("vertex") == "1":
            geo = c.find("mxGeometry")
            if geo is None: continue
            w = float(geo.get("width", "0"))
            h = float(geo.get("height", "0"))
            if w == 0 and h == 0: continue
            all_v.append({
                "id": cid, "label": _clean(c.get("value")),
                "x": float(geo.get("x", "0")), "y": float(geo.get("y", "0")),
                "w": max(w, 1), "h": max(h, 1),
                "parent": c.get("parent", ""),
                "style": _parse_style(c.get("style", "")),
                "style_str": c.get("style", ""),
            })
        elif c.get("edge") == "1":
            edges.append({
                "id": cid, "source": c.get("source", ""), "target": c.get("target", ""),
                "style": _parse_style(c.get("style", "")),
            })

    if not all_v: return [], {}

    # Resolve absolute positions (children → parent coords)
    id_map = {v["id"]: v for v in all_v}
    resolved = set()

    def resolve(v):
        if v["id"] in resolved: return
        resolved.add(v["id"])
        pid = v["parent"]
        if pid not in structural and pid in id_map:
            p = id_map[pid]
            resolve(p)
            v["x"] += p["x"]
            v["y"] += p["y"]
            if p["style"].get("swimlane"):
                v["y"] += float(p["style"].get("startSize", "30"))

    for v in all_v:
        resolve(v)

    # Filter out non-renderable shapes
    max_w = max(v["w"] for v in all_v)
    max_h = max(v["h"] for v in all_v)
    vertices = []
    for v in all_v:
        if v["w"] > max_w * 0.5 and v["h"] > max_h * 0.5 and not v["label"]:
            continue
        if ("image" in v["style_str"][:15] or v["style"].get("image")) and not v["label"]:
            continue
        if not v["label"] and v["style"].get("strokeColor") == "none" and v["style"].get("fillColor") == "none":
            continue
        vertices.append(v)

    if not vertices: return [], {}

    # Detect labeled containers — shapes whose label overlaps children
    _container_ids: set[str] = set()
    for v in vertices:
        if not v["label"]:
            continue
        for other in vertices:
            if other["id"] == v["id"]:
                continue
            if (other["x"] >= v["x"] and other["y"] >= v["y"] and
                other["x"] + other["w"] <= v["x"] + v["w"] and
                other["y"] + other["h"] <= v["y"] + v["h"]):
                _container_ids.add(v["id"])
                break

    # Bounding box of all vertices
    min_x = min(v["x"] for v in vertices)
    min_y = min(v["y"] for v in vertices)
    max_r = max(v["x"] + v["w"] for v in vertices)
    max_b = max(v["y"] + v["h"] for v in vertices)
    dw = max_r - min_x
    dh = max_b - min_y
    if dw == 0 or dh == 0: return [], {}

    # Scale to fit content area (matching design.py layout)
    title_offset = TITLE_RESERVE if title else 0.0
    usable_w = SLIDE_W_IN - 2 * MARGIN_LR
    usable_h = SLIDE_H_IN - MARGIN_TB - title_offset - MARGIN_TB
    scale = min(usable_w / dw, usable_h / dh)

    # Center the diagram in the content area
    scaled_w = dw * scale
    scaled_h = dh * scale
    ox = (SLIDE_W_IN - scaled_w) / 2
    oy = MARGIN_TB + title_offset + (usable_h - scaled_h) / 2

    def emu(inches: float) -> int:
        return int(inches * EMU_PER_INCH)

    def px(val: float) -> int:
        return emu(val * scale)

    def pos_x(x: float) -> int:
        return emu((x - min_x) * scale + ox)

    def pos_y(y: float) -> int:
        return emu((y - min_y) * scale + oy)

    def fit_font(label: str, shape_w_in: float, shape_h_in: float) -> int:
        """Binary search for largest font where text fits inside shape padding."""
        if not label: return 10
        avail_w = max(0.1, (shape_w_in - 2 * SHAPE_INSET)) * 72
        avail_h = max(0.1, (shape_h_in - 2 * SHAPE_INSET)) * 72
        best = MIN_FONT_PT
        for candidate in range(MAX_FONT_PT, MIN_FONT_PT - 1, -1):
            tw = estimate_text_width_pt(label, candidate)
            th = estimate_text_height_pt(label, candidate)
            if tw <= avail_w and th <= avail_h:
                best = candidate
                break
        return best

    requests: list[dict] = []
    node_map: dict[str, str] = {}

    # Sort: largest shapes first (containers behind), smallest last (foreground)
    vertices.sort(key=lambda v: -(v["w"] * v["h"]))

    for v in vertices:
        sid = _id()
        node_map[v["id"]] = sid
        st = v["style"]

        is_text = st.get("text") is True or "text;" in v["style_str"][:10]
        is_image = "image" in v["style_str"][:15] or st.get("image")
        stype = "ROUND_RECTANGLE" if is_image else _shape_type(st)

        raw_fill = st.get("fillColor", "")
        raw_stroke = st.get("strokeColor", "")
        fill = _color(raw_fill, "#FFFFFF")
        stroke = _color(raw_stroke, "#999999")
        fcol = _color(st.get("fontColor"), "#333333")
        orig_font = int(float(st.get("fontSize", "10") or "10"))
        is_dashed = st.get("dashed") == "1"
        is_bold = st.get("fontStyle", "0") in ("1", "3", "5", "7")
        is_container = not v["label"] and v["w"] > 200 and v["h"] > 200

        w_in = v["w"] * scale
        h_in = v["h"] * scale
        raw_sw = float(st.get("strokeWidth", "1.5"))
        stroke_w = max(0.5, min(raw_sw * scale * 30, 3.0))

        # Create shape
        requests.append({
            "createShape": {
                "objectId": sid, "shapeType": stype,
                "elementProperties": {
                    "pageObjectId": slide_id,
                    "size": {"width": {"magnitude": px(v["w"]), "unit": "EMU"},
                             "height": {"magnitude": px(v["h"]), "unit": "EMU"}},
                    "transform": {"scaleX": 1, "scaleY": 1,
                                  "translateX": pos_x(v["x"]), "translateY": pos_y(v["y"]), "unit": "EMU"},
                },
            }
        })

        # Vertical alignment
        va = st.get("verticalAlign", "middle")
        v_align = {"top": "TOP", "bottom": "BOTTOM"}.get(va, "MIDDLE")
        if v["id"] in _container_ids:
            v_align = "TOP"

        props: dict = {"contentAlignment": v_align}
        flds = ["contentAlignment"]

        # Fill — transparent for containers, white, text-style, or "none"
        no_fill = (is_container or is_text or fill == "none"
                   or fill in ("#FFFFFF", "#ffffff"))
        if no_fill:
            props["shapeBackgroundFill"] = {"propertyState": "NOT_RENDERED"}
        else:
            alpha = float(st.get("opacity", "100")) / 100.0
            props["shapeBackgroundFill"] = {"solidFill": {"color": {"rgbColor": hex_to_rgb(fill)}, "alpha": alpha}}
        flds.append("shapeBackgroundFill")

        # Outline — hide for text-style shapes or "none" stroke
        if is_text or stroke == "none":
            props["outline"] = {"propertyState": "NOT_RENDERED"}
        else:
            props["outline"] = {
                "outlineFill": {"solidFill": {"color": {"rgbColor": hex_to_rgb(stroke)}, "alpha": 1.0}},
                "weight": {"magnitude": stroke_w, "unit": "PT"},
                **({"dashStyle": "DASH"} if is_dashed else {}),
            }
        flds.append("outline")

        requests.append({
            "updateShapeProperties": {
                "objectId": sid, "shapeProperties": props, "fields": ",".join(flds),
            }
        })

        # Text — font size calculated to fit within shape padding
        if v["label"]:
            requests.append({"insertText": {"objectId": sid, "text": v["label"]}})
            fpt = fit_font(v["label"], w_in, h_in)
            requests.append({
                "updateTextStyle": {
                    "objectId": sid,
                    "style": {
                        "fontSize": {"magnitude": fpt, "unit": "PT"},
                        "foregroundColor": {"opaqueColor": {"rgbColor": hex_to_rgb(fcol)}},
                        "bold": is_bold,
                    },
                    "textRange": {"type": "ALL"},
                    "fields": "fontSize,foregroundColor,bold",
                }
            })
            requests.append({
                "updateParagraphStyle": {
                    "objectId": sid, "style": {"alignment": "CENTER"},
                    "textRange": {"type": "ALL"}, "fields": "alignment",
                }
            })

    # Edges → connectors with auto-routing
    for edge in edges:
        src, tgt = edge["source"], edge["target"]
        if src not in node_map or tgt not in node_map: continue

        lid = _id()
        est = edge["style"]

        estroke = _color(est.get("strokeColor"), "#666666")
        if estroke == "none": estroke = "#666666"
        earrow = "NONE" if est.get("endArrow") == "none" else "FILL_ARROW"
        edash = est.get("dashed") == "1"
        ew = max(0.75, min(float(est.get("strokeWidth", "1")), 2.0))

        requests.append({
            "createLine": {
                "objectId": lid, "category": "CURVED",
                "elementProperties": {
                    "pageObjectId": slide_id,
                    "size": {"width": {"magnitude": 1, "unit": "EMU"}, "height": {"magnitude": 1, "unit": "EMU"}},
                    "transform": {"scaleX": 1, "scaleY": 1, "translateX": 0, "translateY": 0, "unit": "EMU"},
                },
            }
        })
        requests.append({
            "updateLineProperties": {
                "objectId": lid,
                "lineProperties": {
                    "startConnection": {"connectedObjectId": node_map[src], "connectionSiteIndex": 0},
                    "endConnection": {"connectedObjectId": node_map[tgt], "connectionSiteIndex": 0},
                },
                "fields": "startConnection,endConnection",
            }
        })
        requests.append({"rerouteLine": {"objectId": lid}})

        lp: dict = {
            "lineFill": {"solidFill": {"color": {"rgbColor": hex_to_rgb(estroke)}, "alpha": 1.0}},
            "weight": {"magnitude": ew, "unit": "PT"},
            "endArrow": earrow,
        }
        lf = "lineFill,weight,endArrow"
        if edash:
            lp["dashStyle"] = "DASH"
            lf += ",dashStyle"
        requests.append({"updateLineProperties": {"objectId": lid, "lineProperties": lp, "fields": lf}})

    return requests, node_map
