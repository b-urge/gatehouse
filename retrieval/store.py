"""Corpus store: Firestore schema names + deterministic markdown chunking.

Pure stdlib on purpose — CI (which installs only requirements-dev) imports and
tests this module without ADK or Firestore present. The live seed/search code
lazy-imports the cloud clients elsewhere.

Schema (plan §4 "Firestore schema"):
  vendors/{vendor_id}                 vendor record + review status
  corpus_chunks/{chunk_id}            chunk text + embedding Vector + fact metadata
  reviews/{vendor_id}                 assembled ReviewResult (D4+)

Chunk ids are deterministic (doc_id#NN) so re-seeding is idempotent: the same
corpus always produces the same ids, and Firestore set() overwrites in place.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

COLLECTION_VENDORS = "vendors"
COLLECTION_CHUNKS = "corpus_chunks"
COLLECTION_REVIEWS = "reviews"

EMBED_MODEL = "gemini-embedding-001"
EMBED_DIMS = 768  # Firestore vector cap is 2048; model default 3072 — pin (D1 finding)
MODEL_LOCATION = "global"  # Gemini models + embeddings serve on global (D1 finding)
PLATFORM_LOCATION = "us-central1"  # Firestore et al. are regional (D1 finding)

_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)
_MAX_CHUNK = 1400  # chars; sections longer than this split on paragraph boundaries


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    vendor_id: str
    fact_type: str
    issued: str  # ISO date from the manifest/front matter
    content: str
    embedding: list[float] | None = field(default=None, compare=False)

    @property
    def issued_dt(self) -> datetime:
        return datetime.fromisoformat(self.issued)


def parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    """Split a corpus markdown file into (front-matter dict, body)."""
    m = _FRONT_MATTER.match(text)
    if not m:
        return {}, text
    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip('"')
    return meta, text[m.end() :]


def _sections(body: str) -> list[str]:
    """Split on ## headings, keeping each heading with its section text."""
    parts = re.split(r"(?m)^(?=## )", body)
    return [p.strip() for p in parts if p.strip()]


def _split_long(section: str) -> list[str]:
    if len(section) <= _MAX_CHUNK:
        return [section]
    out: list[str] = []
    buf = ""
    for para in section.split("\n\n"):
        candidate = f"{buf}\n\n{para}".strip()
        if buf and len(candidate) > _MAX_CHUNK:
            out.append(buf)
            buf = para
        else:
            buf = candidate
    if buf:
        out.append(buf)
    return out


def chunk_document(
    doc_id: str, vendor_id: str, fact_type: str, issued: str, text: str
) -> list[Chunk]:
    """Deterministically chunk one corpus markdown file."""
    _, body = parse_front_matter(text)
    pieces: list[str] = []
    for section in _sections(body):
        pieces.extend(_split_long(section))
    return [
        Chunk(
            chunk_id=f"{doc_id}#{i:02d}",
            doc_id=doc_id,
            vendor_id=vendor_id,
            fact_type=fact_type,
            issued=issued,
            content=piece,
        )
        for i, piece in enumerate(pieces)
    ]


def load_corpus(corpus_dir: str | Path) -> list[Chunk]:
    """Read manifest.json + the markdown files it names -> flat chunk list."""
    import json

    corpus_dir = Path(corpus_dir)
    manifest = json.loads((corpus_dir / "manifest.json").read_text())
    vendor_id = manifest["vendor_id"]
    chunks: list[Chunk] = []
    for doc in manifest["documents"]:
        text = (corpus_dir / doc["file"]).read_text()
        chunks.extend(
            chunk_document(
                doc_id=doc["doc_id"],
                vendor_id=vendor_id,
                fact_type=doc["fact_type"],
                issued=doc["issued"],
                text=text,
            )
        )
    return chunks
