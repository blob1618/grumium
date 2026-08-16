"""Tests for WhatsApp-to-Markdown rendering helpers in the chat component."""

from testing.components.chat import whatsapp_to_markdown


class TestWhatsappToMarkdown:
    def test_plain_text_unchanged(self):
        assert whatsapp_to_markdown("hola") == "hola"

    def test_single_newline_becomes_hard_break(self):
        assert whatsapp_to_markdown("l1\nl2") == "l1  \nl2"

    def test_double_newline_keeps_blank_line(self):
        assert whatsapp_to_markdown("a\n\nb") == "a  \n  \nb"

    def test_whatsapp_bold_becomes_markdown_bold(self):
        assert whatsapp_to_markdown("*hola*") == "**hola**"

    def test_multiple_bold_pairs_converted(self):
        assert whatsapp_to_markdown("*a* y *b*") == "**a** y **b**"

    def test_lone_asterisk_left_alone(self):
        assert whatsapp_to_markdown("5 * 3") == "5 * 3"

    def test_empty_string(self):
        assert whatsapp_to_markdown("") == ""
