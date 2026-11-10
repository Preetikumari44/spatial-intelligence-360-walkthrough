from fastapi.testclient import TestClient

from app import colmap_locator
from app.main import app

client = TestClient(app)


def test_health_reports_capabilities_honestly():
    body = client.get("/health").json()
    assert body["status"] == "ok"
    # these now reflect what is really installed; each must be a plain boolean, never a placeholder
    assert isinstance(body["capabilities"]["gaussian_splatting"], bool)
    assert isinstance(body["capabilities"]["dense_mesh"], bool)


def test_reconstruct_with_colmap_required_but_missing_fails_loudly(monkeypatch):
    from app import config
    monkeypatch.setattr(config, "COLMAP_BIN", "colmap-does-not-exist")
    monkeypatch.setattr(colmap_locator, "locate", lambda: colmap_locator.Located(None, "none"))
    monkeypatch.setattr(config, "SFM_BACKEND", "colmap")
    r = client.post("/video/reconstruct", json={"frames_dir": "a", "work_dir": "b"})
    assert r.status_code == 503 and "COLMAP" in r.json()["detail"]


def test_360_reconstruct_without_colmap_is_refused(monkeypatch):
    from app import config
    monkeypatch.setattr(config, "COLMAP_BIN", "colmap-does-not-exist")
    monkeypatch.setattr(colmap_locator, "locate", lambda: colmap_locator.Located(None, "none"))
    r = client.post("/video/reconstruct", json={"frames_dir": "a", "work_dir": "b", "is_360": True})
    assert r.status_code == 503 and "360" in r.json()["detail"]


def test_path_escape_is_rejected():
    r = client.post("/video/probe", json={"video_path": "../../etc/passwd"})
    assert r.status_code == 400
