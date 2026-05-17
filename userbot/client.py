import logging
from telethon import TelegramClient
from telethon.sessions import StringSession
from config import config

logger = logging.getLogger(__name__)

_active: dict[int, TelegramClient] = {}


def _make_client(session_string: str) -> TelegramClient:
    return TelegramClient(
        StringSession(session_string),
        config.api_id,
        config.api_hash,
    )


async def start_client(owner_id: int, session_string: str) -> TelegramClient:
    if owner_id in _active:
        await stop_client(owner_id)

    client = _make_client(session_string)

    from userbot.handlers import register
    register(client, owner_id)

    await client.connect()
    _active[owner_id] = client
    logger.info("Userbot запущен для user_id=%s", owner_id)
    return client


async def stop_client(owner_id: int) -> None:
    client = _active.pop(owner_id, None)
    if client:
        try:
            await client.disconnect()
        except Exception:
            pass
        logger.info("Userbot остановлен для user_id=%s", owner_id)


async def stop_all() -> None:
    for owner_id in list(_active):
        await stop_client(owner_id)


def get_client(owner_id: int) -> TelegramClient | None:
    return _active.get(owner_id)


def active_count() -> int:
    return len(_active)


async def make_temp_client() -> TelegramClient:
    """Временный клиент для авторизации — без сохранённой сессии."""
    client = TelegramClient(StringSession(), config.api_id, config.api_hash)
    await client.connect()
    return client
