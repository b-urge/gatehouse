"""Validity-gated retrieval — the triad in one class (plan §3):

    Firestore finds what's similar; chronofy decides what's still true enough
    to rely on; pollard proves what was consulted.

Design: the two cloud touchpoints (embed the query, nearest-neighbor search)
are injectable seams. Tests inject fakes and exercise the gate offline; the
default seams lazy-import genai/Firestore so importing this module never
requires cloud credentials (CI installs neither).

Pollard integration is a callback (`on_consultation`) rather than a hard
dependency: the orchestrator wires the real ledger on D4; until then the
evidence_node id is "unrecorded".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Protocol

from chronofy import TemporalFact

from retrieval.store import (
    COLLECTION_CHUNKS,
    EMBED_DIMS,
    EMBED_MODEL,
    MODEL_LOCATION,
)
from retrieval.validity import DECAY, gate, verify_freshness


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    doc_id: str
    fact_type: str
    issued: str
    content: str
    distance: float
    validity: float


@dataclass
class RetrievalResult:
    query: str
    query_time: datetime
    valid: list[Hit] = field(default_factory=list)
    pruned: list[Hit] = field(default_factory=list)
    stl_satisfied: bool = True
    stl_robustness: float = 0.0
    evidence_node: str = "unrecorded"

    def to_dict(self) -> dict:
        """The consultation as the ledger records it and the reviewer receives it."""
        return {
            "valid_evidence": [
                {
                    "chunk_id": h.chunk_id,
                    "doc_id": h.doc_id,
                    "fact_type": h.fact_type,
                    "issued": h.issued,
                    "validity": round(h.validity, 3),
                    "content": h.content,
                }
                for h in self.valid
            ],
            "pruned_evidence": [
                {
                    "chunk_id": h.chunk_id,
                    "doc_id": h.doc_id,
                    "fact_type": h.fact_type,
                    "issued": h.issued,
                    "validity": round(h.validity, 3),
                }
                for h in self.pruned
            ],
            "pruned_notices": self.reacquisition_notices(),
            "stl_satisfied": self.stl_satisfied,
            "stl_robustness": round(self.stl_robustness, 3),
        }

    def reacquisition_notices(self) -> list[str]:
        """Human-readable prune notices — these become re-acquisition findings."""
        return [
            (
                f"{h.doc_id} ({h.fact_type}, issued {h.issued}) pruned: "
                f"validity {h.validity:.3f} < 0.5 — request updated evidence."
            )
            for h in self.pruned
        ]


class SearchFn(Protocol):
    def __call__(self, query_vector: list[float], k: int) -> list[dict]: ...


def _default_embed_fn() -> Callable[[str, str], list[float]]:
    """Live query embedding via gemini-embedding-001 on the global endpoint."""
    import os

    from dotenv import load_dotenv
    from google import genai
    from google.genai import types

    load_dotenv("agents/hello/.env")
    client = genai.Client(
        vertexai=True,
        project=os.environ["GOOGLE_CLOUD_PROJECT"],
        location=MODEL_LOCATION,
    )

    def embed(text: str, task: str) -> list[float]:
        r = client.models.embed_content(
            model=EMBED_MODEL,
            contents=text,
            config=types.EmbedContentConfig(output_dimensionality=EMBED_DIMS, task_type=task),
        )
        return list(r.embeddings[0].values)

    return embed


def _default_search_fn() -> SearchFn:
    """Live nearest-neighbor over Firestore's native vector index."""
    import os

    from dotenv import load_dotenv
    from google.cloud import firestore
    from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
    from google.cloud.firestore_v1.vector import Vector

    load_dotenv("agents/hello/.env")
    db = firestore.Client(project=os.environ["GOOGLE_CLOUD_PROJECT"])

    def search(query_vector: list[float], k: int) -> list[dict]:
        hits = (
            db.collection(COLLECTION_CHUNKS)
            .find_nearest(
                vector_field="embedding",
                query_vector=Vector(query_vector),
                limit=k,
                distance_measure=DistanceMeasure.COSINE,
                distance_result_field="dist",
            )
            .get()
        )
        out = []
        for h in hits:
            d = h.to_dict()
            out.append(
                {
                    "chunk_id": h.id,
                    "doc_id": d["doc_id"],
                    "fact_type": d["fact_type"],
                    "issued": d["issued"],
                    "content": d["content"],
                    "distance": float(d.get("dist", 0.0)),
                }
            )
        return out

    return search


class ValidityGatedRetriever:
    """find_nearest -> chronofy gate -> STL verdict -> (optional) pollard node."""

    def __init__(
        self,
        embed_fn: Callable[[str, str], list[float]] | None = None,
        search_fn: SearchFn | None = None,
        on_consultation: Callable[[dict], str] | None = None,
    ) -> None:
        self._embed_fn = embed_fn
        self._search_fn = search_fn
        self._on_consultation = on_consultation

    def _embed(self, text: str, task: str) -> list[float]:
        if self._embed_fn is None:
            self._embed_fn = _default_embed_fn()
        return self._embed_fn(text, task)

    def _search(self, vec: list[float], k: int) -> list[dict]:
        if self._search_fn is None:
            self._search_fn = _default_search_fn()
        return self._search_fn(vec, k)

    def retrieve(
        self, query: str, k: int = 8, query_time: datetime | None = None
    ) -> RetrievalResult:
        query_time = query_time or datetime.now()
        raw = self._search(self._embed(query, "RETRIEVAL_QUERY"), k)

        facts = [
            TemporalFact(
                content=r["content"],
                timestamp=datetime.fromisoformat(r["issued"]),
                fact_type=r["fact_type"],
            )
            for r in raw
        ]
        valid_facts, pruned_facts = gate(facts, query_time)
        valid_ids = {id(f) for f in valid_facts}

        result = RetrievalResult(query=query, query_time=query_time)
        for r, f in zip(raw, facts):
            hit = Hit(
                chunk_id=r["chunk_id"],
                doc_id=r["doc_id"],
                fact_type=r["fact_type"],
                issued=r["issued"],
                content=r["content"],
                distance=r["distance"],
                validity=float(DECAY.compute(f, query_time)),
            )
            (result.valid if id(f) in valid_ids else result.pruned).append(hit)

        if valid_facts:
            verdict = verify_freshness(f"retrieve: {query}", valid_facts, query_time)
            result.stl_satisfied = bool(verdict.satisfied)
            result.stl_robustness = float(verdict.robustness)

        if self._on_consultation is not None:
            result.evidence_node = self._on_consultation(
                {
                    "query": query,
                    "query_time": query_time.isoformat(),
                    "valid": [h.chunk_id for h in result.valid],
                    "pruned": [h.chunk_id for h in result.pruned],
                    "stl_robustness": result.stl_robustness,
                }
            )
        return result
