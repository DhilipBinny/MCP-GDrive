"""Tests for shared.utils — pure functions only (no API calls)."""

import pytest

from shared.utils import (
    col_to_index,
    estimate_text_height_pt,
    estimate_text_width_pt,
    extract_sheet_name,
    hex_to_rgb,
    index_to_col,
    parse_a1_range,
    parse_values,
    quote_sheet_name,
    rgb_to_hex,
    utf16_len,
)


# ---------------------------------------------------------------------------
# utf16_len
# ---------------------------------------------------------------------------

class TestUtf16Len:
    def test_ascii(self):
        assert utf16_len("hello") == 5

    def test_empty(self):
        assert utf16_len("") == 0

    def test_emoji(self):
        # Most emoji are surrogate pairs -> 2 UTF-16 code units each
        assert utf16_len("\U0001f600") == 2  # grinning face

    def test_cjk(self):
        # CJK characters are in the BMP -> 1 UTF-16 code unit each
        assert utf16_len("世界") == 2  # "world" in Chinese

    def test_mixed(self):
        # "A" (1) + emoji (2) + "B" (1) = 4
        assert utf16_len("A\U0001f600B") == 4


# ---------------------------------------------------------------------------
# hex_to_rgb / rgb_to_hex
# ---------------------------------------------------------------------------

class TestHexToRgb:
    def test_black(self):
        result = hex_to_rgb("#000000")
        assert result == {"red": 0.0, "green": 0.0, "blue": 0.0}

    def test_white(self):
        result = hex_to_rgb("#FFFFFF")
        assert result == {"red": 1.0, "green": 1.0, "blue": 1.0}

    def test_red(self):
        result = hex_to_rgb("#FF0000")
        assert result == {"red": 1.0, "green": 0.0, "blue": 0.0}

    def test_three_digit_shorthand(self):
        result = hex_to_rgb("#F00")
        assert result == {"red": 1.0, "green": 0.0, "blue": 0.0}

    def test_three_digit_shorthand_mixed(self):
        result = hex_to_rgb("#ABC")
        expected = hex_to_rgb("#AABBCC")
        assert result == expected

    def test_no_hash(self):
        result = hex_to_rgb("FF0000")
        assert result == {"red": 1.0, "green": 0.0, "blue": 0.0}

    def test_invalid_length(self):
        with pytest.raises(ValueError, match="Invalid hex color"):
            hex_to_rgb("#FFFF")

    def test_with_leading_spaces(self):
        result = hex_to_rgb("  #FF0000  ")
        assert result == {"red": 1.0, "green": 0.0, "blue": 0.0}


class TestRgbToHex:
    def test_black(self):
        assert rgb_to_hex({"red": 0.0, "green": 0.0, "blue": 0.0}) == "#000000"

    def test_white(self):
        assert rgb_to_hex({"red": 1.0, "green": 1.0, "blue": 1.0}) == "#ffffff"

    def test_missing_keys_default_zero(self):
        assert rgb_to_hex({}) == "#000000"

    def test_partial_color(self):
        assert rgb_to_hex({"red": 1.0}) == "#ff0000"


class TestHexRgbRoundtrip:
    def test_roundtrip(self):
        original = "#1a2b3c"
        rgb = hex_to_rgb(original)
        back = rgb_to_hex(rgb)
        assert back == original

    def test_roundtrip_bright(self):
        original = "#ff8800"
        rgb = hex_to_rgb(original)
        back = rgb_to_hex(rgb)
        assert back == original


# ---------------------------------------------------------------------------
# col_to_index / index_to_col
# ---------------------------------------------------------------------------

class TestColToIndex:
    def test_a(self):
        assert col_to_index("A") == 0

    def test_z(self):
        assert col_to_index("Z") == 25

    def test_aa(self):
        assert col_to_index("AA") == 26

    def test_az(self):
        assert col_to_index("AZ") == 51

    def test_ba(self):
        assert col_to_index("BA") == 52

    def test_aaa(self):
        assert col_to_index("AAA") == 702

    def test_lowercase(self):
        assert col_to_index("a") == 0


class TestIndexToCol:
    def test_zero(self):
        assert index_to_col(0) == "A"

    def test_25(self):
        assert index_to_col(25) == "Z"

    def test_26(self):
        assert index_to_col(26) == "AA"

    def test_51(self):
        assert index_to_col(51) == "AZ"

    def test_52(self):
        assert index_to_col(52) == "BA"

    def test_702(self):
        assert index_to_col(702) == "AAA"


class TestColIndexRoundtrip:
    @pytest.mark.parametrize("col", ["A", "Z", "AA", "AZ", "BA", "ZZ", "AAA"])
    def test_roundtrip(self, col):
        assert index_to_col(col_to_index(col)) == col

    @pytest.mark.parametrize("idx", [0, 1, 25, 26, 51, 52, 701, 702])
    def test_roundtrip_index(self, idx):
        assert col_to_index(index_to_col(idx)) == idx


# ---------------------------------------------------------------------------
# quote_sheet_name
# ---------------------------------------------------------------------------

