"""Tests for scripts/cfq_lib/markdown.py -- the small Markdown renderer behind the report portal's
pre-rendered phase plans, `.batch-context.md` sections and queue entries. Pure functions over
literal strings, no files.
"""

import sys
import unittest

from cfq_testlib import SCRIPTS_DIR

sys.path.insert(0, str(SCRIPTS_DIR))

from cfq_lib import markdown as cfq_lib_markdown  # noqa: E402

md_min = cfq_lib_markdown.md_min
md_inline = cfq_lib_markdown.md_inline


class MarkdownBaseTest(unittest.TestCase):
    def test_h1_dropped_by_default_unchanged_from_before(self):
        self.assertEqual(md_min("# Batch Context\n"), "")

    def test_h1_kept_as_title_when_requested(self):
        out = md_min("# Batch Context\n\nBody text.\n", keep_h1=True)
        self.assertEqual(out, "<h1>Batch Context</h1><p>Body text.</p>")

    def test_fenced_code_block_escaped_never_inline_formatted(self):
        out = md_min("```\n**not bold** <tag>\n```\n")
        self.assertIn("<pre><code>", out)
        self.assertIn("&lt;tag&gt;", out)
        self.assertNotIn("<strong>", out)
        self.assertIn("**not bold**", out)  # inline markers pass through literally inside a fence

    def test_unterminated_fence_still_renders_its_content(self):
        out = md_min("```\nstill here\n")
        self.assertIn("<pre><code>still here</code></pre>", out)

    def test_ordered_list_renders_as_ol(self):
        out = md_min("1. one\n2. two\n")
        self.assertIn("<ol>", out)
        self.assertEqual(out.count("<li>"), 2)
        self.assertIn("<li>one</li>", out)

    def test_switching_from_bullet_to_ordered_closes_the_first_list(self):
        out = md_min("- bullet\n1. numbered\n")
        self.assertIn("<ul><li>bullet</li></ul>", out)
        self.assertIn("<ol><li>numbered</li></ol>", out)

    def test_routine_heading_paragraph_and_list(self):
        out = md_min("## Heading\n\nA paragraph.\n\n- one\n- two\n- three\n")
        self.assertIn("<h3>Heading</h3>", out)
        self.assertIn("<p>A paragraph.</p>", out)
        self.assertEqual(out.count("<li>"), 3)
        self.assertIn("<li>one</li>", out)
        self.assertIn("<li>two</li>", out)
        self.assertIn("<li>three</li>", out)

    def test_wrapped_bullet_continuation_stays_one_li_not_a_paragraph(self):
        out = md_min("- first line of the item\n  wraps onto this line\n")
        self.assertEqual(out.count("<li>"), 1)
        self.assertNotIn("<p>", out)
        self.assertIn("<li>first line of the item wraps onto this line</li>", out)

    def test_inline_bold_and_code(self):
        self.assertEqual(md_inline("**bold**"), "<strong>bold</strong>")
        self.assertEqual(md_inline("`code`"), "<code>code</code>")

    def test_inline_backtick_span_wins_over_bold_inside_it(self):
        out = md_inline("`a **b** c`")
        self.assertNotIn("<strong>", out)
        self.assertEqual(out, "<code>a **b** c</code>")

    def test_escaping_happens_before_this_function_is_reached(self):
        # md_min escapes each emitted value itself (via esc()) -- feeding it raw HTML must come
        # out neutralised, never as a literal live tag.
        out = md_min("A line with <script>alert(1)</script> in it.")
        self.assertIn("&lt;script&gt;", out)
        self.assertNotIn("<script", out)

    def test_empty_string_returns_empty(self):
        self.assertEqual(md_min(""), "")

    def test_only_blank_lines_returns_empty(self):
        self.assertEqual(md_min("\n\n\n"), "")

    def test_whitespace_only_returns_empty(self):
        self.assertEqual(md_min("  \n\t\n   \n"), "")

    def test_single_hash_title_alone_is_skipped_entirely(self):
        self.assertEqual(md_min("# Batch Context\n"), "")


class MarkdownHeadingTest(unittest.TestCase):
    def test_heading_levels_map_to_h3_h4_h5(self):
        self.assertEqual(md_min("## A\n"), "<h3>A</h3>")
        self.assertEqual(md_min("### B\n"), "<h4>B</h4>")
        self.assertEqual(md_min("#### C\n"), "<h5>C</h5>")
        self.assertEqual(md_min("###### D\n"), "<h5>D</h5>")


