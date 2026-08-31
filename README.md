# MCP-GDrive

**Three MCP servers for Google Docs, Sheets, and Slides — 26 tools, 110+ actions for Claude Code.**

[![License](https://img.shields.io/github/license/DhilipBinny/MCP-GDrive)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11+-blue)](https://python.org)
[![MCP](https://img.shields.io/badge/MCP-stdio-green)](https://modelcontextprotocol.io)

---

## What it does

Write Markdown and it becomes a formatted Google Doc. Create spreadsheets with charts, conditional formatting, and data validation. Build presentations with native editable diagrams from draw.io XML. Copy slides and elements across presentations. Auto-align shapes, audit styling, enforce brand kits. Upload, export, and share files. All through Claude Code.

## Quick Start

```bash
# 1. Install (no clone needed)
claude mcp add google-docs -- uvx --from git+https://github.com/DhilipBinny/MCP-GDrive google-docs-mcp
claude mcp add google-sheets -- uvx --from git+https://github.com/DhilipBinny/MCP-GDrive google-sheets-mcp
claude mcp add google-slides -- uvx --from git+https://github.com/DhilipBinny/MCP-GDrive google-slides-mcp

# 2. Authenticate (one-time, opens browser)
uvx --from git+https://github.com/DhilipBinny/MCP-GDrive google-docs-mcp auth

# 3. Restart Claude Code — done
```

## Architecture: Consolidated Tools

Each server uses **action-based dispatch** — fewer tools, same capability, less LLM context bloat.

### Google Docs — 4 tools + 3 Drive

| Tool | Actions | What it does |
|------|---------|-------------|
| `gdocs_create` | — | Create a new doc |
| `gdocs_read` | full, section, structure | Read content, specific sections, or document outline |
| `gdocs_write` | write_markdown, append_markdown, insert_at_section, replace, delete_section, add_heading, add_table, add_table_row, delete_table, insert_image, insert_page_break | All content writing operations |
| `gdocs_edit` | highlight, text_color, set_font, add_header, add_footer, cleanup, audit, page_setup, style_table, delete_table_row, update_table_cell | Formatting, text styling, headers/footers, table edits |

### Google Sheets — 5 tools + 3 Drive

| Tool | Actions | What it does |
|------|---------|-------------|
| `gsheets_create` | — | Create a spreadsheet |
| `gsheets_read` | read, info, find, read_format, list_conditional_formats | Read data, metadata, search cells, inspect formatting |
| `gsheets_write` | write, append, clear | Write, append rows, clear ranges. date_format parameter for date display |
| `gsheets_format` | style, borders, merge, unmerge, conditional_format, delete_conditional_format, data_validation | Formatting with vertical alignment and wrap strategy |
| `gsheets_manage` | add_sheet, delete_sheet, rename_sheet, duplicate_sheet, freeze, auto_resize, sort, add_chart, delete_chart, insert_rows, delete_rows, insert_columns, delete_columns | Tab management, column auto-sizing, charts, row/column operations |

### Google Slides — 8 tools + 3 Drive

| Tool | Actions | What it does |
|------|---------|-------------|
| `gslides_create` | — | Create a presentation |
| `gslides_read` | — | Read all slides with element IDs |
| `gslides_add_slide` | title, section, content, table, metrics, quote, code, two_column, image_text, chart, image, blank, from_layout | 13 slide types. Code blocks: dark/terminal/light/notebook styles |
| `gslides_edit` | text_style, shape_fill, table_style, normalize_fonts, brand_kit, hyperlink, move_resize, background | Edit existing elements, enforce brand consistency |
| `gslides_manage` | 27 actions | Slides: delete, duplicate, reorder, clone_slide (cross-deck). Elements: copy_element, align, get_image_url. Templates, page numbers, thumbnails, table ops, video embedding |
| `gslides_analyze` | audit, recommend | Style audit with overflow detection, alignment checks, title consistency. Color palette recommendations with 60/30/10 guidance |
| `gslides_import` | markdown, drawio | Import from Markdown or draw.io XML with auto-scaling text fitting |
| `gslides_search_shapes` | — | 58 curated shapes for draw.io diagrams |

### Google Drive (included in each server) — 3 tools

| Tool | Actions | What it does |
|------|---------|-------------|
| `gdrive_search` | — | Search files by name or content |
| `gdrive_list_folder` | — | List folder contents |
| `gdrive_ops` | move, delete, rename, copy, upload, export, share, info, create_folder | All file operations |

## Key Features

### Draw.io Diagrams
Generate draw.io XML for visual diagrams — the only path for creating diagrams. Auto-scales to fit slides with char-aware text fitting (no overflow). Supports connectors with auto-routing, edge labels, bidirectional arrows, and text alignment.
```
gslides_search_shapes("database") -> generate XML -> gslides_import(format="drawio")
```

### Cross-Presentation Copy
Clone slides or individual elements between presentations. Extract image URLs for reuse.
```
gslides_manage(action="clone_slide", slide_id="...", find="target_pres_id")
gslides_manage(action="copy_element", element_id="...", slide_id="target_slide")
gslides_manage(action="get_image_url", element_id="...")
```

### Auto-Align and Distribute
Detect misaligned shapes on a slide and snap them to rows with equal spacing — like draw.io's Arrange panel.
```
gslides_manage(action="align", slide_id="...", operation="auto")
```
Modes: auto, align_left, align_center, align_right, align_top, align_middle, align_bottom, distribute_h, distribute_v.

### Style Audit + Brand Kit
Audit an existing deck for font inconsistency, text overflow, misaligned elements, title positioning, and table width. Fix everything with one brand_kit call.
```
gslides_analyze(presentation_id) -> gslides_edit(action="brand_kit", accent_color="#4f46e5")
```

### Color Palette Guidance
Built-in 60/30/10 color rule with mood-to-color mapping and WCAG contrast requirements. Four themes: modern, corporate, dark, warm.
```
gslides_analyze(content_type="content", audience="business")
```

### Text Formatting
Change font color, font family, and add document headers/footers with alignment control.
```
gdocs_edit(action="text_color", text="Important", color="#811a1b")
gdocs_edit(action="set_font", font_family="Georgia")
gdocs_edit(action="add_header", text="Confidential", alignment="right")
gdocs_edit(action="add_footer", text="Page 1", alignment="center")
```

### Section Targeting
Disambiguate repeated heading names using `parent_heading` and `occurrence` parameters. Works across read, write, and edit operations.
```
gdocs_read(action="section", heading_text="Change History", parent_heading="Server B")
gdocs_write(action="insert_page_break", before_heading="CPU", occurrence=2)
```

### Template Support
Copy an existing branded presentation, clear content, add new slides that inherit the theme:
```
gslides_manage(action="create_from_template") -> list_layouts -> add_slide(type="from_layout")
```

### Image Sidecar
Insert private/local images via Drive upload:
```
gdrive_ops(action="upload") -> gdrive_ops(action="share") -> insert image -> revoke share
```

## Design System

All slides use a consistent design system (`design.py`):
- Canvas: 9,144,000 x 5,143,500 EMU (10" x 5.625" at 914,400 EMU/inch)
- Margins: 0.75" sides, 0.5" top/bottom
- Typography: Montserrat (headings), Open Sans (body), Roboto Mono (code)
- Four palettes: modern, corporate, dark, warm — each with 60/30/10 role mapping

## Setup

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- A Google Cloud project with Docs, Sheets, Slides, and Drive APIs enabled
- An OAuth 2.0 client ID (Desktop type)

### Authenticate

Place your OAuth client secret at the platform-correct config path:

| OS | Path |
|----|------|
| Linux | `~/.config/google-workspace-mcp/client_secret.json` |
| macOS | `~/Library/Application Support/google-workspace-mcp/client_secret.json` |
| Windows | `%APPDATA%\google-workspace-mcp\client_secret.json` |

Run the one-time auth flow:

```bash
uvx --from git+https://github.com/DhilipBinny/MCP-GDrive google-docs-mcp auth
```

Token saved to OS keyring (macOS Keychain, Windows Credential Locker, Linux libsecret) with file fallback.

### Service Account (headless/team)

```bash
export GOOGLE_SERVICE_ACCOUNT_KEY=/path/to/service-account-key.json
export GOOGLE_IMPERSONATE_USER=user@yourdomain.com  # optional
```

## Dependencies

| Package | Purpose |
|---------|---------|
| `mcp` | MCP server framework (FastMCP, stdio) |
| `google-api-python-client` | Google Workspace API client |
| `google-auth-oauthlib` | OAuth 2.0 browser login |
| `google-auth-httplib2` | HTTP transport |
| `mistune` | Markdown parser (Docs only) |
| `platformdirs` | OS-correct config paths |
| `keyring` | Secure token storage |

## Contributing

Bug reports and pull requests welcome. Open an issue before large changes.

## License

[MIT](LICENSE)
