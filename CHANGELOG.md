# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.3.0] - 2025-07-15

### Added

- **Table operations** in Docs: `add_table_row`, `delete_table`, and `style_table` actions for full table lifecycle management
- **Text formatting** in Docs: `text_color` action for font color changes with hex codes, `set_font` action for font family changes (per-text or whole document)
- **Headers and footers** in Docs: `add_header` and `add_footer` actions with alignment control (idempotent -- replaces existing content)
- **Page breaks** in Docs: `insert_page_break` action to force page breaks before specific headings
- **Section targeting** in Docs: `parent_heading` and `occurrence` parameters to disambiguate repeated heading names across read, write, and edit operations
- **Image placement** in Docs: `after_text` and `index` parameters for precise inline image positioning
- **Read format** in Sheets: `read_format` action to inspect cell formatting (colors, fonts, borders, merges, number formats)
- **Conditional format lifecycle** in Sheets: `list_conditional_formats` action to view existing rules, `delete_conditional_format` action to remove rules by index
- **Date format** in Sheets: `date_format` parameter on `gsheets_write` to apply date number formats during write
- **Row and column operations** in Sheets: `insert_rows`, `delete_rows`, `insert_columns`, `delete_columns` actions for structural edits
- **Table column operations** in Slides: `insert_table_columns` and `delete_table_column` actions for table structure editing
- **Video embedding** in Slides: `create_video` action for embedding YouTube or Google Drive videos on slides
- **MCP tool annotations** across all servers: `readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint` on every tool

### Fixed

- **Stale service connections**: Drive, Docs, Sheets, and Slides services now track credential freshness and rebuild on token refresh
- **Pagination**: Drive file listing now paginates correctly instead of returning only the first page
- **Path sanitization**: export file paths sanitized to prevent directory traversal
- **Chart ID handling**: `chart_id` parameter now correctly typed as integer throughout Sheets server
- **Find in sheet bounds**: `find_in_sheet` search no longer fails on sheets with fewer columns than the search range
- **Table object IDs**: Slides table elements now expose correct `object_id` for downstream styling
- **Speaker notes**: notes now applied to all slide types, not just content slides
- **Header font size**: `header_font_size` parameter in Slides `table_style` correctly controls header text size independent of cell text
- **Insert index race**: Docs write operations use `_safe_insert_index` to avoid inserting inside table boundaries
- **Read format cell refs**: Sheets `read_format` now returns absolute cell references (e.g. `Sheet1!A1`) instead of relative offsets
- **Header/footer idempotent**: `add_header` and `add_footer` now replace existing content instead of duplicating
- **Parameter overloading**: resolved ambiguous parameter reuse across actions in Slides server (e.g. `find` used for both search and target presentation)
- **Docstring mismatch**: tool docstrings now match actual parameter names and accepted values
- **Format rename**: `gslides_import` parameter renamed from `format` to `import_format` to avoid shadowing Python builtin
- **Redundant API calls**: eliminated unnecessary `get_presentation` calls in Slides service methods that already have the data

### Changed

- Extracted shared helper functions (`_safe_insert_index`, `utf16_len`) to reduce code duplication
- Service credential tracking: all service modules now detect stale credentials and rebuild API clients
- Import cleanup: removed unused imports and dead code across all server modules

## [0.2.0] - 2025-03-01

### Added

- Initial release with three MCP servers: Google Docs, Google Sheets, and Google Slides
- Consolidated action-based tool dispatch (26 tools instead of 115 individual tools)
- Google Docs: create, read (full/section/structure), write (markdown/append/replace/delete), edit (highlight/cleanup/audit/page setup/table edits)
- Google Sheets: create, read (data/info/find), write (write/append/clear), format (style/borders/merge/conditional/validation), manage (tabs/freeze/sort/charts)
- Google Slides: create, read, add slides (12 types with 4 code styles), edit (text/shape/table/fonts/brand kit), manage (25+ structural operations), analyze (audit/recommend), import (markdown/draw.io), shape search (58 curated shapes)
- Google Drive tools shared across all servers: search, list folder, file operations (move/delete/rename/copy/upload/export/share/info/create folder)
- Cross-platform authentication with OS keyring storage and file fallback
- Service account support for headless and team deployments
- Design system with 4 color themes (modern, corporate, dark, warm)
- Draw.io diagram import with auto-scaling text fitting and connector routing
- Cross-presentation slide cloning and element copying
- Auto-align and distribute elements on slides
- Style audit with overflow detection, alignment checks, and brand kit enforcement
- Color palette guidance with 60/30/10 rule and WCAG contrast requirements
