"""Google Slides MCP Server — consolidated tools for create, edit, and manage presentations."""

from __future__ import annotations

import sys
import json
import logging
import functools
from typing import Literal

logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)

from mcp.server.fastmcp import FastMCP
from googleapiclient.errors import HttpError

from . import slides_service
from shared import drive_service

mcp = FastMCP(
    "google-slides-mcp",
    instructions="""MCP server for Google Slides — create, read, edit, and manage presentations.

WORKFLOW FOR BUILDING A DECK:
1. gslides_analyze(content_type=...) FIRST — get font sizes tuned for audience
2. gslides_create or gslides_manage(action="create_from_template") for branded decks
3. gslides_manage(action="set_theme") to set color palette BEFORE adding slides
4. gslides_add_slide — one idea per slide, takeaway titles
5. For visual diagrams: gslides_import(format="drawio") — NOT add_slide
6. gslides_analyze(presentation_id=...) to audit — fix issues found
7. gslides_manage(action="add_page_numbers") last

WORKFLOW FOR EDITING EXISTING DECKS:
1. gslides_analyze(presentation_id=...) — see what's wrong
2. gslides_read — get element IDs
3. gslides_edit — apply fixes (text_style, normalize_fonts, brand_kit, table_style)

DESIGN RULES (always follow):
- ONE idea per slide. Two ideas = two slides.
- Titles are TAKEAWAYS ("Revenue grew 23%") not TOPICS ("Revenue Analysis").
- Max 6 bullets, 8 words/bullet, 40 words/slide body.
- Max 2 font families per deck. Third only for code blocks.
- 60/30/10 color ratio: 60% background, 30% secondary, 10% accent. ONE accent color.
- Light bg: text #202124 or darker. Dark bg: text #F5F5F7 or lighter.
- Table: max 8 rows, 6 cols. Header uses deck accent color.
- At least 40% whitespace per slide. If it looks full, split it.
- NEVER below 12pt for visible text. 9pt only for page numbers.
- If user doesn't specify colors, inherit from deck theme. Don't invent new colors.
- For visual diagrams (flows, architectures), use draw.io XML import — NOT shapes.
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
                return "ERROR: Presentation or slide not found. Check the ID is correct."
            elif status == 403:
                return "ERROR: Permission denied. You may not have access."
            elif status == 429:
                return "ERROR: Rate limit exceeded. Wait and try again."
            else:
                return f"ERROR: Google API returned {status}: {e._get_reason()}"
        except RuntimeError as e:
            return f"ERROR: {e}"
        except (FileNotFoundError, ValueError) as e:
            return f"ERROR: {e}"
        except Exception as e:
            return f"ERROR: {type(e).__name__}: {e}"
    return wrapper


# ═══════════════════════════════════════════════════════════════
# TOOL 1: CREATE
# ═══════════════════════════════════════════════════════════════

@mcp.tool()
@_handle_errors
def gslides_create(title: str, folder_id: str | None = None) -> str:
    """Create a new blank Google Slides presentation.

    WHEN TO USE: For new decks without a specific brand/theme.
    FOR BRANDED DECKS: Use gslides_manage(action="create_from_template") instead —
    it copies an existing template preserving theme, logos, and layouts.

    WORKFLOW: create → set_theme → add slides.

    Args:
        title: Presentation title
        folder_id: Optional Drive folder ID
    """
    result = slides_service.create_presentation(title)
    if folder_id:
        drive_service.move_file(result["presentation_id"], folder_id)
    url = f"https://docs.google.com/presentation/d/{result['presentation_id']}/edit"
    return f"Created: **{result['title']}**\n- ID: `{result['presentation_id']}`\n- URL: {url}"


# ═══════════════════════════════════════════════════════════════
# TOOL 2: READ
# ═══════════════════════════════════════════════════════════════

@mcp.tool()
@_handle_errors
def gslides_read(presentation_id: str) -> str:
    """Read all slides — titles, text, tables, images, and element object IDs.

    USE THE OUTPUT FOR: Finding element IDs needed by gslides_edit and gslides_manage.
    Element IDs appear as `backtick-quoted` strings next to each element.

    WORKFLOW: read → identify element IDs → edit/manage.

    Args:
        presentation_id: The presentation ID
    """
    result = slides_service.get_presentation(presentation_id)
    lines = [f"# {result['title']} ({result['total_slides']} slides)\n"]
    for i, slide in enumerate(result["slides"]):
        lines.append(f"## Slide {i + 1} (`{slide['slide_id']}`)")
        for elem in slide["elements"]:
            if elem["type"] == "table":
                lines.append(f"  [TABLE {elem['rows']}x{elem['columns']}] `{elem.get('object_id', '')}`")
                for row in elem["data"]:
                    lines.append(f"    | {' | '.join(row)} |")
            elif elem["type"] == "image":
                lines.append(f"  [IMAGE] `{elem.get('object_id', '')}`")
            elif elem.get("text"):
                label = elem["type"].upper()
                text = elem["text"][:200].replace("\n", " | ")
                lines.append(f"  [{label}] {text} `{elem.get('object_id', '')}`")
        lines.append("")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# TOOL 3: ADD SLIDE (all slide types via `type` parameter)
# ═══════════════════════════════════════════════════════════════

@mcp.tool()
@_handle_errors
def gslides_add_slide(
    presentation_id: str,
    type: str,
    title: str = "",
    body: str = "",
    subtitle: str = "",
    author: str = "",
    section_number: str = "",
    quote: str = "",
    attribution: str = "",
    headers: list[str] | None = None,
    rows: list[list[str]] | None = None,
    metrics: list[dict] | None = None,
    code: str = "",
    language: str = "",
    col1: str = "",
    col2: str = "",
    col1_title: str = "",
    col2_title: str = "",
    image_url: str = "",
    image_side: str = "left",
    spreadsheet_id: str = "",
    chart_id: int = 0,
    speaker_notes: str = "",
    layout_id: str = "",
    texts: dict | None = None,
    theme: str | None = None,
    title_font: str | None = None,
    title_size: float | None = None,
    body_font: str | None = None,
    body_size: float | None = None,
    title_color: str | None = None,
    body_color: str | None = None,
    bg_color: str | None = None,
    line_spacing: float | None = None,
) -> str:
    """Add a slide to a presentation. The `type` parameter selects the layout.

    GUIDELINES FOR BEST RESULTS:
    - Use gslides_analyze(content_type=...) FIRST to get recommended font sizes for your audience
    - One idea per slide. If you have two ideas, make two slides.
    - Titles should be TAKEAWAYS ("Revenue grew 23%") not TOPICS ("Revenue Analysis")
    - Max 6 bullets, max 8 words per bullet, max 40 words per slide body
    - For visual diagrams (flows, architectures), use gslides_import(format="drawio") instead
    - For branded decks, use type="from_layout" with template layout IDs

    TYPES:
    - "title" — title slide (uses: title, subtitle, author)
    - "section" — section divider with accent background (uses: title, section_number)
    - "content" — bullet list slide (uses: title, body). Multi-line body → auto-bullets
    - "two_column" — comparison layout (uses: title, col1, col2, col1_title, col2_title)
    - "table" — styled table with colored header (uses: title, headers, rows). Max 8 rows, 6 cols.
    - "metrics" — 2-4 big numbers (uses: title, metrics=[{"value": "98%", "label": "Uptime"}])
    - "quote" — quote with accent bar (uses: quote, attribution). Don't add quotation marks — added auto.
    - "code" — dark background code block (uses: title, code, language)
    - "image_text" — image + text side by side (uses: title, image_url, body, image_side)
    - "chart" — live Sheets chart embed (uses: title, spreadsheet_id, chart_id)
    - "image" — image slide (uses: title, image_url). Image must be publicly accessible URL.
    - "blank" — empty slide (uses: title)
    - "from_layout" — template layout (uses: layout_id, texts={"TITLE_0": "...", "BODY_0": "..."})

    All styling params are OPTIONAL — defaults from theme. Override any to customize.

    Args:
        presentation_id: The presentation ID
        type: Slide type (see above)
        title: Slide title
        body: Body text (content/image_text types)
        subtitle: Subtitle (title type)
        author: Author line (title type)
        section_number: Section number like "01" (section type)
        quote: Quote text (quote type)
        attribution: Quote attribution (quote type)
        headers: Table column headers (table type)
        rows: Table data rows (table type)
        metrics: List of {"value": "...", "label": "..."} (metrics type)
        code: Code content (code type)
        language: Code language label (code type)
        col1: Left column text (two_column type)
        col2: Right column text (two_column type)
        col1_title: Left column heading (two_column type)
        col2_title: Right column heading (two_column type)
        image_url: Public image URL (image/image_text types)
        image_side: "left" or "right" (image_text type)
        spreadsheet_id: Source spreadsheet (chart type)
        chart_id: Chart ID from gsheets_add_chart (chart type)
        speaker_notes: Optional speaker notes
        layout_id: Layout object ID from template (from_layout type — use gslides_manage action=list_layouts)
        texts: Dict mapping placeholder keys to text (from_layout type — e.g. {"TITLE_0": "...", "BODY_0": "..."})
        theme: Color theme (or set deck-wide via gslides_manage action=set_theme)
        title_font: Override title font
        title_size: Override title size (pt)
        body_font: Override body font
        body_size: Override body size (pt)
        title_color: Override title color hex
        body_color: Override body color hex
        bg_color: Override slide background color hex
        line_spacing: Override line spacing (%)
    """
    style = {k: v for k, v in {
        "title_font": title_font, "title_size": title_size,
        "body_font": body_font, "body_size": body_size,
        "title_color": title_color, "body_color": body_color,
        "bg_color": bg_color, "line_spacing": line_spacing,
    }.items() if v is not None}

    t = type.lower()

    if t == "title":
        r = slides_service.add_title_slide(presentation_id, title, subtitle, author, theme, **style)
    elif t == "section":
        r = slides_service.add_section_slide(presentation_id, title, section_number, theme)
    elif t == "content":
        r = slides_service.add_content_slide(presentation_id, title, body, speaker_notes, theme, **style)
    elif t == "two_column":
        r = slides_service.add_two_column_slide(presentation_id, title, col1, col2, col1_title, col2_title, theme)
    elif t == "table":
        r = slides_service.add_styled_table_slide(presentation_id, title, headers or [], rows or [], theme)
    elif t == "metrics":
        r = slides_service.add_metrics_slide(presentation_id, title, metrics or [], theme)
    elif t == "quote":
        r = slides_service.add_quote_slide(presentation_id, quote, attribution, theme)
    elif t == "code":
        r = slides_service.add_code_slide(presentation_id, title, code, language, theme)
    elif t == "image_text":
        r = slides_service.add_image_text_slide(presentation_id, title, image_url, body, image_side, theme)
    elif t == "chart":
        r = slides_service.add_chart_slide(presentation_id, spreadsheet_id, chart_id, title, theme=theme)
    elif t == "image":
        r = slides_service.add_image_slide(presentation_id, image_url, title, theme=theme)
    elif t == "blank":
        r = slides_service.add_slide(presentation_id, title, body, "BLANK", speaker_notes, theme)
    elif t == "from_layout":
        if not layout_id:
            return "ERROR: layout_id required for from_layout type. Use gslides_manage action=list_layouts to find layout IDs."
        r = slides_service.add_slide_from_layout(presentation_id, layout_id, texts)
    else:
        return f"ERROR: Unknown slide type '{type}'. Use: title, section, content, two_column, table, metrics, quote, code, image_text, chart, image, blank, from_layout"

    return f"Added {t} slide: **{r.get('title', title or quote[:30])}** (`{r['slide_id']}`)"


# ═══════════════════════════════════════════════════════════════
# TOOL 4: EDIT (modify existing elements)
# ═══════════════════════════════════════════════════════════════

@mcp.tool()
@_handle_errors
def gslides_edit(
    presentation_id: str,
    action: str,
    element_id: str = "",
    table_id: str = "",
    font_family: str | None = None,
    font_size: float | None = None,
    bold: bool | None = None,
    italic: bool | None = None,
    color: str | None = None,
    fill_color: str | None = None,
    outline_color: str | None = None,
    outline_weight: float | None = None,
    header_bg: str | None = None,
    header_text_color: str = "#FFFFFF",
    alt_row_color: str | None = None,
    border_color: str | None = None,
    target_font: str = "",
    replace_fonts: list[str] | None = None,
    heading_font: str = "",
    body_font: str = "",
    accent_color: str = "",
    text_color: str = "",
    url: str = "",
    x: float | None = None,
    y: float | None = None,
    width: float | None = None,
    height: float | None = None,
) -> str:
    """Edit existing elements in a presentation.

    WORKFLOW: Always run gslides_analyze FIRST to understand what needs fixing.
    Then use gslides_read to get element IDs. Then apply edits.

    GUIDELINES:
    - For font consistency: use "normalize_fonts" to replace off-brand fonts in one call
    - For full brand enforcement: use "brand_kit" — it normalizes fonts AND styles unstyled tables
    - For individual element fixes: use "text_style" or "shape_fill" with specific element_id
    - Match the deck's existing accent color when styling tables (find it via gslides_analyze)

    ACTIONS:
    - "text_style" — change font/size/color on element (uses: element_id, font_family, font_size, bold, italic, color)
    - "shape_fill" — change fill/outline on shape (uses: element_id, fill_color, outline_color, outline_weight)
    - "table_style" — style a table (uses: table_id, header_bg, alt_row_color, border_color, font_family, font_size)
    - "normalize_fonts" — replace fonts across deck (uses: target_font, replace_fonts)
    - "brand_kit" — enforce brand across deck (uses: heading_font, body_font, accent_color, text_color, replace_fonts)
    - "hyperlink" — add link to text (uses: element_id, url)
    - "move_resize" — move/resize element (uses: element_id, x, y, width, height — inches)
    - "background" — set slide background (uses: element_id=slide_id, color or fill_color)

    Args:
        presentation_id: The presentation ID
        action: Edit action (see above)
        element_id: Target element ID (from gslides_read)
        table_id: Target table ID (for table_style)
        font_family: Font family
        font_size: Font size in pt
        bold: Bold text
        italic: Italic text
        color: Text color hex
        fill_color: Shape fill color hex
        outline_color: Shape outline color hex
        outline_weight: Outline weight in pt
        header_bg: Table header background hex
        header_text_color: Table header text color
        alt_row_color: Table alternating row color hex
        border_color: Table border color hex
        target_font: Target font for normalize_fonts
        replace_fonts: Fonts to replace
        heading_font: Brand heading font
        body_font: Brand body font
        accent_color: Brand accent color hex
        text_color: Brand text color hex
        url: Hyperlink URL
        x: X position in inches (move_resize)
        y: Y position in inches
        width: Width in inches
        height: Height in inches
    """
    a = action.lower()

    if a == "text_style":
        r = slides_service.update_text_style(presentation_id, element_id, font_family, font_size, bold, italic, color)
        return f"Updated text style on `{r['element_id']}`" if r["updated"] else "No changes"
    elif a == "shape_fill":
        r = slides_service.update_shape_fill(presentation_id, element_id, fill_color, outline_color, outline_weight)
        return f"Updated shape `{r['element_id']}`" if r["updated"] else "No changes"
    elif a == "table_style":
        r = slides_service.style_existing_table(presentation_id, table_id, header_bg, header_text_color, alt_row_color, border_color, font_size, font_size, font_family)
        return f"Styled table `{r['table_id']}` ({r['rows']}x{r['cols']})"
    elif a == "normalize_fonts":
        r = slides_service.normalize_fonts(presentation_id, target_font, replace_fonts or [])
        return f"Replaced {r['font_replacements']} text runs → **{r['target_font']}**"
    elif a == "brand_kit":
        r = slides_service.apply_brand_kit(presentation_id, heading_font, body_font, accent_color, text_color, replace_fonts)
        parts = [f"Brand kit applied: {r['heading_font']} + {r['body_font']}"]
        if r.get("font_replacements"): parts.append(f"Replaced {r['font_replacements']} runs")
        if r.get("tables_styled"): parts.append(f"Styled {r['tables_styled']} table(s)")
        return "\n".join(parts)
    elif a == "hyperlink":
        r = slides_service.add_hyperlink(presentation_id, element_id, url)
        return f"Added link → {r['url']}"
    elif a == "move_resize":
        r = slides_service.update_element(presentation_id, element_id, x, y, width, height)
        return f"Updated element `{r['element_id']}`"
    elif a == "background":
        r = slides_service.set_slide_background(presentation_id, element_id, color=fill_color or color)
        return f"Set background on `{r['slide_id']}`"
    else:
        return f"ERROR: Unknown action '{action}'. Use: text_style, shape_fill, table_style, normalize_fonts, brand_kit, hyperlink, move_resize, background"


# ═══════════════════════════════════════════════════════════════
# TOOL 5: MANAGE (structural operations)
# ═══════════════════════════════════════════════════════════════

@mcp.tool()
@_handle_errors
def gslides_manage(
    presentation_id: str,
    action: str,
    slide_id: str = "",
    slide_ids: list[str] | None = None,
    element_id: str = "",
    element_ids: list[str] | None = None,
    position: int = 0,
    operation: str = "BRING_TO_FRONT",
    table_id: str = "",
    row_index: int = 0,
    col_index: int = 0,
    count: int = 1,
    row_span: int = 1,
    col_span: int = 1,
    notes: str = "",
    find: str = "",
    replace: str = "",
    replacements: dict | None = None,
    theme: str = "",
    footer: str = "",
    image_url: str = "",
    placeholder_text: str = "",
) -> str:
    """Structural operations on a presentation.

    TEMPLATE WORKFLOW (for branded decks):
    1. action="create_from_template" with template file ID → copies deck, lists layouts
    2. action="list_layouts" → see available layouts with placeholder types
    3. Use gslides_add_slide(type="from_layout", layout_id=..., texts={...}) to add themed slides

    BATCH REPLACE WORKFLOW (for template filling):
    1. Create slides with {{placeholders}} in text
    2. action="batch_replace" with replacements={"{{name}}": "John", "{{date}}": "2025-01-15"}

    ACTIONS:
    - "delete_slide" — delete a slide (uses: slide_id)
    - "duplicate_slide" — clone a slide (uses: slide_id)
    - "reorder" — move slides (uses: slide_ids, position)
    - "delete_element" — delete any element (uses: element_id)
    - "group" — group elements (uses: element_ids)
    - "ungroup" — ungroup (uses: element_ids)
    - "z_order" — change layer order (uses: element_ids, operation=BRING_TO_FRONT/SEND_TO_BACK)
    - "replace_text" — find/replace text (uses: find, replace)
    - "batch_replace" — replace multiple placeholders (uses: replacements={"{{key}}": "value"})
    - "replace_image" — replace shapes with image (uses: placeholder_text, image_url)
    - "speaker_notes" — set notes (uses: slide_id, notes)
    - "set_theme" — set deck theme (uses: theme=modern/corporate/dark/warm)
    - "set_footer" — set deck footer (uses: footer)
    - "add_page_numbers" — add page numbers to all slides
    - "get_thumbnail" — get slide PNG URL (uses: slide_id)
    - "insert_table_rows" — add rows (uses: table_id, row_index, count)
    - "delete_table_row" — remove row (uses: table_id, row_index)
    - "merge_table_cells" — merge cells (uses: table_id, row_index, col_index, row_span, col_span)
    - "list_layouts" — list available layouts in the deck (for from_layout slides)
    - "create_from_template" — copy a template deck, clear content, return clean deck with theme (uses: find as template_id, name, folder_id)

    Args:
        presentation_id: The presentation ID
        action: Operation (see above)
        slide_id: Target slide ID
        slide_ids: List of slide IDs (reorder, etc.)
        element_id: Target element ID
        element_ids: List of element IDs (group, z_order)
        position: Target position for reorder
        operation: Z-order operation
        table_id: Target table ID
        row_index: Row index for table ops
        col_index: Column index for table ops
        count: Number of rows/columns to insert
        row_span: Rows to merge
        col_span: Columns to merge
        notes: Speaker notes text
        find: Text to find
        replace: Replacement text
        replacements: Dict of find→replace pairs
        theme: Theme name (modern/corporate/dark/warm)
        footer: Footer text
        image_url: Image URL for replace_image
        placeholder_text: Text to match for replace_image
    """
    a = action.lower()

    if a == "delete_slide":
        r = slides_service.delete_slide(presentation_id, slide_id)
        return f"Deleted slide `{r['deleted']}`"
    elif a == "duplicate_slide":
        r = slides_service.duplicate_slide(presentation_id, slide_id)
        return f"Duplicated `{r['original']}` → `{r['duplicate']}`"
    elif a == "reorder":
        r = slides_service.reorder_slides(presentation_id, slide_ids or [], position)
        return f"Moved {r['moved']} slide(s) to position {r['to_position']}"
    elif a == "delete_element":
        r = slides_service.delete_element(presentation_id, element_id)
        return f"Deleted `{r['deleted']}`"
    elif a == "group":
        r = slides_service.group_elements(presentation_id, element_ids or [])
        return f"Grouped → `{r['group_id']}`"
    elif a == "ungroup":
        r = slides_service.ungroup_elements(presentation_id, element_ids or [])
        return f"Ungrouped {len(r['ungrouped'])} group(s)"
    elif a == "z_order":
        r = slides_service.z_order(presentation_id, element_ids or [], operation)
        return f"{r['operation']} on {len(r['elements'])} element(s)"
    elif a == "replace_text":
        r = slides_service.replace_text(presentation_id, find, replace)
        return f"Replaced {r['occurrences_replaced']} occurrence(s)"
    elif a == "batch_replace":
        r = slides_service.batch_replace_text(presentation_id, replacements or {})
        return f"Replaced {r['replacements']} placeholders ({r['total_changed']} occurrences)"
    elif a == "replace_image":
        r = slides_service.replace_image(presentation_id, placeholder_text, image_url)
        return f"Replaced {r['occurrences_replaced']} shape(s) with image"
    elif a == "speaker_notes":
        r = slides_service.set_speaker_notes(presentation_id, slide_id, notes)
        return f"Set notes on `{r['slide_id']}`"
    elif a == "set_theme":
        r = slides_service.set_deck_theme(presentation_id, theme)
        return f"Theme → **{r['theme']}**"
    elif a == "set_footer":
        r = slides_service.set_deck_footer(presentation_id, footer)
        return f"Footer → **{r['footer']}**"
    elif a == "add_page_numbers":
        r = slides_service.add_page_numbers(presentation_id)
        return f"Added page numbers to {r['slides_numbered']}/{r['total_slides']} slides"
    elif a == "get_thumbnail":
        r = slides_service.get_slide_thumbnail(presentation_id, slide_id)
        return f"Thumbnail ({r['width']}x{r['height']}):\n{r['url']}"
    elif a == "insert_table_rows":
        r = slides_service.insert_table_rows(presentation_id, table_id, row_index, count)
        return f"Added {r['rows_added']} row(s)"
    elif a == "delete_table_row":
        r = slides_service.delete_table_row(presentation_id, table_id, row_index)
        return f"Deleted row {r['row_deleted']}"
    elif a == "merge_table_cells":
        r = slides_service.merge_table_cells(presentation_id, table_id, row_index, col_index, row_span, col_span)
        return f"Merged {r['merged']}"
    elif a == "list_layouts":
        layouts = slides_service.list_layouts(presentation_id)
        lines = [f"Available layouts ({len(layouts)}):\n"]
        for l in layouts:
            phs = ", ".join(f"{p['type']}[{p['index']}]" for p in l["placeholders"])
            lines.append(f"- **{l['name']}** `{l['layout_id']}`\n  Placeholders: {phs or 'none'}")
        return "\n".join(lines)
    elif a == "create_from_template":
        r = slides_service.create_from_template(find, name, folder_id or None)
        lines = [f"Created from template: **{r['title']}** (`{r['presentation_id']}`)\nURL: {r['url']}\n\nAvailable layouts:"]
        for l in r["layouts"]:
            phs = ", ".join(f"{p['type']}[{p['index']}]" for p in l["placeholders"])
            lines.append(f"- **{l['name']}** `{l['layout_id']}` — {phs or 'none'}")
        return "\n".join(lines)
    else:
        return f"ERROR: Unknown action '{action}'"


# ═══════════════════════════════════════════════════════════════
# TOOL 6: ANALYZE (audit + recommend)
# ═══════════════════════════════════════════════════════════════

@mcp.tool()
@_handle_errors
def gslides_analyze(
    presentation_id: str = "",
    content_type: str = "",
    text_length: int = 0,
    audience: str = "business",
) -> str:
    """Analyze a presentation's style OR get recommendations for new slides.

    ALWAYS CALL THIS BEFORE EDITING. It tells you what's wrong so you make
    informed decisions instead of guessing.

    MODE 1 — Audit (provide presentation_id):
    Returns fonts, sizes, colors used, unstyled tables, issues found.
    Use before gslides_edit to understand what needs fixing.
    Look for: too many fonts (keep ≤2), unstyled tables, tiny text (<9pt).

    MODE 2 — Recommend (provide content_type):
    Returns suggested font sizes, colors, spacing for a slide type.
    Use before gslides_add_slide to get the right styling values.
    Adjusts recommendations based on audience (keynote=larger, technical=smaller).

    Args:
        presentation_id: Presentation to audit (mode 1)
        content_type: Slide type to get recommendations for (mode 2): title, content, table, metrics, quote, code
        text_length: Approximate body text length in characters (mode 2)
        audience: Target audience — business, technical, academic, keynote (mode 2)
    """
    if presentation_id:
        r = slides_service.audit_styles(presentation_id)
        parts = [f"# Style Audit ({r['slides']} slides)\n"]
        parts.append(f"## Fonts ({len(r['fonts'])})")
        for f, c in r["fonts"].items(): parts.append(f"  - {f}: {c} runs")
        parts.append(f"\n## Font Sizes ({len(r['font_sizes'])} distinct)")
        for s, c in list(r["font_sizes"].items())[:10]: parts.append(f"  - {s}pt: {c}")
        parts.append(f"\n## Colors ({len(r['text_colors'])})")
        for c, n in r["text_colors"].items(): parts.append(f"  - {c}: {n}")
        if r["tables"]:
            parts.append(f"\n## Tables")
            for t in r["tables"]:
                styled = "styled" if t["has_styled_header"] else "UNSTYLED"
                parts.append(f"  - Slide {t['slide']}: {t['rows']}x{t['columns']} ({styled}) `{t['object_id']}`")
        parts.append(f"\n## Issues ({len(r['issues'])})")
        for i in r["issues"]: parts.append(f"  - {i}")
        return "\n".join(parts)

    if content_type:
        bases = {
            "keynote": {"title": 36, "body": 24, "table_h": 20, "table_v": 18},
            "business": {"title": 26, "body": 16, "table_h": 14, "table_v": 13},
            "technical": {"title": 24, "body": 14, "table_h": 13, "table_v": 12},
            "academic": {"title": 22, "body": 14, "table_h": 12, "table_v": 11},
        }
        b = bases.get(audience, bases["business"])
        if text_length > 300: b["body"] = max(b["body"] - 2, 12)
        elif text_length < 100: b["body"] = min(b["body"] + 2, 24)

        return f"""## Recommended: {content_type} ({audience})
**Fonts:** Heading: Montserrat, Body: Open Sans, Code: Roboto Mono
**Title:** {b['title']}pt bold  |  **Body:** {b['body']}pt
**Table:** header {b['table_h']}pt bold, values {b['table_v']}pt
**Spacing:** line {130 if audience == 'business' else 120}%, bullet gap 6pt
**Colors:** Light bg text: #202124. Dark bg text: #F5F5F7. Use set_theme or explicit colors."""

    return "ERROR: Provide either presentation_id (audit) or content_type (recommend)"


# ═══════════════════════════════════════════════════════════════
# TOOL 7: IMPORT (markdown, draw.io)
# ═══════════════════════════════════════════════════════════════

@mcp.tool()
@_handle_errors
def gslides_import(
    presentation_id: str,
    format: str,
    content: str,
    title: str = "",
) -> str:
    """Import content into a presentation.

    WHEN TO USE WHICH FORMAT:
    - "markdown" — for text-heavy content (lectures, reports). Fast bulk slide generation.
    - "drawio" — for visual diagrams (architectures, flows, comparisons). Generates native
      editable shapes with auto-scaling and connector routing.

    DRAW.IO TIPS:
    - Canvas: 1000x562 px (16:9). Grid: x=col*160+40, y=row*100+40.
    - Use gslides_search_shapes to find exact draw.io style strings.
    - Connectors auto-route via RerouteLineRequest — no manual positioning needed.
    - Use pastel fills (fillColor=#dbeafe) with matching strokes (strokeColor=#6c8ebf).

    FORMATS:
    - "markdown" — # title, ## section, ### content, ``` code, > quote, | table
    - "drawio" — draw.io mxGraph XML → native Slides shapes

    Args:
        presentation_id: The presentation ID
        format: Import format — "markdown" or "drawio"
        content: The content to import (markdown text or draw.io XML)
        title: Optional title for draw.io import
    """
    if format.lower() == "markdown":
        r = slides_service.from_markdown(presentation_id, content)
        return f"Generated {r['slides_created']} slides from Markdown"
    elif format.lower() == "drawio":
        r = slides_service.import_drawio(presentation_id, content, title)
        return f"Imported diagram: {r['shapes']} shapes, {r['connectors']} connectors (`{r['slide_id']}`)"
    else:
        return f"ERROR: Unknown format '{format}'. Use: markdown, drawio"


# ═══════════════════════════════════════════════════════════════
# TOOL 8: SEARCH SHAPES
# ═══════════════════════════════════════════════════════════════

@mcp.tool()
@_handle_errors
def gslides_search_shapes(query: str, max_results: int = 10) -> str:
    """Search the curated shape library (58 shapes) for draw.io XML generation.

    USE WITH: gslides_import(format="drawio"). Returns exact draw.io style strings
    you can paste directly into mxCell elements.

    CATEGORIES: basic shapes, flowchart, business/people, data/storage, arrows,
    symbols, tech (server/laptop/router), containers.

    STYLE GUIDE for draw.io XML:
    - Use pastel fills: fillColor=#dbeafe (blue), #dcfce7 (green), #fef9c3 (yellow)
    - Matching strokes: strokeColor=#6c8ebf, #82b366, #d6b656
    - All shapes: rounded=1;whiteSpace=wrap;strokeWidth=1.5
    - Text: fontColor=#333333, fontSize=9-10
    - Connectors: strokeColor=#666666, strokeWidth=1

    Args:
        query: Keywords (e.g. "database", "server", "decision", "gear", "user")
        max_results: Max results (default 10)
    """
    from .shape_search import search_shapes
    results = search_shapes(query, max_results)
    if not results:
        return f"No shapes found for: {query}"
    lines = [f"Found {len(results)} shape(s):\n"]
    for r in results:
        lines.append(f"- **{r['title']}** ({r['width']}x{r['height']})")
        lines.append(f"  `{r['style'][:100]}{'...' if len(r['style']) > 100 else ''}`")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# DRIVE TOOLS (shared)
# ═══════════════════════════════════════════════════════════════

@mcp.tool()
@_handle_errors
def gdrive_search(query: str, max_results: int = 20) -> str:
    """Search for files in Google Drive by name or content.

    USE FOR: Finding presentation IDs, template files, images to insert.
    Returns file IDs needed by other tools (gslides_read, gdrive_ops, etc.).

    Args:
        query: Search query (searches file names and content)
        max_results: Maximum results (default 20)
    """
    results = drive_service.search_files(query, max_results=max_results)
    if not results: return f"No files found for: {query}"
    lines = [f"Found {len(results)} file(s):\n"]
    for f in results:
        lines.append(f"- **{f['name']}** (`{f['id']}`)\n  {f['mime_type']} | {f['modified']}\n  {f['url']}")
    return "\n".join(lines)


@mcp.tool()
@_handle_errors
def gdrive_list_folder(folder_id: str | None = None, max_results: int = 50) -> str:
    """List files in a Google Drive folder.

    USE FOR: Browsing folder contents, finding template files, checking what exists.
    Returns file IDs and types (doc, sheet, slide, folder).

    Args:
        folder_id: Folder ID (omit for root/My Drive)
        max_results: Maximum results (default 50)
    """
    results = drive_service.list_folder(folder_id=folder_id, max_results=max_results)
    if not results: return "Folder is empty"
    lines = [f"Contents ({len(results)} items):\n"]
    for f in results:
        lines.append(f"- **{f['name']}** (`{f['id']}`)\n  {f['mime_type']} | {f['modified']}")
    return "\n".join(lines)


@mcp.tool()
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

    IMAGE SIDECAR (for inserting private/local images into slides):
    1. action="upload" local image → get file_id
    2. action="share" with anyone=true → get public URL
    3. Use the URL in gslides_add_slide(type="image", image_url=...)
    4. action="share" to revoke (image persists in slide after insertion)

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
        if not confirm: return "REFUSED: set confirm=true"
        r = drive_service.trash_file(file_id)
        return f"Trashed **{r['name']}**"
    elif a == "rename":
        r = drive_service.rename_file(file_id, name)
        return f"Renamed → **{r['name']}**"
    elif a == "copy":
        r = drive_service.copy_file(file_id, name, folder_id or None)
        return f"Copied → **{r['name']}** (`{r['id']}`)"
    elif a == "upload":
        r = drive_service.upload_file(local_path, name or None, folder_id or None)
        return f"Uploaded **{r['name']}** (`{r['id']}`)"
    elif a == "export":
        r = drive_service.export_file(file_id, format, output_path or None)
        return f"Exported → **{r['path']}** ({r['size']/1024:.1f} KB)"
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