class MarkdownNestedListTest(unittest.TestCase):
    def test_three_nested_levels_then_back_to_one(self):
        out = md_min("- a\n  - b\n    - c\n- d\n")
        self.assertEqual(
            out,
            "<ul><li>a<ul><li>b<ul><li>c</li></ul></li></ul></li><li>d</li></ul>",
        )

    def test_ordered_nested_in_bullet(self):
        out = md_min("- a\n  1. b\n  2. c\n")
        self.assertEqual(out, "<ul><li>a<ol><li>b</li><li>c</li></ol></li></ul>")

    def test_bullet_nested_in_ordered(self):
        out = md_min("1. a\n   - b\n2. c\n")
        self.assertEqual(out, "<ol><li>a<ul><li>b</li></ul></li><li>c</li></ol>")

    def test_fourth_level_is_folded_into_the_third(self):
        out = md_min("- a\n  - b\n    - c\n      - d\n")
        self.assertEqual(
            out,
            "<ul><li>a<ul><li>b<ul><li>c</li><li>d</li></ul></li></ul></li></ul>",
        )

    def test_tab_indent_counts_as_four_spaces(self):
        out = md_min("- a\n\t- b\n")
        self.assertEqual(out, "<ul><li>a<ul><li>b</li></ul></li></ul>")

    def test_indented_continuation_line_still_joins_its_item(self):
        out = md_min("- a\n  - b\n    wraps here\n")
        self.assertEqual(out, "<ul><li>a<ul><li>b wraps here</li></ul></li></ul>")

    def test_blank_line_ends_the_list(self):
        out = md_min("- a\n\n- b\n")
        self.assertEqual(out, "<ul><li>a</li></ul><ul><li>b</li></ul>")


class MarkdownTableTest(unittest.TestCase):
    def test_header_separator_and_body_rows(self):
        out = md_min("| Name | Note |\n|---|---|\n| **a** | `x` |\n| b | c |\n")
        self.assertEqual(
            out,
            "<table><thead><tr><th>Name</th><th>Note</th></tr></thead>"
            "<tbody><tr><td><strong>a</strong></td><td><code>x</code></td></tr>"
            "<tr><td>b</td><td>c</td></tr></tbody></table>",
        )

    def test_pipe_line_without_separator_stays_a_paragraph(self):
        out = md_min("| a | table |\n")
        self.assertNotIn("<table", out)
        self.assertEqual(out, "<p>| a | table |</p>")

    def test_short_row_is_padded_with_empty_cells(self):
        out = md_min("| a | b | c |\n|---|---|---|\n| 1 |\n")
        self.assertIn("<tr><td>1</td><td></td><td></td></tr>", out)

    def test_table_ends_at_blank_line(self):
        out = md_min("| a |\n|---|\n| 1 |\n\nafter\n")
        self.assertTrue(out.endswith("</table><p>after</p>"))

    def test_html_in_cell_is_escaped(self):
        out = md_min("| a |\n|---|\n| <script>x</script> |\n")
        self.assertIn("&lt;script&gt;", out)
        self.assertNotIn("<script", out)


class MarkdownIndentedCodeTest(unittest.TestCase):
    def test_four_space_block_after_blank_line_is_code(self):
        out = md_min("Intro\n\n    grep -r '<x>' .\n    echo **no**\n")
        self.assertEqual(
            out,
            "<p>Intro</p><pre><code>grep -r &apos;&lt;x&gt;&apos; .\necho **no**</code></pre>",
        )

    def test_tab_indented_block_is_code(self):
        out = md_min("Intro\n\n\tls -la\n")
        self.assertEqual(out, "<p>Intro</p><pre><code>ls -la</code></pre>")

    def test_code_block_keeps_inner_blank_line(self):
        out = md_min("x\n\n    a\n\n    b\nafter\n")
        self.assertEqual(out, "<p>x</p><pre><code>a\n\nb</code></pre><p>after</p>")

    def test_same_indentation_under_a_list_item_is_a_continuation(self):
        out = md_min("- item\n    more text\n")
        self.assertEqual(out, "<ul><li>item more text</li></ul>")
        self.assertNotIn("<pre>", out)

    def test_indented_line_inside_a_paragraph_stays_paragraph_text(self):
        out = md_min("first\n    second\n")
        self.assertEqual(out, "<p>first second</p>")


