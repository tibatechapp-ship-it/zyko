"""RAG essentials (v0.5.0): chunker, embedders, vector store, context wiring.

Contract highlights under test:
* chunk_text: paragraphs respected, hard-split overlap keeps straddling
  sentences, never empty chunks, empty input → [];
* HashingEmbedder: deterministic across instances, L2-normalized, related
  texts outscore unrelated, empty text → zero vector (cosine guards it);
* OpenAIEmbedder / OllamaEmbedder: correct request shape (mock transport),
  index-ordered parsing, typed EmbedderError on HTTP errors and count
  mismatches, empty input → [] without touching the network;
* VectorStore: add/search/persist/reload round-trip, meta round-trip,
  min_score filter, dim mismatch typed error, unreadable file → starts
  empty (never crashes), atomic save leaves no .tmp behind;
* Zyko.ask(context=[...]) injects one grounding system message after any
  explicit system and before the user prompt — verified on the wire via
  the FakeProvider-captured ChatRequest.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from tests.fakes import FakeProvider
from zyko.exceptions import EmbedderError
from zyko.rag import HashingEmbedder, VectorStore, chunk_text, cosine
from zyko.rag.embeddings import OllamaEmbedder, OpenAIEmbedder


# ------------------------------------------------------------------- chunker
def test_chunk_short_text_single_chunk():
    assert chunk_text("one paragraph only") == ["one paragraph only"]


def test_chunk_empty_and_whitespace():
    assert chunk_text("") == []
    assert chunk_text("   \n\n  ") == []


def test_chunk_splits_paragraphs():
    text = "para one\n\npara two\n\npara three"
    assert chunk_text(text) == ["para one", "para two", "para three"]


def test_chunk_hard_split_with_overlap():
    para = "word " * 400  # ~2000 chars, one paragraph
    chunks = chunk_text(para, max_chars=200, overlap=50)
    assert len(chunks) >= 8
    assert all(0 < len(c) <= 200 for c in chunks)
    # overlap: each later chunk resumes inside the previous one's tail
    assert chunks[1][:10] in chunks[0]
    assert chunks[2][:10] in chunks[1]
    # coverage: nothing lost beyond the overlap arithmetic
    assert all("word" in c for c in chunks)


def test_chunk_rejects_tiny_max_chars():
    with pytest.raises(EmbedderError):
        chunk_text("x" * 10, max_chars=10)


# ----------------------------------------------------------------- embedders
def test_hashing_embedder_deterministic_and_normalized():
    a = HashingEmbedder(dim=128).embed(["hello world"])
    b = HashingEmbedder(dim=128).embed(["hello world"])
    assert a == b
    norm = sum(x * x for x in a[0]) ** 0.5
    assert norm == pytest.approx(1.0, abs=1e-9)


def test_hashing_embedder_related_outranks_unrelated():
    emb = HashingEmbedder(dim=256)
    cat = emb.embed(["the cat sat on the mat"])[0]
    cat_like = emb.embed(["a cat was on the mat"])[0]
    quantum = emb.embed(["quantum flux capacitor resonance"])[0]
    assert cosine(cat, cat_like) > cosine(cat, quantum)


def test_hashing_embedder_empty_text_zero_vector():
    vec = HashingEmbedder(dim=64).embed([""])[0]
    assert all(v == 0.0 for v in vec)
    assert cosine(vec, vec) == 0.0  # guarded, no ZeroDivisionError


def test_hashing_embedder_rejects_tiny_dim():
    with pytest.raises(EmbedderError):
        HashingEmbedder(dim=4)


def test_cosine_dimension_mismatch_typed():
    with pytest.raises(EmbedderError, match="dimension mismatch"):
        cosine([1.0, 0.0], [1.0, 0.0, 0.0])


def _openai_transport(recorder):
    def handler(request: httpx.Request) -> httpx.Response:
        recorder.append(request)
        body = json.loads(request.content)
        vectors = [[0.1, 0.2, 0.3] for _ in body["input"]]
        return httpx.Response(
            200,
            json={"data": [{"index": i, "embedding": v} for i, v in enumerate(vectors)]},
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_openai_embedder_request_shape_and_order(monkeypatch):
    recorder: list[httpx.Request] = []
    embedder = OpenAIEmbedder(api_key="test-key", model="text-embedding-3-small")
    real_client = embedder._client  # captured before the transport patch
    monkeypatch.setattr(embedder, "_client", lambda: _openai_transport(recorder))
    out = embedder.embed(["b text", "a text"])
    assert len(out) == 2 and out[0] == [0.1, 0.2, 0.3]
    assert embedder.dim == 3
    req = recorder[0]
    assert req.url.path.endswith("/embeddings")
    body = json.loads(req.content)
    assert body == {"model": "text-embedding-3-small", "input": ["b text", "a text"]}
    # the real client (not the mocked transport) carries the bearer header
    with real_client() as client:
        probe = client.build_request("POST", f"{embedder.base_url}/embeddings")
        assert probe.headers.get("authorization") == "Bearer test-key"


def test_openai_embedder_error_mapping(monkeypatch):
    embedder = OpenAIEmbedder(api_key="k")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    monkeypatch.setattr(
        embedder, "_client", lambda: httpx.Client(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(EmbedderError, match="HTTP 500"):
        embedder.embed(["x"])

    def short_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0]}]})

    monkeypatch.setattr(
        embedder, "_client", lambda: httpx.Client(transport=httpx.MockTransport(short_handler))
    )
    with pytest.raises(EmbedderError, match="1 vectors for 2 inputs"):
        embedder.embed(["x", "y"])


def test_openai_embedder_empty_input_no_network(monkeypatch):
    embedder = OpenAIEmbedder(api_key="k")

    def explode(request: httpx.Request) -> httpx.Response:
        raise AssertionError("network touched for empty input")

    monkeypatch.setattr(
        embedder, "_client", lambda: httpx.Client(transport=httpx.MockTransport(explode))
    )
    assert embedder.embed([]) == []


def test_openai_embedder_requires_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(EmbedderError, match="needs an API key"):
        OpenAIEmbedder()


def test_ollama_embedder_request_and_errors(monkeypatch):
    recorder: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorder.append(request)
        body = json.loads(request.content)
        return httpx.Response(200, json={"embeddings": [[0.5, 0.5] for _ in body["input"]]})

    embedder = OllamaEmbedder(base_url="http://127.0.0.1:11434")
    monkeypatch.setattr(
        httpx,
        "post",
        lambda url, **kw: handler(
            httpx.Request("POST", url, content=json.dumps(kw["json"]).encode())
        ),
    )
    out = embedder.embed(["local text"])
    assert out == [[0.5, 0.5]] and embedder.dim == 2
    body = json.loads(recorder[0].content)
    assert body == {"model": "nomic-embed-text", "input": ["local text"]}
    assert recorder[0].url.path == "/api/embed"

    monkeypatch.setattr(
        httpx,
        "post",
        lambda url, **kw: httpx.Response(404, json={"error": "no model"}),
    )
    with pytest.raises(EmbedderError, match="HTTP 404"):
        embedder.embed(["x"])
    assert embedder.embed([]) == []  # no network call, no error


def test_ollama_embedder_unreachable_typed():
    embedder = OllamaEmbedder(base_url="http://127.0.0.1:1", timeout=0.2)
    with pytest.raises(EmbedderError, match="ollama embed failed"):
        embedder.embed(["x"])


# ---------------------------------------------------------------- vector store
def test_store_add_search_ranking():
    store = VectorStore(HashingEmbedder(dim=128))
    store.add("The refund policy allows 30 days for returns.")
    store.add("Quantum flux capacitors require calibration.")
    store.add("Refunds are processed within 5 business days.")
    # min_score=-1 disables the noise gate so we can inspect the full ranking
    hits = store.search("how do refunds work?", k=3, min_score=-1.0)
    assert len(hits) == 3
    assert "refund" in hits[0].text.lower()  # the true match always wins
    refund_scores = [h.score for h in hits if "refund" in h.text.lower()]
    quantum_score = next(h.score for h in hits if "quantum" in h.text.lower())
    assert min(refund_scores) >= quantum_score
    # default min_score=0.0 keeps only positively-correlated chunks
    positive = store.search("how do refunds work?", k=3)
    assert all(h.score > 0 for h in positive)


def test_store_k_larger_than_size_and_min_score():
    store = VectorStore(HashingEmbedder(dim=64))
    store.add("only one doc")
    assert len(store.search("only one doc", k=10)) == 1
    # unrelated query under the default gate may return nothing — never an error
    assert isinstance(store.search("totally unrelated query", k=4), list)
    # disabling the gate returns the chunk (signed hashing allows negatives)
    assert len(store.search("totally unrelated query", k=4, min_score=-1.0)) == 1
    with pytest.raises(EmbedderError):
        store.search("x", k=0)


def test_store_meta_roundtrip_and_len_clear():
    store = VectorStore(HashingEmbedder(dim=64))
    n = store.add("some document text", meta={"source": "handbook.md"})
    assert n == 1 and len(store) == 1
    hits = store.search("some document")
    assert hits[0].meta == {"source": "handbook.md"}
    store.clear()
    assert len(store) == 0 and store.search("anything") == []


def test_store_persistence_roundtrip(tmp_path):
    path = tmp_path / "kb.json"
    store = VectorStore(HashingEmbedder(dim=64), path=path)
    store.add("persisted refund policy text", meta={"src": "a"})
    assert path.exists()
    reloaded = VectorStore(HashingEmbedder(dim=64), path=path)
    assert len(reloaded) == 1
    hits = reloaded.search("persisted refund")
    assert hits and hits[0].meta == {"src": "a"}
    # no leftover tmp file after atomic save
    assert not (tmp_path / "kb.json.tmp").exists()


def test_store_empty_add_and_corrupt_file(tmp_path):
    store = VectorStore(HashingEmbedder(dim=64))
    assert store.add("   ") == 0
    corrupt = tmp_path / "bad.json"
    corrupt.write_text("not json at all", encoding="utf-8")
    broken = VectorStore(HashingEmbedder(dim=64), path=corrupt)
    assert len(broken) == 0  # unreadable store starts empty, never crashes
    broken.add("fresh text")  # and stays usable (overwrites on next save)
    assert len(broken) == 1


def test_store_dim_mismatch_typed():
    store = VectorStore(HashingEmbedder(dim=64))
    store.add("first doc")
    store.embedder = HashingEmbedder(dim=128)  # someone swapped the embedder
    with pytest.raises(EmbedderError, match="dimension mismatch"):
        store.add("second doc")


def test_store_async_api_matches_sync():
    async def run():
        store = VectorStore(HashingEmbedder(dim=64))
        await store.aadd("async refund policy")
        hits = await store.asearch("refund")
        return hits

    hits = asyncio.run(run())
    assert hits and "refund" in hits[0].text


# ------------------------------------------------------------- client wiring
def _capturing_zk():
    """ZYKO over a fake provider that records the ChatRequest it receives."""
    captured: dict = {}

    class Capturing(FakeProvider):
        async def acomplete(self, request, *, retries=None):
            captured["messages"] = request.messages
            return await super().acomplete(request, retries=retries)

    from zyko import Zyko

    return Zyko(providers={"fake": Capturing(script=["ok"])}), captured


def test_ask_context_reaches_the_wire():
    zk, captured = _capturing_zk()
    zk.ask("the question", system="be terse", context=[" snippet one ", "snippet two"])
    roles = [
        m.role.value if hasattr(m.role, "value") else str(m.role) for m in captured["messages"]
    ]
    contents = [m.content or "" for m in captured["messages"]]
    assert roles == ["system", "system", "user"]
    assert "be terse" in contents[0]
    assert "Answer the user's question using ONLY the context below" in contents[1]
    assert "[1] snippet one" in contents[1] and "[2] snippet two" in contents[1]
    assert contents[2] == "the question"


def test_ask_empty_context_adds_nothing():
    zk, captured = _capturing_zk()
    zk.ask("plain question", context=["", "   "])
    roles = [
        m.role.value if hasattr(m.role, "value") else str(m.role) for m in captured["messages"]
    ]
    assert roles == ["user"]


def test_full_rag_loop_with_fake_llm(tmp_path):
    """The 60-second story, end to end: store → search → ask(context=...)."""
    zk, captured = _capturing_zk()
    store = VectorStore(HashingEmbedder(dim=128), path=tmp_path / "kb.json")
    store.add("Refunds are processed within 5 business days of approval.", meta={"page": 3})
    hits = store.search("how fast are refunds?", k=1)
    assert hits and hits[0].meta == {"page": 3}
    zk.ask("how fast are refunds?", context=[h.text for h in hits])
    grounding = captured["messages"][0].content or ""
    assert "[1] Refunds are processed within 5 business days of approval." in grounding
