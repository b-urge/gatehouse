"""GEAP-adjacent audit: Firestore native vector search, end to end.
Embed 2 docs + 1 query -> seed Firestore -> find_nearest -> right doc ranks first.
Self-diagnoses the embedding endpoint (model x location), per tonight's findings.
NOTE: Firestore caps vectors at 2048 dims; we pin 768 explicitly.
"""

import os
import sys

from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.cloud import firestore
from google.cloud.firestore_v1.vector import Vector
from google.cloud.firestore_v1.base_vector_query import DistanceMeasure

load_dotenv("agents/hello/.env")
PROJECT = os.environ["GOOGLE_CLOUD_PROJECT"]
DIMS = 768
COMBOS = [
    ("gemini-embedding-001", "global"),
    ("gemini-embedding-001", "us-central1"),
    ("text-embedding-005", "us-central1"),
    ("text-embedding-005", "global"),
]

DOCS = [
    ("pen_test", "Pen test 2026-07: one medium finding - MFA gap on the legacy tier."),
    ("comms", "Rollout comms draft: announce the new vendor portal to all staff next Tuesday."),
]
QUERY = "What security gaps were found in testing?"


def probe():
    for model, loc in COMBOS:
        try:
            c = genai.Client(vertexai=True, project=PROJECT, location=loc)
            r = c.models.embed_content(
                model=model,
                contents="probe",
                config=types.EmbedContentConfig(
                    output_dimensionality=DIMS, task_type="RETRIEVAL_DOCUMENT"
                ),
            )
            n = len(r.embeddings[0].values)
            print(f"FINDING: embeddings work -> model={model} location={loc} dims={n}")
            return c, model
        except Exception as e:
            print(f"  probe failed: {model} @ {loc}: {str(e)[:110]}")
    sys.exit("No embedding combo worked - paste the probe lines back.")


def main():
    client, model = probe()

    def emb(text, task):
        r = client.models.embed_content(
            model=model,
            contents=text,
            config=types.EmbedContentConfig(output_dimensionality=DIMS, task_type=task),
        )
        return r.embeddings[0].values

    db = firestore.Client(project=PROJECT)
    col = db.collection("audit_chunks")
    for doc_id, text in DOCS:
        col.document(doc_id).set(
            {"content": text, "embedding": Vector(emb(text, "RETRIEVAL_DOCUMENT"))}
        )
    print("seeded  : 2 docs into audit_chunks")

    try:
        hits = col.find_nearest(
            vector_field="embedding",
            query_vector=Vector(emb(QUERY, "RETRIEVAL_QUERY")),
            limit=2,
            distance_measure=DistanceMeasure.COSINE,
            distance_result_field="dist",
        ).get()
    except Exception as e:
        print("\nQUERY FAILED - almost certainly the missing vector index.")
        print("The error below usually CONTAINS the exact gcloud command to create it.")
        print("Run that command, wait for the index (2-5 min; check:")
        print("  gcloud firestore indexes composite list ), then rerun this script.\n")
        print(str(e))
        sys.exit(1)

    print(f"query   : {QUERY!r}")
    for h in hits:
        d = h.to_dict()
        print(f"  -> [{h.id}] dist={d.get('dist'):.4f}  {d['content'][:70]}")
    top = hits[0].id if hits else None
    print("\nPASS" if top == "pen_test" else f"\nUNEXPECTED: top hit was {top!r} - paste output back.")


if __name__ == "__main__":
    main()
