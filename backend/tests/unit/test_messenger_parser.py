"""Unit tests for the Messenger .json export parser.

TDD: These tests are written before the implementation (T027).
They define the contract that ``parse_messenger`` must satisfy.

Messenger export format
-----------------------
Facebook's "Download Your Information" JSON export looks like::

    {
      "participants": [{"name": "Sender A"}, {"name": "Sender B"}],
      "messages": [
        {
          "sender_name": "Client Name",
          "timestamp_ms": 1715000000000,
          "content": "message text"
        }
      ],
      "title": "Conversation Title"
    }

Messages are delivered newest-first in the export; the parser must reverse
them into ascending chronological order.  Non-text entries (photos, stickers,
reactions) have no ``content`` field and must be excluded.

Multi-file handling
-------------------
A single long conversation may be split across ``message_1.json``,
``message_2.json``, etc.  ``parse_messenger`` accepts a list of file paths,
merges all messages, and deduplicates on ``(sender_name, timestamp_ms, content)``
before sorting.

Coverage
--------
- Missing ``content`` field is skipped (photos/stickers/reactions excluded)
- Output sorted ascending by ``timestamp_ms``
- Multi-file merge deduplicates on ``(sender_name, timestamp_ms, content)``
- Single file with valid messages returns correct dicts with required keys
- Empty messages list returns empty list
- ``timestamp_ms`` is converted to ISO-8601 UTC string in output
"""
import json
from pathlib import Path

import pytest

from bot.kb.parsers.messenger import parse_messenger


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_json(path: Path, data: dict) -> Path:
    """Write *data* as JSON to *path* and return *path*."""
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _make_export(messages: list[dict]) -> dict:
    """Wrap *messages* in a minimal Messenger export envelope."""
    return {
        "participants": [{"name": "A"}, {"name": "B"}],
        "title": "Test Conversation",
        "messages": messages,
    }


# ---------------------------------------------------------------------------
# Missing content field (photos / stickers / reactions excluded)
# ---------------------------------------------------------------------------

class TestMissingContentSkipped:
    """Entries without a ``content`` key must be silently skipped."""

    def test_single_entry_without_content_returns_empty(self, tmp_path):
        data = _make_export([
            {"sender_name": "Anna", "timestamp_ms": 1715000000000},
        ])
        f = _write_json(tmp_path / "message_1.json", data)
        result = parse_messenger([f])
        assert result == []

    def test_sticker_entry_without_content_is_excluded(self, tmp_path):
        """Sticker messages have a ``sticker`` key but no ``content``."""
        data = _make_export([
            {
                "sender_name": "Anna",
                "timestamp_ms": 1715000001000,
                "sticker": {"uri": "sticker.png"},
            },
        ])
        f = _write_json(tmp_path / "message_1.json", data)
        assert parse_messenger([f]) == []

    def test_photo_entry_without_content_is_excluded(self, tmp_path):
        """Photo messages have a ``photos`` key but no ``content``."""
        data = _make_export([
            {
                "sender_name": "Anna",
                "timestamp_ms": 1715000002000,
                "photos": [{"uri": "photo.jpg", "creation_timestamp": 1715000002}],
            },
        ])
        f = _write_json(tmp_path / "message_1.json", data)
        assert parse_messenger([f]) == []

    def test_mixed_content_and_no_content_entries(self, tmp_path):
        """Only entries WITH ``content`` should appear in the output."""
        data = _make_export([
            {"sender_name": "Bot", "timestamp_ms": 1715000003000, "content": "Hi"},
            {"sender_name": "Anna", "timestamp_ms": 1715000002000},       # no content
            {"sender_name": "Anna", "timestamp_ms": 1715000001000, "content": "Hello"},
        ])
        f = _write_json(tmp_path / "message_1.json", data)
        result = parse_messenger([f])
        assert len(result) == 2
        assert all("content" in m for m in result)


