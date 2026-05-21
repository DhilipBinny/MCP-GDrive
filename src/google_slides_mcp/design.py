"""Slide design system — typography, colors, layouts, spacing.

Professional presentation constants based on McKinsey/Google/Apple standards.
Canvas: 9,144,000 x 5,143,500 EMU (720 x 405 pt, 10 x 5.625 inches).
1 inch = 914,400 EMU. 1 pt = 12,700 EMU.
"""

EMU_PER_PT = 12700
EMU_PER_INCH = 914400

CANVAS_W = 9_144_000   # 10 inches
CANVAS_H = 5_143_500   # 5.625 inches

# ── Margins ────────────────────────────────────────────────────────

MARGIN = {
    "top": 457_200,       # 0.5"
    "bottom": 457_200,    # 0.5"
    "left": 685_800,      # 0.75"
    "right": 685_800,     # 0.75"
}

CONTENT = {
    "x": MARGIN["left"],
    "y": MARGIN["top"],
    "w": CANVAS_W - MARGIN["left"] - MARGIN["right"],   # 7,772,400 (8.5")
    "h": CANVAS_H - MARGIN["top"] - MARGIN["bottom"],   # 4,229,100 (4.625")
}

GUTTER = 228_600  # 0.25" between columns/elements


# ── Typography ───────────────────────────────────────────────────

FONTS = {
    "heading": "Montserrat",
    "body": "Open Sans",
    "mono": "Roboto Mono",
}

FONT_SIZES = {
    "slide_title": 26,
    "subtitle": 18,
    "section_title": 36,
    "body": 16,
    "sub_bullet": 14,
    "caption": 11,
    "table_header": 14,
    "table_value": 13,
    "metric_number": 48,
    "metric_label": 14,
    "page_number": 9,
    "source": 9,
    "quote": 22,
    "attribution": 14,
    "author": 13,
    "code": 12,
}

LINE_SPACING = {
    "title": 110,
    "body": 125,
    "bullet": 120,
    "table": 115,
}

LIMITS = {
    "max_bullets_per_slide": 6,
    "max_words_per_bullet": 8,
    "max_words_per_slide": 40,
    "max_table_rows": 8,
    "max_table_cols": 6,
    "max_fonts_per_deck": 2,
    "whitespace_target_pct": 45,
}


# ── Colors ───────────────────────────────────────────────────────

PALETTES = {
    "modern": {
        "background": "#FFFFFF",
        "surface": "#F8F9FA",
        "primary_text": "#202124",
        "secondary_text": "#5F6368",
        "accent": "#1A73E8",
        "accent_secondary": "#34A853",
        "accent_warn": "#FBBC04",
        "accent_danger": "#EA4335",
        "white": "#FFFFFF",
        "table_header_bg": "#1A73E8",
        "table_alt_row": "#F5F5F5",
        "table_border": "#E0E0E0",
        "divider": "#E0E0E0",
        "page_number": "#999999",
        "diagram_series": ["#1A73E8", "#34A853", "#FBBC04", "#EA4335", "#5F6368", "#0A84FF"],
    },
    "corporate": {
        "background": "#FFFFFF",
        "surface": "#F4F6F9",
        "primary_text": "#1B2A4A",
        "secondary_text": "#5F6B7A",
        "accent": "#2B5797",
        "accent_secondary": "#E8792F",
        "accent_warn": "#D4A843",
        "accent_danger": "#C0392B",
        "white": "#FFFFFF",
        "table_header_bg": "#2B5797",
        "table_alt_row": "#F5F5F5",
        "table_border": "#D0D5DD",
        "divider": "#D0D5DD",
        "page_number": "#999999",
        "diagram_series": ["#2B5797", "#E8792F", "#D4A843", "#5F6B7A", "#1B2A4A", "#4A90C4"],
    },
    "dark": {
        "background": "#1A1A1A",
        "surface": "#2D2D2D",
        "primary_text": "#F5F5F7",
        "secondary_text": "#A1A1A6",
        "accent": "#0A84FF",
        "accent_secondary": "#30D158",
        "accent_warn": "#FFD60A",
        "accent_danger": "#FF453A",
        "white": "#FFFFFF",
        "table_header_bg": "#0A84FF",
        "table_alt_row": "#242424",
        "table_border": "#3A3A3A",
        "divider": "#3A3A3A",
        "page_number": "#666666",
        "diagram_series": ["#0A84FF", "#30D158", "#FFD60A", "#FF453A", "#A1A1A6", "#BF5AF2"],
    },
    "warm": {
        "background": "#FEFCF9",
        "surface": "#F5F0EB",
        "primary_text": "#2D2926",
        "secondary_text": "#706B66",
        "accent": "#C45B28",
        "accent_secondary": "#2B6777",
        "accent_warn": "#D4A843",
        "accent_danger": "#C0392B",
        "white": "#FFFFFF",
        "table_header_bg": "#C45B28",
        "table_alt_row": "#F8F5F0",
        "table_border": "#DDD5CC",
        "divider": "#DDD5CC",
        "page_number": "#999999",
        "diagram_series": ["#C45B28", "#2B6777", "#D4A843", "#706B66", "#2D2926", "#8B5E3C"],
    },
}

