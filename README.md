# MCP-GDrive

**Three MCP servers for Google Docs, Sheets, and Slides — 26 consolidated tools for Claude Code.**

[![License](https://img.shields.io/github/license/DhilipBinny/MCP-GDrive)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11+-blue)](https://python.org)
[![MCP](https://img.shields.io/badge/MCP-stdio-green)](https://modelcontextprotocol.io)

---

## What it does

Write a Markdown document and it becomes a formatted Google Doc. Create a spreadsheet with charts, conditional formatting, and data validation. Build a presentation with diagrams from draw.io XML. Upload, export, and share files. Audit and fix existing deck styling. Import themes from templates. All through Claude Code.

## Quick Start

```bash
# 1. Install (no clone needed)
claude mcp add google-docs -- uvx --from git+https://github.com/DhilipBinny/MCP-GDrive google-docs-mcp

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
| `gdocs_write` | write_markdown, append_markdown, insert_at_section, replace, delete_section, add_heading, add_table, insert_image | All content writing operations |
| `gdocs_edit` | highlight, cleanup, audit, page_setup, delete_table_row, update_table_cell | Formatting, quality checks, table edits |

### Google Sheets — 5 tools + 3 Drive

| Tool | Actions | What it does |
|------|---------|-------------|
| `gsheets_create` | — | Create a spreadsheet |
| `gsheets_read` | read, info, find | Read data, get metadata, search cells |
| `gsheets_write` | write, append, clear | Write, append rows, clear ranges |
| `gsheets_format` | style, borders, merge, unmerge, conditional_format, data_validation | All formatting operations |
| `gsheets_manage` | add_sheet, delete_sheet, rename_sheet, duplicate_sheet, freeze, sort, add_chart, delete_chart | Tab management, sorting, charts |

### Google Slides — 8 tools + 3 Drive

| Tool | Actions | What it does |
|------|---------|-------------|
| `gslides_create` | — | Create a presentation |
| `gslides_read` | — | Read all slides with element IDs |
| `gslides_add_slide` | title, section, content, table, metrics, quote, code, two_column, image_text, chart, image, from_layout | 12 slide types + style overrides |
| `gslides_edit` | text_style, shape_fill, table_style, normalize_fonts, brand_kit, hyperlink, move_resize, background | Edit existing elements |
| `gslides_manage` | 20 actions | Delete, duplicate, reorder, group, z-order, replace text, templates, page numbers, thumbnails, table ops |
| `gslides_analyze` | audit, recommend | Audit existing deck styles / get font recommendations |
| `gslides_import` | markdown, drawio | Import from Markdown or draw.io XML |
| `gslides_search_shapes` | — | 58 curated shapes for draw.io diagrams |

### Google Drive (included in each server) — 3 tools

| Tool | Actions | What it does |
|------|---------|-------------|
| `gdrive_search` | — | Search files by name or content |
| `gdrive_list_folder` | — | List folder contents |
| `gdrive_ops` | move, delete, rename, copy, upload, export, share, info, create_folder | All file operations |

## Key Features

### Template Support
Copy an existing branded presentation, clear content, add new slides that inherit the theme:
```
gslides_manage(action="create_from_template") → gslides_manage(action="list_layouts") → gslides_add_slide(type="from_layout")
```

### Brand Kit Enforcement
Audit an existing deck and fix inconsistencies in one call:
```
gslides_analyze(presentation_id) → gslides_edit(action="brand_kit")
```

### Draw.io Diagrams
Generate draw.io XML for visual diagrams, import as native editable Slides shapes:
```
gslides_search_shapes("database") → generate XML → gslides_import(format="drawio")
```

### Image Sidecar
Insert private/local images via Drive upload:
```
gdrive_ops(action="upload") → gdrive_ops(action="share") → insert image → gdrive_ops(action="share" to revoke)
```

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

### Add to Claude Code

```bash
claude mcp add google-docs -- uvx --from git+https://github.com/DhilipBinny/MCP-GDrive google-docs-mcp
claude mcp add google-sheets -- uvx --from git+https://github.com/DhilipBinny/MCP-GDrive google-sheets-mcp
claude mcp add google-slides -- uvx --from git+https://github.com/DhilipBinny/MCP-GDrive google-slides-mcp
```

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
