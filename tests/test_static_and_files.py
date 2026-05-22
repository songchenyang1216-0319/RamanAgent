from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.api.file_api import validate_report_file_name
from backend.main import app


def test_static_and_files():
    assert app is not None
    assert validate_report_file_name("good_report.md") == "good_report.md"

    try:
        validate_report_file_name("../bad.md")
        raise AssertionError("应当拒绝路径穿越文件名")
    except ValueError:
        pass

    try:
        validate_report_file_name("a/b.md")
        raise AssertionError("应当拒绝包含分隔符的文件名")
    except ValueError:
        pass


if __name__ == "__main__":
    test_static_and_files()
    print("static and files test passed")
