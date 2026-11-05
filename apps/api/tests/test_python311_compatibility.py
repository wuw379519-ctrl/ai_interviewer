import ast
from pathlib import Path


def test_online_python_sources_support_python311_grammar() -> None:
    """Guard the declared minimum even when contributors run a newer interpreter."""
    source = Path(__file__).resolve().parents[1] / "interviewer"
    paths = sorted(source.rglob("*.py"))
    assert paths, "must check real online backend sources"
    for path in paths:
        ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path), feature_version=(3, 11))
