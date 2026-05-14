"""ChromaDB-backed long-term memory.

Embeds and stores conversation turns so Lumi can recall relevant context
from past sessions. Gracefully no-ops when chromadb / sentence-transformers
are not installed (memory extra not activated).
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from ..log import get_logger

# Workaround for protobuf version mismatch in chromadb's bundled opentelemetry.
# Must be set BEFORE chromadb is imported. Forces the pure-Python protobuf
# implementation, which is slower but compatible. Memory writes are infrequent
# (one per turn) so the perf cost is negligible.
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

log = get_logger(__name__)

_COLLECTION = "lumi_conversations"
_EMBED_MODEL = "all-MiniLM-L6-v2"


class MemoryStore:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._collection = None
        self._embed = None
        self._init()

    def _init(self) -> None:
        try:
            import chromadb  # noqa: PLC0415
            from sentence_transformers import SentenceTransformer  # noqa: PLC0415

            client = chromadb.PersistentClient(path=str(self._data_dir / "chroma"))
            self._collection = client.get_or_create_collection(_COLLECTION)
            self._embed = SentenceTransformer(_EMBED_MODEL)
            log.info("memory.init", collection=_COLLECTION)
        except Exception as exc:
            log.warning("memory.init_failed", error=str(exc))

    def store_turn(self, user_text: str, assistant_reply: str) -> None:
        if self._collection is None or self._embed is None:
            return
        try:
            doc = f"User: {user_text}\nLumi: {assistant_reply}"
            embedding = self._embed.encode(doc).tolist()
            self._collection.add(
                documents=[doc],
                embeddings=[embedding],
                ids=[str(uuid.uuid4())],
            )
        except Exception as exc:
            log.warning("memory.store_failed", error=str(exc))

    def get_relevant_context(self, query: str, n: int = 3) -> str:
        if self._collection is None or self._embed is None:
            return ""
        try:
            count = self._collection.count()
            if count == 0:
                return ""
            results = self._collection.query(
                query_embeddings=[self._embed.encode(query).tolist()],
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
            from sentence_transformers import SentenceTransformer  # noqa: F401, PLC0415

            return True
        except ImportError:
            return False
