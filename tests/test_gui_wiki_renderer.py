from __future__ import annotations

import unittest

from src.gui.wiki_renderer import codebeamer_wiki_to_html
from src.gui.wiki_renderer import is_explicit_wiki_type
from src.gui.wiki_renderer import payload_uses_wiki
from src.gui.wiki_renderer import sanitize_server_wiki_html
from src.gui.wiki_renderer import sanitize_wiki_style


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

    def test_style_sanitizer_keeps_only_allowlisted_properties(self) -> None:
        style = sanitize_wiki_style(
            "color:#336699; position:fixed; text-decoration:underline"
        )

        self.assertEqual(style, "color: #336699; text-decoration: underline")

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


if __name__ == "__main__":
    unittest.main()
