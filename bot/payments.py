import logging
from datetime import datetime

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery, LabeledPrice,
    PreCheckoutQuery, Message,
)

import db
from config import config
from bot.keyboards import main_menu_kb, premium_kb, premium_tiers, premium_plus_kb, premium_plus_tiers

logger = logging.getLogger(__name__)
router = Router()


def _tier_by_months(months: int) -> tuple[int, str] | None:
    for m, price, label in premium_tiers():
        if m == months:
            return price, label
    return None


# ── Страница с выбором тарифа ─────────────────────────────────────────────────

@router.callback_query(F.data == "premium:info")
async def premium_info(cb: CallbackQuery) -> None:
    lines = []
    for months, price, label in premium_tiers():
        lines.append(f"• {label} — <b>{price} ⭐</b>")
    await cb.message.edit_text(
        "⭐ <b>Premium</b>\n\n"
        "Видишь удалённые и отредактированные сообщения в личных переписках и небольших личных группах.\n\n"
        "<b>Что включено:</b>\n"
        "• 🗑 Полный текст удалённых сообщений\n"
        "• ✏️ История редактирований — видишь что было до правки\n"
        "• 👁 Одноразовые медиа (view-once) — бот перехватывает до исчезновения\n\n"
        "<b>Тарифы:</b>\n" + "\n".join(lines) + "\n\n"
        "Оплата через Telegram Stars — мгновенно, без карт.",
        reply_markup=premium_kb(),
    )
    await cb.answer()


# ── Отправка инвойса ──────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("premium:buy:"))
async def send_invoice(cb: CallbackQuery) -> None:
    months = int(cb.data.split(":")[2])
    tier = _tier_by_months(months)
    if not tier:
        await cb.answer("Неизвестный тариф", show_alert=True)
        return
    price, label = tier
    from bot.client import bot
    await bot.send_invoice(
        chat_id=cb.from_user.id,
        title=f"⭐ Premium — {label}",
        description=f"Мониторинг групп, каналов, ботов и одноразовых сообщений на {label.lower()}.",
        payload=f"premium:{months}",
        currency="XTR",
        prices=[LabeledPrice(label=label, amount=price)],
    )
    await cb.answer()


# ── Premium Plus ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "premium_plus:info")
async def premium_plus_info(cb: CallbackQuery) -> None:
    lines = []
    for months, price, label in premium_plus_tiers():
        lines.append(f"• {label} — <b>{price} ⭐</b>")
    await cb.message.edit_text(
        "🌟 <b>Premium Plus</b>\n\n"
        "Расширение для тех, кто хочет больше.\n\n"
        "<b>Что добавляет:</b>\n"
        "• Видишь удалённые и отредактированные в больших группах-сообществах и каналах\n"
        "• До <b>3 чатов</b> на выбор — добавляешь сам\n\n"
        "<b>Требует активный Premium.</b>\n\n"
        "<b>Тарифы:</b>\n" + "\n".join(lines) + "\n\n"
        "Оплата через Telegram Stars.",
        reply_markup=premium_plus_kb(),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("premium_plus:buy:"))
async def send_plus_invoice(cb: CallbackQuery) -> None:
    if not await db.is_premium(cb.from_user.id):
        await cb.answer("❗ Сначала купи Premium", show_alert=True)
        return
    months = int(cb.data.split(":")[2])
    tier = next(((p, l) for m, p, l in premium_plus_tiers() if m == months), None)
    if not tier:
        await cb.answer("Неизвестный тариф", show_alert=True)
        return
    price, label = tier
    from bot.client import bot
    await bot.send_invoice(
        chat_id=cb.from_user.id,
        title=f"🌟 Premium Plus — {label}",
        description=f"Удалённые и отредактированные в группах-сообществах и каналах на {label.lower()}.",
        payload=f"premium_plus:{months}",
        currency="XTR",
        prices=[LabeledPrice(label=label, amount=price)],
    )
    await cb.answer()


# ── Pre-checkout ──────────────────────────────────────────────────────────────

@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery) -> None:
    await query.answer(ok=True)


# ── Успешная оплата ───────────────────────────────────────────────────────────

