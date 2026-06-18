"""Redis-хранилище FSM для vkbottle (персистентные состояния между перезапусками)."""

from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aioredis
from vkbottle import ABCStateDispenser, BaseStateGroup, StatePeer


class RedisStateDispenser(ABCStateDispenser):
    """Реализация StateDispenser поверх Redis."""

    def __init__(self, redis_dsn: str, key_prefix: str = "vkscope:fsm:") -> None:
        self._redis = aioredis.from_url(redis_dsn, decode_responses=True)
        self._prefix = key_prefix

    def _key(self, peer_id: int) -> str:
        return f"{self._prefix}{peer_id}"

    @staticmethod
    def _serialize_state(state: Any) -> str:
        if isinstance(state, BaseStateGroup):
            return str(state)
        return str(state)

    async def get(self, peer_id: int) -> StatePeer | None:
        raw = await self._redis.get(self._key(peer_id))
        if raw is None:
            return None
        data = json.loads(raw)
        return StatePeer(
            peer_id=peer_id,
            state=data["state"],
            payload=data.get("payload") or {},
        )

    async def set(self, peer_id: int, state: Any, **payload: Any) -> None:
        record = {
            "state": self._serialize_state(state),
            "payload": payload,
        }
        await self._redis.set(self._key(peer_id), json.dumps(record, ensure_ascii=False))

    async def delete(self, peer_id: int) -> None:
        await self._redis.delete(self._key(peer_id))

    async def close(self) -> None:
        await self._redis.aclose()
