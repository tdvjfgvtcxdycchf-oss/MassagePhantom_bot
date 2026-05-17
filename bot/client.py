import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from config import config

# Short HTTP timeout so the proxy never holds a stale long-poll connection
_timeout = aiohttp.ClientTimeout(total=20, connect=5, sock_connect=5, sock_read=15)
session = AiohttpSession(proxy=config.proxy_url, timeout=_timeout) if config.proxy_url else None

bot = Bot(
    token=config.bot_token,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    session=session,
)
dp = Dispatcher(storage=MemoryStorage())
