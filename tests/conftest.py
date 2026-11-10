import shutil
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fixagent.demo import DEMO_SCRIPTS as SCRIPTS  # noqa: E402
from fixagent.demo import MEDIAN_FIX  # noqa: E402,F401

DEMO_REPOS = PROJECT_ROOT / "demo_repos"


@pytest.fixture
def py_repo(tmp_path):
    """A private copy of the Python demo repo."""
    target = tmp_path / "py_stats"
    shutil.copytree(DEMO_REPOS / "py_stats", target)
    return target


def needs(*programs):
    missing = [p for p in programs if shutil.which(p) is None]
    return pytest.mark.skipif(bool(missing), reason=f"missing: {', '.join(missing)}")
