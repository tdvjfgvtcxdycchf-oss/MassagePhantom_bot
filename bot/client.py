import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from config import config

session = AiohttpSession(proxy=config.proxy_url) if config.proxy_url else None

bot = Bot(
    token=config.bot_token,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    session=session,
)
dp = Dispatcher(storage=MemoryStorage())


async def setup_proxy_session() -> None:
    """Replace bot session with force_close connector (must run inside event loop)."""
    if not config.proxy_url:
        return
    connector = aiohttp.TCPConnector(force_close=True, limit=1)
    bot.session = AiohttpSession(proxy=config.proxy_url, connector=connector, timeout=15)
