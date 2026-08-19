"""Local-first ranked retrieval; stdlib BM25, Unicode and Vietnamese friendly."""
from __future__ import annotations

import json
import math
import re
import time
import unicodedata
import urllib.request
from collections import Counter

from litebrowser.core import prefs
from litebrowser.services import ai_service

_WORD_RE = re.compile(r"[^\W_]{2,}", re.UNICODE)
_CACHE: dict[tuple[str, str], tuple[list, Counter, float]] = {}
_SOURCE_BOOST = {"vault_note": 1.16, "task": 1.12, "calendar": 1.08, "saved_page": 1.05, "board_note": 1.05}


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", (text or "").casefold().replace("đ", "d"))
    return "".join(char for char in text if not unicodedata.combining(char))


def _tokens(text: str) -> list[str]:
    return _WORD_RE.findall(_fold(text))


def _terms(doc: ai_service.AIDoc) -> Counter:
    terms = Counter()
    for text, weight in ((doc.title, 4), (doc.url, 2), (doc.snippet, 1)):
        for token in _tokens(text):
            terms[token] += weight
    return terms


def _compiled(base_dir: str, force_rebuild: bool = False):
    docs = ai_service.index_docs(base_dir, force_rebuild=force_rebuild)
    data = ai_service.load_index(base_dir)
    key = (base_dir, str(data.get("signature") or data.get("built_at") or ""))
    cached = _CACHE.get(key)
    if cached:
        return cached
    _CACHE.clear()  # #[c] one active profile index is enough; prevents long-lived profile leaks.
    rows, df, total_len = [], Counter(), 0
    for doc in docs:
        terms = _terms(doc)
        if not terms:
            continue
        title = _fold(doc.title)
        text = _fold(f"{doc.title}\n{doc.url}\n{doc.snippet}")
        rows.append((doc, terms, max(1, sum(terms.values())), title, text))
        total_len += rows[-1][2]
        df.update(terms.keys())
    compiled = (rows, df, total_len / max(1, len(rows)))
    _CACHE[key] = compiled
    return compiled


def collect_docs(base_dir: str):
    return ai_service.collect_docs(base_dir)


def search(base_dir: str, query: str, top_k: int = 8, force_rebuild: bool = False):
    query_terms = Counter(_tokens(query))
    if not query_terms:
        return []
    rows, df, avg_len = _compiled(base_dir, force_rebuild)
    corpus_size, phrase, now = len(rows), _fold(query).strip(), time.time()
    ranked = []
    for doc, terms, length, title, text in rows:
        score = 0.0
        for term, qtf in query_terms.items():
            tf = terms.get(term, 0)
            if not tf:
                continue
            idf = math.log1p((corpus_size - df[term] + 0.5) / (df[term] + 0.5))
            score += qtf * idf * (tf * 2.0 / (tf + 1.2 * (0.25 + 0.75 * length / avg_len)))
            if term in title:
                score += 1.25
        if score <= 0:
            continue
        if phrase and len(query_terms) > 1 and phrase in text:
            score += 2.5
        if doc.source == "history":
            try:
                age_days = max(0.0, (now - int(doc.meta.get("ts", 0))) / 86400)
                score += 0.35 / (1.0 + age_days / 30.0)
            except (TypeError, ValueError):
                pass
        ranked.append((score * _SOURCE_BOOST.get(doc.source, 1.0), doc))
    ranked.sort(key=lambda item: (-item[0], item[1].title.casefold(), item[1].url))
    return [(round(score, 3), doc) for score, doc in ranked[:max(1, min(int(top_k or 8), 50))]]


_OLLAMA_EMBED_URL = "http://127.0.0.1:11434/api/embeddings"


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def _ollama_embedding(model: str, text: str, timeout: float = 1.5) -> list[float]:
    """Return a unit-length embedding from a local Ollama server, or [] on failure.

    The model must already be pulled in Ollama. Any network/parse error returns
    an empty list so callers can fall back to BM25 without surfacing noise.
    """
    if not model or not text:
        return []
    try:
        payload = json.dumps({"model": model, "prompt": (text or "")[:3000]}).encode("utf-8")
        req = urllib.request.Request(
            _OLLAMA_EMBED_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        emb = data.get("embedding") if isinstance(data, dict) else None
        if isinstance(emb, list) and emb:
            vector = [float(x) for x in emb]
            norm = math.sqrt(sum(x * x for x in vector)) or 1.0
            return [x / norm for x in vector]
    except Exception:
        return []
    return []


def _embedding_model_name(base_dir: str):
    """Return the configured Ollama model when the AI provider is Ollama, else None."""
    try:
        settings = prefs.load_ai_settings(base_dir)
    except Exception:
        return None
    if (settings.get("provider") or "") != "ollama":
        return None
    model = (settings.get("ollama_model") or "").strip()
    return model or None


def _doc_text(doc: ai_service.AIDoc) -> str:
    return f"{doc.title}\n{doc.url}\n{doc.snippet}"[:1500]


def search_hybrid(base_dir: str, query: str, top_k: int = 8, force_rebuild: bool = False):
    """BM25 retrieval optionally re-ranked with a local Ollama embedding.

    When an Ollama model is reachable the query and top BM25 candidates are
    embedded and a cosine score is blended in, so semantically related items
    surface even when the exact words differ. Every failure path returns pure
    BM25, so the feature can never make search slower or empty.
    """
    final_k = max(1, min(int(top_k or 8), 50))
    candidate_k = max(final_k * 3, 12)
    bm25 = search(base_dir, query, top_k=candidate_k, force_rebuild=force_rebuild)
    if not bm25:
        return []
    model = _embedding_model_name(base_dir)
    if not model:
        return bm25[:final_k]
    query_vec = _ollama_embedding(model, query)
    if not query_vec:
        return bm25[:final_k]
    scored = []
    for rank, (score, doc) in enumerate(bm25):
        cosine = 0.0
        if rank < 12:  # semantic pass only for the strongest lexical candidates
            doc_vec = _ollama_embedding(model, _doc_text(doc))
            if doc_vec:
                cosine = _cosine(query_vec, doc_vec)
        blended = score + 3.0 * cosine
        scored.append((blended, score, doc))
    scored.sort(key=lambda item: -item[0])
    return [(round(score, 3), doc) for _blended, score, doc in scored[:final_k]]


def rule_based_answer(query: str, results: list[tuple[float, ai_service.AIDoc]]) -> str:
    if not results:
        return "No related items found in local data. Try adding a site name, file, or more specific keywords."
    lines = ["Here are the most relevant items found:"]
    for idx, (_score, doc) in enumerate(results, 1):
        lines.append(f"{idx}) [{doc.source}] {doc.title or doc.url}")
        if doc.url:
            lines.append(f"   - {doc.url}")
        if doc.snippet:
            short = doc.snippet.replace("\n", " ").strip()
            lines.append(f"   - {short[:180]}{'...' if len(short) > 180 else ''}")
    return "\n".join(lines)
