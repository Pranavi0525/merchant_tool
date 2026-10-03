"""End-to-end: spawn the MCP server over stdio against a live mock, call tools as a real client."""
import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).parent.parent
TRUTH = json.loads((ROOT / "fixtures" / "ground_truth.json").read_text())


@pytest.fixture(scope="module")
def mock_url():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    p = subprocess.Popen([sys.executable, "-m", "uvicorn", "mock_server.server:app", "--port", str(port),
                          "--log-level", "warning"], cwd=ROOT)
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close(); break
        except OSError:
            time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    p.terminate(); p.wait()


def call(mock_url, name, args):
    async def go():
        env = {**os.environ, "FRESHDESK_API_KEY": "test-key", "FRESHDESK_BASE_URL": mock_url}
        params = StdioServerParameters(command=sys.executable, args=["-m", "connector.mcp_server"], cwd=str(ROOT), env=env)
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                tools = await s.list_tools()
                res = await s.call_tool(name, args) if name else None
                return tools, res
    return asyncio.run(go())


def test_lists_four_read_only_tools(mock_url):
    tools, _ = call(mock_url, None, {})
    assert sorted(t.name for t in tools.tools) == ["find_by_keyword", "get_ticket", "list_tickets", "search_tickets"]
    assert all(t.annotations.readOnlyHint for t in tools.tools)


def test_search_total_matches_truth(mock_url):
    _, res = call(mock_url, "search_tickets", {"status": "open"})
    assert not res.isError and res.structuredContent["total"] == TRUTH["open_count"]


def test_missing_ticket_is_error_with_next_step(mock_url):
    _, res = call(mock_url, "get_ticket", {"ticket_id": 9999})
    assert res.isError and "search_tickets" in res.content[0].text
