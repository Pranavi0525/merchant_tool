"""Thin, read-only Freshdesk client with rate-limit handling.

Auth: HTTP Basic, API key as username (Freshdesk's documented scheme; verify).
Only GET requests exist in this class on purpose: the agent cannot change data.
"""
import os
import random
import time

import httpx

from .errors import ApiError, AuthError, NotFoundError, RateLimitError

MAX_RETRY_WAIT = 30.0


class FreshdeskClient:
    def __init__(self, api_key=None, base_url=None, http=None, max_retries=4, sleep=time.sleep):
        self.api_key = api_key or os.getenv("FRESHDESK_API_KEY", "")
        if not self.api_key:
            raise AuthError("No API key set. Set FRESHDESK_API_KEY (see README).")
        base_url = base_url or os.getenv("FRESHDESK_BASE_URL", "http://127.0.0.1:8000")
        self.http = http or httpx.Client(base_url=base_url, timeout=15)
        self.max_retries = max_retries
        self.sleep = sleep

    def _get(self, path, params=None):
        for attempt in range(self.max_retries + 1):
            try:
                r = self.http.get(path, params=params, auth=(self.api_key, "X"))
            except httpx.TransportError as e:
                if attempt == self.max_retries:
                    raise ApiError(f"Could not reach Freshdesk ({type(e).__name__}). Try again later.")
                self.sleep(self._backoff(attempt))
                continue
            if r.status_code == 429 or r.status_code in (502, 503, 504):
                if attempt == self.max_retries:
                    raise RateLimitError(
                        f"Freshdesk kept returning {r.status_code} after {self.max_retries} retries. "
                        "Wait a minute, then retry with a smaller request.")
                self.sleep(self._wait_time(r, attempt))
                continue
            if r.status_code == 401:
                raise AuthError("Freshdesk rejected the API key (401). Check FRESHDESK_API_KEY.")
            if r.status_code == 404:
                raise NotFoundError("Not found (404). Check the ticket id; use search or list to find valid ids.")
            if r.status_code >= 400:
                msg = r.json().get("message", "") if r.headers.get("content-type", "").startswith("application/json") else ""
                raise ApiError(f"Freshdesk returned {r.status_code}. {msg}".strip())
            return r.json()

    @staticmethod
    def _backoff(attempt):
        return min(MAX_RETRY_WAIT, 2 ** attempt) + random.uniform(0, 0.25)

    def _wait_time(self, r, attempt):
        try:
            return min(MAX_RETRY_WAIT, float(r.headers["Retry-After"]))
        except (KeyError, ValueError):
            return self._backoff(attempt)

    # ---- primitives ----
    def list_tickets(self, page=1, per_page=30, updated_since=None):
        params = {"page": page, "per_page": min(per_page, 100)}
        if updated_since:
            params["updated_since"] = updated_since
        return self._get("/api/v2/tickets", params)

    def get_ticket(self, ticket_id, include_conversations=False):
        params = {"include": "conversations"} if include_conversations else None
        return self._get(f"/api/v2/tickets/{int(ticket_id)}", params)

    def search_tickets(self, query, page=1):
        return self._get("/api/v2/search/tickets", {"query": f'"{query}"', "page": page})