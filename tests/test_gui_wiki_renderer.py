from __future__ import annotations

import unittest

from src.gui.tracker_content_models import AttachmentResource
from src.gui.tracker_content_models import AttachmentSummary
from src.gui.tracker_content_models import WikiLink
from src.gui.wiki_renderer import codebeamer_wiki_to_html
from src.gui.wiki_renderer import is_explicit_wiki_type
from src.gui.wiki_renderer import payload_uses_wiki
from src.gui.wiki_renderer import resolve_wiki_images
from src.gui.wiki_renderer import sanitize_server_wiki_html
from src.gui.wiki_renderer import sanitize_wiki_style
from src.gui.wiki_renderer import wiki_image_references
from src.gui.wiki_renderer import wiki_image_resource_key
from src.gui.wiki_renderer import wiki_link_from_url
from tests.gui_widget_cleanup import tearDownModule  # noqa: F401


# Codebeamer 편집기에 붙여넣은 표가 저장되는 모양을 값만 바꿔 옮겼다.
# 한 줄에 셀 하나, 빈 줄이 행 구분이고 셀 CSS 안에 괄호가 겹친다.
PASTED_TABLE_WIKI = (
    "\\\\\n"
    "[{Table style='border-collapse:collapse;background:rgb(229, 229, 229);width:1084px;'"
    " dataStyle='color:black;padding:12px 5px 11px;vertical-align:middle;'\n"
    "\n"
    "|(border:0.5pt solid windowtext;text-align:center;width:203px;background:rgb(204, 204, 204))Col A\n"
    "|(border-top:0.5pt solid windowtext;text-align:center;background:rgb(204, 204, 204))Col B\n"
    "\n"
    "|(border-top:none;background:white)Value_%%(color:rgb(30, 30, 30);display:inline !important;)styled%!\n"
    "|(border-top:none;background:white)Line one.\\\\\n"
    "\\\\\n"
    "~- item a\\\\\n"
    "~- item b}]\n"
    "after"
)


