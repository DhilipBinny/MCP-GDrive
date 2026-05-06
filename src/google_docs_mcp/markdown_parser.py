"""Convert Markdown to Google Docs API batchUpdate requests.

Two-phase approach:
1. Parse markdown to AST via mistune v3
2. Walk AST to build insert + format requests
3. All formatting applied in reverse index order via a single batchUpdate
"""

from __future__ import annotations

import mistune
from mistune.plugins.table import table as table_plugin
from mistune.plugins.formatting import strikethrough as strikethrough_plugin

from shared.utils import utf16_len

PT = "PT"


def _dim(magnitude: float) -> dict:
    return {"magnitude": magnitude, "unit": PT}


class DocsRequestBuilder:
    """Walks a mistune v3 AST and accumulates Google Docs API requests."""

    def __init__(self, start_index: int = 1):
        self._cursor = start_index
        self._insert_requests: list[dict] = []
        self._format_requests: list[dict] = []
        self._bullet_requests: list[dict] = []
        self._delete_bullet_requests: list[dict] = []
        self._pending_list_items: list[dict] = []
        self._bullet_ranges: set[tuple[int, int]] = set()
        self._all_paragraph_ranges: list[tuple[int, int]] = []

    def build(self, markdown: str) -> list[dict]:
        md = mistune.create_markdown(
            renderer="ast",
            plugins=[table_plugin, strikethrough_plugin],
        )
        tokens = md(markdown)
        self._walk_tokens(tokens)
        self._flush_list_items()
        self._build_delete_bullet_requests()
        return (
            self._insert_requests
            + self._format_requests
            + self._bullet_requests
            + self._delete_bullet_requests
        )

    def _build_delete_bullet_requests(self) -> None:
        """Explicitly clear bullet formatting from non-list paragraphs.
        Prevents inherited list styles from pre-existing document content."""
        for start, end in self._all_paragraph_ranges:
            if (start, end) not in self._bullet_ranges:
                self._delete_bullet_requests.append({
                    "deleteParagraphBullets": {
                        "range": {"startIndex": start, "endIndex": end}
                    }
                })

    def _walk_tokens(self, tokens: list[dict]) -> None:
        for token in tokens:
            ttype = token["type"]
            if ttype == "heading":
                self._flush_list_items()
                self._handle_heading(token)
            elif ttype == "paragraph":
                self._flush_list_items()
                self._handle_paragraph(token)
            elif ttype == "list":
                self._handle_list(token, depth=0)
            elif ttype == "thematic_break":
                self._flush_list_items()
                self._handle_thematic_break()
            elif ttype == "block_code":
                self._flush_list_items()
                self._handle_code_block(token)
            elif ttype == "table":
                self._flush_list_items()
                self._handle_table(token)
            elif ttype == "block_quote":
                self._flush_list_items()
                self._handle_block_quote(token)
            elif ttype == "blank_line":
                pass

    def _handle_heading(self, token: dict) -> None:
        level = token["attrs"]["level"]
        style_map = {1: "HEADING_1", 2: "HEADING_2", 3: "HEADING_3", 4: "HEADING_4", 5: "HEADING_5", 6: "HEADING_6"}
        named_style = style_map.get(level, "HEADING_6")

        text, inline_formats = self._extract_inline(token["children"])
        text += "\n"
        start = self._cursor
        end = start + utf16_len(text)

        self._insert_requests.append({"insertText": {"location": {"index": start}, "text": text}})
        self._format_requests.append({
            "updateParagraphStyle": {
                "range": {"startIndex": start, "endIndex": end},
                "paragraphStyle": {"namedStyleType": named_style},
                "fields": "namedStyleType",
            }
        })
        self._apply_inline_formats(start, inline_formats)
        self._all_paragraph_ranges.append((start, end))
        self._cursor = end

    def _handle_paragraph(self, token: dict) -> None:
        children = token.get("children", [])
        if not children:
            return
        text, inline_formats = self._extract_inline(children)
        text += "\n"
        start = self._cursor
        end = start + utf16_len(text)

        self._insert_requests.append({"insertText": {"location": {"index": start}, "text": text}})
        self._format_requests.append({
            "updateParagraphStyle": {
                "range": {"startIndex": start, "endIndex": end},
                "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                "fields": "namedStyleType",
            }
        })
        self._apply_inline_formats(start, inline_formats)
        self._all_paragraph_ranges.append((start, end))
        self._cursor = end

    def _handle_list(self, token: dict, depth: int) -> None:
        ordered = token.get("attrs", {}).get("ordered", False)
        children = token.get("children", [])
        for item in children:
            self._handle_list_item(item, depth, ordered)

    def _handle_list_item(self, token: dict, depth: int, ordered: bool) -> None:
        children = token.get("children", [])
        for child in children:
            if child["type"] in ("paragraph", "block_text"):
                text, inline_formats = self._extract_inline(child.get("children", []))
                text += "\n"
                start = self._cursor
                end = start + utf16_len(text)

                self._insert_requests.append({"insertText": {"location": {"index": start}, "text": text}})
                self._pending_list_items.append({
                    "start": start,
                    "end": end,
                    "depth": depth,
                    "ordered": ordered,
                    "inline_formats": inline_formats,
                })
                self._cursor = end
            elif child["type"] == "list":
                self._handle_list(child, depth + 1)

    def _flush_list_items(self) -> None:
        for item in self._pending_list_items:
            preset = "NUMBERED_DECIMAL_ALPHA_ROMAN" if item["ordered"] else "BULLET_DISC_CIRCLE_SQUARE"
            self._bullet_requests.append({
                "createParagraphBullets": {
                    "range": {"startIndex": item["start"], "endIndex": item["end"]},
                    "bulletPreset": preset,
                }
            })
            self._bullet_ranges.add((item["start"], item["end"]))
            if item["depth"] > 0:
                self._format_requests.append({
                    "updateParagraphStyle": {
                        "range": {"startIndex": item["start"], "endIndex": item["end"]},
                        "paragraphStyle": {"indentStart": _dim(36 * (item["depth"] + 1))},
                        "fields": "indentStart",
                    }
                })
            self._apply_inline_formats(item["start"], item["inline_formats"])
        self._pending_list_items.clear()

    def _handle_block_quote(self, token: dict) -> None:
        children = token.get("children", [])
        for child in children:
            if child["type"] == "paragraph":
                text, inline_formats = self._extract_inline(child.get("children", []))
                text += "\n"
                start = self._cursor
                end = start + utf16_len(text)

                self._insert_requests.append({"insertText": {"location": {"index": start}, "text": text}})
                self._format_requests.append({
                    "updateParagraphStyle": {
                        "range": {"startIndex": start, "endIndex": end},
                        "paragraphStyle": {
                            "namedStyleType": "NORMAL_TEXT",
                            "indentStart": _dim(36),
                            "borderLeft": {
                                "color": {"color": {"rgbColor": {"red": 0.75, "green": 0.75, "blue": 0.75}}},
                                "width": _dim(3),
                                "padding": _dim(10),
                                "dashStyle": "SOLID",
                            },
                        },
                        "fields": "namedStyleType,indentStart,borderLeft",
                    }
                })
                self._format_requests.append({
                    "updateTextStyle": {
                        "range": {"startIndex": start, "endIndex": end},
                        "textStyle": {
                            "foregroundColor": {
                                "color": {"rgbColor": {"red": 0.4, "green": 0.4, "blue": 0.4}}
                            },
                            "italic": True,
                        },
                        "fields": "foregroundColor,italic",
                    }
                })
                self._apply_inline_formats(start, inline_formats)
                self._all_paragraph_ranges.append((start, end))
                self._cursor = end
            elif child["type"] in ("list", "block_quote"):
                self._walk_tokens([child])

    def _handle_thematic_break(self) -> None:
        text = "\n"
        start = self._cursor
        end = start + utf16_len(text)
        self._insert_requests.append({"insertText": {"location": {"index": start}, "text": text}})
        self._format_requests.append({
            "updateParagraphStyle": {
                "range": {"startIndex": start, "endIndex": end},
                "paragraphStyle": {
                    "borderBottom": {
                        "color": {"color": {"rgbColor": {"red": 0.8, "green": 0.8, "blue": 0.8}}},
                        "width": _dim(1),
                        "padding": _dim(6),
                        "dashStyle": "SOLID",
                    }
                },
                "fields": "borderBottom",
            }
        })
        self._cursor = end

    def _handle_code_block(self, token: dict) -> None:
        raw = token.get("raw", "")
        if raw.endswith("\n"):
            text = raw
        else:
            text = raw + "\n"
        start = self._cursor

        # InsertTable at `start` creates: newline para at start, table at start+1
        # For 1x1 table: cell paragraph is at start+4
        self._insert_requests.append({
            "insertTable": {
                "location": {"index": start},
                "rows": 1,
                "columns": 1,
            }
        })
        table_text_index = start + 4
        self._insert_requests.append({"insertText": {"location": {"index": table_text_index}, "text": text}})

        text_end = table_text_index + utf16_len(text)
        self._format_requests.append({
            "updateTextStyle": {
                "range": {"startIndex": table_text_index, "endIndex": text_end},
                "textStyle": {
                    "weightedFontFamily": {"fontFamily": "Courier New"},
                    "fontSize": _dim(9),
                },
                "fields": "weightedFontFamily,fontSize",
            }
        })
        self._format_requests.append({
            "updateTableCellStyle": {
                "tableRange": {
                    "tableCellLocation": {
                        "tableStartLocation": {"index": start + 1},
                        "rowIndex": 0,
                        "columnIndex": 0,
                    },
                    "rowSpan": 1,
                    "columnSpan": 1,
                },
                "tableCellStyle": {
                    "backgroundColor": {
                        "color": {"rgbColor": {"red": 0.95, "green": 0.95, "blue": 0.95}}
                    }
                },
                "fields": "backgroundColor",
            }
        })
        # Cursor after 1x1 table: start + 1 (newline) + 1 (table) + R*(2C+1) + 1 (trailing para)
        # = start + 1 + 1*(2*1+1) + 2 = start + 6
        # Plus the text we inserted shifts things: + utf16_len(text)
        self._cursor = start + 6 + utf16_len(text)

    def _handle_table(self, token: dict) -> None:
        children = token.get("children", [])
        if not children:
            return

        # In mistune v3: table_head contains table_cell children directly (no row wrapper)
        # table_body contains table_row children, each with table_cell children
        all_rows: list[list[str]] = []
        for child in children:
            if child["type"] == "table_head":
                # Head cells are direct children
                cells = []
                for cell in child.get("children", []):
                    if cell["type"] == "table_cell":
                        cell_text, _ = self._extract_inline(cell.get("children", []))
                        cells.append(cell_text)
                if cells:
                    all_rows.append(cells)
            elif child["type"] == "table_body":
                for row in child.get("children", []):
                    cells = []
                    for cell in row.get("children", []):
                        if cell["type"] == "table_cell":
                            cell_text, _ = self._extract_inline(cell.get("children", []))
                            cells.append(cell_text)
                    if cells:
                        all_rows.append(cells)

        if not all_rows:
            return

        num_rows = len(all_rows)
        num_cols = max(len(r) for r in all_rows)
        start = self._cursor

        self._insert_requests.append({
            "insertTable": {
                "location": {"index": start},
                "rows": num_rows,
                "columns": num_cols,
            }
        })

        cell_entries = []
        for r_idx in range(num_rows):
            for c_idx in range(num_cols):
                text = all_rows[r_idx][c_idx] if c_idx < len(all_rows[r_idx]) else ""
                cell_entries.append((r_idx, c_idx, text))

        # Empirically verified cell index formula:
        # InsertTable at `start` creates newline para at start, table at start+1
        # Cell(r,c) paragraph index = start + 4 + r*(2*num_cols+1) + c*2
        cell_indices = []
        for r_idx in range(num_rows):
            for c_idx in range(num_cols):
                idx = start + 4 + r_idx * (2 * num_cols + 1) + c_idx * 2
                cell_indices.append(idx)

        # Insert cell text in reverse order to preserve indices
        for i in range(len(cell_entries) - 1, -1, -1):
            r_idx, c_idx, text = cell_entries[i]
            if text:
                self._insert_requests.append({
                    "insertText": {
                        "location": {"index": cell_indices[i]},
                        "text": text,
                    }
                })
                if r_idx == 0:
                    self._format_requests.append({
                        "updateTextStyle": {
                            "range": {
                                "startIndex": cell_indices[i],
                                "endIndex": cell_indices[i] + utf16_len(text),
                            },
                            "textStyle": {"bold": True},
                            "fields": "bold",
                        }
                    })

        # Cursor after table: start + 1 (newline) + 1 (table structure) +
        # num_rows*(2*num_cols+1) + 1 (trailing para) + total cell text length
        total_text_len = sum(utf16_len(e[2]) for e in cell_entries if e[2])
        self._cursor = start + 2 + num_rows * (2 * num_cols + 1) + 1 + total_text_len

    def _extract_inline(self, children: list[dict]) -> tuple[str, list[dict]]:
        """Extract plain text and inline format markers from AST children."""
        text = ""
        formats: list[dict] = []

        for child in children:
            ctype = child["type"]
            if ctype == "text":
                text += child.get("raw", "")
            elif ctype == "codespan":
                code_text = child.get("raw", child.get("children", ""))
                start_offset = utf16_len(text)
                text += code_text
                end_offset = utf16_len(text)
                formats.append({"type": "code", "start": start_offset, "end": end_offset})
            elif ctype == "strong":
                inner_text, inner_formats = self._extract_inline(child.get("children", []))
                start_offset = utf16_len(text)
                text += inner_text
                end_offset = utf16_len(text)
                formats.append({"type": "bold", "start": start_offset, "end": end_offset})
                for f in inner_formats:
                    formats.append({**f, "start": f["start"] + start_offset, "end": f["end"] + start_offset})
            elif ctype == "emphasis":
                inner_text, inner_formats = self._extract_inline(child.get("children", []))
                start_offset = utf16_len(text)
                text += inner_text
                end_offset = utf16_len(text)
                formats.append({"type": "italic", "start": start_offset, "end": end_offset})
                for f in inner_formats:
                    formats.append({**f, "start": f["start"] + start_offset, "end": f["end"] + start_offset})
            elif ctype == "strikethrough":
                inner_text, inner_formats = self._extract_inline(child.get("children", []))
                start_offset = utf16_len(text)
                text += inner_text
                end_offset = utf16_len(text)
                formats.append({"type": "strikethrough", "start": start_offset, "end": end_offset})
                for f in inner_formats:
                    formats.append({**f, "start": f["start"] + start_offset, "end": f["end"] + start_offset})
            elif ctype == "link":
                link_text, inner_formats = self._extract_inline(child.get("children", []))
                start_offset = utf16_len(text)
                text += link_text
                end_offset = utf16_len(text)
                url = child.get("attrs", {}).get("url", child.get("link", ""))
                formats.append({"type": "link", "start": start_offset, "end": end_offset, "url": url})
                for f in inner_formats:
                    formats.append({**f, "start": f["start"] + start_offset, "end": f["end"] + start_offset})
            elif ctype == "softbreak":
                text += " "
            elif ctype == "linebreak":
                text += "\n"
            elif ctype == "image":
                alt = child.get("attrs", {}).get("alt", "[image]")
                text += alt

        return text, formats

    def _apply_inline_formats(self, base_index: int, formats: list[dict]) -> None:
        for fmt in formats:
            start = base_index + fmt["start"]
            end = base_index + fmt["end"]
            if fmt["type"] == "bold":
                self._format_requests.append({
                    "updateTextStyle": {
                        "range": {"startIndex": start, "endIndex": end},
                        "textStyle": {"bold": True},
                        "fields": "bold",
                    }
                })
            elif fmt["type"] == "italic":
                self._format_requests.append({
                    "updateTextStyle": {
                        "range": {"startIndex": start, "endIndex": end},
                        "textStyle": {"italic": True},
                        "fields": "italic",
                    }
                })
            elif fmt["type"] == "strikethrough":
                self._format_requests.append({
                    "updateTextStyle": {
                        "range": {"startIndex": start, "endIndex": end},
                        "textStyle": {"strikethrough": True},
                        "fields": "strikethrough",
                    }
                })
            elif fmt["type"] == "code":
                self._format_requests.append({
                    "updateTextStyle": {
                        "range": {"startIndex": start, "endIndex": end},
                        "textStyle": {
                            "weightedFontFamily": {"fontFamily": "Courier New"},
                            "backgroundColor": {
                                "color": {"rgbColor": {"red": 0.94, "green": 0.94, "blue": 0.94}}
                            },
                        },
                        "fields": "weightedFontFamily,backgroundColor",
                    }
                })
            elif fmt["type"] == "link":
                self._format_requests.append({
                    "updateTextStyle": {
                        "range": {"startIndex": start, "endIndex": end},
                        "textStyle": {
                            "link": {"url": fmt["url"]},
                            "foregroundColor": {
                                "color": {"rgbColor": {"red": 0.06, "green": 0.36, "blue": 0.72}}
                            },
                            "underline": True,
                        },
                        "fields": "link,foregroundColor,underline",
                    }
                })


def markdown_to_requests(markdown: str, start_index: int = 1) -> list[dict]:
    """Convert markdown text to a list of Google Docs API batchUpdate requests."""
    builder = DocsRequestBuilder(start_index=start_index)
    return builder.build(markdown)
