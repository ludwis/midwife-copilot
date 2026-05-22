"""Unit tests for the WhatsApp .txt export parser.

TDD: These tests are written before the implementation (T026).
They define the contract that `parse_whatsapp` must satisfy.

Timestamp format note
---------------------
WhatsApp exports use two common formats depending on locale/OS:
  1. Brackets + dash (iOS-like):   [DD/MM/YYYY, HH:MM:SS] - Sender: content
  2. No brackets + dash (Android): DD/MM/YYYY, HH:MM - Sender: content

The `WHATSAPP_LINE_RE` regex from research.md §1 handles both. Tests use
format 1 or 2 explicitly; the parametrized timestamp-variant tests cover
the two date-separator styles (slash YYYY vs dot YY).

Coverage
--------
- DD/MM/YYYY and DD.MM.YY timestamp variants (parametrized)
- Multi-line message continuation is appended to the previous message
- Known system message strings are filtered out
- Empty input returns empty list
"""
import textwrap

import pytest

from bot.kb.parsers.whatsapp import parse_whatsapp, WHATSAPP_LINE_RE


# ---------------------------------------------------------------------------
# WHATSAPP_LINE_RE contract
# ---------------------------------------------------------------------------

class TestWhatsappLineRe:
    """Sanity-check the exported regex before testing the parser."""

    @pytest.mark.parametrize(
        "line,expected_groups",
        [
            # DD/MM/YYYY, HH:MM:SS — brackets + dash (iOS-like with EU locale)
            (
                "[12/05/2024, 09:30:00] - Anna Kowalska: Dzień dobry",
                ("12/05/2024", "09:30:00", "Anna Kowalska", "Dzień dobry"),
            ),
            # DD.MM.YY, HH:MM — dot notation, 2-digit year, brackets + dash
            (
                "[12.05.24, 09:30] - Midwife Bot: Hello",
                ("12.05.24", "09:30", "Midwife Bot", "Hello"),
            ),
            # DD/MM/YYYY, HH:MM — Android format: no brackets, with dash
            (
                "12/05/2024, 09:30:00 - Anna: message",
                ("12/05/2024", "09:30:00", "Anna", "message"),
            ),
        ],
    )
    def test_regex_matches_expected_variants(self, line, expected_groups):
        m = WHATSAPP_LINE_RE.match(line)
        assert m is not None, f"Regex did not match: {line!r}"
        assert m.groups() == expected_groups

    def test_regex_does_not_match_continuation_line(self):
        """A continuation line (no timestamp prefix) must not match."""
        assert WHATSAPP_LINE_RE.match("    continued text here") is None
        assert WHATSAPP_LINE_RE.match("continued text here") is None

    def test_regex_does_not_match_system_message_line(self):
        """System messages that have no 'Sender:' segment must not match."""
        # The system message in Android no-bracket format would need a ':'
        # in the content for the regex to potentially match — it doesn't.
        line = "12/05/2024, 09:00 - Messages and calls are end-to-end encrypted"
        assert WHATSAPP_LINE_RE.match(line) is None


# ---------------------------------------------------------------------------
# parse_whatsapp contract
# ---------------------------------------------------------------------------

