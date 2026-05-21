"""Slide design system — typography, colors, layouts, spacing.

Professional presentation constants based on McKinsey/Google/Apple standards.
Canvas: 10,000,000 x 5,625,000 EMU (720 x 405 pt, 10 x 5.625 inches).
Research-backed values from BrightCarbon, Deckary (MBB standards), WCAG 2.2.
"""

EMU_PER_PT = 12700
EMU_PER_INCH = 914400

CANVAS_W = 10_000_000
CANVAS_H = 5_625_000

# ── Margins (0.75 inches = 54pt — industry recommended) ─────────

MARGIN = {
    "top": 457_200,       # 36pt (0.5")
    "bottom": 457_200,
    "left": 685_800,      # 54pt (0.75")
    "right": 685_800,
}

CONTENT = {
    "x": MARGIN["left"],
    "y": MARGIN["top"],
    "w": CANVAS_W - MARGIN["left"] - MARGIN["right"],   # 8,628,400 (8.5")
    "h": CANVAS_H - MARGIN["top"] - MARGIN["bottom"],   # 4,710,600 (4.625")
}

GUTTER = 254_000  # 20pt between columns/elements


# ── Typography ───────────────────────────────────────────────────
# Scale: Perfect Fourth ratio (1.333x) — title ~1.9x body

FONTS = {
    "heading": "Montserrat",
    "body": "Open Sans",
    "mono": "Roboto Mono",
}

FONT_SIZES = {
    "slide_title": 34,       # was 38 — research says 28-36 for business
    "subtitle": 22,
    "section_title": 44,     # was 46
    "body": 18,
    "sub_bullet": 16,
    "caption": 12,           # was 11 — research minimum
    "table_header": 18,      # was 14 — research says same as body, bold
    "table_value": 15,       # was 13 — research says body minus 2-4pt
    "metric_number": 60,     # was 64
    "metric_label": 16,
    "page_number": 10,
    "source": 10,
    "quote": 28,
    "attribution": 16,
    "author": 14,
    "code": 13,
}

LINE_SPACING = {
    "title": 110,            # was 115 — research says 100-110 for titles
    "body": 130,             # was 140 — research sweet spot is 130
    "bullet": 130,
    "table": 120,
}

# Content density limits (for LLM guidance in tool descriptions)
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
        "table_alt_row": "#F5F5F5",   # was #F4F6F9 — research says barely noticeable
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


def get_palette(name: str | None = None) -> dict:
    return PALETTES.get(name or DEFAULT_PALETTE, PALETTES[DEFAULT_PALETTE])


# ── Layout positions (EMU) ───────────────────────────────────────
# All positions respect 0.75" side margins, 0.5" top/bottom margins.
# Title position is IDENTICAL on every content slide (flip test).

_TITLE = {"x": 685_800, "y": 365_760, "w": 8_628_400, "h": 1_143_000}  # 90pt tall — fits 2-line action titles at 34pt
_BODY_Y = 1_828_800  # after title + accent line + generous gap
_BODY_H = 3_028_950  # remaining to bottom margin

LAYOUT = {
    "title_slide": {
        "title": {"x": 1_270_000, "y": 1_524_000, "w": 7_460_000, "h": 1_016_000},
        "subtitle": {"x": 1_905_000, "y": 2_667_000, "w": 6_190_000, "h": 635_000},
        "author": {"x": 2_540_000, "y": 3_429_000, "w": 4_920_000, "h": 381_000},
    },
    "content": {
        "title": _TITLE,
        "body": {"x": 685_800, "y": _BODY_Y, "w": 8_628_400, "h": _BODY_H},
    },
    "two_column": {
        "title": _TITLE,
        "col1": {"x": 685_800, "y": _BODY_Y, "w": 4_187_200, "h": _BODY_H},
        "col2": {"x": 5_127_000, "y": _BODY_Y, "w": 4_187_200, "h": _BODY_H},
    },
    "image_text": {
        "title": _TITLE,
        "image": {"x": 685_800, "y": _BODY_Y, "w": 3_886_200, "h": 3_429_000},
        "text": {"x": 4_826_000, "y": _BODY_Y, "w": 4_488_200, "h": 3_429_000},
    },
    "quote": {
        "bar": {"x": 1_905_000, "y": 1_270_000, "w": 50_800, "h": 2_794_000},
        "text": {"x": 2_286_000, "y": 1_270_000, "w": 6_350_000, "h": 2_286_000},
        "attribution": {"x": 2_286_000, "y": 3_937_000, "w": 6_350_000, "h": 381_000},
    },
    "section": {
        "number": {"x": 685_800, "y": 1_524_000, "w": 8_628_400, "h": 635_000},
        "title": {"x": 685_800, "y": 2_159_000, "w": 8_628_400, "h": 1_270_000},
        "underline_x": 685_800,
        "underline_y": 3_556_000,
        "underline_w": 1_524_000,
    },
    "metrics": {
        "title": _TITLE,
        "area_y": 1_524_000,
        "number_h": 1_270_000,
        "label_h": 508_000,
    },
    "table": {
        "title": _TITLE,
        "table": {"x": 685_800, "y": _BODY_Y, "w": 8_628_400, "h": _BODY_H},
    },
    "title_accent": {
        "x": 685_800,
        "y": 1_700_000,   # well below 2-line title bottom
        "w": 1_524_000,
        "weight": 2.5,
    },
    "footer": {
        "x": 685_800, "y": 5_130_800, "w": 5_080_000, "h": 254_000,
    },
    "page_number": {
        "x": 8_686_800, "y": 5_130_800, "w": 635_000, "h": 254_000,
    },
}


# ── Spacing (EMU) ────────────────────────────────────────────────

SPACING = {
    "title_to_body": 228_600,   # 18pt gap
    "title_to_divider": 101_600,
    "divider_to_body": 152_400,
    "between_paragraphs": 101_600,  # 8pt
    "between_bullets": 76_200,      # 6pt
    "image_to_text": 254_000,
    "caption_gap": 101_600,
}

BULLET_INDENT = {
    0: 0,
    1: 457_200,
    2: 914_400,
}

TABLE_PADDING = {
    "header_v": 76_200,     # 6pt — research says 4-6pt
    "header_h": 101_600,    # 8pt — research says 6-10pt
    "cell_v": 50_800,       # 4pt
    "cell_h": 101_600,      # 8pt
}
