from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketState


@dataclass(slots=True)
class ManagedConnection:
    websocket: WebSocket
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def send_json(self, message: dict[str, Any]) -> None:
        async with self.send_lock:
            await self.websocket.send_json(message)

    async def close(self, *, code: int, reason: str) -> None:
        if self.websocket.application_state == WebSocketState.DISCONNECTED:
            return

        async with self.send_lock:
            if self.websocket.application_state != WebSocketState.DISCONNECTED:
                await self.websocket.close(code=code, reason=reason)


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, ManagedConnection] = {}
        self._lock = asyncio.Lock()

    @property
    def active_count(self) -> int:
        return len(self._connections)

    async def register(self, session_id: str, websocket: WebSocket) -> ManagedConnection | None:
        new_connection = ManagedConnection(websocket=websocket)
        async with self._lock:
            previous = self._connections.get(session_id)
            self._connections[session_id] = new_connection
            return previous

    async def disconnect(self, session_id: str, websocket: WebSocket) -> bool:
        async with self._lock:
            current = self._connections.get(session_id)
            if current is None or current.websocket is not websocket:
                return False
            del self._connections[session_id]
            return True

    async def get(self, session_id: str) -> ManagedConnection | None:
        async with self._lock:
            return self._connections.get(session_id)

    async def is_current(self, session_id: str, websocket: WebSocket) -> bool:
        async with self._lock:
            current = self._connections.get(session_id)
            return current is not None and current.websocket is websocket

    async def send_json(self, session_id: str, message: dict[str, Any]) -> bool:
        async with self._lock:
            connection = self._connections.get(session_id)
            if connection is None:
                return False

            await connection.send_json(message)
            return True

    async def send_json_to_current(
        self,
        session_id: str,
        websocket: WebSocket,
        message: dict[str, Any],
    ) -> bool:
        async with self._lock:
            connection = self._connections.get(session_id)
            if connection is None or connection.websocket is not websocket:
                return False

            await connection.send_json(message)
            return True

    async def close(self, session_id: str, *, code: int, reason: str) -> bool:
        async with self._lock:
            connection = self._connections.pop(session_id, None)

        if connection is None:
            return False

        await connection.close(code=code, reason=reason)
        return True

    async def close_all(self, *, code: int, reason: str) -> None:
        async with self._lock:
            connections = list(self._connections.values())
            self._connections.clear()

        await asyncio.gather(
            *(connection.close(code=code, reason=reason) for connection in connections),
            return_exceptions=True,
        )
