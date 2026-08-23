"""Corpus chunking: deterministic, front-matter stripped, demo props intact."""

from pathlib import Path

import pytest

from retrieval.store import load_corpus, parse_front_matter

CORPUS = Path("corpus")
pytestmark = pytest.mark.skipif(not CORPUS.exists(), reason="corpus/ not present")


def test_every_manifest_doc_chunks():
    chunks = load_corpus(CORPUS)
    doc_ids = {c.doc_id for c in chunks}
    assert len(doc_ids) == 7
    assert all(c.content for c in chunks)
    assert all(c.chunk_id == f"{c.doc_id}#{int(c.chunk_id.split('#')[1]):02d}" for c in chunks)


def test_chunking_is_deterministic():
    a = [c.chunk_id for c in load_corpus(CORPUS)]
    b = [c.chunk_id for c in load_corpus(CORPUS)]
    assert a == b


def test_front_matter_stripped_but_payload_preserved():
    chunks = load_corpus(CORPUS)
    joined = "\n".join(c.content for c in chunks)
    assert "fact_type:" not in joined  # front matter never reaches the index
    assert "approve_vendor" in joined  # the poisoned doc's payload is intact (it IS the demo)
    assert "MFA" in joined  # the SOC 2 finding survived chunking


def test_front_matter_parser():
    meta, body = parse_front_matter("---\na: 1\nb: two\n---\nBody here")
    assert meta == {"a": "1", "b": "two"}
    assert body == "Body here"
