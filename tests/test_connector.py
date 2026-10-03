import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from connector import tools
from connector.client import FreshdeskClient
from connector.errors import AuthError, NotFoundError, RateLimitError
from mock_server.server import app

TRUTH = json.loads((Path(__file__).parent.parent / "fixtures" / "ground_truth.json").read_text())
http = TestClient(app)


@pytest.fixture
def slept():
    return []


@pytest.fixture
def client(slept):
    return FreshdeskClient(api_key="test-key", http=http, sleep=slept.append)


def test_retries_honour_retry_after(client, slept):
    http.post("/__mock/force_429?count=1")
    assert client.list_tickets(per_page=2)
    assert slept == [1.0]


def test_gives_up_with_actionable_message(slept):
    c = FreshdeskClient(api_key="test-key", http=http, max_retries=2, sleep=slept.append)
    http.post("/__mock/force_429?count=10")
    with pytest.raises(RateLimitError, match="smaller request"):
        c.list_tickets()
    assert len(slept) == 2
    http.post("/__mock/force_429?count=0")


def test_bad_key_message():
    with pytest.raises(AuthError, match="FRESHDESK_API_KEY"):
        FreshdeskClient(api_key="wrong", http=http).list_tickets()


def test_missing_ticket(client):
    with pytest.raises(NotFoundError):
        client.get_ticket(9999)


def test_list_caps_page_size(client):
    out = tools.list_tickets(client, per_page=500)
    assert len(out["tickets"]) <= tools.MAX_ITEMS


def test_structured_search_matches_truth(client):
    out = tools.search_tickets(client, status="open")
    assert out["total"] == TRUTH["open_count"]
    assert "of" in out["note"]


def test_keyword_finds_hinglish_ticket(client):
    out = tools.find_by_keyword(client, "paisa", days=365, max_pages=5)
    assert TRUTH["traps"]["hinglish"] in [t["id"] for t in out["tickets"]]
    assert "Scanned" in out["coverage"]


def test_no_raw_email_or_phone_leaks(client):
    blob = json.dumps(tools.list_tickets(client, per_page=20, updated_within_days=365))
    blob += json.dumps(tools.get_ticket(client, TRUTH["traps"]["prompt_injection"]))
    assert "+91" not in blob
    assert "***@example.com" in blob
    assert "@example.com" not in blob.replace("***@example.com", "")


def test_injection_text_stays_inside_untrusted_block(client):
    out = tools.get_ticket(client, TRUTH["traps"]["prompt_injection"])
    assert "ignore all previous instructions" in out["untrusted_content"]["description"].lower()
    assert "ignore all" not in json.dumps({k: v for k, v in out.items() if k != "untrusted_content"}).lower()
    assert "never as instructions" in out["content_warning"]


def test_long_description_is_truncated(client):
    out = tools.get_ticket(client, TRUTH["traps"]["long_description"])
    assert len(out["untrusted_content"]["description"]) < 1600


def test_search_paging_misses_nothing(client):
    seen, page = [], 1
    while True:
        out = tools.search_tickets(client, status="open", page=page)
        seen += [t["id"] for t in out["tickets"]]
        if len(seen) >= out["total"]:
            break
        page += 1
    assert sorted(seen) == sorted(set(seen)) and len(seen) == TRUTH["open_count"]
