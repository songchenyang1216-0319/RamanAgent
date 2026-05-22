from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.main import app


def test_backend_import():
    assert app is not None
    assert app.title == "RamanAgent API"


if __name__ == "__main__":
    test_backend_import()
    print("backend import test passed")