DEFAULT_PALETTE = "modern"

# 60/30/10 role mapping (same keys across all palettes):
#   60% (dominant):  "background"
#   30% (secondary): "surface", "secondary_text", "divider"
#   10% (accent):    "accent" — used for headings, table headers, CTAs
#   Text:            "primary_text" on background, "white" on accent
#   Data viz:        "diagram_series" (up to 6 colors, accent-first)

PALETTE_ROLES = {
    "dominant": "background",
    "secondary": "surface",
    "accent": "accent",
    "text_on_bg": "primary_text",
    "text_on_accent": "white",
}


def get_palette(name: str | None = None) -> dict:
    return PALETTES.get(name or DEFAULT_PALETTE, PALETTES[DEFAULT_PALETTE])


# ── Layout positions (EMU) ───────────────────────────────────────
# All positions computed from CANVAS_W/H and MARGIN. No hardcoded values.
# Title position is IDENTICAL on every content slide (flip test).

_CONTENT_W = CONTENT["w"]                              # 7,772,400
_TITLE = {
    "x": MARGIN["left"],
    "y": MARGIN["top"],
    "w": _CONTENT_W,
    "h": 762_000,                                      # 60pt tall
}
_BODY_Y = _TITLE["y"] + _TITLE["h"] + 152_400         # title bottom + 12pt gap
_BODY_H = CANVAS_H - _BODY_Y - MARGIN["bottom"]       # remaining to bottom margin

def _centered(w: int, y: int, h: int) -> dict:
    return {"x": (CANVAS_W - w) // 2, "y": y, "w": w, "h": h}

_COL_W = (_CONTENT_W - GUTTER) // 2

LAYOUT = {
    "title_slide": {
        "title": _centered(6_858_000, 1_371_600, 914_400),
        "subtitle": _centered(5_715_000, 2_400_300, 571_500),
        "author": _centered(4_572_000, 3_086_100, 342_900),
    },
    "content": {
        "title": _TITLE,
        "body": {"x": MARGIN["left"], "y": _BODY_Y, "w": _CONTENT_W, "h": _BODY_H},
    },
    "two_column": {
        "title": _TITLE,
        "col1": {"x": MARGIN["left"], "y": _BODY_Y, "w": _COL_W, "h": _BODY_H},
        "col2": {"x": MARGIN["left"] + _COL_W + GUTTER, "y": _BODY_Y, "w": _COL_W, "h": _BODY_H},
    },
    "image_text": {
        "title": _TITLE,
        "image": {"x": MARGIN["left"], "y": _BODY_Y, "w": _COL_W, "h": _BODY_H},
        "text": {"x": MARGIN["left"] + _COL_W + GUTTER, "y": _BODY_Y, "w": _COL_W, "h": _BODY_H},
    },
    "quote": {
        "bar": {"x": (CANVAS_W - 5_715_000) // 2 - 228_600, "y": 1_143_000, "w": 45_720, "h": 2_514_600},
        "text": {"x": (CANVAS_W - 5_715_000) // 2, "y": 1_143_000, "w": 5_715_000, "h": 2_057_400},
        "attribution": {"x": (CANVAS_W - 5_715_000) // 2, "y": 3_429_000, "w": 5_715_000, "h": 342_900},
    },
    "section": {
        "number": {"x": MARGIN["left"], "y": 1_371_600, "w": _CONTENT_W, "h": 571_500},
        "title": {"x": MARGIN["left"], "y": 1_943_100, "w": _CONTENT_W, "h": 1_143_000},
        "underline_x": MARGIN["left"],
        "underline_y": 3_200_400,
        "underline_w": 1_371_600,
    },
    "metrics": {
        "title": _TITLE,
        "area_y": _BODY_Y,
        "number_h": 1_143_000,
        "label_h": 457_200,
    },
    "table": {
        "title": _TITLE,
        "table": {"x": MARGIN["left"], "y": _BODY_Y, "w": _CONTENT_W, "h": _BODY_H},
    },
    "footer_line_y": CANVAS_H - MARGIN["bottom"] - 228_600,
    "footer": {
        "x": MARGIN["left"],
        "y": CANVAS_H - MARGIN["bottom"] - 114_300,
        "w": _CONTENT_W // 2,
        "h": 228_600,
    },
    "page_number": {
        "x": CANVAS_W - MARGIN["right"] - 571_500,
        "y": CANVAS_H - MARGIN["bottom"] - 114_300,
        "w": 571_500,
        "h": 228_600,
    },
}


# ── Spacing (EMU) ────────────────────────────────────────────────

SPACING = {
    "title_to_body": 152_400,    # actual gap used in _BODY_Y computation
    "title_to_divider": 101_600,
    "divider_to_body": 152_400,
    "between_paragraphs": 101_600,
    "between_bullets": 76_200,
    "image_to_text": 228_600,
    "caption_gap": 101_600,
}

BULLET_INDENT = {
    0: 0,
    1: 457_200,
    2: 914_400,
}

TABLE_PADDING = {
    "header_v": 76_200,
    "header_h": 101_600,
    "cell_v": 50_800,
    "cell_h": 101_600,
}
