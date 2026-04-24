"""Tests for EmailParser — specifically the hardened html_to_text.

Focus on the cases that the original regex-only implementation got
wrong: <script>/<style> bodies leaking through, un-decoded HTML
entities, and comment contents being treated as visible text.
"""

from __future__ import annotations

from services.email_intake.parser import EmailParser


class TestHtmlToText:
    """html_to_text should produce LLM-safe plain text."""

    def test_plain_html_is_converted(self) -> None:
        result = EmailParser.html_to_text("<p>Hello <b>world</b></p>")
        assert result == "Hello world"

    def test_empty_input_returns_empty_string(self) -> None:
        assert EmailParser.html_to_text("") == ""

    def test_script_body_is_removed(self) -> None:
        """Inline JS should not leak into the LLM prompt."""
        html = (
            "<p>Visible</p>"
            "<script>alert('xss'); var secret = 'leaked';</script>"
            "<p>Also visible</p>"
        )
        result = EmailParser.html_to_text(html)
        assert "Visible" in result
        assert "Also visible" in result
        assert "alert" not in result
        assert "leaked" not in result

    def test_style_body_is_removed(self) -> None:
        """Inline CSS must not appear in the extracted text."""
        html = (
            "<style>.header { color: red; }</style>"
            "<p>Message body</p>"
        )
        result = EmailParser.html_to_text(html)
        assert "Message body" in result
        assert "color: red" not in result

    def test_html_entities_are_decoded(self) -> None:
        """&amp; / &nbsp; / &#39; should become their real characters."""
        html = "<p>Tom &amp; Jerry&#39;s&nbsp;show</p>"
        result = EmailParser.html_to_text(html)
        assert "&amp;" not in result
        assert "&#39;" not in result
        assert "Tom & Jerry's" in result

    def test_comments_are_removed(self) -> None:
        """HTML comments should not end up in the text."""
        html = "<p>Real</p><!-- hidden note -->"
        result = EmailParser.html_to_text(html)
        assert "Real" in result
        assert "hidden note" not in result

    def test_multiple_whitespace_collapsed(self) -> None:
        """Tables or multiple block elements should not produce long runs
        of spaces."""
        html = "<table><tr><td>A</td><td>B</td></tr></table>"
        result = EmailParser.html_to_text(html)
        assert "  " not in result
        assert "A" in result and "B" in result
