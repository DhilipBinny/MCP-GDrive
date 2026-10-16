# System Reference — Google Workspace MCP

Where things live in code. Use this when you need to find, modify, or extend a feature.

## Core Concepts

| Concept | Definition | Primary File |
|---------|-----------|-------------|
| MCP Tool | A callable function exposed to Claude via MCP protocol | `src/*/server.py` |
| Action | A sub-operation within a consolidated tool | `src/*/server.py` (routed by `action` parameter) |
| Service | Google API wrapper that handles API calls | `src/*_service.py` + `src/shared/drive_service.py` |
| Design System | Slide layout constants, colors, typography | `src/google_slides_mcp/design.py` |

## Key Files

### Shared (all servers)
| File | Purpose |
|------|---------|
| `src/shared/auth.py` | OAuth 2.0 + service account authentication, keyring storage |
| `src/shared/drive_service.py` | Google Drive API wrapper — search, list, upload, export, share |
| `src/shared/utils.py` | `execute_with_retry()`, color parsing, A1 notation, text measurement |

### Google Docs Server
| File | Purpose |
|------|---------|
| `src/google_docs_mcp/server.py` | 4 tools: `gdocs_create`, `gdocs_read`, `gdocs_write`, `gdocs_edit` |
| `src/google_docs_mcp/docs_service.py` | Docs API wrapper — read/write/format documents |
| `src/google_docs_mcp/formatter.py` | Document content formatting helpers |
| `src/google_docs_mcp/markdown_parser.py` | Markdown → Docs batchUpdate requests (via mistune) |

### Google Sheets Server
| File | Purpose |
|------|---------|
| `src/google_sheets_mcp/server.py` | 5 tools: `gsheets_create/read/write/format/manage` |
| `src/google_sheets_mcp/sheets_service.py` | Sheets API wrapper — read/write/format/chart operations |

### Google Slides Server
| File | Purpose |
|------|---------|
| `src/google_slides_mcp/server.py` | 8 tools: `gslides_create/read/add_slide/edit/manage/analyze/import/search_shapes` |
| `src/google_slides_mcp/slides_service.py` | Slides API wrapper — create/edit/manage slides |
| `src/google_slides_mcp/design.py` | Canvas dimensions, margins, fonts, 4 color palettes |
| `src/google_slides_mcp/drawio_converter.py` | draw.io XML → Slides API shape/connector requests |
| `src/google_slides_mcp/shape_search.py` | Fuzzy search over curated shape index |
| `src/google_slides_mcp/shape-index.json` | 58 curated shapes for draw.io diagrams |

### Google Drive (shared across servers)
| File | Purpose |
|------|---------|
| `src/shared/drive_service.py` | 3 tools: `gdrive_search`, `gdrive_list_folder`, `gdrive_ops` |

## Tool → Code Mapping

### Docs (4 tools + 3 Drive)
| Tool | Server Entry | Service Layer |
|------|-------------|---------------|
| `gdocs_create` | `server.py:gdocs_create()` | `docs_service.create_document()` |
| `gdocs_read` | `server.py:gdocs_read()` | `docs_service.read_document*()` |
| `gdocs_write` | `server.py:gdocs_write()` | `docs_service.*` + `markdown_parser.*` |
| `gdocs_edit` | `server.py:gdocs_edit()` | `docs_service.*` + `formatter.*` |

### Sheets (5 tools + 3 Drive)
| Tool | Server Entry | Service Layer |
|------|-------------|---------------|
| `gsheets_create` | `server.py:gsheets_create()` | `sheets_service.create_spreadsheet()` |
| `gsheets_read` | `server.py:gsheets_read()` | `sheets_service.read*()` |
| `gsheets_write` | `server.py:gsheets_write()` | `sheets_service.write*()` |
| `gsheets_format` | `server.py:gsheets_format()` | `sheets_service.*_format*()` |
| `gsheets_manage` | `server.py:gsheets_manage()` | `sheets_service.*()` |

### Slides (8 tools + 3 Drive)
| Tool | Server Entry | Service Layer |
|------|-------------|---------------|
| `gslides_create` | `server.py:gslides_create()` | `slides_service.create_presentation()` |
| `gslides_read` | `server.py:gslides_read()` | `slides_service.read_presentation()` |
| `gslides_add_slide` | `server.py:gslides_add_slide()` | `slides_service.add_slide()` |
| `gslides_edit` | `server.py:gslides_edit()` | `slides_service.*()` |
| `gslides_manage` | `server.py:gslides_manage()` | `slides_service.*()` |
| `gslides_analyze` | `server.py:gslides_analyze()` | `slides_service.audit/recommend()` |
| `gslides_import` | `server.py:gslides_import()` | `drawio_converter.*` + `slides_service.*` |
| `gslides_search_shapes` | `server.py:gslides_search_shapes()` | `shape_search.search()` |

## Common Tasks

### To add a new action to an existing tool
1. Add the action name to the `Literal[...]` type in the tool's `action` parameter
2. Add the routing branch in the tool function body
3. Implement the service method in `*_service.py`
4. Update the tool's docstring to document the new action
5. Add tests in `tests/`

### To add a new tool to a server
1. Define the function in `server.py` with `@mcp.tool()` decorator
2. Add `ToolAnnotations` (readOnlyHint, destructiveHint, etc.)
3. Wrap with `@_handle_errors`
4. Implement service methods in `*_service.py`
5. Update README tool table

### To add a new server
1. Create `src/new_server_mcp/` with `__init__.py`, `server.py`, `*_service.py`
2. Add `py.typed` marker
3. Register entry point in `pyproject.toml` under `[project.scripts]`
4. Add to `[tool.hatch.build.targets.wheel]` packages list
5. Import and register Drive tools from `shared/drive_service.py`
6. Update README, CHANGELOG

## Shared Utilities

| Function | File | Purpose |
|----------|------|---------|
| `execute_with_retry()` | `shared/utils.py` | Exponential backoff for Google API calls (429/5xx) |
| `hex_to_rgb()` / `rgb_to_hex()` | `shared/utils.py` | Color format conversion |
| `utf16_len()` | `shared/utils.py` | Google Docs UTF-16 index calculation |
| `reverse_requests()` | `shared/utils.py` | Sort batchUpdate requests by index (descending) |
| `batch_update()` | `shared/utils.py` | Send Docs batchUpdate with auto-ordering |
| `estimate_text_width_pt()` | `shared/utils.py` | Text width estimation for slide layout |
| `parse_a1_range()` | `shared/utils.py` | A1 notation → GridRange for Sheets |
| `parse_values()` | `shared/utils.py` | Accept values as list[list] or JSON string |
| `resolve_sheet_id()` | `shared/utils.py` | Sheet name → numeric sheetId |
| `get_credentials()` | `shared/auth.py` | Get valid Google credentials (service account or OAuth) |
