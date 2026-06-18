"""Главный сценарий анализа подписок и выдачи рекомендаций."""

from vkbottle import VKAPIError as BottleVKAPIError
from vkbottle.bot import BotLabeler, Message

from bot.app import get_bot
from bot.handlers.recommendations_page import (
    CAROUSEL_PAGE_SIZE,
    MORE_BUTTON_TEXTS,
    send_recommendations_page,
)
from bot.keyboards.carousel_builder import (
    build_carousel,
    build_more_recommendations_keyboard,
)
from bot.utils.auth import get_access_token
from bot.states.user_states import UserStates
from bot.utils.carousel_photos import attach_carousel_photos
from bot.utils.recommender import rank_friends_by_subscription_similarity, recommend_groups
from bot.utils.vk_format import format_friend_mentions
from bot.utils.user_token import TOKEN_IP_BINDING_MSG, clear_user_token, is_token_ip_binding_error
from bot.utils.vk_api_client import VKAPIClient, VKAPIError, VKNetworkError
from config import settings
from database import async_session_factory
from database import crud
from database.models import AnalysisStatus
from loguru import logger

labeler = BotLabeler()


async def _get_user_token(message: Message) -> str | None:
    return await get_access_token(message)


async def run_analysis(message: Message) -> None:
    """Полный цикл: подписки → похожие друзья → рекомендации → карусель."""
    vk_user_id = message.from_id
    user_token = await _get_user_token(message)

    if not user_token:
        await message.answer(
            "Сначала нужна авторизация. Нажмите «Начать анализ →» в меню /start.",
        )
        return

    await get_bot().state_dispenser.set(
        message.peer_id,
        UserStates.ANALYZING,
        access_token=user_token,
    )
    await message.answer("⏳ Анализирую подписки и друзей… Это может занять до минуты.")

    vk_client = VKAPIClient(access_token=user_token)
    group_meta_client = VKAPIClient(access_token=settings.vk_group_token)

    try:
        try:
            token_owner = await vk_client.get_token_owner_id()
            if token_owner and token_owner != vk_user_id:
                await message.answer(
                    f"Токен принадлежит id {token_owner}, а вы — {vk_user_id}. /logout → войдите снова.",
                )
                return
        except VKAPIError as exc:
            if is_token_ip_binding_error(exc):
                await clear_user_token(vk_user_id, message.peer_id)
                await get_bot().state_dispenser.set(message.peer_id, UserStates.WAITING_ACCESS_TOKEN)
                await message.answer(TOKEN_IP_BINDING_MSG)
                return
            raise

        async with async_session_factory() as db_session:
            user_info = await vk_client.get_user_info(vk_user_id)
            db_user = await crud.get_or_create_user(
                db_session,
                vk_user_id=vk_user_id,
                first_name=user_info.first_name,
                last_name=user_info.last_name,
            )

            already_offered = await crud.get_already_recommended_group_ids(db_session, db_user.id)
            analysis = await crud.create_analysis_session(
                db_session,
                user_id=db_user.id,
                status=AnalysisStatus.IN_PROGRESS.value,
            )

            user_groups = await vk_client.get_user_subscriptions(vk_user_id)
            friend_ids = await vk_client.get_friends_list(vk_user_id)

            if not friend_ids:
                await message.answer("У вас нет доступных друзей для анализа или список закрыт.")
                await crud.update_session_status(db_session, analysis.id, AnalysisStatus.FAILED.value)
                return

            # Сканируем подписки друзей и выбираем топ-5 с максимальным пересечением
            friends_subs = await vk_client.collect_friends_subscriptions_for_similarity(
                owner_vk_id=vk_user_id,
                friend_ids=friend_ids,
                max_friends_to_scan=30,
            )
            top_friend_ids = rank_friends_by_subscription_similarity(user_groups, friends_subs, top_friends=5)

            if not top_friend_ids:
                # Если пересечений нет — берём первых 5 друзей из списка VK
                top_friend_ids = friend_ids[:5]

            friends_groups_map = await vk_client.get_friends_subscriptions(top_friend_ids)

            recommendations = recommend_groups(
                user_groups=user_groups,
                friends_groups_map=friends_groups_map,
                exclude_group_ids=already_offered,
                top_n=10,
            )

            # Диагностика для отладки пустого результата
            friend_group_ids: set[int] = set()
            for groups in friends_groups_map.values():
                friend_group_ids.update(groups)

            if not recommendations:
                privacy_hint = ""
                if len(friend_group_ids) == 0 and len(friends_groups_map) > 0:
                    privacy_hint = (
                        "\n\nУ друзей VK часто скрывает их подписки (приватность). "
                        "В настройках VK: Приватность → Сообщества → «Кто видит» → Все или Друзья."
                    )
                if len(user_groups) == 0:
                    privacy_hint += (
                        "\n\nУ вас 0 сообществ по API — проверьте, что при входе "
                        "разрешили доступ «группы» (не только «друзья»). /logout → войти снова."
                    )
                await message.answer(
                    "Пока не нашёл новых групп.\n\n"
                    f"• Ваших сообществ: {len(user_groups)}\n"
                    f"• Друзей в анализе: {len(friends_groups_map)}\n"
                    f"• Уникальных групп у друзей: {len(friend_group_ids)}\n"
                    f"• Уже предлагали ранее: {len(already_offered)}"
                    f"{privacy_hint}",
                )
                await crud.update_session_status(db_session, analysis.id, AnalysisStatus.COMPLETED.value)
                return

            group_ids = [rec.group_id for rec in recommendations]
            groups_info = await group_meta_client.get_groups_info_batch(group_ids)
            meta_map = {
                g.group_id: {
                    "name": g.name,
                    "members_count": g.members_count,
                    "photo_url": g.photo_url,
                }
                for g in groups_info
            }

            await crud.save_recommended_groups(
                db_session,
                analysis_session_id=analysis.id,
                groups=recommendations,
                group_meta=meta_map,
                start_order=0,
            )
            await crud.update_session_status(db_session, analysis.id, AnalysisStatus.COMPLETED.value)

            first_page = await crud.get_recommendations_page(
                db_session,
                analysis.id,
                offset=0,
                limit=CAROUSEL_PAGE_SIZE,
            )

        total_recs = len(recommendations)
        first_page = await attach_carousel_photos(
            first_page,
            group_meta_client,
            message.peer_id,
        )
        carousel = build_carousel(first_page)
        has_more = total_recs > CAROUSEL_PAGE_SIZE
        friends_info = await vk_client.get_users_info_batch(top_friend_ids[:5])
        friends_line = format_friend_mentions(friends_info)
        more_hint = (
            "\n\nЛистайте карусель. Ниже появится кнопка «Ещё →», если рекомендаций больше пяти."
            if has_more
            else "\n\nЛистайте карусель влево/вправо."
        )
        summary = (
            f"✅ Анализ завершён.\n"
            f"• Ваших подписок: {len(user_groups)}\n"
            f"• Похожих друзей (топ-5): {friends_line}\n"
            f"• Новых рекомендаций: {total_recs}"
            f"{more_hint}"
        )

        await message.answer(summary)
        if carousel:
            try:
                await message.answer("Рекомендации для вас:", template=carousel)
            except BottleVKAPIError as exc:
                error_text = str(exc).lower()
                if exc.code in (911, 100) and ("photo_id" in error_text or "different content" in error_text):
                    for group in first_page:
                        group.photo_vk_id = ""
                    carousel = build_carousel(first_page)
                    await message.answer("Рекомендации для вас:", template=carousel)
                else:
                    raise
            if has_more:
                await message.answer(
                    "Показать ещё 5 сообществ:",
                    keyboard=build_more_recommendations_keyboard(),
                )
        else:
            await message.answer("Карусель не сформирована.")

        await get_bot().state_dispenser.set(
            message.peer_id,
            UserStates.READY_TO_ANALYZE,
            access_token=user_token,
            last_session_id=analysis.id,
            carousel_offset=CAROUSEL_PAGE_SIZE,
        )

    except VKNetworkError as exc:
        logger.exception("Сеть VK API при анализе: {}", exc)
        await message.answer(
            "Не удалось связаться с VK API (сеть или прокси).\n\n"
            "• Проверьте интернет и VPN/прокси (127.0.0.1:10809 часто мешает)\n"
            "• В .env можно задать VK_HTTP_TRUST_ENV=true, если прокси нужен\n"
            "• Подождите минуту и нажмите «Запустить анализ» снова",
        )
    except VKAPIError as exc:
        logger.exception("Ошибка VK API при анализе: {}", exc)
        if is_token_ip_binding_error(exc):
            await clear_user_token(vk_user_id, message.peer_id)
            await get_bot().state_dispenser.set(message.peer_id, UserStates.WAITING_ACCESS_TOKEN)
            await message.answer(TOKEN_IP_BINDING_MSG)
        else:
            await message.answer(
                f"Ошибка VK API ({exc.code}): {exc.message}\n"
                "Проверьте токен и права (groups, friends).",
            )
    except Exception as exc:
        logger.exception("Непредвиденная ошибка анализа: {}", exc)
        await message.answer("Произошла ошибка при анализе. Попробуйте позже.")
    finally:
        await vk_client.close()
        await group_meta_client.close()


