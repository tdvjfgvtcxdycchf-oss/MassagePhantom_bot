import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    api_id: int
    api_hash: str
    bot_token: str
    session_name: str
    owner_id: int
    premium_price: int
    fernet_key: bytes
    proxy_url: str | None
    bot_api_url: str | None
    webhook_host: str


def load_config() -> Config:
    missing = [k for k in ("API_ID", "API_HASH", "BOT_TOKEN", "OWNER_ID", "WEBHOOK_HOST") if not os.getenv(k)]
    if missing:
        raise ValueError(
            f"Не заданы переменные окружения: {', '.join(missing)}\n"
            "Скопируй .env.example в .env и заполни."
        )

    raw_key = os.getenv("FERNET_KEY", "")
    if not raw_key:
        from cryptography.fernet import Fernet as _F
        generated = _F.generate_key().decode()
        raise ValueError(
            f"\n[!] FERNET_KEY не задан в .env!\n"
            f"    Сгенерируй и добавь в .env:\n"
            f"    FERNET_KEY={generated}\n"
            f"    Без этого ключа сессии не шифруются и бот не запустится."
        )
    fernet_bytes = raw_key.encode()

    return Config(
        api_id=int(os.environ["API_ID"]),
        api_hash=os.environ["API_HASH"],
        bot_token=os.environ["BOT_TOKEN"],
        session_name=os.getenv("SESSION_NAME", "transparency"),
        owner_id=int(os.environ["OWNER_ID"]),
        premium_price=int(os.getenv("PREMIUM_PRICE", "100")),
        fernet_key=fernet_bytes,
        proxy_url=os.getenv("PROXY_URL") or None,
        bot_api_url=os.getenv("BOT_API_URL") or None,
        webhook_host=os.environ["WEBHOOK_HOST"],
    )


config = load_config()
