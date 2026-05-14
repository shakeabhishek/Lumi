"""End-to-end smoke test for the ChromaDB memory store.

Runs without mocks: real chromadb persistence, real sentence-transformers
embeddings. Stores a handful of conversation turns, then queries for
semantically related content to verify retrieval ranks the right turn first.

Usage: uv run --extra memory python scripts/memory_smoke.py
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from lumi.runtime.memory import MemoryStore


CORPUS = [
    ("what's the weather like today",          "It's sunny and 72 degrees."),
    ("my partner's name is Mira",              "Got it — I'll remember Mira."),
    ("I usually drink oat milk in my coffee",  "Noted. Oat milk it is."),
    ("set a timer for 5 minutes",              "Timer set for 5 minutes."),
    ("what time does my flight leave tomorrow", "Your flight is at 7:45 AM."),
    ("I'm vegetarian",                          "Understood, I'll keep that in mind."),
]

QUERIES = [
    ("who is my partner",            "Mira"),
    ("what kind of milk do I like",   "oat milk"),
    ("dietary preferences",           "vegetarian"),
    ("flight info",                   "7:45 AM"),
]


def main() -> int:
    print("=== Memory smoke test ===\n")
    print(f"is_available(): {MemoryStore.is_available()}")
    if not MemoryStore.is_available():
        print("FAIL: chromadb/sentence-transformers not installed.")
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="lumi_mem_"))
    try:
        store = MemoryStore(tmp)
        print(f"store created at {tmp}\n")

        print(f"Storing {len(CORPUS)} turns...")
        for user, reply in CORPUS:
            store.store_turn(user, reply)
        print("  done.\n")

        passed = 0
        failed = 0
        for query, expected_substr in QUERIES:
            ctx = store.get_relevant_context(query, n=2)
            top_chunk = ctx.split("\n\n")[0] if ctx else ""
            ok = expected_substr.lower() in top_chunk.lower()
            mark = "OK " if ok else "MISS"
            print(f"[{mark}] query: {query!r}")
            print(f"        expected ~ {expected_substr!r}")
            print(f"        top hit  : {top_chunk[:90]}")
            if ok:
                passed += 1
            else:
                failed += 1
            print()

        print(f"=== {passed}/{passed + failed} queries returned the right top hit ===")
        return 0 if failed == 0 else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
