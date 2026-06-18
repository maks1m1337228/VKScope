"""Временное хранилище OAuth-сессий (до переноса токена в FSM бота)."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field


@dataclass
class OAuthSession:
    vk_user_id: int
    peer_id: int
    created_at: float = field(default_factory=time.time)


# state → сессия ожидания авторизации
_pending: dict[str, OAuthSession] = {}
# vk_user_id → access_token после успешного входа
_tokens: dict[int, str] = {}


def create_session(vk_user_id: int, peer_id: int) -> str:
    state = secrets.token_urlsafe(24)
    _pending[state] = OAuthSession(vk_user_id=vk_user_id, peer_id=peer_id)
    return state


def get_session(state: str) -> OAuthSession | None:
    return _pending.get(state)


def complete(state: str, access_token: str) -> OAuthSession | None:
    session = _pending.pop(state, None)
    if session is None:
        return None
    _tokens[session.vk_user_id] = access_token
    return session


def get_token(vk_user_id: int) -> str | None:
    return _tokens.get(vk_user_id)


def pop_token(vk_user_id: int) -> str | None:
    return _tokens.pop(vk_user_id, None)
