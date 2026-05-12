"""Tests for MemoryStore — storage, retrieval, and availability check."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from lumi.runtime.memory import MemoryStore


def _make_store() -> MemoryStore:
    """Build a MemoryStore with all I/O mocked out, bypassing _init."""
    store = MemoryStore.__new__(MemoryStore)
    store._data_dir = Path("/tmp/lumi_test")
    store._collection = MagicMock()
    store._embed = MagicMock()
    return store


class TestIsAvailable:
    def test_returns_false_when_chromadb_missing(self) -> None:
        saved = sys.modules.get("chromadb")
        sys.modules["chromadb"] = None  # type: ignore[assignment]
        try:
            assert MemoryStore.is_available() is False
        finally:
            if saved is None:
                sys.modules.pop("chromadb", None)
            else:
                sys.modules["chromadb"] = saved

    def test_returns_false_when_sentence_transformers_missing(self) -> None:
        saved = sys.modules.get("sentence_transformers")
        sys.modules["sentence_transformers"] = None  # type: ignore[assignment]
        try:
            assert MemoryStore.is_available() is False
        finally:
            if saved is None:
                sys.modules.pop("sentence_transformers", None)
            else:
                sys.modules["sentence_transformers"] = saved


class TestStoreTurn:
    def test_calls_collection_add(self) -> None:
        store = _make_store()
        store._embed.encode.return_value = MagicMock(tolist=lambda: [0.1, 0.2])
        store.store_turn("hello", "world")
        store._collection.add.assert_called_once()

    def test_stored_document_contains_both_turns(self) -> None:
        store = _make_store()
        store._embed.encode.return_value = MagicMock(tolist=lambda: [0.1])
        store.store_turn("what time is it", "it is 3pm")
        call_kwargs = store._collection.add.call_args.kwargs
        assert "what time is it" in call_kwargs["documents"][0]
        assert "it is 3pm" in call_kwargs["documents"][0]

    def test_noop_when_collection_is_none(self) -> None:
        store = _make_store()
        store._collection = None
        store.store_turn("hello", "world")  # should not raise

    def test_noop_when_embed_is_none(self) -> None:
        store = _make_store()
        store._embed = None
        store.store_turn("hello", "world")  # should not raise


class TestGetRelevantContext:
    def test_returns_empty_when_collection_empty(self) -> None:
        store = _make_store()
        store._collection.count.return_value = 0
        assert store.get_relevant_context("anything") == ""

    def test_returns_empty_when_no_collection(self) -> None:
        store = _make_store()
        store._collection = None
        assert store.get_relevant_context("anything") == ""

    def test_returns_joined_docs(self) -> None:
        store = _make_store()
        store._collection.count.return_value = 2
        store._embed.encode.return_value = MagicMock(tolist=lambda: [0.1])
        store._collection.query.return_value = {
            "documents": [["User: hi\nLumi: hello", "User: bye\nLumi: goodbye"]]
        }
        result = store.get_relevant_context("hi")
        assert "User: hi" in result
        assert "User: bye" in result

    def test_caps_n_at_collection_size(self) -> None:
        store = _make_store()
        store._collection.count.return_value = 1
        store._embed.encode.return_value = MagicMock(tolist=lambda: [0.1])
        store._collection.query.return_value = {"documents": [["doc"]]}
        store.get_relevant_context("query", n=5)
        call_kwargs = store._collection.query.call_args.kwargs
        assert call_kwargs["n_results"] == 1
