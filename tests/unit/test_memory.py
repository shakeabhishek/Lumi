"""Tests for MemoryStore — storage, retrieval, and availability check.

Embeddings are owned by the ChromaDB collection (ONNX all-MiniLM-L6-v2), so the
store no longer holds an embedder — add()/query() pass text and the collection
embeds it.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock


from lumi.runtime.memory import MemoryStore


def _make_store() -> MemoryStore:
    """Build a MemoryStore with all I/O mocked out, bypassing _init."""
    store = MemoryStore.__new__(MemoryStore)
    store._data_dir = Path("/tmp/lumi_test")
    store._collection = MagicMock()
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


class TestStoreTurn:
    def test_calls_collection_add(self) -> None:
        store = _make_store()
        store.store_turn("hello", "world")
        store._collection.add.assert_called_once()

    def test_stored_document_contains_both_turns(self) -> None:
        store = _make_store()
        store.store_turn("what time is it", "it is 3pm")
        call_kwargs = store._collection.add.call_args.kwargs
        assert "what time is it" in call_kwargs["documents"][0]
        assert "it is 3pm" in call_kwargs["documents"][0]

    def test_passes_text_not_precomputed_embeddings(self) -> None:
        # Collection owns the embedder now — we must not pass embeddings.
        store = _make_store()
        store.store_turn("hello", "world")
        call_kwargs = store._collection.add.call_args.kwargs
        assert "documents" in call_kwargs
        assert "embeddings" not in call_kwargs

    def test_noop_when_collection_is_none(self) -> None:
        store = _make_store()
        store._collection = None
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
        store._collection.query.return_value = {
            "documents": [["User: hi\nLumi: hello", "User: bye\nLumi: goodbye"]]
        }
        result = store.get_relevant_context("hi")
        assert "User: hi" in result
        assert "User: bye" in result

    def test_queries_by_text(self) -> None:
        store = _make_store()
        store._collection.count.return_value = 1
        store._collection.query.return_value = {"documents": [["doc"]]}
        store.get_relevant_context("find me")
        call_kwargs = store._collection.query.call_args.kwargs
        assert call_kwargs["query_texts"] == ["find me"]

    def test_caps_n_at_collection_size(self) -> None:
        store = _make_store()
        store._collection.count.return_value = 1
        store._collection.query.return_value = {"documents": [["doc"]]}
        store.get_relevant_context("query", n=5)
        call_kwargs = store._collection.query.call_args.kwargs
        assert call_kwargs["n_results"] == 1
