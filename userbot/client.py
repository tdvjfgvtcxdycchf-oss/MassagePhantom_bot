import logging
from urllib.parse import urlparse
from telethon import TelegramClient
from telethon.sessions import StringSession
from config import config

logger = logging.getLogger(__name__)

_active: dict[int, TelegramClient] = {}


def _parse_proxy(proxy_url: str | None) -> dict | None:
    """Парсит PROXY_URL в формат для Telethon."""
    if not proxy_url:
        return None
    p = urlparse(proxy_url)
    scheme = p.scheme.lower()
    proxy_type = 2 if "socks5" in scheme else (1 if "socks4" in scheme else 3)  # 3=HTTP
    proxy = {
        "proxy_type": proxy_type,
        "addr": p.hostname,
        "port": p.port,
    }
    if p.username:
        proxy["username"] = p.username
    if p.password:
        proxy["password"] = p.password
    return proxy


_PROXY = _parse_proxy(config.proxy_url)


def _make_client(session_string: str) -> TelegramClient:
    return TelegramClient(
        StringSession(session_string),
        config.api_id,
        config.api_hash,
        proxy=_PROXY,
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
    client = TelegramClient(StringSession(), config.api_id, config.api_hash, proxy=_PROXY)
    await client.connect()
    return client
