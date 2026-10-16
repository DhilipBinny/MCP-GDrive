# Google Workspace MCP

Three MCP servers for Google Docs, Sheets, and Slides — 26 tools, 110+ actions for Claude Code.

## Tech Stack
- **Language:** Python 3.11+
- **Package manager:** uv
- **MCP framework:** FastMCP (mcp>=1.0.0, stdio transport)
- **Google APIs:** google-api-python-client, google-auth-oauthlib
- **Markdown parsing:** mistune 3.x (Docs server)
- **Linting:** ruff
- **Type checking:** mypy
- **Testing:** pytest

## Project Structure
```
src/
├── shared/                    # Cross-server shared code
│   ├── auth.py                # OAuth 2.0 + service account authentication
│   ├── drive_service.py       # Google Drive API wrapper (search, upload, export, share)
│   └── utils.py               # Retry logic, color parsing, A1 notation, text measurement
├── google_docs_mcp/
│   ├── server.py              # MCP tools: gdocs_create, gdocs_read, gdocs_write, gdocs_edit
│   ├── docs_service.py        # Google Docs API wrapper
│   ├── formatter.py           # Document content formatting
│   └── markdown_parser.py     # Markdown → Google Docs batchUpdate requests
├── google_sheets_mcp/
│   ├── server.py              # MCP tools: gsheets_create, gsheets_read, gsheets_write, gsheets_format, gsheets_manage
│   └── sheets_service.py      # Google Sheets API wrapper
├── google_slides_mcp/
│   ├── server.py              # MCP tools: gslides_create, gslides_read, gslides_add_slide, gslides_edit, gslides_manage, gslides_analyze, gslides_import, gslides_search_shapes
│   ├── slides_service.py      # Google Slides API wrapper
│   ├── design.py              # Slide design system (colors, typography, layout constants)
│   ├── drawio_converter.py    # draw.io XML → Slides API requests
│   ├── shape_search.py        # Shape index search for draw.io diagrams
│   └── shape-index.json       # 58 curated shapes for diagram creation
tests/
├── test_utils.py              # Tests for shared utilities
```

## Commands
```bash
# Install dependencies
uv sync

# Install with dev tools
uv sync --extra dev

# Run linter
uv run ruff check src/

# Run formatter
uv run ruff format src/

# Run type checker
uv run mypy src/

# Run tests
uv run pytest tests/ -v

# Run a server directly (for testing)
PYTHONPATH=src uv run python -m google_docs_mcp.server

# Authenticate (one-time)
uvx --from . google-docs-mcp auth
```

## Key Patterns

### Action-Based Dispatch
Each server uses consolidated tools with an `action` parameter instead of one tool per operation. This reduces LLM context usage.

### Service Layer Separation
`server.py` defines MCP tools → delegates to `*_service.py` for Google API calls → uses `shared/utils.py` for retry/parsing.

### Credential Tracking
Each service module caches the API client and rebuilds it when credentials change (token refresh). Pattern: `_service` + `_service_creds` globals.

### Error Handling
All tools wrapped with `@_handle_errors` — catches `HttpError`, returns human-readable messages.

## Environment Variables
| Variable | Required | Description |
|----------|----------|-------------|
| `GOOGLE_SERVICE_ACCOUNT_KEY` | No | Path to service account JSON (headless mode) |
| `GOOGLE_IMPERSONATE_USER` | No | Email to impersonate with service account |

OAuth tokens stored in OS keyring (macOS Keychain / Windows Credential Locker / Linux libsecret) with file fallback at `~/.config/google-workspace-mcp/token.json`.

## Git Rules
- No `Co-Authored-By` or AI attribution in commits
- Imperative subject line, ≤72 chars
- One logical change per commit
- Run `uv run ruff check src/` and `uv run pytest tests/ -v` before committing
