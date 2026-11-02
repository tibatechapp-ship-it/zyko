"""Public RAG surface: ``from zyko.rag import VectorStore``.

The LlamaIndex-minimum layer: chunk + embed + cosine search over files you
own, with a deterministic zero-dependency default embedder and typed errors.
Feed hits into ``zk.ask(..., context=[h.text for h in hits])``.
"""

from __future__ import annotations

from zyko.rag.embeddings import (
    HashingEmbedder,
    OllamaEmbedder,
    OpenAIEmbedder,
    chunk_text,
    cosine,
)
from zyko.rag.store import Hit, VectorStore

__all__ = [
    "HashingEmbedder",
    "Hit",
    "OllamaEmbedder",
    "OpenAIEmbedder",
    "VectorStore",
    "chunk_text",
    "cosine",
]
