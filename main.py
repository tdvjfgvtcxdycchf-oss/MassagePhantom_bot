import asyncio
import logging
import ssl

from aiohttp import web
from aiogram import Bot
from aiogram.types import BufferedInputFile
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from bot.client import bot, dp
from bot.handlers import router as main_router
from bot.payments import router as payments_router
from bot.filter_handlers import router as filters_router
from bot.admin_handlers import router as admin_router
import db
import userbot.client as ub
from config import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

WEBHOOK_PORT = 8443
WEBHOOK_PATH = f"/webhook/{config.bot_token}"
WEBHOOK_URL = f"https://{config.webhook_host}:{WEBHOOK_PORT}{WEBHOOK_PATH}"
CERT_PATH = "/app/ssl/bot_cert.pem"
KEY_PATH = "/app/ssl/bot_key.pem"


async def restore_sessions() -> None:
    sessions = await db.get_all_sessions()
    if not sessions:
        logger.info("Активных сессий не найдено.")
        return
    logger.info("Восстанавливаем %d сессий...", len(sessions))
    for user_id, session_string in sessions:
        try:
            await ub.start_client(user_id, session_string)
        except Exception as e:
            logger.error("Не удалось восстановить сессию user=%s: %s", user_id, e)
            await db.delete_session(user_id)
    logger.info("Восстановлено %d сессий.", ub.active_count())


async def purge_loop() -> None:
    while True:
        await asyncio.sleep(3600)
        try:
            deleted = await db.purge_expired()
            if deleted:
                logger.info("Очистка: удалено %d устаревших сообщений.", deleted)
        except Exception as e:
            logger.error("Ошибка очистки: %s", e)


async def _send_expiry_notice(user_id: int) -> None:
    from bot.keyboards import expired_kb
    try:
        await bot.send_message(
            user_id,
            "⏰ <b>Твой доступ к Premium закончился.</b>\n\n"
            "Хочешь продолжать получать уведомления из групп, каналов и видеть содержимое удалённых сообщений?\n\n"
            "Выбери вариант:",
            reply_markup=expired_kb(),
        )
    except Exception as e:
        logger.error("Не удалось отправить уведомление об истечении user=%s: %s", user_id, e)


async def expiry_loop() -> None:
    while True:
        await asyncio.sleep(1800)
        try:
            user_ids = await db.get_users_to_notify_expiry()
            for uid in user_ids:
                await _send_expiry_notice(uid)
                await db.mark_trial_notified(uid)
        except Exception as e:
            logger.error("Ошибка проверки истечения: %s", e)


async def on_startup(bot: Bot) -> None:
    await db.init_db()
    await restore_sessions()
    asyncio.create_task(purge_loop())
    asyncio.create_task(expiry_loop())

    with open(CERT_PATH, "rb") as f:
        cert = f.read()

    await bot.set_webhook(
        url=WEBHOOK_URL,
        certificate=BufferedInputFile(cert, filename="cert.pem"),
        allowed_updates=dp.resolve_used_update_types(),
        drop_pending_updates=True,
    )
    logger.info("Webhook установлен: %s", WEBHOOK_URL)


async def on_shutdown(bot: Bot) -> None:
    await bot.delete_webhook()
    await ub.stop_all()
    await bot.session.close()
    logger.info("Бот остановлен.")


def main() -> None:
    dp.include_router(main_router)
    dp.include_router(payments_router)
    dp.include_router(filters_router)
    dp.include_router(admin_router)

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_context.load_cert_chain(CERT_PATH, KEY_PATH)

    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    logger.info("Бот запущен (webhook, порт %d).", WEBHOOK_PORT)
    web.run_app(app, host="0.0.0.0", port=WEBHOOK_PORT, ssl_context=ssl_context)


if __name__ == "__main__":
    main()
