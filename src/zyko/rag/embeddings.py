"""Embedders: text → vectors, with a zero-dependency default.

Three ships, one contract (``embed`` / ``aembed`` mapping ``list[str]`` →
``list[list[float]]``):

* :class:`HashingEmbedder` — pure-stdlib feature hashing (the ``hashing
  trick``): deterministic, offline, phone-capable. Not semantic, but honest:
  shared vocabulary scores high, and it makes RAG testable and demoable with
  zero keys and zero network — the same keyless philosophy as ZYKO's mock
  provider.
* :class:`OpenAIEmbedder` — ``/v1/embeddings`` (``text-embedding-3-small``
  by default), also works for any OpenAI-compatible embeddings endpoint.
* :class:`OllamaEmbedder` — local ``/api/embed`` (``nomic-embed-text``),
  real semantics on your own machine, no keys.

Failures raise :class:`~zyko.exceptions.EmbedderError` — a typed ZYKO error,
never a raw ``httpx`` exception.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import os
import re

import httpx

from zyko.exceptions import EmbedderError
from zyko.log import get_logger

log = get_logger("rag")

_TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


class HashingEmbedder:
    """Deterministic feature-hashing embedder — zero deps, offline, instant.

    Each token is hashed (blake2b) into a ``(bucket, sign)`` pair; counts are
    accumulated sign-weighted and L2-normalized. Semantically blind but
    perfectly deterministic and reproducible across machines — ideal for
    tests, demos, Termux and CI. Documents sharing vocabulary rank together;
    do not expect synonymy.
    """

    def __init__(self, dim: int = 256) -> None:
        if dim < 8:
            raise EmbedderError("HashingEmbedder dim must be >= 8", hint="use 256 (default)")
        self.dim = dim
        self.name = f"hashing-{dim}"

    def _one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for token in _tokens(text):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            value = int.from_bytes(digest, "big")
            bucket = value % self.dim
            sign = 1.0 if (value >> 63) & 1 else -1.0
            vec[bucket] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    async def aembed(self, texts: list[str]) -> list[list[float]]:
        return self.embed(texts)


class OpenAIEmbedder:
    """OpenAI-compatible ``/embeddings`` (OpenAI, or any vendor speaking it)."""

    def __init__(
        self,
        *,
        model: str = "text-embedding-3-small",
        api_key: str | None = None,
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 30.0,
    ) -> None:
        self.model = model
        self.name = f"openai/{model}"
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY") or ""
        if not self.api_key:
            raise EmbedderError(
                "OpenAIEmbedder needs an API key",
                hint="pass api_key= or set OPENAI_API_KEY (or use HashingEmbedder/OllamaEmbedder offline)",
            )
        self.dim = 0  # discovered on first response

    def _client(self) -> httpx.Client:
        return httpx.Client(
            timeout=self.timeout,
            headers={"authorization": f"Bearer {self.api_key}"},
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            with self._client() as client:
                resp = client.post(
                    f"{self.base_url}/embeddings",
                    json={"model": self.model, "input": list(texts)},
                )
        except httpx.HTTPError as exc:
            raise EmbedderError(f"embeddings request failed: {exc}") from exc
        if resp.status_code >= 300:
            raise EmbedderError(f"embeddings endpoint returned HTTP {resp.status_code}")
        data = resp.json().get("data") or []
        if len(data) != len(texts):
            raise EmbedderError(
                f"embeddings endpoint returned {len(data)} vectors for {len(texts)} inputs"
            )
        ordered = sorted(data, key=lambda item: item.get("index") or 0)
        vectors = [list(item["embedding"]) for item in ordered]
        if vectors and self.dim == 0:
            self.dim = len(vectors[0])
        return vectors

    async def aembed(self, texts: list[str]) -> list[list[float]]:
        return await asyncio.to_thread(self.embed, texts)


class OllamaEmbedder:
    """Local Ollama ``/api/embed`` — real semantics on your machine, no keys."""

    def __init__(
        self,
        *,
        model: str = "nomic-embed-text",
        base_url: str = "http://127.0.0.1:11434",
        timeout: float = 30.0,
    ) -> None:
        self.model = model
        self.name = f"ollama/{model}"
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.dim = 0  # discovered on first response

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            resp = httpx.post(
                f"{self.base_url}/api/embed",
                json={"model": self.model, "input": list(texts)},
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise EmbedderError(
                f"ollama embed failed: {exc}",
                hint="start ollama and pull the model: ollama pull nomic-embed-text",
            ) from exc
        if resp.status_code >= 300:
            raise EmbedderError(f"ollama embed returned HTTP {resp.status_code}")
        vectors = resp.json().get("embeddings") or []
        if len(vectors) != len(texts):
            raise EmbedderError(f"ollama returned {len(vectors)} vectors for {len(texts)} inputs")
        if vectors and self.dim == 0:
            self.dim = len(vectors[0])
        return [list(v) for v in vectors]

    async def aembed(self, texts: list[str]) -> list[list[float]]:
        return await asyncio.to_thread(self.embed, texts)


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity; zero vectors score 0.0 instead of dividing by zero."""
    if len(a) != len(b):
        raise EmbedderError(
            f"cosine dimension mismatch: {len(a)} vs {len(b)}",
            hint="query and store must use the same embedder (and the same dim)",
        )
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / math.sqrt(na * nb)


def chunk_text(text: str, *, max_chars: int = 800, overlap: int = 120) -> list[str]:
    """Split text into overlapping chunks — paragraphs first, then hard splits.

    Returns at least one chunk for non-empty input and never returns empty
    chunks; empty/whitespace input returns ``[]``. ``overlap`` keeps context
    across the hard-split boundary so an answer never loses the sentence that
    straddles two chunks.
    """
    text = (text or "").strip()
    if not text:
        return []
    if max_chars < 32:
        raise EmbedderError("chunk max_chars must be >= 32", hint="use 800 (default)")
    overlap = max(0, min(overlap, max_chars // 2))
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [text]
    pieces: list[str] = []
    for para in paragraphs:
        if len(para) <= max_chars:
            pieces.append(para)
            continue
        step = max_chars - overlap
        start = 0
        while start < len(para):
            piece = para[start : start + max_chars].strip()
            if piece:
                pieces.append(piece)
            if start + max_chars >= len(para):
                break
            start += step
    return pieces or [text]
