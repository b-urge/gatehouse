import os
import sys
from pathlib import Path

# Local `adk run`: ADK's loader puts agents/ on sys.path, not the repo root; the
# fleet imports repo packages (contracts, retrieval), so add the root. On Agent
# Engine the same packages are staged via --extra_packages onto /app, so this
# insert is a harmless no-op there.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# Gemini 3.x serves on the GLOBAL Vertex endpoint (D1 finding). Locally the
# .env sets this; on Agent Engine the ambient location is the platform region
# (us-central1), which 404s for the model — force it for model calls. Platform
# services in this repo pass their regional location explicitly in code.
os.environ["GOOGLE_CLOUD_LOCATION"] = "global"

from . import agent  # noqa: E402,F401
