"""Unit tests for cfq_lib/text.py, the shared terminal-rendering helper module (batch 035 phase
01). Exercises the module directly rather than through `bin/cfq`, since these are library-level
guarantees other scripts import against -- padding, wrapping, table layout and icon lookup, all
stdlib-only and I/O-free."""

import sys
import unittest

from cfq_testlib import SCRIPTS_DIR

sys.path.insert(0, str(SCRIPTS_DIR))

import cfq_batch_id  # noqa: E402
from cfq_lib import text  # noqa: E402


class IconsTest(unittest.TestCase):
    def test_icons_match_output_format_contract(self):
        self.assertEqual(
            text.ICONS, {"done": "✅", "warn": "⚠️", "fail": "❌", "skip": "➖"}
        )

    def test_label_width_is_sixteen(self):
        self.assertEqual(text.LABEL_WIDTH, 16)


class StatusLineTest(unittest.TestCase):
    def test_short_label_is_padded(self):
        line = text.status_line("done", "Repo", "ready")
        self.assertEqual(line, "✅ Repo            ready")
        self.assertEqual(len(line) - len("✅ "), text.LABEL_WIDTH + len("ready"))

    def test_label_exactly_label_width_gets_one_space_before_detail(self):
        label = "x" * text.LABEL_WIDTH
        line = text.status_line("warn", label, "detail")
        self.assertEqual(line, f"⚠️ {label} detail")

    def test_label_longer_than_label_width_overflows_not_truncated(self):
        label = "x" * (text.LABEL_WIDTH + 5)
        line = text.status_line("fail", label, "detail")
        self.assertEqual(line, f"❌ {label} detail")
        self.assertIn(label, line)

    def test_icon_accepts_literal_glyph_not_just_an_icons_key(self):
        self.assertEqual(text.status_line("✅", "Repo", "ready"), text.status_line("done", "Repo", "ready"))

    def test_icon_key_maps_to_icons_dict(self):
        for key, glyph in text.ICONS.items():
            self.assertTrue(text.status_line(key, "L", "d").startswith(glyph))


class SubLineTest(unittest.TestCase):
    def test_sub_line_form(self):
        self.assertEqual(text.sub_line("detail here"), "   └ detail here")


class WrapTest(unittest.TestCase):
    def test_text_shorter_than_one_line(self):
        self.assertEqual(text.wrap("short text", 40), ["short text"])

    def test_wraps_on_word_boundaries(self):
        lines = text.wrap("one two three four five six seven eight nine ten", 12)
        for line in lines:
            self.assertLessEqual(len(line), 12)
        self.assertEqual(" ".join(lines).replace("  ", " "), "one two three four five six seven eight nine ten")

    def test_collapses_whitespace(self):
        self.assertEqual(text.wrap("a   b\n\nc   d", 40), ["a b c d"])

    def test_wraps_to_exactly_max_lines_when_it_fits(self):
        # Short enough that it naturally wraps to exactly max_lines, no truncation needed.
        lines = text.wrap("one two three four", 8, max_lines=3)
        self.assertEqual(len(lines), 3)
        self.assertFalse(lines[-1].endswith("…"))

    def test_exceeding_max_lines_truncates_with_ellipsis_and_exact_line_count(self):
        long_text = " ".join(f"word{i}" for i in range(40))
        lines = text.wrap(long_text, 12, max_lines=3)
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[-1].endswith("…"))
        # word boundary: strip the ellipsis, what remains must not end mid-word (no trailing
        # partial fragment glued to a truncated word).
        without_ellipsis = lines[-1][:-1].rstrip()
        self.assertTrue(long_text.startswith(without_ellipsis) or without_ellipsis == "" or
                         any(without_ellipsis.endswith(w) for w in long_text.split()))

    def test_single_word_longer_than_width_does_not_raise_or_loop(self):
        lines = text.wrap("supercalifragilisticexpialidocious", 5)
        self.assertTrue(len(lines) >= 1)

    def test_indent_prefixes_every_line(self):
        lines = text.wrap("one two three four five six", 10, indent="  ")
        for line in lines:
            self.assertTrue(line.startswith("  "))

    def test_empty_text_returns_no_lines(self):
        self.assertEqual(text.wrap("   ", 40), [])


