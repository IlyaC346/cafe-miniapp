import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    bot_token: str
    webapp_url: str
    admin_ids: frozenset[int]
    db_path: str = "orders.db"
    proxy: str | None = None


def load_config() -> Config:
    load_dotenv()
    token = os.getenv("BOT_TOKEN", "").strip()
    url = os.getenv("WEBAPP_URL", "").strip()
    if not token:
        raise RuntimeError("Не задан BOT_TOKEN в файле .env")
    if not url.startswith("https://"):
        raise RuntimeError("WEBAPP_URL должен начинаться с https:// — Telegram открывает Mini App только по HTTPS")
    return Config(
        bot_token=token,
        webapp_url=url,
        admin_ids=frozenset(int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x),
        db_path=os.getenv("DB_PATH", "orders.db"),
        # Если Telegram доступен только через VPN — берём прокси из .env или системных настроек
        proxy=os.getenv("PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("https_proxy") or None,
    )
