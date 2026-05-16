"""Unit tests for the PII stripper.

TDD: These tests are written before the implementation (T028).
They define the contract that ``strip_pii`` must satisfy.

strip_pii(text: str) -> tuple[str, bool]:
  - Pass 1: spaCy NER — PERSON → [IMIĘ], LOC → [ADRES], ORG → [FIRMA]
  - Pass 2: regex — phone → [TELEFON], email → [EMAIL], PESEL → [PESEL]
  - Post-strip rescan: if any digit sequence >6 digits remains → flag=True
  - Returns (stripped_text, flag)

NER tests mock ``bot.kb.pii_stripper._nlp`` to avoid requiring the
``xx_ent_wiki_sm`` model in the unit-test environment.

Phone-regex note (research.md §3)
----------------------------------
The phone regex ``(\\+\\d{1,3}[\\s-]?)?\\(?\\d{2,4}\\)?[\\s-]?\\d{3,4}[\\s-]?\\d{3,4}``
requires three digit groups totalling a minimum of 2+3+3 = 8 consecutive
digits (without separators).  A bare 7-digit sequence therefore CANNOT match
the phone regex, PESEL (``\\b\\d{11}\\b``), or NIP (``\\b\\d{10}\\b``), so it
slips through all patterns and is caught only by the post-strip rescan.
This is why the rescan tests use a 7-digit number as the trigger value.

Coverage
--------
- PERSON entity → [IMIĘ]
- LOC entity → [ADRES]
- phone ``+48 601 234 567`` → [TELEFON]
- email ``anna@gmail.com`` → [EMAIL]
- PESEL 11-digit → [PESEL]
- post-strip rescan flags a remaining 7-digit sequence
- post-strip rescan does NOT flag a 6-digit sequence (boundary condition)
- clean text (no long digit sequences) → flag=False
- return type is always (str, bool)
"""
from unittest.mock import MagicMock, patch

import pytest

from bot.kb.pii_stripper import strip_pii


# ---------------------------------------------------------------------------
# Helpers — lightweight stand-ins for spaCy Doc / Span objects
# ---------------------------------------------------------------------------

def _make_span(label_: str, start_char: int, end_char: int) -> MagicMock:
    """Return a MagicMock that quacks like a spaCy Span."""
    span = MagicMock()
    span.label_ = label_
    span.start_char = start_char
    span.end_char = end_char
    return span


def _doc_with_ents(*ents: MagicMock) -> MagicMock:
    """Return a mock spaCy Doc whose ``.ents`` is the given list."""
    doc = MagicMock()
    doc.ents = list(ents)
    return doc


# ---------------------------------------------------------------------------
# Pass 1 — spaCy NER entity replacements
# ---------------------------------------------------------------------------

class TestNerReplacements:
    """spaCy NER entities must be replaced with Polish-language placeholders."""

    @patch("bot.kb.pii_stripper._nlp")
    def test_person_entity_replaced_with_imie(self, mock_nlp):
        """A PERSON span detected by spaCy must be replaced with [IMIĘ]."""
        text = "Czy Ania powinna odpoczywać?"
        # "Ania" spans positions 3–7 in the string above
        ent = _make_span("PERSON", 3, 7)
        mock_nlp.return_value = _doc_with_ents(ent)

        stripped, _ = strip_pii(text)

        assert "[IMIĘ]" in stripped
        assert "Ania" not in stripped

    @patch("bot.kb.pii_stripper._nlp")
    def test_loc_entity_replaced_with_adres(self, mock_nlp):
        """A LOC span detected by spaCy must be replaced with [ADRES]."""
        text = "Mieszkam na ul. Krótka."
        # "ul. Krótka" spans positions 12–22
        ent = _make_span("LOC", 12, 22)
        mock_nlp.return_value = _doc_with_ents(ent)

        stripped, _ = strip_pii(text)

        assert "[ADRES]" in stripped
        assert "ul. Krótka" not in stripped


