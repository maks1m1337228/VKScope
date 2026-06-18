"""Конфигурация VKScope: загрузка переменных окружения через pydantic-settings."""

from functools import lru_cache
from pathlib import Path
from urllib.parse import urlencode

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parent / ".env"


class Settings(BaseSettings):
    """Настройки приложения из .env и переменных окружения."""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    vk_group_token: str = Field(alias="VK_GROUP_TOKEN")
    vk_group_id: int = Field(default=0, alias="VK_GROUP_ID")
    vk_api_version: str = Field(default="5.199", alias="VK_API_VERSION")
    vk_app_id: int = Field(default=0, alias="VK_APP_ID")  # VK ID (кабинет id.vk.ru)

    # Для oauth.vk.com (friends/groups). VK ID-приложения дают invalid scope —
    # используйте Kate Mobile или своё Standalone с vk.com/apps?act=create
    vk_oauth_legacy_app_id: int = Field(default=2685278, alias="VK_OAUTH_LEGACY_APP_ID")

    postgres_dsn: str = Field(alias="POSTGRES_DSN")
    redis_dsn: str = Field(default="redis://localhost:6379/0", alias="REDIS_DSN")
    # false — FSM в памяти (без Redis), удобно для локальной разработки
    use_redis_fsm: bool = Field(default=False, alias="USE_REDIS_FSM")

    vk_api_request_delay: float = Field(default=0.35, alias="VK_API_REQUEST_DELAY")
    # api.vk.ru — актуальный хост; api.vk.com — запасной
    vk_api_base_url: str = Field(default="https://api.vk.ru/method", alias="VK_API_BASE_URL")
    vk_api_fallback_base_url: str = Field(
        default="https://api.vk.com/method",
        alias="VK_API_FALLBACK_BASE_URL",
    )
    # false — не использовать HTTP_PROXY/HTTPS_PROXY (часто ломает VK через локальный VPN)
    vk_http_trust_env: bool = Field(default=False, alias="VK_HTTP_TRUST_ENV")
    vk_api_max_retries: int = Field(default=4, alias="VK_API_MAX_RETRIES")
    # Права OAuth: только те, что включены в настройках приложения на dev.vk.com
    # Standalone-приложение: обычно friends,groups (offline часто даёт invalid scope)
    vk_oauth_scope: str = Field(default="friends", alias="VK_OAUTH_SCOPE")

    # OAuth без копирования токена: публичный URL (localhost или ngrok) + секрет приложения
    oauth_public_url: str = Field(default="http://127.0.0.1:8765", alias="OAUTH_PUBLIC_URL")
    oauth_port: int = Field(default=8765, alias="OAUTH_PORT")
    vk_client_secret: str = Field(default="", alias="VK_CLIENT_SECRET")

    # Демо для защиты диплома: ваш личный access_token (получите один раз через oauth.vk.com/blank.html)
    demo_user_token: str = Field(default="", alias="DEMO_USER_TOKEN")

    def build_implicit_auth_url(self, scope: str | None = "friends", *, legacy: bool = True) -> str:
        """
        Прямой вход oauth.vk.com/blank.html.
        legacy=True — ID приложения, совместимого с scope friends (не VK ID 54624312).
        """
        app_id = self.vk_oauth_legacy_app_id if legacy else self.vk_app_id
        if app_id <= 0:
            return "https://vk.com"
        params: dict[str, str] = {
            "client_id": str(app_id),
            "display": "mobile",
            "redirect_uri": "https://oauth.vk.com/blank.html",
            "response_type": "token",
            "v": self.vk_api_version,
        }
        effective = self.vk_oauth_scope if scope is None else scope
        if effective:
            params["scope"] = effective.replace(" ", ",").strip()
        return "https://oauth.vk.com/authorize?" + urlencode(params)

    @property
    def vk_implicit_auth_url(self) -> str:
        return self.build_implicit_auth_url("friends")

    @property
    def oauth_redirect_uri(self) -> str:
        return f"{self.oauth_public_url.rstrip('/')}/oauth/callback"

    @property
    def oauth_https(self) -> bool:
        return self.oauth_public_url.strip().lower().startswith("https://")

    @property
    def oauth_ready(self) -> bool:
        return bool(
            self.vk_app_id > 0
            and self.vk_client_secret.strip()
            and self.oauth_public_url.strip()
            and self.oauth_https,
        )

    def oauth_login_url(self, vk_user_id: int, peer_id: int, scope: str = "friends") -> str:
        base = self.oauth_public_url.rstrip("/")
        return f"{base}/oauth/login?user_id={vk_user_id}&peer_id={peer_id}&scope={scope}"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
