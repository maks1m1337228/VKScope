"""Построение карусели VK и клавиатур авторизации."""

from __future__ import annotations

import json
from typing import Any

from vkbottle import Keyboard, KeyboardButtonColor, OpenLink, Text
from vkbottle.tools import TemplateElement, template_gen

from database.models import RecommendedGroup


# Лимиты VK для carousel template (messages.send template)
CAROUSEL_TITLE_MAX_LEN = 80
CAROUSEL_DESC_MAX_LEN = 80


def group_public_url(group_id: int) -> str:
    return f"https://vk.com/club{group_id}"


def _carousel_title(group: RecommendedGroup) -> str:
    if group.group_name:
        return group.group_name[:CAROUSEL_TITLE_MAX_LEN]
    return f"Группа {group.group_id}"[:CAROUSEL_TITLE_MAX_LEN]


def _carousel_description(group: RecommendedGroup) -> str:
    text = f"Подписчиков: {group.members_count:,}".replace(",", " ")
    return text[:CAROUSEL_DESC_MAX_LEN]


def _normalize_carousel_photo_id(raw: str) -> str:
    """VK template: 624240924_123 или -109837093_456, не photo624240924_123."""
    value = (raw or "").strip()
    if value.startswith("photo"):
        value = value[5:]
    return value


def _fallback_photo_id(groups_list: list[RecommendedGroup]) -> str:
    for group in groups_list:
        photo_id = _normalize_carousel_photo_id(getattr(group, "photo_vk_id", "") or "")
        if photo_id:
            return photo_id
    return ""


def build_carousel(groups_list: list[RecommendedGroup]) -> str:
    """
    Карусель VK. Все слайды должны иметь одинаковую структуру (photo_id у всех или ни у кого).
  Кнопка «Ещё» — отдельным сообщением (build_more_recommendations_keyboard).
    """
    if not groups_list:
        return ""

    fallback_photo = _fallback_photo_id(groups_list)
    use_photos = bool(fallback_photo)
    elements: list[TemplateElement] = []

    for group in groups_list:
        kb = Keyboard(inline=True).add(
            OpenLink(group_public_url(group.group_id), "Перейти"),
        )
        element_kwargs: dict[str, Any] = {
            "title": _carousel_title(group),
            "description": _carousel_description(group),
            "buttons": kb.get_json(),
        }
        if use_photos:
            photo_id = _normalize_carousel_photo_id(getattr(group, "photo_vk_id", "") or "")
            element_kwargs["photo_id"] = photo_id or fallback_photo
        elements.append(TemplateElement(**element_kwargs))

    return template_gen(*elements)


def build_more_recommendations_keyboard() -> str:
    """Текстовая inline-кнопка — надёжнее callback (не нужен message_event в Long Poll)."""
    return (
        Keyboard(inline=True)
        .add(Text("Ещё рекомендации →"))
        .get_json()
    )


def build_start_keyboard() -> str:
    return (
        Keyboard(one_time=False, inline=False)
        .add(Text("Начать анализ →"), KeyboardButtonColor.POSITIVE)
        .get_json()
    )


def build_login_keyboard(login_url: str, *, label: str = "Вход (+ группы)") -> str:
    """Одна кнопка — implicit OAuth (Kate Mobile, friends+groups)."""
    return (
        Keyboard(inline=True)
        .add(OpenLink(login_url, label))
        .get_json()
    )


def build_run_analysis_keyboard() -> str:
    return (
        Keyboard(one_time=False, inline=False)
        .add(Text("Запустить анализ"), KeyboardButtonColor.POSITIVE)
        .get_json()
    )


def payload_to_dict(payload: Any) -> dict[str, Any]:
    if payload is None:
        return {}
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return {}
    return {}
