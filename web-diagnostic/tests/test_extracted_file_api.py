import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["WEB_DIAGNOSTIC_SKIP_CLAUDE"] = "1"

import pytest
from fastapi.testclient import TestClient
from server import app, UPLOAD_DIR, _REPO


@pytest.fixture
def sample_log_file():
    """Create a sample log file in the allowed directory."""
    log_file = UPLOAD_DIR / "test_sample_20260407.log"
    log_file.write_text("line1\nline2\nline3\n", encoding="utf-8")
    yield log_file
    log_file.unlink(missing_ok=True)


def test_extracted_file_returns_content(sample_log_file):
    client = TestClient(app)
    rel = sample_log_file.relative_to(_REPO)
    resp = client.get(f"/api/extracted-file?path={rel}")
    assert resp.status_code == 200
    data = resp.json()
    assert "content" in data
    assert "line1" in data["content"]
    assert "size_kb" in data


def test_extracted_file_download_mode(sample_log_file):
    client = TestClient(app)
    rel = sample_log_file.relative_to(_REPO)
    resp = client.get(f"/api/extracted-file?path={rel}&dl=1")
    assert resp.status_code == 200
    assert "attachment" in resp.headers.get("content-disposition", "")


def test_extracted_file_rejects_path_traversal():
    client = TestClient(app)
    resp = client.get("/api/extracted-file?path=../../etc/passwd")
    assert resp.status_code == 400


def test_extracted_file_rejects_outside_allowed_dir():
    client = TestClient(app)
    resp = client.get("/api/extracted-file?path=web-diagnostic/server.py")
    assert resp.status_code == 400


def test_extracted_file_not_found():
    client = TestClient(app)
    resp = client.get("/api/extracted-file?path=tools/log-analyzer/data/nonexistent_xyz.log")
    assert resp.status_code == 404