@labeler.message(
    text=["Запустить анализ", "запустить анализ", "Анализ", "анализ"],
    state=UserStates.READY_TO_ANALYZE,
)
async def analyze_ready_handler(message: Message) -> None:
    await run_analysis(message)


@labeler.message(text=MORE_BUTTON_TEXTS, state=UserStates.READY_TO_ANALYZE)
async def more_recommendations_handler(message: Message) -> None:
    state = await get_bot().state_dispenser.get(message.peer_id)
    payload = state.payload if state else {}
    session_id = int(payload.get("last_session_id", 0))
    offset = int(payload.get("carousel_offset", CAROUSEL_PAGE_SIZE))
    if not session_id:
        await message.answer("Сначала запустите анализ.")
        return

    await message.answer("⏳ Загружаю следующие рекомендации…")
    try:
        next_offset = await send_recommendations_page(
            message.peer_id,
            session_id,
            offset,
            message.answer,
        )
        if next_offset is not None:
            await get_bot().state_dispenser.set(
                message.peer_id,
                UserStates.READY_TO_ANALYZE,
                access_token=payload.get("access_token"),
                last_session_id=session_id,
                carousel_offset=next_offset,
            )
    except Exception as exc:
        logger.exception("Ошибка пагинации рекомендаций: {}", exc)
        await message.answer("Не удалось загрузить рекомендации. Попробуйте позже.")


@labeler.message(state=UserStates.READY_TO_ANALYZE)
async def analyze_repeat_handler(message: Message) -> None:
    """Повторный анализ по любому сообщению в состоянии READY (кроме служебных)."""
    text = (message.text or "").lower()
    if text in ("/start", "начать анализ →", "начать анализ"):
        return
    if text in {t.lower() for t in MORE_BUTTON_TEXTS}:
        return
    await run_analysis(message)
