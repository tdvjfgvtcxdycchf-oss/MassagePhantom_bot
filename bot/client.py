from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from config import config

if config.proxy_url:
    session = AiohttpSession(proxy=config.proxy_url)
    # force_close=True: each request opens a fresh TCP connection to the proxy,
    # preventing stale keep-alive connections that cause TelegramConflictError.
    # _connector_init is applied lazily when the first request is made.
    session._connector_init["force_close"] = True
else:
    session = None
