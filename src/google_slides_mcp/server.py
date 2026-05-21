"""Google Slides MCP Server — create and edit presentations."""

from __future__ import annotations

import sys
import logging
import functools

logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)

from mcp.server.fastmcp import FastMCP
from googleapiclient.errors import HttpError

from . import slides_service
from shared import drive_service

mcp = FastMCP(
    "google-slides-mcp",
    instructions="MCP server for Google Slides — create and edit presentations",
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
                return "ERROR: Permission denied. You may not have access to this presentation."
            elif status == 429:
                return "ERROR: Google API rate limit exceeded. Wait a moment and try again."
            else:
                return f"ERROR: Google API returned {status}: {e._get_reason()}"
        except RuntimeError as e:
            return f"ERROR: {e}"
        except (FileNotFoundError, ValueError) as e:
            return f"ERROR: {e}"
        except Exception as e:
            return f"ERROR: Unexpected — {type(e).__name__}: {e}"
    return wrapper


# ── Slides Tools ───────────────────────────────────────────────────


@mcp.tool()
@_handle_errors
def gslides_create(title: str, folder_id: str | None = None) -> str:
    """Create a new Google Slides presentation.

    Args:
        title: Presentation title
        folder_id: Optional Drive folder ID to place it in
    """
    result = slides_service.create_presentation(title)
    if folder_id:
        drive_service.move_file(result["presentation_id"], folder_id)
    url = f"https://docs.google.com/presentation/d/{result['presentation_id']}/edit"
    return f"Created: **{result['title']}**\n- ID: `{result['presentation_id']}`\n- Slides: {len(result['slides'])}\n- URL: {url}"


@mcp.tool()
@_handle_errors
def gslides_read(presentation_id: str) -> str:
    """Read all slides from a presentation — titles, body text, tables, images.

    Args:
        presentation_id: The presentation ID
    """
    result = slides_service.get_presentation(presentation_id)
    lines = [f"# {result['title']} ({result['total_slides']} slides)\n"]

    for i, slide in enumerate(result["slides"]):
        lines.append(f"## Slide {i + 1} (`{slide['slide_id']}`)")
        for elem in slide["elements"]:
            if elem["type"] == "table":
                lines.append(f"  [TABLE {elem['rows']}x{elem['columns']}]")
                for row in elem["data"]:
                    lines.append(f"    | {' | '.join(row)} |")
            elif elem["type"] == "image":
                lines.append(f"  [IMAGE] {elem['url'][:60]}...")
            elif elem["text"]:
                label = elem["type"].upper()
                text = elem["text"][:200].replace("\n", " | ")
                lines.append(f"  [{label}] {text}")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
@_handle_errors
def gslides_add_slide(
    presentation_id: str,
    title: str,
    body: str = "",
    speaker_notes: str = "",
) -> str:
    """Add a slide with a title and body text. Multi-line body becomes a bullet list.

    Args:
        presentation_id: The presentation ID
        title: Slide title
        body: Body text (each line becomes a bullet point)
        speaker_notes: Optional speaker notes
    """
    result = slides_service.add_slide(
        presentation_id, title, body, speaker_notes=speaker_notes
    )
    return f"Added slide: **{result['title']}** (`{result['slide_id']}`)"


@mcp.tool()
@_handle_errors
def gslides_add_table_slide(
    presentation_id: str,
    title: str,
    headers: list[str],
    rows: list[list[str]],
) -> str:
    """Add a slide with a formatted data table. Header row is bolded.

    Args:
        presentation_id: The presentation ID
        title: Slide title
        headers: Column header labels
        rows: Data rows (list of lists)
    """
    result = slides_service.add_table_slide(presentation_id, title, headers, rows)
    return f"Added table slide: **{result['title']}** ({result['table']}) (`{result['slide_id']}`)"


@mcp.tool()
@_handle_errors
def gslides_add_image_slide(
    presentation_id: str,
    image_url: str,
    title: str = "",
    as_background: bool = False,
) -> str:
    """Add a slide with an image. Can be positioned in content area or as full-slide background.

    The image must be accessible via a public URL or a Google Drive URL with sharing enabled.

    Args:
        presentation_id: The presentation ID
        image_url: URL of the image
        title: Optional slide title (omit for blank + image)
        as_background: True to set as full-slide background image
    """
    result = slides_service.add_image_slide(presentation_id, image_url, title, as_background)
    mode = "background" if result["background"] else "content"
    return f"Added image slide ({mode}): **{result['title']}** (`{result['slide_id']}`)"


@mcp.tool()
@_handle_errors
def gslides_delete_slide(presentation_id: str, slide_id: str) -> str:
    """Delete a slide from a presentation.

    Args:
        presentation_id: The presentation ID
        slide_id: The slide object ID (from gslides_read)
    """
    result = slides_service.delete_slide(presentation_id, slide_id)
    return f"Deleted slide `{result['deleted']}`"


@mcp.tool()
@_handle_errors
def gslides_add_shape(
    presentation_id: str,
    slide_id: str,
    text: str = "",
    shape_type: str = "rounded",
    x: float = 1.0, y: float = 1.0,
    width: float = 2.0, height: float = 0.7,
    fill_color: str = "#4285F4",
    text_color: str = "#FFFFFF",
    font_size: int = 10,
    bold: bool = False,
    outline_color: str | None = None,
) -> str:
    """Add a shape to an existing slide. Returns the shape object ID.

    Coordinates in inches. Standard slide is 10 x 5.625 inches.
    Shape types: rounded, rectangle, circle, diamond, database, cloud,
    hexagon, chevron, cube, process, decision, terminator, or any Google Slides ShapeType.

    Args:
        presentation_id: The presentation ID
        slide_id: The slide to add the shape to
        text: Text inside the shape
        shape_type: Shape type name or alias
        x: X position in inches from left
        y: Y position in inches from top
        width: Width in inches
        height: Height in inches
        fill_color: Background color hex "#RRGGBB"
        text_color: Text color hex "#RRGGBB"
        font_size: Font size in points
        bold: Bold text
        outline_color: Optional border color hex
    """
    result = slides_service.add_shape(
        presentation_id, slide_id, shape_type, x, y, width, height,
        text, fill_color, text_color, font_size, bold, outline_color,
    )
    return f"Added shape `{result['shape_id']}` — {result['text'] or shape_type}"


@mcp.tool()
@_handle_errors
def gslides_add_connector(
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
) -> str:
    """Connect two shapes with a line/arrow. Uses smart connectors that snap to shape edges.

    Args:
        presentation_id: The presentation ID
        slide_id: The slide containing both shapes
        from_shape_id: Source shape object ID
        to_shape_id: Target shape object ID
        from_side: Side to connect from — top, right, bottom, left
        to_side: Side to connect to — top, right, bottom, left
        connector_type: STRAIGHT, BENT, or CURVED
        color: Line color hex
        weight: Line weight in points
        end_arrow: Arrow style — OPEN_ARROW, FILL_ARROW, STEALTH_ARROW, NONE
    """
    result = slides_service.add_connector(
        presentation_id, slide_id, from_shape_id, to_shape_id,
        from_side, to_side, connector_type, color, weight, end_arrow,
    )
    return f"Connected `{result['from']}` → `{result['to']}` (`{result['connector_id']}`)"


@mcp.tool()
@_handle_errors
def gslides_add_text_box(
    presentation_id: str,
    slide_id: str,
    text: str,
    x: float = 1.0, y: float = 1.0,
    width: float = 2.0, height: float = 0.5,
    font_size: int = 9,
    font_color: str = "#5F6368",
    bold: bool = False,
) -> str:
    """Add a text label to a slide (no background/border). For annotations and labels.

    Args:
        presentation_id: The presentation ID
        slide_id: The slide to add text to
        text: Label text
        x: X position in inches
        y: Y position in inches
        width: Width in inches
        height: Height in inches
        font_size: Font size in points
        font_color: Text color hex
        bold: Bold text
    """
    result = slides_service.add_text_box(
        presentation_id, slide_id, text, x, y, width, height, font_size, font_color, bold,
    )
    return f"Added text box `{result['text_box_id']}` — {result['text']}"


@mcp.tool()
@_handle_errors
def gslides_add_diagram(
    presentation_id: str,
    title: str,
    nodes: list[dict],
    connections: list[dict] | None = None,
    style: str = "corporate",
) -> str:
    """Create a full diagram slide with auto-positioned nodes and smart connectors.

    nodes: list of node objects with:
        - id: unique identifier (used in connections)
        - label: text displayed in the node
        - type: shape type — rounded, rectangle, database, cloud, hexagon, diamond, etc.
        - tier: row number for auto-layout (1=top, 2=middle, 3=bottom). Or set x/y manually.
        - x, y, w, h: optional position/size in inches (auto-calculated if omitted)
        - color: optional fill color hex (auto-assigned from palette if omitted)

    connections: list of connection objects with:
        - from: source node ID
        - to: target node ID
        - from_side: top/right/bottom/left (default: bottom)
        - to_side: top/right/bottom/left (default: top)
        - label: optional text on the arrow
        - type: STRAIGHT/BENT/CURVED (default: STRAIGHT)

    style: color palette — corporate, tech, minimal, colorful

    Args:
        presentation_id: The presentation ID
        title: Diagram title
        nodes: Node definitions
        connections: Connection definitions
        style: Color palette name
    """
    result = slides_service.add_diagram(
        presentation_id, title, nodes, connections, style,
    )
    return f"Added diagram: **{result['title']}** ({result['nodes']} nodes, {result['connections']} connections) — slide `{result['slide_id']}`"


@mcp.tool()
@_handle_errors
def gslides_search_shapes(query: str, max_results: int = 10) -> str:
    """Search the curated draw.io shape library (58 presentation shapes).

    Covers: basic shapes, flowchart, business/people, data/storage, arrows,
    symbols, tech (server/laptop/router), and containers. Returns exact
    draw.io style strings for use in mxCell elements with gslides_import_drawio.

    Args:
        query: Search keywords (e.g. "database", "server", "decision", "gear", "user")
        max_results: Max results to return (default 10)
    """
    from .shape_search import search_shapes
    results = search_shapes(query, max_results)
    if not results:
        return f"No shapes found for: {query}"
    lines = [f"Found {len(results)} shape(s) for \"{query}\":\n"]
    for r in results:
        lines.append(f"- **{r['title']}** ({r['width']}x{r['height']})")
        lines.append(f"  `{r['style'][:100]}{'...' if len(r['style']) > 100 else ''}`")
    return "\n".join(lines)


@mcp.tool()
@_handle_errors
def gslides_import_drawio(
    presentation_id: str,
    drawio_xml: str,
    title: str = "",
) -> str:
    """Import a draw.io diagram as native editable Google Slides shapes.

    Generate mxGraph XML sized for a slide canvas of 1000x562 pixels (16:9).

    CANVAS: 1000x562 px. GRID: x = col*160+40, y = row*100+40.
    SHAPES: Rectangles 130x55, Diamonds 100x70, Cylinders 90x65.
    CONTAINERS: swimlane;startSize=25 with children using relative coords.
    EDGES: Always include <mxGeometry relative="1" as="geometry"/>.
    Connectors auto-route to closest edges via RerouteLineRequest.

    MODERN STYLE GUIDE (2025-2026):
    Color palette (draw.io defaults — proven professional):
      Blue:   fillColor=#dae8fc;strokeColor=#6c8ebf
      Green:  fillColor=#d5e8d4;strokeColor=#82b366
      Orange: fillColor=#ffe6cc;strokeColor=#d79b00
      Yellow: fillColor=#fff2cc;strokeColor=#d6b656
      Red:    fillColor=#f8cecc;strokeColor=#b85450
      Purple: fillColor=#e1d5e7;strokeColor=#9673a6
      Gray:   fillColor=#f5f5f5;strokeColor=#666666
    For dark-fill shapes (headers/accents): fontColor=#FFFFFF
    Shapes: rounded=1;whiteSpace=wrap;html=1;strokeWidth=1.5 on ALL shapes
    Text: fontColor=#333333 (NEVER #000000), fontSize=8-10, titles=10-12
    Connectors: thin (strokeWidth=1), color=#666666, curved preferred
    Database: shape=cylinder3;boundedLbl=1;size=15
    Containers: dashed=1;strokeWidth=2;fillColor=none;fontStyle=1
    AVOID: sharp corners, saturated colors, thick borders, drop shadows, gradients
    Use gslides_search_shapes for exact draw.io style strings

    Also supports importing existing draw.io files (auto-scales to fit).

    Args:
        presentation_id: The presentation ID
        drawio_xml: The draw.io mxGraph XML content
        title: Optional slide title
    """
    result = slides_service.import_drawio(presentation_id, drawio_xml, title)
    return f"Imported diagram: **{result['title'] or '(untitled)'}** — {result['shapes']} shapes, {result['connectors']} connectors (`{result['slide_id']}`)"


@mcp.tool()
@_handle_errors
def gslides_replace_text(presentation_id: str, find: str, replace: str) -> str:
    """Find and replace text across all slides. Useful for template fill workflows.

    Create a presentation with placeholders like {{company_name}}, then replace them.

    Args:
        presentation_id: The presentation ID
        find: Text to search for (case-sensitive)
        replace: Replacement text
    """
    result = slides_service.replace_text(presentation_id, find, replace)
    return f"Replaced {result['occurrences_replaced']} occurrence(s) of `{find}`"


@mcp.tool()
@_handle_errors
def gslides_replace_image(
    presentation_id: str,
    placeholder_text: str,
    image_url: str,
) -> str:
    """Replace all shapes containing placeholder text with an image.

    For template workflows: create shapes with text like {{logo}}, then replace with actual images.
    The image takes the shape's size and position.

    Args:
        presentation_id: The presentation ID
        placeholder_text: Text in shapes to replace (case-sensitive)
        image_url: URL of the replacement image
    """
    result = slides_service.replace_image(presentation_id, placeholder_text, image_url)
    return f"Replaced {result['occurrences_replaced']} shape(s) containing `{placeholder_text}` with image"


@mcp.tool()
@_handle_errors
def gslides_set_speaker_notes(
    presentation_id: str,
    slide_id: str,
    notes: str,
) -> str:
    """Set speaker notes on a slide.

    Args:
        presentation_id: The presentation ID
        slide_id: The slide object ID (from gslides_read)
        notes: Speaker notes text
    """
    result = slides_service.set_speaker_notes(presentation_id, slide_id, notes)
    return f"Set speaker notes on slide `{result['slide_id']}`"


@mcp.tool()
@_handle_errors
def gslides_duplicate_slide(presentation_id: str, slide_id: str) -> str:
    """Duplicate (clone) a slide within the same presentation.

    Args:
        presentation_id: The presentation ID
        slide_id: The slide object ID to duplicate
    """
    result = slides_service.duplicate_slide(presentation_id, slide_id)
    return f"Duplicated slide `{result['original']}` → `{result['duplicate']}`"


@mcp.tool()
@_handle_errors
def gslides_add_title_slide(
    presentation_id: str,
    title: str,
    subtitle: str = "",
    author: str = "",
    theme: str = "modern",
) -> str:
    """Add a professional title slide with centered title, subtitle, and author.

    Args:
        presentation_id: The presentation ID
        title: Main title text
        subtitle: Optional subtitle
        author: Optional author/date line
        theme: Color theme — modern, corporate, dark, warm
    """
    result = slides_service.add_title_slide(presentation_id, title, subtitle, author, theme)
    return f"Added title slide: **{result['title']}** (`{result['slide_id']}`)"


@mcp.tool()
@_handle_errors
def gslides_add_section_slide(
    presentation_id: str,
    title: str,
    section_number: str = "",
    theme: str = "modern",
) -> str:
    """Add a section divider slide with accent-colored background.

    Args:
        presentation_id: The presentation ID
        title: Section title
        section_number: Optional section number (e.g. "01", "Part 2")
        theme: Color theme — modern, corporate, dark, warm
    """
    result = slides_service.add_section_slide(presentation_id, title, section_number, theme)
    return f"Added section slide: **{result['title']}** (`{result['slide_id']}`)"


@mcp.tool()
@_handle_errors
def gslides_add_two_column_slide(
    presentation_id: str,
    title: str,
    col1: str,
    col2: str,
    col1_title: str = "",
    col2_title: str = "",
    theme: str = "modern",
) -> str:
    """Add a two-column content slide with proper gutter spacing.

    Args:
        presentation_id: The presentation ID
        title: Slide title
        col1: Left column text (multi-line for bullets)
        col2: Right column text
        col1_title: Optional left column heading
        col2_title: Optional right column heading
        theme: Color theme
    """
    result = slides_service.add_two_column_slide(
        presentation_id, title, col1, col2, col1_title, col2_title, theme)
    return f"Added two-column slide: **{result['title']}** (`{result['slide_id']}`)"


@mcp.tool()
@_handle_errors
def gslides_add_image_text_slide(
    presentation_id: str,
    title: str,
    image_url: str,
    text: str,
    image_side: str = "left",
    theme: str = "modern",
) -> str:
    """Add a slide with image on one side and text on the other.

    Args:
        presentation_id: The presentation ID
        title: Slide title
        image_url: Public image URL
        text: Text content (multi-line supported)
        image_side: "left" or "right" — where to place the image
        theme: Color theme
    """
    result = slides_service.add_image_text_slide(
        presentation_id, title, image_url, text, image_side, theme)
    return f"Added image+text slide: **{result['title']}** (`{result['slide_id']}`)"


@mcp.tool()
@_handle_errors
def gslides_add_quote_slide(
    presentation_id: str,
    quote: str,
    attribution: str = "",
    theme: str = "modern",
) -> str:
    """Add a quote slide with accent bar and attribution.

    Args:
        presentation_id: The presentation ID
        quote: Quote text (don't include quotation marks — they're added automatically)
        attribution: Who said it (e.g. "Steve Jobs")
        theme: Color theme
    """
    result = slides_service.add_quote_slide(presentation_id, quote, attribution, theme)
    return f"Added quote slide (`{result['slide_id']}`)"


@mcp.tool()
@_handle_errors
def gslides_add_metrics_slide(
    presentation_id: str,
    title: str,
    metrics: list[dict],
    theme: str = "modern",
) -> str:
    """Add a big-numbers metrics slide (2-4 key metrics displayed prominently).

    metrics: list of objects with "value" and "label" keys.
    Example: [{"value": "98.5%", "label": "Uptime"}, {"value": "4.2M", "label": "Users"}]

    Args:
        presentation_id: The presentation ID
        title: Slide title
        metrics: List of metric objects (max 4) with "value" and "label"
        theme: Color theme
    """
    result = slides_service.add_metrics_slide(presentation_id, title, metrics, theme)
    return f"Added metrics slide: **{result['title']}** ({result['metrics_count']} metrics) (`{result['slide_id']}`)"


@mcp.tool()
@_handle_errors
def gslides_add_styled_table(
    presentation_id: str,
    title: str,
    headers: list[str],
    rows: list[list[str]],
    theme: str = "modern",
) -> str:
    """Add a professionally styled table slide — colored header, alternating rows, borders.

    Args:
        presentation_id: The presentation ID
        title: Slide title
        headers: Column headers
        rows: Data rows
        theme: Color theme — modern (blue), corporate (navy), dark, warm
    """
    result = slides_service.add_styled_table_slide(presentation_id, title, headers, rows, theme)
    return f"Added styled table: **{result['title']}** ({result['table']}) (`{result['slide_id']}`)"


@mcp.tool()
@_handle_errors
def gslides_add_chart_slide(
    presentation_id: str,
    spreadsheet_id: str,
    chart_id: int,
    title: str = "",
    linked: bool = True,
) -> str:
    """Embed a live Google Sheets chart onto a slide.

    The chart_id is returned by gsheets_add_chart. If linked=true, the chart
    updates automatically when the spreadsheet data changes.

    Args:
        presentation_id: The presentation ID
        spreadsheet_id: The source spreadsheet ID
        chart_id: The chart ID (from gsheets_add_chart)
        title: Optional slide title
        linked: Keep chart linked to source data (default true)
    """
    result = slides_service.add_chart_slide(presentation_id, spreadsheet_id, chart_id, title, linked)
    return f"Added chart slide: **{result['title'] or '(chart)'}** (`{result['slide_id']}`)"


@mcp.tool()
@_handle_errors
def gslides_set_background(
    presentation_id: str,
    slide_id: str,
    color: str | None = None,
    image_url: str | None = None,
) -> str:
    """Set a slide's background to a solid color or image.

    Args:
        presentation_id: The presentation ID
        slide_id: The slide object ID
        color: Background color hex (e.g. "#1A1A1A")
        image_url: Background image URL (overrides color)
    """
    result = slides_service.set_slide_background(presentation_id, slide_id, color, image_url)
    return f"Set {result['background']} background on slide `{result['slide_id']}`"


@mcp.tool()
@_handle_errors
def gslides_update_element(
    presentation_id: str,
    element_id: str,
    x: float | None = None,
    y: float | None = None,
    width: float | None = None,
    height: float | None = None,
) -> str:
    """Move or resize any element on a slide. Dimensions in inches.

    Args:
        presentation_id: The presentation ID
        element_id: The element object ID (from gslides_read)
        x: New x position in inches (from left)
        y: New y position in inches (from top)
        width: New width in inches
        height: New height in inches
    """
    result = slides_service.update_element(presentation_id, element_id, x, y, width, height)
    return f"Updated element `{result['element_id']}`"


@mcp.tool()
@_handle_errors
def gslides_z_order(
    presentation_id: str,
    element_ids: list[str],
    operation: str = "BRING_TO_FRONT",
) -> str:
    """Change z-order of elements (layering).

    Args:
        presentation_id: The presentation ID
        element_ids: List of element object IDs
        operation: BRING_TO_FRONT, SEND_TO_BACK, BRING_FORWARD, SEND_BACKWARD
    """
    result = slides_service.z_order(presentation_id, element_ids, operation)
    return f"{result['operation']} applied to {len(result['elements'])} element(s)"


@mcp.tool()
@_handle_errors
def gslides_group(
    presentation_id: str,
    element_ids: list[str],
) -> str:
    """Group multiple elements together.

    Args:
        presentation_id: The presentation ID
        element_ids: List of element object IDs to group (min 2)
    """
    result = slides_service.group_elements(presentation_id, element_ids)
    return f"Grouped {len(result['children'])} elements → `{result['group_id']}`"


@mcp.tool()
@_handle_errors
def gslides_ungroup(
    presentation_id: str,
    group_ids: list[str],
) -> str:
    """Ungroup previously grouped elements.

    Args:
        presentation_id: The presentation ID
        group_ids: List of group object IDs to ungroup
    """
    result = slides_service.ungroup_elements(presentation_id, group_ids)
    return f"Ungrouped {len(result['ungrouped'])} group(s)"


@mcp.tool()
@_handle_errors
def gslides_get_thumbnail(
    presentation_id: str,
    slide_id: str,
    size: str = "LARGE",
) -> str:
    """Get a temporary PNG thumbnail URL for a slide (expires in ~30 minutes).

    Args:
        presentation_id: The presentation ID
        slide_id: The slide object ID (from gslides_read)
        size: LARGE (1600px), MEDIUM (800px), or SMALL (200px)
    """
    result = slides_service.get_slide_thumbnail(presentation_id, slide_id, size)
    return f"Thumbnail ({result['width']}x{result['height']}):\n{result['url']}\n\n(Expires in ~30 minutes)"


# ── Google Drive Tools (shared) ────────────────────────────────────


@mcp.tool()
@_handle_errors
def gdrive_search(query: str, max_results: int = 20) -> str:
    """Search for files in Google Drive.

    Args:
        query: Search query
        max_results: Maximum results (default 20)
    """
    results = drive_service.search_files(query, max_results=max_results)
    if not results:
        return f"No files found for: {query}"
    lines = [f"Found {len(results)} file(s):\n"]
    for f in results:
        lines.append(f"- **{f['name']}** (`{f['id']}`)\n  {f['mime_type']} | {f['modified']}\n  {f['url']}")
    return "\n".join(lines)


@mcp.tool()
@_handle_errors
def gdrive_list_folder(folder_id: str | None = None, max_results: int = 50) -> str:
    """List files in a Google Drive folder.

    Args:
        folder_id: Folder ID (omit for root)
        max_results: Maximum results (default 50)
    """
    results = drive_service.list_folder(folder_id=folder_id, max_results=max_results)
    if not results:
        return "Folder is empty"
    label = f"folder `{folder_id}`" if folder_id else "My Drive"
    lines = [f"Contents of {label} ({len(results)} items):\n"]
    for f in results:
        lines.append(f"- **{f['name']}** (`{f['id']}`)\n  {f['mime_type']} | {f['modified']}")
    return "\n".join(lines)


@mcp.tool()
@_handle_errors
def gdrive_move(file_id: str, folder_id: str) -> str:
    """Move a file to a different Drive folder.

    Args:
        file_id: The file ID
        folder_id: Target folder ID
    """
    result = drive_service.move_file(file_id, folder_id)
    return f"Moved **{result['name']}** to folder `{folder_id}`"


@mcp.tool()
@_handle_errors
def gdrive_delete(file_id: str, confirm: bool = False) -> str:
    """DESTRUCTIVE: Move a file to trash (recoverable 30 days). Requires confirm=true.

    Args:
        file_id: The file ID to delete
        confirm: Must be true to proceed
    """
    if not confirm:
        return "REFUSED: confirm must be true. Ask the user first."
    result = drive_service.trash_file(file_id)
    return f"Trashed **{result['name']}** (`{result['id']}`)"


@mcp.tool()
@_handle_errors
def gdrive_upload(local_path: str, folder_id: str | None = None, name: str | None = None) -> str:
    """Upload a local file to Google Drive.

    Args:
        local_path: Path to the local file
        folder_id: Optional target folder ID
        name: Optional name override
    """
    result = drive_service.upload_file(local_path, name, folder_id)
    return f"Uploaded **{result['name']}** (`{result['id']}`)\n- Type: {result['mime_type']}\n- URL: {result['url']}"


@mcp.tool()
@_handle_errors
def gdrive_export(
    file_id: str,
    format: str = "pdf",
    output_path: str | None = None,
) -> str:
    """Export a Google Workspace file to a local format. Max 10MB.

    Args:
        file_id: The Google Workspace file ID
        format: Export format (pdf, docx, xlsx, pptx, csv, txt, png, jpg, svg)
        output_path: Optional output path
    """
    result = drive_service.export_file(file_id, format, output_path)
    size_kb = result["size"] / 1024
    return f"Exported to **{result['path']}** ({size_kb:.1f} KB)"


@mcp.tool()
@_handle_errors
def gdrive_copy(file_id: str, name: str | None = None, folder_id: str | None = None) -> str:
    """Copy a file (for template workflows).

    Args:
        file_id: The file ID to copy
        name: Optional name for the copy
        folder_id: Optional folder for the copy
    """
    result = drive_service.copy_file(file_id, name, folder_id)
    return f"Copied to **{result['name']}** (`{result['id']}`)\n- URL: {result['url']}"


@mcp.tool()
@_handle_errors
def gdrive_share(
    file_id: str,
    email: str | None = None,
    role: str = "reader",
    anyone: bool = False,
) -> str:
    """Share a file with a user or make it public.

    Args:
        file_id: The file ID
        email: Email to share with (omit if anyone=true)
        role: Permission level (reader, writer, commenter)
        anyone: Make public (anyone with link)
    """
    result = drive_service.share_file(file_id, email, role, anyone)
    return f"Shared with {result['shared_with']} as {result['role']}\n- URL: {result['url']}"


# ── Entry Point ────────────────────────────────────────────────────


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "auth":
        from shared.auth import run_auth_flow
        run_auth_flow()
        return
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
