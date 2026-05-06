# GDriveMcp

**MCP server for Google Docs — create, read, and write formatted documents with Markdown.**

[![License](https://img.shields.io/github/license/DhilipBinny/GDriveMcp)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11+-blue)](https://python.org)
[![MCP](https://img.shields.io/badge/MCP-stdio-green)](https://modelcontextprotocol.io)

---

## About

GDriveMcp connects Claude Code to Google Docs and Google Drive. Write a full Markdown document and it becomes a properly formatted Google Doc in one call — headings, bold, italic, tables, code blocks, bullet lists, and more. No more hand-crafting `batchUpdate` JSON.

Built for engineers who use Claude Code daily and need to create, read, and edit Google Docs without leaving the terminal.

## Features

- **Markdown to Google Docs** — full Markdown rendered as native Google Docs formatting in a single API call
- **13 tools** covering Docs creation, reading, writing, formatting, and Drive file management
- **Rich formatting** — headings, bold, italic, strikethrough, inline code, links, blockquotes
- **Tables** — pipe-format Markdown tables with bold headers
- **Code blocks** — monospace font with grey background (1x1 table styling)
- **Bullet and numbered lists** — including nested lists
- **Find & replace, highlight, audit, cleanup** — document maintenance tools
- **Read as Markdown** — round-trip: write Markdown in, read Markdown out
- **Dual auth** — OAuth 2.0 (personal use) or Service Account (headless/team)
- **Safe delete** — trash with `confirm=true` guard + Claude Code permission prompt

## Tools

### Google Docs (`gdocs_*`)

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

### Google Drive (`gdrive_*`)

| Tool | Description |
|------|-------------|
| `gdrive_search` | Search files by name or content |
| `gdrive_list_folder` | List files in a folder (or root) |
| `gdrive_move` | Move any file to a different folder |
| `gdrive_delete` | Trash a file (recoverable 30 days, requires `confirm=true`) |

## Getting Started

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- A Google Cloud project with **Docs API** and **Drive API** enabled
- An OAuth 2.0 client ID (Desktop type) — download the `client_secret.json`

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
~/.config/gws/client_secret.json               (fallback — reuses gws CLI creds)
```

Then run the one-time auth flow:

```bash
uv run google-docs-mcp auth
```

This opens your browser for Google OAuth. The refresh token is saved to `~/.config/google-docs-mcp/token.json` and auto-refreshes silently — no browser needed again.

### Add to Claude Code

```bash
claude mcp add google-docs -- uv run --directory /path/to/GDriveMcp google-docs-mcp
```

Restart Claude Code. The 13 tools are now available.

### Service Account (headless/team use)

For servers without a browser, use a Google Cloud service account instead:

```bash
export GOOGLE_SERVICE_ACCOUNT_KEY=/path/to/service-account-key.json
export GOOGLE_IMPERSONATE_USER=user@yourdomain.com  # optional, for Workspace
```

## Architecture

```
src/google_docs_mcp/
  server.py            FastMCP server + 13 tool definitions
  auth.py              Dual auth: OAuth 2.0 + Service Account
  markdown_parser.py   Markdown AST -> Google Docs batchUpdate requests
  docs_service.py      Google Docs API wrapper
  drive_service.py     Google Drive API wrapper
  formatter.py         Highlight, cleanup, audit utilities
  utils.py             UTF-16 index math, retry logic, batch helpers
```

### How Markdown-to-Docs Works

1. **Parse** — Markdown text is parsed to an AST using [mistune](https://github.com/lepture/mistune) v3
2. **Generate** — The AST is walked to build Google Docs API `batchUpdate` requests (insert text, apply styles, create bullets, populate table cells)
3. **Apply** — All requests are sent in a single API call, with table cell indices calculated using an empirically verified formula

### Key Design Decisions

- **Named styles over manual formatting** — headings use `HEADING_1`, `HEADING_2`, etc. and inherit the document's own font/spacing defaults
- **Table cell index formula** — empirically verified: `Cell(r,c) paragraph = insertIndex + 4 + r*(2*cols+1) + c*2`
- **Bullet cleanup** — `deleteParagraphBullets` is emitted for all non-list paragraphs to prevent inherited list styles from pre-existing document content
- **Reverse cell insertion** — table cells are populated in reverse order to avoid index shifts

## Roadmap

- [x] Google Docs — full Markdown read/write
- [ ] Google Sheets — read/write spreadsheets
- [ ] Google Slides — create/edit presentations

## Contributing

Bug reports and pull requests are welcome. Please open an issue before submitting large changes.

## License

[MIT](LICENSE)
