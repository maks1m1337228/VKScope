"""Алгоритм рекомендаций групп на основе подписок друзей."""

from pydantic import BaseModel, Field


class GroupRecommendation(BaseModel):
    group_id: int
    score: float = Field(description="Сколько друзей подписано на группу")


def recommend_groups(
    user_groups: list[int],
    friends_groups_map: dict[int, list[int]],
    exclude_group_ids: set[int] | None = None,
    top_n: int = 10,
) -> list[GroupRecommendation]:
    """
    Рекомендует группы по весу = число друзей из топ-5, подписанных на группу.

    :param user_groups: ID групп, на которые уже подписан пользователь
    :param friends_groups_map: {friend_id: [group_ids]} — подписки похожих друзей
    :param exclude_group_ids: уже предлагавшиеся ранее (из истории БД)
    :param top_n: сколько групп вернуть
    """
    user_set = set(user_groups)
    excluded = exclude_group_ids or set()
    scores: dict[int, int] = {}

    for friend_groups in friends_groups_map.values():
        for group_id in friend_groups:
            if group_id in user_set or group_id in excluded:
                continue
            scores[group_id] = scores.get(group_id, 0) + 1

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    return [
        GroupRecommendation(group_id=group_id, score=float(score))
        for group_id, score in ranked[:top_n]
    ]


def rank_friends_by_subscription_similarity(
    user_groups: list[int],
    friends_subscriptions: dict[int, list[int]],
    top_friends: int = 5,
) -> list[int]:
    """
    Выбирает top-5 друзей с наибольшим пересечением подписок с пользователем.
    Используется перед сбором подписок для рекомендателя.
    """
    user_set = set(user_groups)
    similarity: list[tuple[int, int]] = []

    for friend_id, groups in friends_subscriptions.items():
        overlap = len(user_set.intersection(groups))
        if overlap > 0:
            similarity.append((friend_id, overlap))

    similarity.sort(key=lambda x: x[1], reverse=True)
    return [friend_id for friend_id, _ in similarity[:top_friends]]
