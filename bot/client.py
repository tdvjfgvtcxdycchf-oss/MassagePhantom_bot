import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from config import config

if config.proxy_url:
    # force_close=True: each request gets a fresh TCP connection (like curl),
    # preventing the proxy from accumulating stale keep-alive connections to Telegram
    _connector = aiohttp.TCPConnector(force_close=True, limit=1)
    session = AiohttpSession(proxy=config.proxy_url, connector=_connector, timeout=15)
else:
    session = None

bot = Bot(
    token=config.bot_token,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    session=session,
)
dp = Dispatcher(storage=MemoryStorage())