class TestQuoteSheetName:
    def test_plain_name(self):
        assert quote_sheet_name("Sheet1") == "Sheet1"

    def test_underscore_name(self):
        assert quote_sheet_name("my_sheet") == "my_sheet"

    def test_name_with_spaces(self):
        assert quote_sheet_name("Q2 Data") == "'Q2 Data'"

    def test_name_with_single_quote(self):
        assert quote_sheet_name("Tom's Sheet") == "'Tom''s Sheet'"

    def test_name_starting_with_digit(self):
        assert quote_sheet_name("2024 Budget") == "'2024 Budget'"

    def test_name_with_special_chars(self):
        assert quote_sheet_name("Sheet-1") == "'Sheet-1'"

    def test_plain_alpha_only(self):
        assert quote_sheet_name("Revenue") == "Revenue"


# ---------------------------------------------------------------------------
# parse_a1_range
# ---------------------------------------------------------------------------

class TestParseA1Range:
    def test_full_range(self):
        result = parse_a1_range("A1:C3", 0)
        assert result == {
            "sheetId": 0,
            "startColumnIndex": 0,
            "startRowIndex": 0,
            "endColumnIndex": 3,
            "endRowIndex": 3,
        }

    def test_single_cell(self):
        result = parse_a1_range("B2", 5)
        assert result == {
            "sheetId": 5,
            "startColumnIndex": 1,
            "startRowIndex": 1,
        }

    def test_column_only_range(self):
        result = parse_a1_range("A:C", 0)
        assert result == {
            "sheetId": 0,
            "startColumnIndex": 0,
            "endColumnIndex": 3,
        }

    def test_row_only_range(self):
        result = parse_a1_range("1:5", 0)
        assert result == {
            "sheetId": 0,
            "startRowIndex": 0,
            "endRowIndex": 5,
        }

    def test_with_sheet_prefix(self):
        result = parse_a1_range("Sheet1!A1:B2", 0)
        assert result == {
            "sheetId": 0,
            "startColumnIndex": 0,
            "startRowIndex": 0,
            "endColumnIndex": 2,
            "endRowIndex": 2,
        }

    def test_large_range(self):
        result = parse_a1_range("AA10:AZ100", 0)
        assert result == {
            "sheetId": 0,
            "startColumnIndex": 26,
            "startRowIndex": 9,
            "endColumnIndex": 52,
            "endRowIndex": 100,
        }


# ---------------------------------------------------------------------------
# parse_values
# ---------------------------------------------------------------------------

class TestParseValues:
    def test_list_of_lists(self):
        data = [["a", "b"], ["c", "d"]]
        assert parse_values(data) == data

    def test_json_string(self):
        result = parse_values('[["x", 1], ["y", 2]]')
        assert result == [["x", 1], ["y", 2]]

    def test_invalid_json_string(self):
        with pytest.raises(ValueError, match="valid JSON string"):
            parse_values("not json at all")

    def test_flat_list_raises(self):
        with pytest.raises(ValueError, match="2D array"):
            parse_values(["a", "b"])

    def test_empty_list(self):
        assert parse_values([]) == []

    def test_non_list_raises(self):
        with pytest.raises(ValueError, match="2D array"):
            parse_values(42)


# ---------------------------------------------------------------------------
# extract_sheet_name
# ---------------------------------------------------------------------------

class TestExtractSheetName:
    def test_with_sheet_prefix(self):
        assert extract_sheet_name("Sheet1!A1:B2") == "Sheet1"

    def test_without_sheet_prefix(self):
        assert extract_sheet_name("A1:B2") is None

    def test_quoted_sheet_name(self):
        assert extract_sheet_name("'Q2 Data'!A1") == "Q2 Data"

    def test_sheet_with_exclamation_only(self):
        assert extract_sheet_name("MySheet!C5") == "MySheet"

    def test_plain_cell(self):
        assert extract_sheet_name("Z99") is None


# ---------------------------------------------------------------------------
# estimate_text_width_pt
# ---------------------------------------------------------------------------

class TestEstimateTextWidthPt:
    def test_empty(self):
        assert estimate_text_width_pt("", 12) == 0.0

    def test_single_char(self):
        width = estimate_text_width_pt("a", 12)
        assert width > 0

    def test_narrow_chars_narrower_than_wide(self):
        narrow = estimate_text_width_pt("iiiii", 12)
        wide = estimate_text_width_pt("MMMMM", 12)
        assert narrow < wide

    def test_multiline_uses_longest(self):
        short_line = "hi"
        long_line = "hello world"
        multiline = f"{short_line}\n{long_line}"
        assert estimate_text_width_pt(multiline, 12) == estimate_text_width_pt(long_line, 12)

    def test_scales_with_font_size(self):
        small = estimate_text_width_pt("hello", 10)
        large = estimate_text_width_pt("hello", 20)
        assert large == pytest.approx(small * 2, rel=1e-9)


# ---------------------------------------------------------------------------
# estimate_text_height_pt
# ---------------------------------------------------------------------------

class TestEstimateTextHeightPt:
    def test_empty(self):
        assert estimate_text_height_pt("", 12) == 0.0

    def test_single_line(self):
        height = estimate_text_height_pt("hello", 12)
        assert height == pytest.approx(12 * 1.4)

    def test_multiline(self):
        height = estimate_text_height_pt("a\nb\nc", 12)
        assert height == pytest.approx(3 * 12 * 1.4)

    def test_scales_with_font_size(self):
        small = estimate_text_height_pt("test", 10)
        large = estimate_text_height_pt("test", 20)
        assert large == pytest.approx(small * 2, rel=1e-9)

    def test_trailing_newline_adds_line(self):
        # "a\n" has 2 lines (count("\n") + 1 = 2)
        height = estimate_text_height_pt("a\n", 12)
        assert height == pytest.approx(2 * 12 * 1.4)
