# MCP-GDrive

**Three MCP servers for Google Docs, Sheets, and Slides — 82 tools for Claude Code.**

[![License](https://img.shields.io/github/license/DhilipBinny/MCP-GDrive)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11+-blue)](https://python.org)
[![MCP](https://img.shields.io/badge/MCP-stdio-green)](https://modelcontextprotocol.io)

---

## What it does

Write a Markdown document and it becomes a formatted Google Doc. Create a spreadsheet with charts, conditional formatting, and data validation. Build a presentation with diagrams from draw.io XML. Upload, export, and share files. All through Claude Code.

## Quick Start

```bash
# 1. Install (no clone needed)
claude mcp add google-docs -- uvx --from git+https://github.com/DhilipBinny/MCP-GDrive google-docs-mcp

# 2. Authenticate (one-time, opens browser)
uvx --from git+https://github.com/DhilipBinny/MCP-GDrive google-docs-mcp auth

# 3. Restart Claude Code — done
```

## Servers & Tools

### Google Docs — 17 tools

| Tool | What it does |
|------|-------------|
| `gdocs_create` | Create a new doc, optionally in a folder |
| `gdocs_write_markdown` | Write formatted content from Markdown (headings, bold, tables, code blocks, lists) |
| `gdocs_append_markdown` | Append formatted Markdown to existing doc |
| `gdocs_read` | Read as text, Markdown, or structural outline |
| `gdocs_read_section` | Read content from a specific section (by heading text) |
| `gdocs_insert_at_section` | Insert Markdown content before or after a section |
| `gdocs_delete_section` | Delete an entire section (heading + content) |
| `gdocs_add_heading` | Insert heading at a specific position |
| `gdocs_add_table` | Insert table — supports positional insertion (before/after heading) |
| `gdocs_delete_table_row` | Delete a row from a table |
| `gdocs_update_table_cell` | Update a specific table cell |
| `gdocs_insert_image` | Insert inline image from public URL |
| `gdocs_page_setup` | Set document margins |
| `gdocs_replace` | Find/replace — scoped: all, first only, or within a section |
| `gdocs_highlight` | Highlight text in yellow, green, blue, red, orange, or purple |
| `gdocs_cleanup` | Fix formatting: blank paragraphs, style inheritance, bold leaks, table fonts |
| `gdocs_audit` | Report formatting quality — style inheritance, bold leaks, table fonts |

### Google Sheets — 21 tools

| Tool | What it does |
|------|-------------|
| `gsheets_create` | Create spreadsheet with optional tab names |
| `gsheets_get_info` | List tabs with row/column counts |
| `gsheets_read` | Read range as markdown table (formatted, raw, or formula) |
| `gsheets_write` | Write data to a range (formulas, dates, currency) |
| `gsheets_append` | Append rows after last data |
| `gsheets_clear` | Clear values (keeps formatting) |
| `gsheets_find` | Search text across all cells and sheets |
| `gsheets_format` | Bold, italic, colors, alignment, number format, font |
| `gsheets_freeze` | Freeze header rows/columns + auto-resize |
| `gsheets_sort` | Sort data by column |
| `gsheets_conditional_format` | Color-code cells by value (>, <, contains, formula) |
| `gsheets_data_validation` | Dropdowns, number ranges, email validation |
| `gsheets_merge` | Merge cells (MERGE_ALL, MERGE_COLUMNS, MERGE_ROWS) |
| `gsheets_unmerge` | Unmerge previously merged cells |
| `gsheets_borders` | Add cell borders (all, outer, inner, per-side) |
| `gsheets_duplicate_sheet` | Clone a tab |
| `gsheets_add_sheet` | Add a tab |
| `gsheets_delete_sheet` | Delete a tab |
| `gsheets_rename_sheet` | Rename a tab |
| `gsheets_add_chart` | Insert chart (COLUMN, BAR, LINE, AREA, SCATTER, PIE, DONUT) |
| `gsheets_delete_chart` | Delete a chart |

### Google Slides — 17 tools

| Tool | What it does |
|------|-------------|
| `gslides_create` | Create presentation |
| `gslides_read` | Read all slides — text, tables, images, structure |
| `gslides_add_slide` | Add slide with title and body (multi-line becomes bullets) |
| `gslides_add_table_slide` | Add slide with data table (bold headers) |
| `gslides_add_image_slide` | Add slide with image (content or full-slide background) |
| `gslides_add_shape` | Add positioned shape with text and styling |
| `gslides_add_connector` | Connect two shapes with an arrow |
| `gslides_add_text_box` | Add positioned text label |
| `gslides_add_diagram` | Create diagram with auto-positioned nodes and connectors |
| `gslides_import_drawio` | Import draw.io XML as native editable Slides shapes |
| `gslides_search_shapes` | Search 58 curated shapes (flowchart, business, tech) |
| `gslides_get_thumbnail` | Get slide as PNG URL (LARGE/MEDIUM/SMALL) |
| `gslides_replace_text` | Find/replace across all slides (template fill) |
| `gslides_replace_image` | Replace placeholder shapes with images |
| `gslides_set_speaker_notes` | Set speaker notes |
| `gslides_duplicate_slide` | Clone a slide |
| `gslides_delete_slide` | Delete a slide |

### Google Drive (included in each server) — 11 tools

| Tool | What it does |
|------|-------------|
| `gdrive_search` | Search files by name or content |
| `gdrive_list_folder` | List files in a folder |
| `gdrive_get_info` | File metadata — size, owner, sharing status |
| `gdrive_create_folder` | Create a new folder |
| `gdrive_upload` | Upload a local file to Drive |
| `gdrive_export` | Export as PDF, DOCX, XLSX, PPTX, CSV, TXT, PNG, and more |
| `gdrive_copy` | Copy a file (template workflows) |
| `gdrive_share` | Share with a user or make public |
| `gdrive_rename` | Rename a file or folder |
| `gdrive_move` | Move file to a different folder |
| `gdrive_delete` | Trash a file (recoverable 30 days, requires `confirm=true`) |

### Image Workflow (sidecar for private images)

Google APIs require publicly accessible URLs for image insertion. For private/local images:

```
gdrive_upload → gdrive_share (anyone=true) → gdocs_insert_image / gslides_add_image_slide → gdrive_share (revoke)
```

Images are stored server-side after insertion — revoking access afterward is safe.

## Setup

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- A Google Cloud project with these APIs enabled:
  - [Google Docs API](https://console.cloud.google.com/apis/library/docs.googleapis.com)
  - [Google Sheets API](https://console.cloud.google.com/apis/library/sheets.googleapis.com)
  - [Google Slides API](https://console.cloud.google.com/apis/library/slides.googleapis.com)
  - [Google Drive API](https://console.cloud.google.com/apis/library/drive.googleapis.com)
- An OAuth 2.0 client ID (Desktop type) — download the JSON from [APIs & Services → Credentials](https://console.cloud.google.com/apis/credentials)

### Authenticate

Place your OAuth client secret at the platform-correct config path:

| OS | Path |
|----|------|
| Linux | `~/.config/google-workspace-mcp/client_secret.json` |
| macOS | `~/Library/Application Support/google-workspace-mcp/client_secret.json` |
| Windows | `%APPDATA%\google-workspace-mcp\client_secret.json` |

Fallback paths also checked: `~/.config/google-docs-mcp/`, `~/.config/gws/`, `~/.config/google/`.

Run the one-time auth flow:

```bash
# From GitHub install:
uvx --from git+https://github.com/DhilipBinny/MCP-GDrive google-docs-mcp auth

# From local clone:
uv run google-docs-mcp auth
```

This opens your browser. The token is saved to your OS keyring (macOS Keychain, Windows Credential Locker, Linux libsecret) with a file fallback, and auto-refreshes silently.

### Add to Claude Code

**From GitHub (recommended):**

```bash
claude mcp add google-docs -- uvx --from git+https://github.com/DhilipBinny/MCP-GDrive google-docs-mcp
claude mcp add google-sheets -- uvx --from git+https://github.com/DhilipBinny/MCP-GDrive google-sheets-mcp
claude mcp add google-slides -- uvx --from git+https://github.com/DhilipBinny/MCP-GDrive google-slides-mcp
```

**From local clone:**

```bash
git clone https://github.com/DhilipBinny/MCP-GDrive.git
cd MCP-GDrive && uv sync

claude mcp add google-docs -- uv run --directory /path/to/MCP-GDrive google-docs-mcp
claude mcp add google-sheets -- uv run --directory /path/to/MCP-GDrive google-sheets-mcp
claude mcp add google-slides -- uv run --directory /path/to/MCP-GDrive google-slides-mcp
```

Restart Claude Code after adding.

### Service Account (headless/team)

For servers without a browser:

```bash
export GOOGLE_SERVICE_ACCOUNT_KEY=/path/to/service-account-key.json
export GOOGLE_IMPERSONATE_USER=user@yourdomain.com  # optional, for Workspace
```

## Architecture

```
src/
  shared/                  Auth, Drive, utilities (shared by all servers)
    auth.py                Dual auth: OAuth 2.0 + Service Account, OS keyring
    drive_service.py       Upload, export, share, copy, search, move, trash
    utils.py               Retry, hex colors, A1 notation, sheet helpers

  google_docs_mcp/         Docs server (28 tools)
    server.py              MCP tool definitions
    docs_service.py        Docs API — sections, tables, images, margins
    markdown_parser.py     Markdown → Google Docs formatting engine
    formatter.py           Highlight, cleanup, audit (searches tables too)

  google_sheets_mcp/       Sheets server (29 tools)
    server.py              MCP tool definitions
    sheets_service.py      Sheets API — values, formatting, charts, validation

  google_slides_mcp/       Slides server (25 tools)
    server.py              MCP tool definitions
    slides_service.py      Slides API — shapes, connectors, thumbnails
    drawio_converter.py    draw.io XML → Slides shapes (auto-routed connectors)
    shape_search.py        Curated shape library (58 shapes)
```

## Dependencies

| Package | Purpose |
|---------|---------|
| `mcp` | MCP server framework (FastMCP, stdio transport) |
| `google-api-python-client` | Google Workspace API client |
| `google-auth-oauthlib` | OAuth 2.0 browser login |
| `google-auth-httplib2` | HTTP transport |
| `mistune` | Markdown parser (Docs only) |
| `platformdirs` | OS-correct config paths (macOS/Windows/Linux) |
| `keyring` | Secure token storage in OS keyring |

All install automatically via `uv sync` or `uvx`.

## Contributing

Bug reports and pull requests welcome. Open an issue before large changes.

## License

[MIT](LICENSE)
