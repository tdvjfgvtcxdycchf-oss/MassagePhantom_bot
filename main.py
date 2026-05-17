import asyncio
import logging

from datetime import datetime
from bot.client import bot, dp
from bot.handlers import router as main_router
from bot.payments import router as payments_router
from bot.filter_handlers import router as filters_router
from bot.admin_handlers import router as admin_router
import db
import userbot.client as ub

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def restore_sessions() -> None:
    """Восстанавливает все userbot-сессии после перезапуска."""
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
    """Фоновая задача: удаляет истёкшие сообщения раз в час."""
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
    """Уведомляет пользователей об истечении пробного периода / Premium."""
    while True:
        await asyncio.sleep(1800)  # каждые 30 минут
        try:
            user_ids = await db.get_users_to_notify_expiry()
            for uid in user_ids:
                await _send_expiry_notice(uid)
                await db.mark_trial_notified(uid)
        except Exception as e:
            logger.error("Ошибка проверки истечения: %s", e)


async def main() -> None:
    await db.init_db()
    await restore_sessions()

    dp.include_router(main_router)
    dp.include_router(payments_router)
    dp.include_router(filters_router)
    dp.include_router(admin_router)

    asyncio.create_task(purge_loop())
    asyncio.create_task(expiry_loop())

    logger.info("Бот запущен.")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types(), timeout=5)
    finally:
        await ub.stop_all()
        await bot.session.close()
        logger.info("Бот остановлен.")


if __name__ == "__main__":
    asyncio.run(main())
