import base64
import json
from pathlib import Path

from fastapi.testclient import TestClient

from mock_server.server import app

c = TestClient(app)
AUTH = {"Authorization": "Basic " + base64.b64encode(b"test-key:X").decode()}
TRUTH = json.loads((Path(__file__).parent.parent / "fixtures" / "ground_truth.json").read_text())


def test_bad_key_is_401():
    r = c.get("/api/v2/tickets", headers={"Authorization": "Basic " + base64.b64encode(b"nope:X").decode()})
    assert r.status_code == 401


def test_list_pagination():
    r = c.get("/api/v2/tickets?per_page=5&page=1", headers=AUTH)
    assert r.status_code == 200 and len(r.json()) == 5


def test_get_with_conversations_and_404():
    assert c.get("/api/v2/tickets/9999", headers=AUTH).status_code == 404
    assert c.get(f"/api/v2/tickets/{TRUTH['traps']['hinglish']}", headers=AUTH).status_code == 200


def test_search_matches_ground_truth():
    r = c.get('/api/v2/search/tickets?query="status:2"', headers=AUTH).json()
    assert r["total"] == TRUTH["open_count"]


def test_429_has_retry_after_then_recovers():
    c.post("/__mock/force_429?count=1")
    r = c.get("/api/v2/tickets", headers=AUTH)
    assert r.status_code == 429 and r.headers["Retry-After"] == "1"
    assert c.get("/api/v2/tickets", headers=AUTH).status_code == 200


def test_default_list_window_hides_old_tickets():
    ids = {t["id"] for t in c.get("/api/v2/tickets?per_page=100", headers=AUTH).json()}
    assert not ids & set(TRUTH["older_than_30d_ids"])