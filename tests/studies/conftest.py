import sys
import os

# Make the repo root importable so `studies.*` packages can be found.
# studies/ lives at the repo root (not under src/), so it is not on the
# default sys.path that hatchling's editable install provides.
_repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)
