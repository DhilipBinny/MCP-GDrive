# Google Workspace MCP

**Three MCP servers for Google Docs, Sheets, and Slides — 52 tools for Claude Code.**

[![License](https://img.shields.io/github/license/DhilipBinny/GDriveMcp)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11+-blue)](https://python.org)
[![MCP](https://img.shields.io/badge/MCP-stdio-green)](https://modelcontextprotocol.io)

---

## About

Three focused MCP servers that give Claude Code full access to Google Workspace. Write formatted documents with Markdown, manage spreadsheets with charts and formulas, and create presentations with diagrams — all from the terminal.

## Servers

### Google Docs MCP — 13 tools

| Tool | Description |
|------|-------------|
| `gdocs_create` | Create a new doc, optionally in a folder |
| `gdocs_write_markdown` | Replace doc content with formatted Markdown |
| `gdocs_append_markdown` | Append formatted Markdown to end of doc |
| `gdocs_read` | Read doc as text, Markdown, or structural outline |
| `gdocs_add_table` | Insert a formatted table with headers and rows |
| `gdocs_replace` | Find and replace text (case-sensitive) |
| `gdocs_highlight` | Highlight text occurrences in a color |
| `gdocs_cleanup` | Remove consecutive blank paragraphs |
| `gdocs_audit` | Report on formatting quality, fonts, headings |
| `gdrive_search` | Search files by name or content |
| `gdrive_list_folder` | List files in a folder |
| `gdrive_move` | Move any file to a different folder |
| `gdrive_delete` | Trash a file (recoverable 30 days, requires `confirm=true`) |

### Google Sheets MCP — 19 tools

| Tool | Description |
|------|-------------|
| `gsheets_create` | Create spreadsheet with optional tab names + folder |
| `gsheets_get_info` | List tabs with row/col counts, title, URL |
| `gsheets_read` | Read range as markdown table (formatted/raw/formula) |
| `gsheets_write` | Write 2D array to a range (supports formulas, dates) |
| `gsheets_append` | Append rows after last data |
| `gsheets_clear` | Clear values in range (keeps formatting) |
| `gsheets_find` | Search text across all cells/sheets |
| `gsheets_format` | Bold, italic, colors, alignment, number format |
| `gsheets_add_sheet` | Add a new tab |
| `gsheets_delete_sheet` | Delete a tab |
| `gsheets_rename_sheet` | Rename a tab |
| `gsheets_freeze` | Freeze rows/columns + auto-resize |
| `gsheets_sort` | Sort data by column |
| `gsheets_add_chart` | Insert chart (COLUMN, BAR, LINE, AREA, SCATTER, PIE, DONUT) |
| `gsheets_delete_chart` | Delete a chart by ID |
| `gdrive_search` | Search files |
| `gdrive_list_folder` | List folder contents |
| `gdrive_move` | Move file to folder |
| `gdrive_delete` | Trash file (confirm required) |

### Google Slides MCP — 20 tools

| Tool | Description |
|------|-------------|
| `gslides_create` | Create presentation, optional folder |
| `gslides_read` | Read all slides (text, tables, structure) |
| `gslides_add_slide` | Add slide with title/body/layout |
| `gslides_add_table_slide` | Add slide with formatted table |
| `gslides_add_image_slide` | Add slide with positioned image or background |
| `gslides_delete_slide` | Delete a slide |
| `gslides_add_shape` | Add positioned shape with text and styling |
| `gslides_add_connector` | Connect two shapes with arrow |
| `gslides_add_text_box` | Add positioned text label |
| `gslides_add_diagram` | Create full diagram with auto-positioned nodes |
| `gslides_import_drawio` | Import draw.io XML as native Slides shapes |
| `gslides_search_shapes` | Search curated shape library (58 shapes) |
| `gslides_replace_text` | Find/replace across all slides (template fill) |
| `gslides_replace_image` | Replace placeholder shapes with images |
| `gslides_set_speaker_notes` | Set speaker notes on a slide |
| `gslides_duplicate_slide` | Clone a slide |
| `gdrive_search` | Search files |
| `gdrive_list_folder` | List folder contents |
| `gdrive_move` | Move file to folder |
| `gdrive_delete` | Trash file (confirm required) |

## Getting Started

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- A Google Cloud project with **Docs**, **Sheets**, **Slides**, and **Drive** APIs enabled
- An OAuth 2.0 client ID (Desktop type)

### Install

```bash
git clone https://github.com/DhilipBinny/GDriveMcp.git
cd GDriveMcp
uv sync
```

### Authenticate

Place your OAuth client secret in one of these locations:

```
~/.config/google-docs-mcp/client_secret.json   (preferred)
~/.config/gws/client_secret.json               (fallback)
```

Run the one-time auth flow:

```bash
# If installed from GitHub (Option 1):
uvx --from git+https://github.com/DhilipBinny/MCP-GDrive google-docs-mcp auth

# If using local clone (Option 2):
uv run google-docs-mcp auth
```

This opens your browser for Google OAuth. The token saves to `~/.config/google-docs-mcp/token.json` and auto-refreshes — no browser needed again.

### Add to Claude Code

**Option 1 — Install from GitHub (no clone needed):**

```bash
claude mcp add google-docs -- uvx --from git+https://github.com/DhilipBinny/MCP-GDrive google-docs-mcp
claude mcp add google-sheets -- uvx --from git+https://github.com/DhilipBinny/MCP-GDrive google-sheets-mcp
claude mcp add google-slides -- uvx --from git+https://github.com/DhilipBinny/MCP-GDrive google-slides-mcp
```

**Option 2 — From local clone:**

```bash
git clone https://github.com/DhilipBinny/MCP-GDrive.git
cd MCP-GDrive && uv sync

claude mcp add google-docs -- uv run --directory /path/to/MCP-GDrive google-docs-mcp
claude mcp add google-sheets -- uv run --directory /path/to/MCP-GDrive google-sheets-mcp
claude mcp add google-slides -- uv run --directory /path/to/MCP-GDrive google-slides-mcp
```

Restart Claude Code. The tools are now available.

### Service Account (headless/team use)

For servers without a browser:

```bash
export GOOGLE_SERVICE_ACCOUNT_KEY=/path/to/service-account-key.json
export GOOGLE_IMPERSONATE_USER=user@yourdomain.com  # optional, for Workspace
```

## Architecture

```
src/
  shared/                  Auth, Drive, utilities (shared by all 3 servers)
    auth.py                Dual auth: OAuth 2.0 + Service Account
    drive_service.py       Google Drive API wrapper
    utils.py               Retry logic, color parsing, A1 notation helpers

  google_docs_mcp/         Google Docs server (13 tools)
    server.py              FastMCP tool definitions
    docs_service.py        Google Docs API wrapper
    markdown_parser.py     Markdown AST → Google Docs batchUpdate requests
    formatter.py           Highlight, cleanup, audit utilities

  google_sheets_mcp/       Google Sheets server (19 tools)
    server.py              FastMCP tool definitions
    sheets_service.py      Google Sheets API wrapper

  google_slides_mcp/       Google Slides server (20 tools)
    server.py              FastMCP tool definitions
    slides_service.py      Google Slides API wrapper
    drawio_converter.py    draw.io XML → native Slides shapes converter
    shape_search.py        Curated shape library search (58 shapes)
    shape-index.json       Shape definitions (10KB)
```

### Key Design Decisions

- **Three servers, shared auth** — install only what you need, one OAuth token covers all
- **Markdown-to-Docs engine** — headings, bold, italic, tables, code blocks, bullet lists in one API call
- **draw.io XML import** — Claude generates mxGraph XML, converter creates native Slides shapes with auto-routed connectors via `RerouteLineRequest`
- **Modern style guide** — soft pastel colors, rounded corners, thin strokes (draw.io default palette)
- **Safe delete** — `confirm=true` parameter + Claude Code permission prompt + trash (not permanent)
- **Error handling** — all tools wrapped with actionable error messages, never raw stack traces

## Dependencies

| Package | Why |
|---------|-----|
| `mcp` | FastMCP framework (stdio transport, tool registration) |
| `google-api-python-client` | Google Docs/Sheets/Slides/Drive API client |
| `google-auth-oauthlib` | OAuth 2.0 browser login flow |
| `google-auth-httplib2` | HTTP transport for Google API |
| `mistune` | Markdown parser (Docs server only) |

All dependencies install automatically via `uv sync` or `uvx`.

## Contributing

Bug reports and pull requests are welcome. Please open an issue before submitting large changes.

## License

[MIT](LICENSE)
