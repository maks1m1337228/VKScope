"""Асинхронные CRUD-операции для VKScope."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.utils.recommender import GroupRecommendation
from database.models import AnalysisSession, AnalysisStatus, RecommendedGroup, User


async def get_or_create_user(
    session: AsyncSession,
    vk_user_id: int,
    first_name: str = "",
    last_name: str = "",
) -> User:
    result = await session.execute(select(User).where(User.vk_user_id == vk_user_id))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(
            vk_user_id=vk_user_id,
            first_name=first_name,
            last_name=last_name,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
    elif first_name or last_name:
        user.first_name = first_name or user.first_name
        user.last_name = last_name or user.last_name
        await session.commit()
        await session.refresh(user)
    return user


async def get_user_by_vk_id(session: AsyncSession, vk_user_id: int) -> User | None:
    result = await session.execute(select(User).where(User.vk_user_id == vk_user_id))
    return result.scalar_one_or_none()


async def get_already_recommended_group_ids(session: AsyncSession, user_id: int) -> set[int]:
    """Группы, которые уже предлагали этому пользователю (любые сессии)."""
    stmt = (
        select(RecommendedGroup.group_id)
        .join(AnalysisSession, AnalysisSession.id == RecommendedGroup.session_id)
        .where(AnalysisSession.user_id == user_id)
    )
    result = await session.execute(stmt)
    return {row[0] for row in result.all()}


async def save_user_access_token(
    session: AsyncSession,
    vk_user_id: int,
    access_token: str,
) -> None:
    user = await get_or_create_user(session, vk_user_id=vk_user_id)
    user.access_token = access_token
    user.token_updated_at = datetime.now(timezone.utc)
    await session.commit()


async def get_user_access_token(session: AsyncSession, vk_user_id: int) -> str | None:
    user = await get_user_by_vk_id(session, vk_user_id)
    if user and user.access_token:
        return user.access_token
    return None


async def clear_user_access_token(session: AsyncSession, vk_user_id: int) -> None:
    user = await get_user_by_vk_id(session, vk_user_id)
    if user:
        user.access_token = None
        user.token_updated_at = None
        await session.commit()


async def create_analysis_session(
    session: AsyncSession,
    user_id: int,
    status: str = AnalysisStatus.IN_PROGRESS.value,
) -> AnalysisSession:
    analysis = AnalysisSession(user_id=user_id, status=status, timestamp=datetime.now(timezone.utc))
    session.add(analysis)
    await session.commit()
    await session.refresh(analysis)
    return analysis


async def update_session_status(
    session: AsyncSession,
    session_id: int,
    status: str,
) -> None:
    result = await session.execute(select(AnalysisSession).where(AnalysisSession.id == session_id))
    analysis = result.scalar_one()
    analysis.status = status
    await session.commit()


async def save_recommended_groups(
    session: AsyncSession,
    analysis_session_id: int,
    groups: list[GroupRecommendation],
    group_meta: dict[int, dict[str, str | int]],
    start_order: int = 0,
) -> list[RecommendedGroup]:
    saved: list[RecommendedGroup] = []
    for offset, rec in enumerate(groups):
        meta = group_meta.get(rec.group_id, {})
        row = RecommendedGroup(
            session_id=analysis_session_id,
            group_id=rec.group_id,
            group_name=str(meta.get("name", f"Сообщество {rec.group_id}")),
            members_count=int(meta.get("members_count", 0)),
            photo_url=str(meta.get("photo_url", "")),
            photo_vk_id=str(meta.get("photo_vk_id", "")),
            weight=float(rec.score),
            display_order=start_order + offset,
        )
        session.add(row)
        saved.append(row)
    await session.commit()
    for row in saved:
        await session.refresh(row)
    return saved


async def get_recommendations_page(
    session: AsyncSession,
    analysis_session_id: int,
    offset: int,
    limit: int = 5,
) -> list[RecommendedGroup]:
    stmt = (
        select(RecommendedGroup)
        .where(RecommendedGroup.session_id == analysis_session_id)
        .order_by(RecommendedGroup.display_order.asc())
        .offset(offset)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_recommendations(session: AsyncSession, analysis_session_id: int) -> int:
    stmt = select(RecommendedGroup).where(RecommendedGroup.session_id == analysis_session_id)
    result = await session.execute(stmt)
    return len(result.scalars().all())


async def get_analysis_session(
    session: AsyncSession,
    session_id: int,
) -> AnalysisSession | None:
    result = await session.execute(select(AnalysisSession).where(AnalysisSession.id == session_id))
    return result.scalar_one_or_none()
