"""Асинхронная обёртка над VK API (httpx) с учётом rate limit."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from loguru import logger
from pydantic import BaseModel, Field

from config import settings


class VKUserInfo(BaseModel):
    vk_user_id: int
    first_name: str = ""
    last_name: str = ""
    photo_url: str = ""


class VKGroupInfo(BaseModel):
    group_id: int
    name: str = ""
    members_count: int = 0
    photo_url: str = ""
    photo_vk_id: str = ""  # не используется в карусели напрямую — только после upload


class VKAPIError(Exception):
    def __init__(self, code: int, message: str, method: str = "") -> None:
        self.code = code
        self.message = message
        self.method = method
        super().__init__(f"VK API [{method}] {code}: {message}")


class VKNetworkError(Exception):
    """Временная ошибка сети при обращении к VK API."""

    def __init__(self, method: str, cause: Exception) -> None:
        self.method = method
        self.cause = cause
        super().__init__(f"Сеть недоступна при вызове {method}: {cause}")


class VKAPIClient:
    """
    Клиент VK API.

    Для подписок и друзей нужен user access_token (OAuth).
    Для groups.getById можно использовать и group token.
    """

    def __init__(
        self,
        access_token: str,
        api_version: str | None = None,
        request_delay: float | None = None,
    ) -> None:
        self.access_token = access_token
        self.api_version = api_version or settings.vk_api_version
        self.request_delay = request_delay if request_delay is not None else settings.vk_api_request_delay
        self._api_bases = [
            settings.vk_api_base_url.rstrip("/"),
            settings.vk_api_fallback_base_url.rstrip("/"),
        ]
        self._api_bases = list(dict.fromkeys(base for base in self._api_bases if base))
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=15.0),
            trust_env=settings.vk_http_trust_env,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        max_retries: int | None = None,
    ) -> Any:
        """Вызов VK API: пауза, повтор при rate limit и при обрыве сети."""
        payload = dict(params or {})
        payload["access_token"] = self.access_token
        payload["v"] = self.api_version
        retries = max_retries if max_retries is not None else settings.vk_api_max_retries
        last_network_error: Exception | None = None

        for attempt in range(retries):
            await asyncio.sleep(self.request_delay)
            data: dict[str, Any] | None = None

            for base in self._api_bases:
                try:
                    response = await self._client.get(f"{base}/{method}", params=payload)
                    response.raise_for_status()
                    data = response.json()
                    last_network_error = None
                    break
                except httpx.HTTPError as exc:
                    last_network_error = exc
                    logger.warning(
                        "Сеть VK API {} через {} (попытка {}): {}",
                        method,
                        base,
                        attempt + 1,
                        exc,
                    )

            if data is None:
                if attempt < retries - 1:
                    wait = 2.0 * (attempt + 1)
                    await asyncio.sleep(wait)
                    continue
                raise VKNetworkError(method, last_network_error or httpx.ConnectError("unknown"))

            if "error" in data:
                error = data["error"]
                code = int(error.get("error_code", 0))
                message = str(error.get("error_msg", "unknown"))
                if code in (6, 9, 29) and attempt < retries - 1:
                    wait = self.request_delay * (attempt + 2) * 2
                    logger.warning(
                        "Rate limit VK API {} (код {}), пауза {:.1f} с",
                        method,
                        code,
                        wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                raise VKAPIError(code, message, method)

            return data.get("response")

        raise VKAPIError(29, "Превышено число попыток после rate limit", method)

    async def get_token_owner_id(self) -> int:
        """ID пользователя, которому принадлежит access_token."""
        response = await self._call("users.get", {})
        if not response:
            return 0
        return int(response[0]["id"])

    async def get_users_info_batch(self, user_ids: list[int]) -> list[VKUserInfo]:
        """Имена пользователей пачкой (до 1000 ID)."""
        if not user_ids:
            return []

        response = await self._call(
            "users.get",
            {
                "user_ids": ",".join(str(uid) for uid in user_ids),
                "fields": "photo_200",
            },
        )
        if not response:
            return []

        users: list[VKUserInfo] = []
        by_id = {int(item["id"]): item for item in response if isinstance(item, dict)}
        for uid in user_ids:
            item = by_id.get(uid)
            if not item:
                users.append(VKUserInfo(vk_user_id=uid))
                continue
            users.append(
                VKUserInfo(
                    vk_user_id=uid,
                    first_name=item.get("first_name", ""),
                    last_name=item.get("last_name", ""),
                    photo_url=item.get("photo_200", ""),
                )
            )
        return users

    async def get_user_info(self, vk_user_id: int) -> VKUserInfo:
        """Имя, фамилия и аватар пользователя."""
        response = await self._call(
            "users.get",
            {
                "user_ids": vk_user_id,
                "fields": "photo_200",
            },
        )
        if not response:
            return VKUserInfo(vk_user_id=vk_user_id)
        user = response[0]
        return VKUserInfo(
            vk_user_id=int(user["id"]),
            first_name=user.get("first_name", ""),
            last_name=user.get("last_name", ""),
            photo_url=user.get("photo_200", ""),
        )

    @staticmethod
    def _parse_subscription_groups(response: Any) -> list[int]:
        """
        users.getSubscriptions при extended=0 отдаёт groups.items, не items.
        При extended=1 — объединённый items с type=group.
        """
        if not isinstance(response, dict):
            return []

        group_ids: list[int] = []

        groups_block = response.get("groups")
        if isinstance(groups_block, dict):
            for gid in groups_block.get("items", []):
                group_ids.append(int(gid))

        for item in response.get("items", []):
            if isinstance(item, dict):
                if item.get("type") == "group":
                    group_ids.append(int(item["id"]))
            elif isinstance(item, (int, str)):
                group_ids.append(int(item))

        return list(dict.fromkeys(group_ids))

    async def get_user_communities_via_groups_get(
        self,
        vk_user_id: int,
        count: int = 1000,
    ) -> list[int]:
        """groups.get — сообщества, в которых состоит пользователь (часто надёжнее)."""
        group_ids: list[int] = []
        offset = 0
        page_size = 1000

        while offset < count:
            response = await self._call(
                "groups.get",
                {
                    "user_id": vk_user_id,
                    "extended": 0,
                    "filter": "groups",
                    "count": min(page_size, count - offset),
                    "offset": offset,
                },
            )
            if isinstance(response, dict):
                items = response.get("items", [])
                total = int(response.get("count", 0))
            elif isinstance(response, list):
                items = response
                total = len(items)
            else:
                break

            if not items:
                break
            group_ids.extend(int(g) for g in items)
            offset += len(items)
            if offset >= total:
                break

        return list(dict.fromkeys(group_ids))

    async def get_user_subscriptions(
        self,
        vk_user_id: int,
        count: int = 1000,
    ) -> list[int]:
        """
        ID сообществ пользователя: groups.get + users.getSubscriptions.
        Для друзей список может быть пустым из‑за приватности VK.
        """
        merged: list[int] = []

        try:
            merged.extend(await self.get_user_communities_via_groups_get(vk_user_id, count))
        except VKAPIError as exc:
            logger.warning("groups.get для {}: {}", vk_user_id, exc)

        # extended=0: все id в groups.items (пагинация только при extended=1)
        try:
            response = await self._call(
                "users.getSubscriptions",
                {"user_id": vk_user_id, "extended": 0},
            )
            merged.extend(self._parse_subscription_groups(response))
        except VKAPIError as exc:
            if exc.code == 260:
                logger.debug("Подписки {} скрыты приватностью", vk_user_id)
            else:
                logger.warning("getSubscriptions для {}: {}", vk_user_id, exc)

        # extended=1 — если список длинный
        offset = 0
        page_size = 200
        while offset < count:
            try:
                response = await self._call(
                    "users.getSubscriptions",
                    {
                        "user_id": vk_user_id,
                        "extended": 1,
                        "count": page_size,
                        "offset": offset,
                        "fields": "id",
                    },
                )
            except VKAPIError:
                break
            chunk = self._parse_subscription_groups(response)
            if not chunk:
                break
            merged.extend(chunk)
            total = int(response.get("count", 0)) if isinstance(response, dict) else 0
            offset += page_size
            if offset >= total:
                break

        return list(dict.fromkeys(merged))

    async def get_friends_list(self, vk_user_id: int, count: int = 500) -> list[int]:
        """Список ID друзей пользователя."""
        response = await self._call(
            "friends.get",
            {
                "user_id": vk_user_id,
                "count": count,
                "order": "hints",
            },
        )
        if isinstance(response, dict):
            return [int(uid) for uid in response.get("items", [])]
        return []

    async def collect_friends_subscriptions_for_similarity(
        self,
        owner_vk_id: int,
        friend_ids: list[int],
        max_friends_to_scan: int = 30,
    ) -> dict[int, list[int]]:
        """
        Собирает подписки друзей для расчёта похожести.
        Ограничиваем число запросов, чтобы не упереться в лимиты VK.
        """
        result: dict[int, list[int]] = {}
        for friend_id in friend_ids[:max_friends_to_scan]:
            try:
                groups = await self.get_user_subscriptions(friend_id, count=500)
                result[friend_id] = groups
            except VKAPIError as exc:
                logger.warning("Не удалось получить подписки друга {}: {}", friend_id, exc)
        return result

    async def get_friends_subscriptions(
        self,
        top_friend_ids: list[int],
    ) -> dict[int, list[int]]:
        """Подписки топ-5 похожих друзей для алгоритма рекомендаций."""
        result: dict[int, list[int]] = {}
        for friend_id in top_friend_ids[:5]:
            try:
                result[friend_id] = await self.get_user_subscriptions(friend_id, count=500)
            except VKAPIError as exc:
                logger.warning("Подписки друга {} недоступны: {}", friend_id, exc)
        return result

    @staticmethod
    def _parse_groups_list(response: Any) -> list[dict[str, Any]]:
        """groups.getById в API 5.199+ может вернуть list или {groups: [...]}."""
        if isinstance(response, list):
            return [item for item in response if isinstance(item, dict)]
        if isinstance(response, dict):
            if isinstance(response.get("groups"), list):
                return [item for item in response["groups"] if isinstance(item, dict)]
            if "id" in response:
                return [response]
        return []

    async def get_groups_info_batch(self, group_ids: list[int]) -> list[VKGroupInfo]:
        """Название, обложка, photo_id и число участников пачкой."""
        if not group_ids:
            return []

        groups: list[VKGroupInfo] = []
        chunk_size = 500

        for i in range(0, len(group_ids), chunk_size):
            chunk = group_ids[i : i + chunk_size]
            response = await self._call(
                "groups.getById",
                {
                    "group_ids": ",".join(str(g) for g in chunk),
                    "fields": "members_count,photo_200",
                },
            )
            for item in self._parse_groups_list(response):
                gid = int(item["id"])
                groups.append(
                    VKGroupInfo(
                        group_id=gid,
                        name=item.get("name", ""),
                        members_count=int(item.get("members_count", 0)),
                        photo_url=item.get("photo_200", ""),
                    )
                )
        return groups
