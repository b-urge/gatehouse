"""Seed the Acme corpus into Firestore: chunk -> embed -> write (plan §D3).

  python infra/seed_corpus.py --dry-run    # offline: chunk + validity report only
  python infra/seed_corpus.py              # live: embeds (global) + writes Firestore

Idempotent by construction: chunk ids are deterministic (doc_id#NN) and writes
use set(), so re-seeding overwrites in place. The validity column is computed
live at run time with the real decay constants — the freshness trap's numbers
drift daily and the gate recomputes at query_time, exactly as designed.

Requires (live mode): the corpus vector index on corpus_chunks. First run
prints the exact gcloud command if it is missing (Firestore emits it).
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def report(chunks, now: datetime) -> None:
    from chronofy import TemporalFact

    from retrieval.validity import DECAY, FILTER_THRESHOLD

    by_doc: dict[str, list] = {}
    for c in chunks:
        by_doc.setdefault(c.doc_id, []).append(c)
    print(f"{'doc':28} {'fact_type':14} {'issued':12} {'chunks':>6}  validity@now")
    for doc_id, cs in by_doc.items():
        f = TemporalFact(content="", timestamp=cs[0].issued_dt, fact_type=cs[0].fact_type)
        v = float(DECAY.compute(f, now))
        flag = "PRUNED" if v < FILTER_THRESHOLD else "valid"
        print(f"{doc_id:28} {cs[0].fact_type:14} {cs[0].issued:12} {len(cs):>6}  {v:.3f} {flag}")
    print(f"\ntotal chunks: {len(chunks)}")


def seed_live(chunks) -> None:
    import os

    from dotenv import load_dotenv
    from google import genai
    from google.cloud import firestore
    from google.cloud.firestore_v1.vector import Vector
    from google.genai import types

    from retrieval.store import COLLECTION_CHUNKS, COLLECTION_VENDORS, EMBED_DIMS

    load_dotenv("agents/hello/.env")
    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    client = genai.Client(vertexai=True, project=project, location="global")
    db = firestore.Client(project=project)

    def embed(text: str) -> list[float]:
        r = client.models.embed_content(
            model="gemini-embedding-001",
            contents=text,
            config=types.EmbedContentConfig(
                output_dimensionality=EMBED_DIMS, task_type="RETRIEVAL_DOCUMENT"
            ),
        )
        return list(r.embeddings[0].values)

    col = db.collection(COLLECTION_CHUNKS)
    for i, c in enumerate(chunks, 1):
        col.document(c.chunk_id).set(
            {
                "doc_id": c.doc_id,
                "vendor_id": c.vendor_id,
                "fact_type": c.fact_type,
                "issued": c.issued,
                "content": c.content,
                "embedding": Vector(embed(c.content)),
            }
        )
        print(f"  [{i:>2}/{len(chunks)}] {c.chunk_id}")

    vendor = chunks[0].vendor_id
    db.collection(COLLECTION_VENDORS).document(vendor).set(
        {"vendor_id": vendor, "status": "docs-received", "chunks": len(chunks)},
        merge=True,
    )
    print(f"\nSeeded {len(chunks)} chunks into {COLLECTION_CHUNKS}; vendor '{vendor}' upserted.")
    print("If find_nearest later fails: the error prints the exact index-create command.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="corpus")
    ap.add_argument("--dry-run", action="store_true", help="chunk + validity report, no cloud")
    args = ap.parse_args()

    from retrieval.store import load_corpus

    chunks = load_corpus(args.corpus)
    report(chunks, datetime.now())
    if args.dry_run:
        print("\n(dry run: nothing written)")
        return
    seed_live(chunks)


if __name__ == "__main__":
    main()