# ---------------------------------------------------------------------------
# Sort order — ascending by timestamp_ms
# ---------------------------------------------------------------------------

class TestSortOrder:
    """Output must be sorted ascending by ``timestamp_ms``."""

    def test_newest_first_export_is_reversed(self, tmp_path):
        """Messenger exports are newest-first; the parser must reverse them."""
        # Messenger stores messages newest-first, so timestamp_ms decreases
        data = _make_export([
            {"sender_name": "Bot",  "timestamp_ms": 1715000002000, "content": "Third"},
            {"sender_name": "Anna", "timestamp_ms": 1715000001000, "content": "Second"},
            {"sender_name": "Anna", "timestamp_ms": 1715000000000, "content": "First"},
        ])
        f = _write_json(tmp_path / "message_1.json", data)
        result = parse_messenger([f])
        assert len(result) == 3
        assert result[0]["content"] == "First"
        assert result[1]["content"] == "Second"
        assert result[2]["content"] == "Third"

    def test_already_sorted_input_remains_correct(self, tmp_path):
        """If input happens to be ascending, output must still be ascending."""
        data = _make_export([
            {"sender_name": "Anna", "timestamp_ms": 1715000000000, "content": "A"},
            {"sender_name": "Bot",  "timestamp_ms": 1715000001000, "content": "B"},
        ])
        f = _write_json(tmp_path / "message_1.json", data)
        result = parse_messenger([f])
        assert result[0]["content"] == "A"
        assert result[1]["content"] == "B"

    def test_timestamps_are_strictly_ascending_in_output(self, tmp_path):
        """Verify ascending order numerically via the timestamp field."""
        data = _make_export([
            {"sender_name": "Bot",  "timestamp_ms": 1715000009000, "content": "Last"},
            {"sender_name": "Anna", "timestamp_ms": 1715000001000, "content": "First"},
            {"sender_name": "Anna", "timestamp_ms": 1715000005000, "content": "Middle"},
        ])
        f = _write_json(tmp_path / "message_1.json", data)
        result = parse_messenger([f])
        # Timestamps in output must be increasing (ISO-8601 sorts lexicographically)
        timestamps = [m["timestamp"] for m in result]
        assert timestamps == sorted(timestamps)


# ---------------------------------------------------------------------------
# Multi-file merge and deduplication on (sender_name, timestamp_ms, content)
# ---------------------------------------------------------------------------

