from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from ormah.adapters import mcp_adapter


class _FakeStdioServer:
    async def __aenter__(self):
        return ("read-stream", "write-stream")

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_run_mcp_stdio_generates_session_id_and_runs_server(monkeypatch):
    fake_uuid = "12345678-1234-5678-1234-567812345678"
    run = AsyncMock()
    server = MagicMock()
    server.run = run
    server.create_initialization_options.return_value = {"name": "ormah"}

    monkeypatch.setattr(mcp_adapter.uuid, "uuid4", lambda: fake_uuid)
    monkeypatch.setattr(mcp_adapter, "detect_space_from_cwd", lambda: "ormah")
    monkeypatch.setattr(mcp_adapter, "create_mcp_server", MagicMock(return_value=server))
    monkeypatch.setattr(mcp_adapter, "stdio_server", lambda: _FakeStdioServer())

    await mcp_adapter.run_mcp_stdio()

    mcp_adapter.create_mcp_server.assert_called_once_with(
        mcp_adapter._BASE_URL,
        default_space="ormah",
        session_id=fake_uuid,
    )
    run.assert_awaited_once_with("read-stream", "write-stream", {"name": "ormah"})