class WikiRendererTest(unittest.TestCase):
    def test_wiki_detection_requires_explicit_metadata(self) -> None:
        self.assertTrue(is_explicit_wiki_type("WikiTextField"))
        self.assertTrue(is_explicit_wiki_type("WikiTextFieldValue"))
        self.assertTrue(payload_uses_wiki({"descriptionFormat": "Wiki"}))
        self.assertFalse(payload_uses_wiki({"type": "TextFieldValue"}))
        self.assertFalse(payload_uses_wiki({"value": "%%(color:red)text%%"}))

    def test_style_block_is_rendered_and_theme_foreground_is_removed(self) -> None:
        rendered = codebeamer_wiki_to_html(
            "%%(color:black;font-style:normal;)안전한 내용%%"
        )

        self.assertEqual(
            rendered,
            '<span style="font-style: normal">안전한 내용</span>',
        )

    def test_named_color_and_basic_emphasis_are_rendered(self) -> None:
        rendered = codebeamer_wiki_to_html("%%red __중요__%%")

        self.assertEqual(
            rendered,
            '<span style="color: red"><strong>중요</strong></span>',
        )

    def test_unsafe_html_and_css_are_not_executed(self) -> None:
        rendered = codebeamer_wiki_to_html(
            "%%(color:url(evil);font-weight:bold)"
            "<script>alert(1)</script>%%"
        )

        self.assertNotIn("url(", rendered)
        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertIn("font-weight: bold", rendered)

    def test_nested_style_blocks_close_innermost_first(self) -> None:
        """붙여넣은 서식은 `%%(바깥)%%(안쪽)글자%!%!`로 겹친다. 바깥 블록이 안쪽 시작에서 닫히면
        안쪽 CSS 원문이 글자로 드러난다."""
        rendered = codebeamer_wiki_to_html(
            "%%(font-size:12px;)%%(color:rgb(30, 30, 30);display:inline !important;)111 %!설명.%!"
        )

        self.assertEqual(
            rendered,
            '<span style="font-size: 12px"><span style="color: rgb(30, 30, 30)">111 </span>설명.</span>',
        )

    def test_unpaired_style_marks_stay_as_text_and_open_blocks_close_at_the_end(self) -> None:
        self.assertEqual(codebeamer_wiki_to_html("100%! 할인"), "100%! 할인")
        self.assertEqual(
            codebeamer_wiki_to_html("%%(color:red)끝까지"),
            '<span style="color: red">끝까지</span>',
        )

    def test_style_sanitizer_keeps_only_allowlisted_properties(self) -> None:
        style = sanitize_wiki_style(
            "color:#336699; position:fixed; text-decoration:underline"
        )

        self.assertEqual(style, "color: #336699; text-decoration: underline")

    def test_style_sanitizer_keeps_table_alignment_and_background_shorthand(self) -> None:
        style = sanitize_wiki_style(
            "background:rgb(204, 204, 204); text-align:center; vertical-align:middle;"
            "text-align:expression(bad); background:url(evil); width:203px"
        )

        self.assertEqual(
            style,
            "background-color: rgb(204, 204, 204); text-align: center; vertical-align: middle",
        )

    def test_forced_line_break_and_escape_are_rendered(self) -> None:
        rendered = codebeamer_wiki_to_html("first\\\\\nsecond ~__plain__ ~- dash 3~5 1~(2)")

        self.assertEqual(rendered, "first<br>second &#95;_plain__ &#45; dash 3~5 1~(2)")

    def test_pasted_table_plugin_is_rendered_as_rows_of_cells(self) -> None:
        rendered = codebeamer_wiki_to_html(PASTED_TABLE_WIKI)

        self.assertEqual(rendered.count("<tr>"), 2)
        self.assertEqual(rendered.count("<td "), 4)
        for raw in ("[{Table", "}]", "(border", "windowtext", "~-", "width"):
            self.assertNotIn(raw, rendered)
        self.assertTrue(rendered.startswith("<br><table "))
        self.assertIn("background-color: rgb(229, 229, 229)", rendered)
        self.assertIn(
            "vertical-align: middle; text-align: center; background-color: rgb(204, 204, 204)\">Col A",
            rendered,
        )
        self.assertIn(
            'Value_<span style="color: rgb(30, 30, 30)">styled</span>',
            rendered,
        )
        self.assertIn("Line one.<br><br>&#45; item a<br>&#45; item b</td>", rendered)
        self.assertTrue(rendered.endswith("</table>after"))

    def test_table_plugin_merges_cells_and_numbers_rows(self) -> None:
        rendered = codebeamer_wiki_to_html(
            "[{Table rowNumber='0' headerStyle='background:#eeeeee'\n"
            "\n"
            "||No||A||B||C\n"
            "|#|a1|<|c1|\n"
            "|#|a2|b2|^\n"
            "}]"
        )

        self.assertEqual(rendered.count("<tr>"), 3)
        self.assertEqual(rendered.count("<th "), 4)
        self.assertIn("background-color: #eeeeee\">No</th>", rendered)
        self.assertIn('colspan="2">a1</td>', rendered)
        self.assertIn('rowspan="2">c1</td>', rendered)
        self.assertIn(">1</td>", rendered)
        self.assertIn(">2</td>", rendered)
        self.assertNotIn(">^<", rendered)
        self.assertNotIn("&lt;", rendered)

    def test_table_plugin_keeps_text_that_is_not_markup(self) -> None:
        rendered = codebeamer_wiki_to_html(
            "[{Table\n\n|(참고) [링크|https://example.test] 내용\n}]"
        )

        # 링크 안의 `|`는 셀 구분자가 아니다.
        self.assertEqual(rendered.count("<td "), 1)
        self.assertIn('(참고) <a href="https://example.test">링크</a> 내용</td>', rendered)

    def test_wiki_links_become_attachment_item_and_web_links(self) -> None:
        rendered = codebeamer_wiki_to_html(
            "AAA Report : [AA_BB_CC_v1.2.3.docx|CB:/displayDocument/AA_BB_CC_v1.2.3.docx"
            "?task_id=112345&artifact_id=111111]\n"
            "[CB:1234] [요구 사항|ISSUE:42] [사이트|https://example.test/a?b=1]"
        )

        self.assertEqual(
            rendered,
            'AAA Report : <a href="cb-link:attachment/111111/AA_BB_CC_v1.2.3.docx">'
            "AA_BB_CC_v1.2.3.docx</a><br>"
            '<a href="cb-link:item/1234">CB:1234</a> '
            '<a href="cb-link:item/42">요구 사항</a> '
            '<a href="https://example.test/a?b=1">사이트</a>',
        )

    def test_links_the_app_cannot_open_stay_as_source(self) -> None:
        """Wiki 페이지 이름이나 첨부 ID가 없는 경로는 짐작하지 않고 원문으로 둔다."""
        rendered = codebeamer_wiki_to_html(
            "[WikiPage] [문서|CB:/proj/doc/42] [mail|mailto:a@example.test] ~[x|https://a.test] [!img.png!]"
        )

        self.assertIn("[WikiPage] [문서|CB:/proj/doc/42] [mail|mailto:a@example.test] &#91;x|https://a.test]", rendered)
        self.assertNotIn("<a ", rendered)
        self.assertIn("<img ", rendered)

    def test_wiki_link_urls_are_read_back(self) -> None:
        self.assertEqual(
            wiki_link_from_url("cb-link:attachment/111111/AA%20BB.docx"),
            WikiLink("attachment", 111111, "AA BB.docx"),
        )
        self.assertEqual(wiki_link_from_url("cb-link:item/1234"), WikiLink("item", 1234, ""))
        self.assertIsNone(wiki_link_from_url("cb-link:folder/12"))
        self.assertIsNone(wiki_link_from_url("https://example.test/cb-link:item/1"))

    def test_unclosed_table_plugin_stays_as_source(self) -> None:
        rendered = codebeamer_wiki_to_html("[{Table\n\n|a|b")

        self.assertTrue(rendered.startswith("[{Table<br>"))
        self.assertIn("<table", rendered)

    def test_simple_wiki_table_is_rendered_locally(self) -> None:
        rendered = codebeamer_wiki_to_html(
            "|| 이름 || 상태\n| __요구사항__ | ''완료''\n표 다음"
        )

        self.assertIn("<table", rendered)
        self.assertIn("<th", rendered)
        self.assertIn("<strong>요구사항</strong>", rendered)
        self.assertIn("<em>완료</em>", rendered)
        self.assertIn("표 다음", rendered)

    def test_server_html_is_sanitized_and_only_attachment_images_are_rewritten(self) -> None:
        result = sanitize_server_wiki_html(
            '<script>alert(1)</script><table><tr><td colspan="2" onclick="bad()">값</td></tr></table>'
            '<img src="/cb/displayDocument/sample.png?task_id=10&amp;artifact_id=28" onerror="bad()">'
            '<img src="https://outside.test/image.png">'
            '<a href="javascript:bad()">위험</a>',
            base_url="https://example.test/cb",
        )

        self.assertNotIn("alert", result.html)
        self.assertNotIn("onclick", result.html)
        self.assertNotIn("javascript", result.html)
        self.assertIn('colspan="2"', result.html)
        self.assertIn("cb-attachment://", result.html)
        self.assertIn("이미지 차단", result.html)
        self.assertEqual(len(result.resources), 1)
        self.assertEqual(result.resources[0].attachment_id, 28)

    def test_attachment_image_becomes_a_named_image_slot(self) -> None:
        rendered = codebeamer_wiki_to_html(
            "before [!Primary Architecture.png#A114E08877977D75CFAC6AADE92755CB!] __after__"
        )

        self.assertEqual(
            rendered,
            'before <img src="cb-attachment://wiki-image/Primary%20Architecture.png/'
            'a114e08877977d75cfac6aade92755cb" alt="Primary Architecture.png"> '
            "<strong>after</strong>",
        )

    def test_escaped_or_external_images_stay_as_source(self) -> None:
        rendered = codebeamer_wiki_to_html("~[!plain.png!] [!https://outside.test/a.png!]")

        self.assertEqual(rendered, "&#91;!plain.png!] [!https://outside.test/a.png!]")
        self.assertEqual(
            wiki_image_references("~[!plain.png!] [!https://outside.test/a.png!]"),
            (),
        )

    def test_wiki_images_pick_the_attachment_whose_md5_matches(self) -> None:
        """붙여넣은 그림은 이름이 겹치므로 해시로 고르고, 해시가 없으면 첫 번째를 쓴다."""
        attachments = (
            AttachmentSummary(attachment_id=1, name="image.png", md5="aaaa0000aaaa0000"),
            AttachmentSummary(attachment_id=2, name="image.png", md5="bbbb1111bbbb1111"),
            AttachmentSummary(attachment_id=3, name="Diagram.PNG"),
        )
        resources = (
            AttachmentResource("attachment-1", "image/png", b"first"),
            AttachmentResource("attachment-2", "image/png", b"second"),
            AttachmentResource("attachment-3", "image/png", b"third"),
        )
        markup = (
            "[!image.png#BBBB1111BBBB1111!] [!image.png!] [!image.png!] "
            "[!diagram.png!] [!missing.png!]"
        )

        resolved = {
            resource.resource_key: resource.data
            for resource in resolve_wiki_images(markup, attachments, resources)
        }

        self.assertEqual(
            resolved,
            {
                wiki_image_resource_key("image.png", "bbbb1111bbbb1111"): b"second",
                wiki_image_resource_key("image.png", ""): b"first",
                wiki_image_resource_key("diagram.png", ""): b"third",
            },
        )

    def test_wiki_images_inside_table_plugin_cells_are_found(self) -> None:
        markup = "[{Table\n\n|(background:white)[!cell.png#0123456789abcdef!]\n|text\n}]"

        self.assertIn(
            'src="cb-attachment://wiki-image/cell.png/0123456789abcdef"',
            codebeamer_wiki_to_html(markup),
        )
        self.assertEqual(
            [reference.name for reference in wiki_image_references(markup)],
            ["cell.png"],
        )


if __name__ == "__main__":
    unittest.main()