@router.message(F.successful_payment)
async def payment_success(msg: Message) -> None:
    user_id = msg.from_user.id
    payload = msg.successful_payment.invoice_payload
    charge_id = msg.successful_payment.telegram_payment_charge_id
    amount = msg.successful_payment.total_amount

    parts = payload.split(":")
    payment_type = parts[0]
    months = int(parts[1]) if len(parts) > 1 else 1

    await db.save_payment(user_id, charge_id, amount, months)

    from userbot.handlers import invalidate_status_cache
    invalidate_status_cache(user_id)

    if payment_type == "premium_plus":
        expires = await db.set_premium_plus(user_id, months=months)
        dt = datetime.fromtimestamp(expires).strftime("%d.%m.%Y")
        premium = await db.is_premium(user_id)
        await msg.answer(
            f"🌟 <b>Premium Plus активирован!</b>\n\n"
            f"Действует до: <b>{dt}</b>\n\n"
            "Теперь можешь добавить до 3 больших групп или каналов — и видеть удалённые и отредактированные сообщения и в них.",
            reply_markup=main_menu_kb(premium, is_premium_plus=True),
        )
    else:
        tier = _tier_by_months(months)
        label = tier[1] if tier else f"{months} мес."
        expires = await db.set_premium(user_id, months=months)
        dt = datetime.fromtimestamp(expires).strftime("%d.%m.%Y")
        premium = await db.is_premium(user_id)
        plus = await db.is_premium_plus(user_id)
        await msg.answer(
            f"🎉 <b>Premium активирован!</b>\n\n"
            f"Тариф: {label}\n"
            f"Действует до: <b>{dt}</b>\n\n"
            "Теперь доступно:\n"
            "• 🗑 Полный текст удалённых сообщений\n"
            "• ✏️ История редактирований\n"
            "• 👁 Одноразовые медиа (view-once)",
            reply_markup=main_menu_kb(premium, is_premium_plus=plus),
        )


# ── Команды владельца ─────────────────────────────────────────────────────────

def _owner_only(msg: Message) -> bool:
    return msg.from_user.id == config.owner_id


@router.message(Command("give_premium"))
async def cmd_give_premium(msg: Message) -> None:
    if not _owner_only(msg):
        return
    parts = msg.text.split()
    if len(parts) < 3:
        await msg.answer("Формат: <code>/give_premium &lt;user_id&gt; &lt;месяцы&gt;</code>")
        return
    try:
        target_id = int(parts[1])
        months = int(parts[2])
    except ValueError:
        await msg.answer("user_id и месяцы должны быть числами")
        return
    await db.ensure_user(target_id)
    expires = await db.set_premium(target_id, months=months)
    dt = datetime.fromtimestamp(expires).strftime("%d.%m.%Y")
    await msg.answer(f"✅ Premium выдан пользователю <code>{target_id}</code> до {dt}")
    try:
        from bot.client import bot
        await bot.send_message(
            target_id,
            f"🎁 Вам выдан Premium на {months} мес. (до {dt})!\n\nНажми /start для обновления меню.",
        )
    except Exception:
        pass


@router.message(Command("revoke_premium"))
async def cmd_revoke_premium(msg: Message) -> None:
    if not _owner_only(msg):
        return
    parts = msg.text.split()
    if len(parts) < 2:
        await msg.answer("Формат: <code>/revoke_premium &lt;user_id&gt;</code>")
        return
    try:
        target_id = int(parts[1])
    except ValueError:
        await msg.answer("user_id должен быть числом")
        return
    await db.revoke_premium(target_id)
    await msg.answer(f"✅ Premium отозван у пользователя <code>{target_id}</code>")


@router.message(Command("refund"))
async def cmd_refund(msg: Message) -> None:
    if not _owner_only(msg):
        return
    parts = msg.text.split()
    if len(parts) < 2:
        await msg.answer("Формат: <code>/refund &lt;user_id&gt;</code>")
        return
    try:
        target_id = int(parts[1])
    except ValueError:
        await msg.answer("user_id должен быть числом")
        return

    payment = await db.get_last_payment(target_id)
    if not payment:
        await msg.answer(f"❌ Нет активных платежей у пользователя <code>{target_id}</code>")
        return

    from bot.client import bot
    try:
        await bot.refund_star_payment(target_id, payment["charge_id"])
        await db.mark_refunded(payment["charge_id"])
        await db.revoke_premium(target_id)
        dt = datetime.fromtimestamp(payment["created_at"]).strftime("%d.%m.%Y")
        await msg.answer(
            f"✅ Возврат выполнен:\n"
            f"Пользователь: <code>{target_id}</code>\n"
            f"Сумма: {payment['amount']} ⭐\n"
            f"Дата платежа: {dt}"
        )
        try:
            await bot.send_message(
                target_id,
                f"💫 Вам возвращено {payment['amount']} Stars. Premium деактивирован.",
            )
        except Exception:
            pass
    except Exception as e:
        logger.error("Ошибка возврата Stars: %s", e)
        await msg.answer(f"❌ Ошибка возврата: {e}")
