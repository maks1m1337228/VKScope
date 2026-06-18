"""FSM-состояния пользователя VKScope."""

from vkbottle import BaseStateGroup


class UserStates(BaseStateGroup):
    """Состояния диалога с пользователем."""

    IDLE = "idle"
    WAITING_ACCESS_TOKEN = "waiting_access_token"
    READY_TO_ANALYZE = "ready_to_analyze"
    ANALYZING = "analyzing"
