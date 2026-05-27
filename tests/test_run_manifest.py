from src.domain.manifest import build_run_manifest

def test_build_run_manifest():
    m = build_run_manifest("run123", "abc1234", "nordrhein-westfalen", "xvfb", "uc-popup", 0, 4, 100, 10, {"test": True})
    assert m["run_id"] == "run123"
    assert "started_at" in m
