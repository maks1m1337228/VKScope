"""Загрузка обложек сообществ для карусели VK (messages API)."""

from __future__ import annotations

import httpx
from loguru import logger

from bot.utils.vk_api_client import VKAPIClient, VKAPIError
from config import settings
from database.models import RecommendedGroup


def carousel_template_photo_id(photo: dict) -> str:
    """В template карусели: owner_id_photo_id, без префикса photo."""
    owner_id = photo.get("owner_id")
    photo_id = photo.get("id")
    if owner_id is None or photo_id is None:
        return ""
    return f"{owner_id}_{photo_id}"


async def upload_carousel_photo(
    client: VKAPIClient,
    peer_id: int,
    image_url: str,
) -> str:
    """
    Скачивает photo_200 и загружает через photos.saveMessagesPhoto.
    Только такой photo_id принимает carousel в messages.send.
    """
    if not image_url.strip():
        return ""

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, connect=15.0),
        trust_env=settings.vk_http_trust_env,
    ) as http:
        image_response = await http.get(image_url)
        image_response.raise_for_status()
        image_bytes = image_response.content

        upload_params: dict[str, int] = {"peer_id": peer_id}
        if settings.vk_group_id > 0:
            upload_params["group_id"] = settings.vk_group_id

        server = await client._call("photos.getMessagesUploadServer", upload_params)
        upload_url = str(server.get("upload_url", ""))
        if not upload_url:
            return ""

        upload_response = await http.post(
            upload_url,
            files={"photo": ("group.jpg", image_bytes, "image/jpeg")},
        )
        upload_response.raise_for_status()
        upload_data = upload_response.json()

    save_params = dict(upload_data)
    if settings.vk_group_id > 0:
        save_params["group_id"] = settings.vk_group_id
    saved = await client._call("photos.saveMessagesPhoto", save_params)
    if isinstance(saved, list) and saved:
        return carousel_template_photo_id(saved[0])
    if isinstance(saved, dict):
        return carousel_template_photo_id(saved)
    return ""


async def attach_carousel_photos(
    groups: list[RecommendedGroup],
    client: VKAPIClient,
    peer_id: int,
) -> list[RecommendedGroup]:
    """Подготавливает photo_id для карусели; crop_photo из API не подходит."""
    for group in groups:
        group.photo_vk_id = ""
        if not group.photo_url:
            continue
        try:
            group.photo_vk_id = await upload_carousel_photo(
                client,
                peer_id,
                group.photo_url,
            )
        except (VKAPIError, httpx.HTTPError) as exc:
            logger.warning(
                "Не удалось загрузить обложку для группы {}: {}",
                group.group_id,
                exc,
            )
    return groups
