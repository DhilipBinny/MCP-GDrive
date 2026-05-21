"""Slide design system — typography, colors, layouts, spacing.

Professional presentation constants based on McKinsey/Google/Apple standards.
Canvas: 10,000,000 x 5,625,000 EMU (720 x 405 pt, 10 x 5.625 inches).
"""

EMU_PER_PT = 12700
EMU_PER_INCH = 914400

CANVAS_W = 10_000_000
CANVAS_H = 5_625_000

# ── Margins ──────────────────────────────────────────────────────

MARGIN = {
    "top": 381_000,       # 30pt
    "bottom": 381_000,
    "left": 508_000,      # 40pt
    "right": 508_000,
}

CONTENT = {
    "x": MARGIN["left"],
    "y": MARGIN["top"],
    "w": CANVAS_W - MARGIN["left"] - MARGIN["right"],   # 8,984,000
    "h": CANVAS_H - MARGIN["top"] - MARGIN["bottom"],   # 4,863,000
}

GUTTER = 254_000  # 20pt between columns/elements


# ── Typography ───────────────────────────────────────────────────

FONTS = {
    "heading": "Montserrat",
    "body": "Open Sans",
    "mono": "Roboto Mono",
}

FONT_SIZES = {
    "slide_title": 38,
    "subtitle": 22,
    "section_title": 46,
    "body": 18,
    "sub_bullet": 16,
    "caption": 11,
    "table_header": 14,
    "table_value": 13,
    "metric_number": 64,
    "metric_label": 16,
    "page_number": 10,
    "source": 10,
    "quote": 28,
    "attribution": 16,
    "author": 14,
}

LINE_SPACING = {
    "title": 115,
    "body": 140,
    "bullet": 130,
    "table": 120,
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
        "table_alt_row": "#F4F6F9",
        "table_border": "#E0E0E0",
        "divider": "#E0E0E0",
        "page_number": "#999999",
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
        "table_alt_row": "#F0F3F8",
        "table_border": "#D0D5DD",
        "divider": "#D0D5DD",
        "page_number": "#999999",
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
        "table_alt_row": "#FAF5F0",
        "table_border": "#DDD5CC",
        "divider": "#DDD5CC",
        "page_number": "#999999",
    },
}

DEFAULT_PALETTE = "modern"


def get_palette(name: str | None = None) -> dict:
    return PALETTES.get(name or DEFAULT_PALETTE, PALETTES[DEFAULT_PALETTE])


# ── Layout positions (EMU) ───────────────────────────────────────

LAYOUT = {
    "title_slide": {
        "title": {"x": 1_270_000, "y": 1_524_000, "w": 7_460_000, "h": 1_016_000},
        "subtitle": {"x": 1_905_000, "y": 2_667_000, "w": 6_190_000, "h": 635_000},
        "author": {"x": 2_540_000, "y": 3_429_000, "w": 4_920_000, "h": 381_000},
    },
    "content": {
        "title": {"x": 508_000, "y": 254_000, "w": 8_984_000, "h": 635_000},
        "body": {"x": 508_000, "y": 1_143_000, "w": 8_984_000, "h": 4_100_000},
    },
    "two_column": {
        "title": {"x": 508_000, "y": 254_000, "w": 8_984_000, "h": 635_000},
        "col1": {"x": 508_000, "y": 1_143_000, "w": 4_365_000, "h": 4_100_000},
        "col2": {"x": 5_127_000, "y": 1_143_000, "w": 4_365_000, "h": 4_100_000},
    },
    "image_text": {
        "title": {"x": 508_000, "y": 254_000, "w": 8_984_000, "h": 635_000},
        "image": {"x": 508_000, "y": 1_143_000, "w": 4_111_000, "h": 3_810_000},
        "text": {"x": 4_873_000, "y": 1_143_000, "w": 4_619_000, "h": 3_810_000},
    },
    "quote": {
        "bar": {"x": 1_905_000, "y": 1_524_000, "w": 50_800, "h": 2_540_000},
        "text": {"x": 2_286_000, "y": 1_524_000, "w": 6_350_000, "h": 2_032_000},
        "attribution": {"x": 2_286_000, "y": 3_683_000, "w": 6_350_000, "h": 381_000},
    },
    "section": {
        "number": {"x": 508_000, "y": 1_524_000, "w": 8_984_000, "h": 635_000},
        "title": {"x": 508_000, "y": 2_159_000, "w": 8_984_000, "h": 1_270_000},
        "underline_x": 508_000,
        "underline_y": 3_556_000,
        "underline_w": 1_524_000,
    },
    "metrics": {
        "title": {"x": 508_000, "y": 254_000, "w": 8_984_000, "h": 635_000},
        "area_y": 1_524_000,
        "number_h": 1_270_000,
        "label_h": 508_000,
    },
    "table": {
        "title": {"x": 508_000, "y": 254_000, "w": 8_984_000, "h": 635_000},
        "table": {"x": 508_000, "y": 1_143_000, "w": 8_984_000, "h": 4_100_000},
    },
    "page_number": {
        "x": 9_017_000, "y": 5_130_800, "w": 635_000, "h": 254_000,
    },
}


# ── Spacing (EMU) ────────────────────────────────────────────────

SPACING = {
    "title_to_body": 254_000,
    "title_to_divider": 101_600,
    "divider_to_body": 152_400,
    "between_paragraphs": 127_000,
    "between_bullets": 76_200,
    "image_to_text": 254_000,
    "caption_gap": 101_600,
}

BULLET_INDENT = {
    0: 0,
    1: 457_200,
    2: 914_400,
}

TABLE_PADDING = {
    "header_v": 101_600,
    "header_h": 152_400,
    "cell_v": 76_200,
    "cell_h": 152_400,
}