class TestMultiFileMergeAndDedup:
    """Multi-file exports must be merged and deduplicated."""

    def test_two_files_are_merged(self, tmp_path):
        """Messages from two files must appear in the combined output."""
        f1 = _write_json(
            tmp_path / "message_1.json",
            _make_export([
                {"sender_name": "Anna", "timestamp_ms": 1715000000000, "content": "Hi"},
            ]),
        )
        f2 = _write_json(
            tmp_path / "message_2.json",
            _make_export([
                {"sender_name": "Bot",  "timestamp_ms": 1715000001000, "content": "Hello"},
            ]),
        )
        result = parse_messenger([f1, f2])
        assert len(result) == 2
        senders = {m["sender"] for m in result}
        assert senders == {"Anna", "Bot"}

    def test_duplicate_message_across_files_is_deduplicated(self, tmp_path):
        """The same (sender_name, timestamp_ms, content) tuple must appear once."""
        duplicate = {"sender_name": "Anna", "timestamp_ms": 1715000000000, "content": "Hi"}
        f1 = _write_json(tmp_path / "message_1.json", _make_export([duplicate]))
        f2 = _write_json(tmp_path / "message_2.json", _make_export([duplicate]))
        result = parse_messenger([f1, f2])
        assert len(result) == 1

    def test_same_sender_different_timestamp_not_deduplicated(self, tmp_path):
        """Two messages from the same sender with different timestamps are distinct."""
        f1 = _write_json(
            tmp_path / "message_1.json",
            _make_export([
                {"sender_name": "Anna", "timestamp_ms": 1715000000000, "content": "Hi"},
            ]),
        )
        f2 = _write_json(
            tmp_path / "message_2.json",
            _make_export([
                {"sender_name": "Anna", "timestamp_ms": 1715000001000, "content": "Hi"},
            ]),
        )
        result = parse_messenger([f1, f2])
        assert len(result) == 2

    def test_same_sender_same_timestamp_different_content_not_deduplicated(self, tmp_path):
        """Different content at the same timestamp is distinct (edge case)."""
        f1 = _write_json(
            tmp_path / "message_1.json",
            _make_export([
                {"sender_name": "Anna", "timestamp_ms": 1715000000000, "content": "Hi"},
            ]),
        )
        f2 = _write_json(
            tmp_path / "message_2.json",
            _make_export([
                {"sender_name": "Anna", "timestamp_ms": 1715000000000, "content": "Bye"},
            ]),
        )
        result = parse_messenger([f1, f2])
        assert len(result) == 2

    def test_multi_file_result_is_sorted_ascending(self, tmp_path):
        """After merging multiple files the output must still be ascending."""
        # File 1 has a later message, file 2 has an earlier one
        f1 = _write_json(
            tmp_path / "message_1.json",
            _make_export([
                {"sender_name": "Bot",  "timestamp_ms": 1715000002000, "content": "Later"},
            ]),
        )
        f2 = _write_json(
            tmp_path / "message_2.json",
            _make_export([
                {"sender_name": "Anna", "timestamp_ms": 1715000000000, "content": "Earlier"},
            ]),
        )
        result = parse_messenger([f1, f2])
        assert result[0]["content"] == "Earlier"
        assert result[1]["content"] == "Later"


# ---------------------------------------------------------------------------
# Required keys and empty inputs
# ---------------------------------------------------------------------------

class TestOutputShape:
    """Output dicts must have exactly the required keys; edge cases handled."""

    def test_single_message_returns_required_keys(self, tmp_path):
        data = _make_export([
            {"sender_name": "Anna", "timestamp_ms": 1715000000000, "content": "Hello"},
        ])
        f = _write_json(tmp_path / "message_1.json", data)
        result = parse_messenger([f])
        assert len(result) == 1
        assert set(result[0].keys()) >= {"timestamp", "sender", "content"}

    def test_sender_field_matches_sender_name(self, tmp_path):
        data = _make_export([
            {"sender_name": "Anna Kowalska", "timestamp_ms": 1715000000000, "content": "Msg"},
        ])
        f = _write_json(tmp_path / "message_1.json", data)
        result = parse_messenger([f])
        assert result[0]["sender"] == "Anna Kowalska"

    def test_content_field_matches_message_content(self, tmp_path):
        data = _make_export([
            {"sender_name": "Bot", "timestamp_ms": 1715000000000, "content": "Test message"},
        ])
        f = _write_json(tmp_path / "message_1.json", data)
        result = parse_messenger([f])
        assert result[0]["content"] == "Test message"

    def test_empty_messages_list_returns_empty(self, tmp_path):
        data = _make_export([])
        f = _write_json(tmp_path / "message_1.json", data)
        assert parse_messenger([f]) == []

    def test_empty_file_list_returns_empty(self):
        assert parse_messenger([]) == []

    def test_timestamp_is_iso8601_utc_string(self, tmp_path):
        """timestamp_ms must be converted to an ISO-8601 UTC string."""
        # 1715000000000 ms = 2024-05-06T19:33:20+00:00
        data = _make_export([
            {"sender_name": "Anna", "timestamp_ms": 1715000000000, "content": "Hi"},
        ])
        f = _write_json(tmp_path / "message_1.json", data)
        result = parse_messenger([f])
        ts = result[0]["timestamp"]
        # Must be a string and contain the date portion
        assert isinstance(ts, str)
        assert "2024-05-06" in ts
