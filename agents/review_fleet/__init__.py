import sys
from pathlib import Path

# ADK's loader puts agents/ on sys.path, not the repo root; the fleet imports
# repo packages (contracts, retrieval), so add the root before loading.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from . import agent  # noqa: E402,F401
