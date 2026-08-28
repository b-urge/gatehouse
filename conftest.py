# Makes the repo root importable in pytest without packaging ceremony.
import pytest


@pytest.fixture(autouse=True)
def _isolated_ledger_files(tmp_path, monkeypatch):
    """Tests never write the repo's evidence/*.db: ledger and seal custody go to tmp."""
    monkeypatch.setenv("GATEHOUSE_EVIDENCE_DB", str(tmp_path / "runs.db"))
    monkeypatch.setenv("GATEHOUSE_SEAL_DB", str(tmp_path / "seals.db"))