class MarkdownBlockQuoteTest(unittest.TestCase):
    def test_consecutive_quote_lines_form_one_blockquote(self):
        out = md_min("> one **two**\n> three\n\nafter\n")
        self.assertEqual(
            out, "<blockquote><p>one <strong>two</strong> three</p></blockquote><p>after</p>"
        )

    def test_html_in_quote_is_escaped(self):
        out = md_min("> <b>x</b>\n")
        self.assertEqual(out, "<blockquote><p>&lt;b&gt;x&lt;/b&gt;</p></blockquote>")


class MarkdownRuleTest(unittest.TestCase):
    def test_three_dashes_are_a_horizontal_rule(self):
        self.assertEqual(md_min("a\n\n---\n\nb\n"), "<p>a</p><hr><p>b</p>")

    def test_longer_run_of_dashes_too(self):
        self.assertEqual(md_min("------\n"), "<hr>")


class MarkdownEmphasisTest(unittest.TestCase):
    def test_single_star_pair_is_em(self):
        self.assertEqual(md_inline("*when*"), "<em>when</em>")
        self.assertEqual(md_inline("so *when* it runs."), "so <em>when</em> it runs.")

    def test_closing_star_after_whitespace_is_not_a_closer(self):
        self.assertEqual(md_inline("*.md and *.js"), "*.md and *.js")

    def test_bold_and_code_unchanged(self):
        self.assertEqual(md_inline("**bold**"), "<strong>bold</strong>")
        self.assertEqual(md_inline("`code`"), "<code>code</code>")

    def test_star_inside_a_code_span_stays_literal(self):
        self.assertEqual(md_inline("`*x*`"), "<code>*x*</code>")
        self.assertEqual(md_inline("*a `b*` c"), "*a <code>b*</code> c")

    def test_em_in_a_paragraph_and_in_a_list_item(self):
        self.assertEqual(md_min("say *hi*\n"), "<p>say <em>hi</em></p>")
        self.assertEqual(md_min("- *hi*\n"), "<ul><li><em>hi</em></li></ul>")

    def test_star_line_start_with_emphasis_is_not_a_bullet(self):
        self.assertEqual(md_min("*hi* there\n"), "<p><em>hi</em> there</p>")


class MarkdownCheckLineTest(unittest.TestCase):
    def test_check_line_becomes_a_check_paragraph(self):
        out = md_min("check: grep -c 'a' <file> && echo **x**\n")
        self.assertEqual(
            out,
            '<p class="check"><span>check</span>'
            "<code>grep -c &apos;a&apos; &lt;file&gt; &amp;&amp; echo **x**</code></p>",
        )

    def test_check_line_after_a_paragraph_is_its_own_block(self):
        out = md_min("Text.\ncheck: true\n")
        self.assertEqual(out, '<p>Text.</p><p class="check"><span>check</span><code>true</code></p>')


class MarkdownFenceTest(unittest.TestCase):
    def test_language_tag_renders_like_an_untagged_fence(self):
        body = "echo <a>\nls\n"
        self.assertEqual(md_min("```bash\n" + body + "```\n"), md_min("```\n" + body + "```\n"))
        self.assertEqual(
            md_min("```bash\n" + body + "```\n"),
            "<pre><code>echo &lt;a&gt;\nls</code></pre>",
        )


class MarkdownSafetyTest(unittest.TestCase):
    def test_raw_html_is_escaped_in_every_construct(self):
        for src in (
            "| h |\n|---|\n| <img src=x onerror=1> |\n",
            "> <img src=x onerror=1>\n",
            "- <img src=x onerror=1>\n",
            "  - <img src=x onerror=1>\n",
            "*<img src=x onerror=1>*\n",
            "para <img src=x onerror=1>\n",
            "check: <img src=x onerror=1>\n",
            "\n    <img src=x onerror=1>\n",
        ):
            out = md_min(src)
            self.assertNotIn("<img", out, src)
            self.assertIn("&lt;img", out, src)


if __name__ == "__main__":
    unittest.main()
