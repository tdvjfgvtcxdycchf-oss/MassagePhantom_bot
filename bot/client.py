from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from config import config

if config.bot_api_url:
    session = AiohttpSession(api=TelegramAPIServer.from_base(config.bot_api_url))
elif config.proxy_url:
    session = AiohttpSession(proxy=config.proxy_url)
else:
    session = None

bot = Bot(
    token=config.bot_token,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    session=session,
)
dp = Dispatcher(storage=MemoryStorage())
