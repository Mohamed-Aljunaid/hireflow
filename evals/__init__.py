"""HireFlow evals. Run from the repo root:

uv run --project backend python -m evals.run --mock      # free: proves the harness
uv run --project backend python -m evals.run             # real model: needs a key, costs money
"""

import sys
from pathlib import Path

# The evals drive the backend's own code (app.*), which lives in backend/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
