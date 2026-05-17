import logging
import os
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.network.connection import ConnectionTcpMTProxyRandomizedIntermediate
from config import config

logger = logging.getLogger(__name__)

_active: dict[int, TelegramClient] = {}


def _mtproxy_settings():
    raw = os.getenv("MTPROXY_URL", "")
    if not raw:
        return None, None
    parts = raw.split(":")
    if len(parts) != 3:
        return None, None
    host, port, secret = parts
    return ConnectionTcpMTProxyRandomizedIntermediate, (host, int(port), secret)


_MTPROXY_CONN, _MTPROXY = _mtproxy_settings()


def _make_client(session_string: str) -> TelegramClient:
    if _MTPROXY_CONN:
        return TelegramClient(
            StringSession(session_string),
            config.api_id,
            config.api_hash,
            connection=_MTPROXY_CONN,
            proxy=_MTPROXY,
        )
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
    """Временный клиент для авторизации."""
    client = _make_client("")
    await client.connect()
    return client