# ---------------------------------------------------------------------------
# Pass 2 — Regex patterns for structured PII
# (NER mocked to return no entities so only regex pass is exercised)
# ---------------------------------------------------------------------------

class TestRegexPatterns:
    """Structured PII (phone, email, PESEL) must be replaced by regex in pass 2."""

    @patch("bot.kb.pii_stripper._nlp")
    def test_phone_number_replaced_with_telefon(self, mock_nlp):
        """Polish phone +48 601 234 567 must become [TELEFON]."""
        mock_nlp.return_value = _doc_with_ents()
        text = "Zadzwoń pod numer +48 601 234 567."

        stripped, _ = strip_pii(text)

        assert "[TELEFON]" in stripped
        assert "+48 601 234 567" not in stripped

    @patch("bot.kb.pii_stripper._nlp")
    def test_email_replaced_with_email_placeholder(self, mock_nlp):
        """Email address anna@gmail.com must become [EMAIL]."""
        mock_nlp.return_value = _doc_with_ents()
        text = "Napisz do mnie na anna@gmail.com."

        stripped, _ = strip_pii(text)

        assert "[EMAIL]" in stripped
        assert "anna@gmail.com" not in stripped

    @patch("bot.kb.pii_stripper._nlp")
    def test_pesel_replaced_with_pesel_placeholder(self, mock_nlp):
        """11-digit PESEL number must become [PESEL]."""
        mock_nlp.return_value = _doc_with_ents()
        text = "Mój PESEL to 12345678901."

        stripped, _ = strip_pii(text)

        assert "[PESEL]" in stripped
        assert "12345678901" not in stripped


# ---------------------------------------------------------------------------
# Post-strip rescan — flag remaining digit sequences longer than 6 digits
# ---------------------------------------------------------------------------

class TestPostStripRescan:
    """After all stripping, digit sequences >6 chars must set the flag to True."""

    @patch("bot.kb.pii_stripper._nlp")
    def test_remaining_seven_digit_sequence_sets_flag(self, mock_nlp):
        """A 7-digit sequence that survives all stripping passes sets flag=True.

        The phone regex (research.md §3) requires a minimum of 8 consecutive
        digits to match (groups: 2-4 + 3-4 + 3-4), so a bare 7-digit number
        cannot match it.  PESEL needs 11 and NIP needs 10.  The 7-digit number
        therefore slips through all regex patterns and is detected only by the
        post-strip rescan.
        """
        mock_nlp.return_value = _doc_with_ents()
        text = "Kod weryfikacyjny: 1234567"

        stripped, flag = strip_pii(text)

        assert flag is True

    @patch("bot.kb.pii_stripper._nlp")
    def test_six_digit_sequence_does_not_set_flag(self, mock_nlp):
        """A 6-digit sequence is not >6 digits and must NOT set the flag.

        Boundary condition: the rescan threshold is strictly greater than 6.
        """
        mock_nlp.return_value = _doc_with_ents()
        text = "Rok 202526 był szczególny."

        stripped, flag = strip_pii(text)

        assert flag is False

    @patch("bot.kb.pii_stripper._nlp")
    def test_clean_text_without_long_digits_returns_false_flag(self, mock_nlp):
        """Text with no digit sequences of any length must return flag=False."""
        mock_nlp.return_value = _doc_with_ents()
        text = "Jak często powinnam odwiedzać lekarza w trakcie ciąży?"

        stripped, flag = strip_pii(text)

        assert flag is False

    @patch("bot.kb.pii_stripper._nlp")
    def test_return_type_is_tuple_of_str_and_bool(self, mock_nlp):
        """strip_pii must return a (str, bool) 2-tuple."""
        mock_nlp.return_value = _doc_with_ents()
        text = "Pytanie bez danych osobowych."

        result = strip_pii(text)

        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], str)
        assert isinstance(result[1], bool)
