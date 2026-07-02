"""ChromaDB-backed long-term memory.

Embeds and stores conversation turns so Lumi can recall relevant context
from past sessions. Gracefully no-ops when chromadb is not installed
(memory extra not activated).

Embeddings use ChromaDB's built-in ONNX ``all-MiniLM-L6-v2``
(``DefaultEmbeddingFunction``), which runs on onnxruntime (already a core dep
for Piper) — no PyTorch. Same model as the previous sentence-transformers
path, but ~1 GB less resident RAM and a faster cold start — useful headroom
for V2 (full OpenClaw runtime + MCP servers + a ChromaDB that grows over time).
"""

from __future__ import annotations

import uuid
from pathlib import Path

from ..log import get_logger

log = get_logger(__name__)

_COLLECTION = "lumi_conversations"
_EMBED_MODEL = "all-MiniLM-L6-v2"  # via ChromaDB's ONNX DefaultEmbeddingFunction


class MemoryStore:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._collection = None
        self._init()

    def _init(self) -> None:
        try:
            import chromadb  # noqa: PLC0415
            from chromadb.utils import embedding_functions  # noqa: PLC0415

            client = chromadb.PersistentClient(path=str(self._data_dir / "chroma"))
            # DefaultEmbeddingFunction = ONNX all-MiniLM-L6-v2 (no torch). The
            # collection owns the embedder, so add()/query() embed automatically.
            embed_fn = embedding_functions.DefaultEmbeddingFunction()
            self._collection = client.get_or_create_collection(
                _COLLECTION, embedding_function=embed_fn
            )
            log.info("memory.init", collection=_COLLECTION, embed_model=_EMBED_MODEL)
        except Exception as exc:
            log.warning("memory.init_failed", error=str(exc))

    def store_turn(self, user_text: str, assistant_reply: str) -> None:
        if self._collection is None:
            return
        try:
            doc = f"User: {user_text}\nLumi: {assistant_reply}"
            # Collection embeds the document itself (ONNX MiniLM).
            self._collection.add(
                documents=[doc],
                ids=[str(uuid.uuid4())],
            )
        except Exception as exc:
            log.warning("memory.store_failed", error=str(exc))

    def get_relevant_context(self, query: str, n: int = 3) -> str:
        if self._collection is None:
            return ""
        try:
            count = self._collection.count()
            if count == 0:
                return ""
            results = self._collection.query(
                query_texts=[query],
                n_results=min(n, count),
            )
            docs: list[str] = results.get("documents", [[]])[0]
            return "\n\n".join(docs) if docs else ""
        except Exception as exc:
            log.warning("memory.query_failed", error=str(exc))
            return ""

    @staticmethod
    def is_available() -> bool:
        try:
            import chromadb  # noqa: F401, PLC0415

            return True
        except ImportError:
            return False