class TestParseWhatsapp:
    """Contract tests for the parse_whatsapp function.

    All sample lines use the Android-style format (no brackets, with dash)
    because it is the widest-compatibility format matched by WHATSAPP_LINE_RE.
    """

    # ------------------------------------------------------------------
    # Empty / trivial inputs
    # ------------------------------------------------------------------

    def test_empty_string_returns_empty_list(self):
        assert parse_whatsapp("") == []

    def test_whitespace_only_string_returns_empty_list(self):
        assert parse_whatsapp("   \n\n  ") == []

    # ------------------------------------------------------------------
    # Timestamp variant parametrization (the core TDD requirement)
    # ------------------------------------------------------------------

    @pytest.mark.parametrize(
        "line",
        [
            # DD/MM/YYYY, HH:MM:SS — slash-separated, 4-digit year
            "12/05/2024, 09:30:00 - Anna: Hello",
            # DD.MM.YY, HH:MM — dot-separated, 2-digit year
            "[12.05.24, 09:30] - Anna: Hello",
        ],
    )
    def test_parses_single_message_various_timestamp_formats(self, line):
        """Both DD/MM/YYYY and DD.MM.YY timestamp variants must be parsed."""
        result = parse_whatsapp(line)
        assert len(result) == 1
        msg = result[0]
        assert msg["sender"] == "Anna"
        assert msg["content"] == "Hello"
        assert "timestamp" in msg

    def test_returns_dicts_with_required_keys(self):
        result = parse_whatsapp("12/05/2024, 09:30:00 - Anna: Hello")
        assert len(result) == 1
        assert set(result[0].keys()) >= {"timestamp", "sender", "content"}

    # ------------------------------------------------------------------
    # Multi-line message continuation
    # ------------------------------------------------------------------

    def test_multiline_message_is_appended_to_previous(self):
        """Lines without a timestamp prefix are appended to the previous message."""
        text = textwrap.dedent("""\
            12/05/2024, 09:30:00 - Anna: First line
            second line
            third line
        """)
        result = parse_whatsapp(text)
        assert len(result) == 1
        assert "First line" in result[0]["content"]
        assert "second line" in result[0]["content"]
        assert "third line" in result[0]["content"]

    def test_multiline_does_not_create_extra_messages(self):
        """Continuation lines must not be turned into separate messages."""
        text = textwrap.dedent("""\
            12/05/2024, 09:30:00 - Anna: Line one
            still Anna talking
            12/05/2024, 09:31:00 - Bot: Response
        """)
        result = parse_whatsapp(text)
        assert len(result) == 2

    def test_first_message_gets_continuation_before_second_arrives(self):
        """The first message must absorb its continuations before the next starts."""
        text = textwrap.dedent("""\
            12/05/2024, 09:30:00 - Anna: Part A
            Part B
            12/05/2024, 09:31:00 - Bot: Reply
        """)
        result = parse_whatsapp(text)
        assert "Part B" in result[0]["content"]
        assert result[1]["sender"] == "Bot"

    # ------------------------------------------------------------------
    # System message filtering
    # ------------------------------------------------------------------

    def test_system_message_encryption_notice_is_filtered(self):
        """The 'end-to-end encrypted' system notice must not appear in output."""
        text = textwrap.dedent("""\
            12/05/2024, 09:00 - Messages and calls are end-to-end encrypted. Tap for more info.
            12/05/2024, 09:30:00 - Anna: Hi
        """)
        result = parse_whatsapp(text)
        # Only the real message should appear
        assert len(result) == 1
        assert result[0]["sender"] == "Anna"

    @pytest.mark.parametrize(
        "system_line",
        [
            # Android no-bracket format
            "12/05/2024, 09:00 - Messages and calls are end-to-end encrypted. Tap for more info.",
            # Bracket format
            "[12/05/2024, 09:01:00] - You deleted this message",
            "[12/05/2024, 09:02:00] - This message was deleted",
        ],
    )
    def test_known_system_prefixes_are_filtered(self, system_line):
        """Each known system-message pattern must produce no output."""
        result = parse_whatsapp(system_line)
        assert result == []

    def test_all_system_messages_in_export_are_stripped(self):
        """A realistic multi-system-message export must yield only real messages."""
        text = textwrap.dedent("""\
            12/05/2024, 09:00 - Messages and calls are end-to-end encrypted. Tap for more info.
            12/05/2024, 09:01 - You deleted this message
            12/05/2024, 09:30:00 - Anna: Real message
            12/05/2024, 09:31 - This message was deleted
            12/05/2024, 09:32:00 - Bot: Another real message
        """)
        result = parse_whatsapp(text)
        assert len(result) == 2
        senders = {msg["sender"] for msg in result}
        assert senders == {"Anna", "Bot"}

    # ------------------------------------------------------------------
    # Multiple messages — ordering and correctness
    # ------------------------------------------------------------------

    def test_multiple_messages_parsed_in_order(self):
        text = textwrap.dedent("""\
            12/05/2024, 09:30:00 - Anna: First
            12/05/2024, 09:31:00 - Bot: Second
            12/05/2024, 09:32:00 - Anna: Third
        """)
        result = parse_whatsapp(text)
        assert len(result) == 3
        assert result[0]["sender"] == "Anna"
        assert result[0]["content"] == "First"
        assert result[1]["sender"] == "Bot"
        assert result[2]["sender"] == "Anna"
        assert result[2]["content"] == "Third"

    def test_sender_with_spaces_in_name_is_parsed_correctly(self):
        result = parse_whatsapp("12/05/2024, 09:30:00 - Anna Kowalska: Hello there")
        assert len(result) == 1
        assert result[0]["sender"] == "Anna Kowalska"

    def test_message_content_with_colon_is_preserved(self):
        """Colons inside message content must not truncate the message."""
        result = parse_whatsapp("12/05/2024, 09:30:00 - Anna: Note: this is important")
        assert result[0]["content"] == "Note: this is important"
