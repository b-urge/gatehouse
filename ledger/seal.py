"""Seal and verify (plan §5): the audit artifact.

`seal_review(root_id)` computes pollard's rolling SHA-256 over the run's subtree.
On the way every node id is re-derived from its identity fields and every result
digest re-checked, so a ledger that has been edited cannot be sealed at all — it
raises IntegrityError instead of producing a digest. The digest then goes to an
append-only custody log (`evidence/seals.db`, a separate SQLite file) with who
sealed it and when. That digest is what goes on camera and into the lifecycle
report; `pollard seal <db> <root>` reproduces it from the ledger alone, and a
replay of the recording seals to the very same value.

Environment:
  GATEHOUSE_SEAL_DB   custody log path (default evidence/seals.db)
  GATEHOUSE_SIGNER    signer identity recorded in custody
                      (default: the service name on Cloud Run/Agent Engine, else user@host)
"""

from __future__ import annotations

import getpass
import os
import socket
import sqlite3
import warnings
from pathlib import Path
from typing import Any

from pollard import ReplayMode, SealReport, SQLiteSealSink, Store, seal, verify
from pollard.seal_custody import SealCustodyRecord

DEFAULT_SEAL_DB = "evidence/seals.db"


def signer_identity() -> str:
    for var in ("GATEHOUSE_SIGNER", "K_SERVICE", "GOOGLE_CLOUD_AGENT_ENGINE_ID"):
        if os.environ.get(var):
            return os.environ[var]
    return f"{getpass.getuser()}@{socket.gethostname()}"


def store_identity(store: Store) -> str:
    path = getattr(store, "path", None)
    return str(path) if path else "memory"


def seal_review(root_id: str, *, store: Store | None = None, publish: bool | None = None) -> dict:
    """Seal one run. Raises pollard.IntegrityError if any node fails validation.
    Publishes a custody record unless replaying (a replay re-derives, it does not attest)."""
    from ledger import runtime

    store = store or runtime().store
    report = seal(store, root_id)
    sealed: dict[str, Any] = {
        "root_id": root_id,
        "algorithm": report.algorithm,
        "digest": report.digest,
        "nodes": len(report.entries),
    }
    if publish is None:
        publish = runtime().mode != ReplayMode.REPLAY
    if publish:
        record = publish_custody(report, store)
        if record is not None:
            sealed["custody"] = {
                "sequence": record.sequence,
                "sealed_at": record.sealed_at,
                "signer": record.signer_identity,
                "log": os.environ.get("GATEHOUSE_SEAL_DB", DEFAULT_SEAL_DB),
            }
    return sealed


def publish_custody(report: SealReport, store: Store) -> SealCustodyRecord | None:
    """Append the seal to the custody log; a log that cannot open is a warning, not a failure."""
    path = os.environ.get("GATEHOUSE_SEAL_DB", DEFAULT_SEAL_DB)
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        return SQLiteSealSink(path).publish(
            report, store_id=store_identity(store), signer_identity=signer_identity()
        )
    except (OSError, sqlite3.Error, ValueError) as exc:
        warnings.warn(
            f"seal custody log {path!r} unavailable ({type(exc).__name__}: {exc}); "
            "seal digest computed but not published",
            RuntimeWarning,
            stacklevel=2,
        )
        return None


def custody_records() -> list[SealCustodyRecord]:
    path = os.environ.get("GATEHOUSE_SEAL_DB", DEFAULT_SEAL_DB)
    if not Path(path).exists():
        return []
    return SQLiteSealSink(path).records()


def verify_review(root_id: str, *, store: Store | None = None) -> dict[str, Any]:
    """Every node in the run checked (identity and result digest), as {ok, findings}."""
    from ledger import runtime

    store = store or runtime().store
    findings: list[dict[str, str]] = []
    for node in store.walk(root_id):
        report = verify(store, node.id)
        findings.extend({"node_id": f.node_id, "message": f.message} for f in report.findings)
    unique = {(f["node_id"], f["message"]): f for f in findings}
    return {"ok": not unique, "findings": list(unique.values())}
