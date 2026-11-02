"""Local vector store: cosine search over chunks you own on disk.

The LlamaIndex-minimum, ZYKO-style: an in-memory index with **JSON
persistence you own** (same philosophy as the trace log — no server, no
daemon, no lock-in), thread-safe writes, and typed errors. Add documents,
search by similarity, and feed the hits straight into
``zk.ask(..., context=hits)``.

::

    from zyko import Zyko
    from zyko.rag import HashingEmbedder, VectorStore

    store = VectorStore(HashingEmbedder(), path="kb.json")
    store.add(open("handbook.md").read(), meta={"source": "handbook"})
    hits = store.search("refund policy", k=4)
    answer = zk.ask("what is the refund policy?", context=[h.text for h in hits])
"""

from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from zyko.exceptions import EmbedderError
from zyko.log import get_logger
from zyko.rag.embeddings import chunk_text, cosine

log = get_logger("rag")

_STORE_VERSION = 1


@dataclass
class Hit:
    """One retrieved chunk with its similarity score."""

    text: str
    score: float
    index: int
    meta: dict[str, Any] = field(default_factory=dict)


class VectorStore:
    """In-memory cosine index with optional JSON persistence.

    * ``path=None`` keeps everything in memory (tests, one-shot scripts).
    * ``path="kb.json"`` auto-loads on construction (if the file exists) and
      auto-saves after every ``add`` — atomic (tmp + replace), thread-safe.
    * Searching embeds only the query — one embedder call per search.
    """

    def __init__(self, embedder: Any, *, path: str | Path | None = None) -> None:
        self.embedder = embedder
        self.path = Path(path) if path else None
        self._lock = threading.Lock()
        self._texts: list[str] = []
        self._vectors: list[list[float]] = []
        self._metas: list[dict[str, Any]] = []
        if self.path is not None and self.path.exists():
            self._load()

    # ------------------------------------------------------------------ add
    def add(self, text: str, *, meta: dict[str, Any] | None = None) -> int:
        """Chunk + embed + index one document; returns the number of chunks.

        Empty/whitespace input adds nothing (returns 0). Persists atomically
        when ``path`` was configured.
        """
        chunks = chunk_text(text)
        if not chunks:
            return 0
        vectors = self.embedder.embed(chunks)
        if self._vectors and len(vectors[0]) != len(self._vectors[0]):
            raise EmbedderError(
                f"dimension mismatch: store has {len(self._vectors[0])}, "
                f"new chunks have {len(vectors[0])}",
                hint="mixing embedders (or dims) in one store is not supported",
            )
        with self._lock:
            self._texts.extend(chunks)
            self._vectors.extend(vectors)
            self._metas.extend(dict(meta) if meta else {} for _ in chunks)
        self._save()
        return len(chunks)

    async def aadd(self, text: str, *, meta: dict[str, Any] | None = None) -> int:
        return await asyncio.to_thread(self.add, text, meta=meta)

    # ---------------------------------------------------------------- search
    def search(self, query: str, *, k: int = 4, min_score: float = 0.0) -> list[Hit]:
        """Top-k chunks by cosine similarity (``min_score`` filters noise).

        An empty store or an all-zero query returns ``[]`` — never an error.
        """
        if k < 1:
            raise EmbedderError("k must be >= 1")
        with self._lock:
            if not self._vectors:
                return []
            vectors = list(self._vectors)
            texts = list(self._texts)
            metas = list(self._metas)
        qvec = self.embedder.embed([query])[0]
        scored = [(i, cosine(qvec, vec)) for i, vec in enumerate(vectors)]
        hits = [
            Hit(text=texts[i], score=round(score, 4), index=i, meta=dict(metas[i]))
            for i, score in scored
            if score > min_score
        ]
        hits.sort(key=lambda h: (-h.score, h.index))
        return hits[:k]

    async def asearch(self, query: str, *, k: int = 4, min_score: float = 0.0) -> list[Hit]:
        return await asyncio.to_thread(self.search, query, k=k, min_score=min_score)

    # ------------------------------------------------------------- lifecycle
    def __len__(self) -> int:
        with self._lock:
            return len(self._texts)

    def clear(self) -> None:
        with self._lock:
            self._texts.clear()
            self._vectors.clear()
            self._metas.clear()
        if self.path is not None and self.path.exists():
            self.path.unlink()

    # ------------------------------------------------------------ persistence
    def _save(self) -> None:
        if self.path is None:
            return
        payload = {
            "version": _STORE_VERSION,
            "embedder": self.embedder.name,
            "dim": len(self._vectors[0]) if self._vectors else 0,
            "chunks": [
                {"text": t, "meta": m, "vector": v}
                for t, m, v in zip(self._texts, self._metas, self._vectors)
            ],
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")
            tmp.replace(self.path)
        except OSError as exc:
            # Searching still works from memory; persistence is best-effort.
            log.warning("vector store %s could not be saved (%s)", self.path, exc)

    def _load(self) -> None:
        assert self.path is not None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("vector store %s unreadable (%s) — starting empty", self.path, exc)
            return
        chunks = payload.get("chunks") or []
        stored = payload.get("embedder")
        if stored and stored != self.embedder.name:
            log.warning(
                "vector store %s was built with '%s' but searched with '%s' — "
                "scores will be meaningless; rebuild the store",
                self.path,
                stored,
                self.embedder.name,
            )
        for chunk in chunks:
            self._texts.append(chunk.get("text") or "")
            self._vectors.append(list(chunk.get("vector") or []))
            self._metas.append(dict(chunk.get("meta") or {}))
