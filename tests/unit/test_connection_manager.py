import asyncio
from typing import Any

import pytest
from starlette.websockets import WebSocketState

from app.realtime.connection_manager import ConnectionManager


class FakeWebSocket:
    def __init__(self) -> None:
        self.application_state = WebSocketState.CONNECTED
        self.sent: list[dict[str, Any]] = []
        self.close_calls: list[tuple[int, str]] = []

    async def send_json(self, message: dict[str, Any]) -> None:
        await asyncio.sleep(0)
        self.sent.append(message)

    async def close(self, *, code: int, reason: str) -> None:
        self.application_state = WebSocketState.DISCONNECTED
        self.close_calls.append((code, reason))


class BlockingSendWebSocket(FakeWebSocket):
    def __init__(self) -> None:
        super().__init__()
        self.send_started = asyncio.Event()
        self.release_send = asyncio.Event()

    async def send_json(self, message: dict[str, Any]) -> None:
        self.send_started.set()
        await self.release_send.wait()
        self.sent.append(message)


@pytest.mark.asyncio
async def test_register_get_send_disconnect_and_close() -> None:
    manager = ConnectionManager()
    websocket = FakeWebSocket()

    previous = await manager.register("session-1", websocket)
    assert previous is None
    assert manager.active_count == 1
    assert (await manager.get("session-1")).websocket is websocket

    sent = await manager.send_json("session-1", {"type": "PING"})
    assert sent is True
    assert websocket.sent == [{"type": "PING"}]

    removed = await manager.disconnect("session-1", websocket)
    assert removed is True
    assert manager.active_count == 0

    assert await manager.close("session-1", code=1000, reason="missing") is False


@pytest.mark.asyncio
async def test_duplicate_register_returns_previous_and_old_disconnect_does_not_remove_new() -> None:
    manager = ConnectionManager()
    first = FakeWebSocket()
    second = FakeWebSocket()

    assert await manager.register("session-1", first) is None
    previous = await manager.register("session-1", second)

    assert previous is not None
    assert previous.websocket is first
    assert manager.active_count == 1
    assert (await manager.get("session-1")).websocket is second

    assert await manager.disconnect("session-1", first) is False
    assert manager.active_count == 1
    assert (await manager.get("session-1")).websocket is second


@pytest.mark.asyncio
async def test_send_json_to_current_uses_object_identity() -> None:
    manager = ConnectionManager()
    first = FakeWebSocket()
    second = FakeWebSocket()
    await manager.register("session-1", first)

    assert await manager.send_json_to_current("session-1", second, {"type": "PING"}) is False
    assert first.sent == []
    assert second.sent == []

    assert await manager.send_json_to_current("session-1", first, {"type": "PING"}) is True
    assert first.sent == [{"type": "PING"}]


@pytest.mark.asyncio
async def test_send_json_to_current_serializes_replacement_until_send_finishes() -> None:
    manager = ConnectionManager()
    first = BlockingSendWebSocket()
    second = FakeWebSocket()
    await manager.register("session-1", first)

    send_task = asyncio.create_task(
        manager.send_json_to_current("session-1", first, {"type": "DETECTION_UPDATE"})
    )
    await asyncio.wait_for(first.send_started.wait(), timeout=1)

    register_task = asyncio.create_task(manager.register("session-1", second))
    await asyncio.sleep(0)

    assert not register_task.done()

    first.release_send.set()
    assert await asyncio.wait_for(send_task, timeout=1) is True
    previous = await asyncio.wait_for(register_task, timeout=1)

    assert previous is not None
    assert previous.websocket is first
    assert first.sent == [{"type": "DETECTION_UPDATE"}]
    assert (await manager.get("session-1")).websocket is second


@pytest.mark.asyncio
async def test_close_and_close_all_remove_and_close_connections() -> None:
    manager = ConnectionManager()
    first = FakeWebSocket()
    second = FakeWebSocket()
    await manager.register("first", first)
    await manager.register("second", second)

    assert await manager.close("first", code=4008, reason="HEARTBEAT_TIMEOUT") is True
    assert first.close_calls == [(4008, "HEARTBEAT_TIMEOUT")]
    assert manager.active_count == 1

    await manager.close_all(code=1012, reason="SERVICE_RESTART")
    assert second.close_calls == [(1012, "SERVICE_RESTART")]
    assert manager.active_count == 0
