"""Hybrid advisory retrieval: BM25 (lexical) + vector similarity, fused with RRF.

Bulletins are Markdown files with a front-matter header (or PDFs, whose text is
extracted with pypdf) under data/bulletins. Each is chunked by paragraph, tagged
with crop and language, and indexed twice:

- BM25 over word tokens (rank_bm25),
- a vector index. The default embedder is a character n-gram TF-IDF model,
  which needs no model download and handles Devanagari inflections reasonably.
  RETRIEVAL_EMBEDDER=sentence-transformers swaps in a multilingual sentence-
  embedding model. Search is a numpy dot product: exact, and instant at this
  corpus size (add an ANN index such as FAISS only past ~100k chunks).

Results from both rankers are combined with reciprocal rank fusion.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import numpy as np
from rank_bm25 import BM25Okapi
from sklearn.feature_extraction.text import TfidfVectorizer

from app.config import DATA_DIR
from app.reference import tokens
from app.translation.glossary import expand_query

log = logging.getLogger(__name__)

BULLETIN_DIR = DATA_DIR / "bulletins"
RRF_K = 60


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    title: str
    crop: str
    language: str
    source: str
    published: str
    text: str
    meta: dict = field(default_factory=dict)


class Embedder(Protocol):
    def fit(self, texts: list[str]) -> None: ...
    def encode(self, texts: list[str]) -> np.ndarray: ...


class CharNgramEmbedder:
    def __init__(self) -> None:
        self._vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), sublinear_tf=True, min_df=1)

    def fit(self, texts: list[str]) -> None:
        self._vec.fit(texts)

    def encode(self, texts: list[str]) -> np.ndarray:
        m = self._vec.transform(texts).toarray().astype(np.float32)
        norms = np.linalg.norm(m, axis=1, keepdims=True)
        return m / np.where(norms == 0, 1, norms)


class SentenceEmbedder:
    """Multilingual sentence embeddings (RETRIEVAL_EMBEDDER=sentence-transformers).

    The default model maps English, Hindi and Marathi into one space, so a Marathi
    question can match an English bulletin without the glossary. Needs
    `pip install sentence-transformers` (downloads ~470 MB on first use).
    """

    def __init__(self, model_name: str, model=None) -> None:
        if model is None:
            from sentence_transformers import SentenceTransformer  # type: ignore

            model = SentenceTransformer(model_name)
        self._model = model

    def fit(self, texts: list[str]) -> None:  # pretrained: nothing to fit
        pass

    def encode(self, texts: list[str]) -> np.ndarray:
        m = np.asarray(self._model.encode(texts, normalize_embeddings=True), dtype=np.float32)
        return m.reshape(len(texts), -1)


def make_embedder() -> Embedder:
    from app.config import get_settings

    s = get_settings()
    if s.retrieval_embedder == "sentence-transformers":
        try:
            return SentenceEmbedder(s.embedding_model)
        except Exception as exc:  # missing package, no network for the download, ...
            log.warning("sentence-transformers embedder unavailable (%s); using char n-grams", exc)
    return CharNgramEmbedder()


_FRONT_MATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


def parse_bulletin(path: Path) -> tuple[dict, str]:
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader

        text = "\n\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
        meta_path = path.with_suffix(".meta")
        meta = _parse_meta(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        meta.setdefault("id", path.stem)
        meta.setdefault("title", path.stem)
        return meta, text
    raw = path.read_text(encoding="utf-8")
    m = _FRONT_MATTER.match(raw)
    if not m:
        return {"id": path.stem, "title": path.stem}, raw
    return _parse_meta(m.group(1)), m.group(2)


def _parse_meta(block: str) -> dict:
    meta = {}
    for line in block.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta


def chunk_text(text: str, max_words: int = 120) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    buf: list[str] = []
    for p in paras:
        if buf and len(" ".join(buf + [p]).split()) > max_words:
            chunks.append(" ".join(buf))
            buf = []
        buf.append(p)
    if buf:
        chunks.append(" ".join(buf))
    return chunks


class AdvisoryIndex:
    def __init__(self, chunks: list[Chunk], embedder: Embedder | None = None) -> None:
        self.chunks = chunks
        self.embedder = embedder or CharNgramEmbedder()
        corpus = [f"{c.title} {c.text}" for c in chunks]
        self.bm25 = BM25Okapi([tokens(t) for t in corpus]) if chunks else None
        if chunks:
            self.embedder.fit(corpus)
            self.vectors = self.embedder.encode(corpus)
        else:
            self.vectors = np.zeros((0, 1), dtype=np.float32)

    @classmethod
    def from_directory(cls, directory: Path = BULLETIN_DIR, embedder: Embedder | None = None) -> "AdvisoryIndex":
        chunks: list[Chunk] = []
        for path in sorted(directory.glob("*")):
            if path.suffix.lower() not in {".md", ".txt", ".pdf"}:
                continue
            try:
                meta, body = parse_bulletin(path)
            except Exception as exc:  # a bad file should not take the index down
                log.warning("could not parse bulletin %s: %s", path, exc)
                continue
            for i, text in enumerate(chunk_text(body)):
                chunks.append(
                    Chunk(
                        chunk_id=f"{meta.get('id', path.stem)}#{i}",
                        doc_id=meta.get("id", path.stem),
                        title=meta.get("title", path.stem),
                        crop=meta.get("crop", "all"),
                        language=meta.get("language", "en"),
                        source=meta.get("source", "unknown"),
                        published=meta.get("published", ""),
                        text=text,
                    )
                )
        log.info("indexed %d advisory chunks from %s", len(chunks), directory)
        return cls(chunks, embedder)

    def search(self, query: str, crop: str | None = None, language: str | None = None, k: int = 3) -> list[dict]:
        if not self.chunks:
            return []
        q = expand_query(query)
        allowed = [i for i, c in enumerate(self.chunks) if crop is None or c.crop in (crop, "all")]
        if not allowed:
            return []

        bm25_scores = self.bm25.get_scores(tokens(q))
        vec_scores = self.vectors @ self.embedder.encode([q])[0]

        def ranks(scores: np.ndarray) -> dict[int, int]:
            order = sorted(allowed, key=lambda i: -scores[i])
            return {i: r for r, i in enumerate(order)}

        r_bm25, r_vec = ranks(bm25_scores), ranks(vec_scores)
        fused = {}
        for i in allowed:
            score = 1 / (RRF_K + r_bm25[i]) + 1 / (RRF_K + r_vec[i])
            if language and self.chunks[i].language == language:
                score *= 1.15  # prefer the farmer's language when relevance is similar
            fused[i] = score

        results = []
        for i in sorted(fused, key=lambda i: -fused[i])[:k]:
            c = self.chunks[i]
            results.append(
                {
                    "chunk_id": c.chunk_id,
                    "title": c.title,
                    "crop": c.crop,
                    "language": c.language,
                    "source": c.source,
                    "published": c.published,
                    "text": c.text,
                    "score": round(fused[i], 5),
                    "bm25": round(float(bm25_scores[i]), 3),
                    "vector": round(float(vec_scores[i]), 3),
                }
            )
        return results


@lru_cache
def get_index() -> AdvisoryIndex:
    return AdvisoryIndex.from_directory(embedder=make_embedder())