class TableTest(unittest.TestCase):
    def test_three_rows_with_header(self):
        rows = text.table(
            [["a", "1"], ["bb", "22"], ["ccc", "333"]],
            headers=["Name", "Count"],
        )
        self.assertEqual(len(rows), 4)
        # every non-last column is padded to the widest cell in that column (header included)
        first_col_widths = {len(line.split("  ")[0]) for line in rows}
        self.assertEqual(len(first_col_widths), 1)

    def test_ragged_row_is_padded_not_raising(self):
        rows = text.table([["a", "b", "c"], ["only-one"]])
        self.assertEqual(len(rows), 2)

    def test_right_aligned_numeric_column(self):
        rows = text.table([["a", "1"], ["bb", "22"]], aligns=["l", "r"])
        for line in rows:
            self.assertFalse(line.endswith(" "))

    def test_last_column_never_padded_no_trailing_whitespace(self):
        rows = text.table([["a", "b"], ["ccc", "d"]])
        for line in rows:
            self.assertEqual(line, line.rstrip())

    def test_empty_rows_returns_empty_list_even_with_headers(self):
        self.assertEqual(text.table([], headers=["A", "B"]), [])


class DisplayWidthTest(unittest.TestCase):
    def test_ascii_string(self):
        self.assertEqual(text.display_width("hello"), 5)

    def test_string_containing_check_mark_glyph(self):
        self.assertEqual(text.display_width("✅"), 2)
        self.assertEqual(text.display_width("✅ ready"), 2 + len(" ready"))

    def test_string_containing_cjk_character(self):
        self.assertEqual(text.display_width("中"), 2)
        self.assertEqual(text.display_width("a中b"), 1 + 2 + 1)


class ParseBatchNameTest(unittest.TestCase):
    def test_numbered_name(self):
        self.assertEqual(
            text.parse_batch_name("035-2026-09-22-ifq-batch-gate-and-output-design"),
            {"number": 35, "date": "2026-09-22", "slug": "ifq-batch-gate-and-output-design"},
        )

    def test_legacy_unnumbered_name(self):
        self.assertEqual(
            text.parse_batch_name("2026-09-22-legacy-batch"),
            {"number": None, "date": None, "slug": "2026-09-22-legacy-batch"},
        )

    def test_name_matching_neither_grammar(self):
        self.assertEqual(
            text.parse_batch_name("not-a-batch-name-at-all"),
            {"number": None, "date": None, "slug": "not-a-batch-name-at-all"},
        )

    def test_grammar_matches_cfq_batch_id_numbered_re_verbatim(self):
        # The claim `Reuse` makes: parse_batch_name and cfq_batch_id.NUMBERED_RE accept and
        # reject the same set of names -- a numbered name, a legacy name, a two-digit-number
        # name (too short to qualify), and a name with an uppercase slug (grammar forbids it).
        fixtures = [
            "035-2026-09-22-ifq-batch-gate-and-output-design",
            "2026-09-22-legacy-batch",
            "42-2026-09-22-two-digit-number",
            "035-2026-09-22-Uppercase-Slug",
        ]
        for name in fixtures:
            parsed_matches = text.parse_batch_name(name)["number"] is not None
            regex_matches = cfq_batch_id.NUMBERED_RE.match(name) is not None
            self.assertEqual(
                parsed_matches, regex_matches,
                msg=f"{name!r}: parse_batch_name matched={parsed_matches}, NUMBERED_RE matched={regex_matches}",
            )


if __name__ == "__main__":
    unittest.main()
