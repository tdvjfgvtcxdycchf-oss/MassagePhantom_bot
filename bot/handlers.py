import logging
from datetime import datetime

from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from telethon.errors import (
    PhoneNumberInvalidError, PhoneCodeInvalidError, PhoneCodeExpiredError,
    SessionPasswordNeededError, PasswordHashInvalidError, FloodWaitError,
)

import db
from config import config
from bot.keyboards import consent_kb, main_menu_kb, account_settings_kb, status_kb, confirm_delete_kb, cancel_kb, request_phone_kb, remove_kb

logger = logging.getLogger(__name__)
router = Router()

CONSENT_TEXT = (
    "👋 <b>Добро пожаловать в Прозрачность!</b>\n\n"
    "Этот бот подключается к твоему аккаунту Telegram и уведомляет тебя об:\
\n"
    "• 🗑 удалённых сообщениях\n"
    "• ✏️ отредактированных сообщениях\n"
    "• 👁 одноразовых медиа (только Premium)\n\n"
    "<b>Что мы храним:</b>\n"
    "• Текст сообщений — <b>максимум 7 дней</b>, потом автоудаление\n"
    "• Сессия твоего аккаунта — зашифрована, нужна для работы\n\n"
    "<b>Что мы НЕ храним:</b>\n"
    "• Твой номер телефона\n"
    "• Медиафайлы (только ссылки Telegram)\n"
    "• Любые данные дольше 7 дней\n\n"
    "Ты можешь удалить все данные в любой момент командой /delete_my_data\n\n"
    "<i>Нажимая «Принимаю», ты соглашаешься с условиями обработки данных.</i>"
)


class AuthState(StatesGroup):
    waiting_phone = State()
    waiting_code = State()
    waiting_password = State()


class PromoState(StatesGroup):
    waiting_code = State()


# ── /start ────────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(msg: Message, state: FSMContext) -> None:
    # Сохраняем реферальный код до очистки стейта
    parts = (msg.text or "").split(maxsplit=1)
    ref_arg = parts[1] if len(parts) > 1 else ""

    await state.clear()

    if ref_arg.startswith("ref_"):
        await state.update_data(ref_code=ref_arg[4:])

    user_id = msg.from_user.id
    is_owner = user_id == config.owner_id
    display_name = msg.from_user.full_name or msg.from_user.username or str(user_id)
    await db.ensure_user(user_id, is_owner=is_owner, display_name=display_name)

    if not await db.has_consent(user_id):
        await msg.answer(CONSENT_TEXT, reply_markup=consent_kb())
        return

    session = await db.get_session(user_id)
    if session:
        premium = await db.is_premium(user_id)
        premium_plus = await db.is_premium_plus(user_id)
        header = await _menu_header(user_id)
        await _send_menu(
            msg,
            header,
            main_menu_kb(premium, is_owner=is_owner, is_premium_plus=premium_plus),
        )
    else:
        await msg.answer(
            "🔌 <b>Аккаунт не подключён.</b>\n\nНажми кнопку ниже или введи номер вручную (например: <code>+79001234567</code>)",
            reply_markup=request_phone_kb(),
        )
        await state.set_state(AuthState.waiting_phone)


# ── Consent ───────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "consent:accept")
async def consent_accept(cb: CallbackQuery, state: FSMContext) -> None:
    await db.set_consent(cb.from_user.id, True)
    await cb.message.edit_text("✅ <b>Согласие получено.</b>\n\nТеперь подключи свой аккаунт.")
    await cb.message.answer(
        "Нажми кнопку ниже или введи номер вручную (например: <code>+79001234567</code>)",
        reply_markup=request_phone_kb(),
    )
    await state.set_state(AuthState.waiting_phone)
    await cb.answer()


@router.callback_query(F.data == "consent:decline")
async def consent_decline(cb: CallbackQuery) -> None:
    await cb.message.edit_text(
        "❌ Хорошо. Если передумаешь — напиши /start."
    )
    await cb.answer()


# ── Auth: phone ───────────────────────────────────────────────────────────────

@router.message(AuthState.waiting_phone, F.contact)
async def auth_phone_contact(msg: Message, state: FSMContext) -> None:
    phone = msg.contact.phone_number
    if not phone.startswith("+"):
        phone = "+" + phone
    await _do_send_code(msg, state, phone)


async def _do_send_code(msg: Message, state: FSMContext, phone: str) -> None:
    await msg.answer("⏳ Отправляю код подтверждения...", reply_markup=remove_kb())
    try:
        from userbot.client import make_temp_client
        client = await make_temp_client()
        sent = await client.send_code_request(phone)
        await state.update_data(phone=phone, phone_code_hash=sent.phone_code_hash)
        _temp_clients[msg.from_user.id] = client
        await state.set_state(AuthState.waiting_code)
        await msg.answer(
            "📲 Код отправлен в Telegram.\n\n"
            "Введи код <b>с пробелами между цифрами</b>:\n"
            "например: <code>1 2 3 4 5</code>\n\n"
            "<i>(это защита от блокировки Telegram)</i>",
            reply_markup=cancel_kb(),
        )
    except PhoneNumberInvalidError:
        await msg.answer("❌ Неверный номер телефона. Попробуй ещё раз:", reply_markup=request_phone_kb())
    except FloodWaitError as e:
        await msg.answer(f"⏳ Слишком много попыток. Подожди {e.seconds} секунд.")
        await state.clear()
    except Exception as e:
        logger.error("Ошибка отправки кода: %s", e)
        await msg.answer("❌ Ошибка. Попробуй позже.")
        await state.clear()


@router.message(AuthState.waiting_phone)
async def auth_phone(msg: Message, state: FSMContext) -> None:
    phone = msg.text.strip().replace(" ", "")
    if not phone.startswith("+"):
        await msg.answer("⚠️ Номер должен начинаться с + (например <code>+79001234567</code>)")
        return
    await _do_send_code(msg, state, phone)


# ── Auth: code ────────────────────────────────────────────────────────────────

@router.message(AuthState.waiting_code)
async def auth_code(msg: Message, state: FSMContext) -> None:
    code = msg.text.strip().replace(" ", "")
    data = await state.get_data()
    client = _temp_clients.get(msg.from_user.id)

    if not client:
        await msg.answer("❌ Сессия устарела. Начни заново: /start")
        await state.clear()
        return

    try:
        await client.sign_in(data["phone"], code=code, phone_code_hash=data["phone_code_hash"])
        await _finalize_auth(msg, state, client)
    except SessionPasswordNeededError:
        await msg.answer("🔐 Включена двухфакторная аутентификация.\nВведи пароль:", reply_markup=cancel_kb())
        await state.set_state(AuthState.waiting_password)
    except PhoneCodeInvalidError:
        await msg.answer("❌ Неверный код. Попробуй ещё раз:", reply_markup=cancel_kb())
    except PhoneCodeExpiredError:
        await msg.answer("❌ Код устарел. Начни заново: /start")
        await state.clear()
        _temp_clients.pop(msg.from_user.id, None)
    except Exception as e:
        logger.error("Ошибка авторизации: %s", e)
        await msg.answer("❌ Ошибка. Попробуй позже.")
        await state.clear()
        _temp_clients.pop(msg.from_user.id, None)


# ── Auth: 2FA password ────────────────────────────────────────────────────────

@router.message(AuthState.waiting_password)
async def auth_password(msg: Message, state: FSMContext) -> None:
    client = _temp_clients.get(msg.from_user.id)
    if not client:
        await msg.answer("❌ Сессия устарела. Начни заново: /start")
        await state.clear()
        return

    try:
        await client.sign_in(password=msg.text.strip())
        await _finalize_auth(msg, state, client)
    except PasswordHashInvalidError:
        await msg.answer("❌ Неверный пароль. Попробуй ещё раз:", reply_markup=cancel_kb())
    except Exception as e:
        logger.error("Ошибка 2FA: %s", e)
        await msg.answer("❌ Ошибка. Попробуй позже.")
        await state.clear()
        _temp_clients.pop(msg.from_user.id, None)


async def _finalize_auth(msg: Message, state: FSMContext, client) -> None:
    user_id = msg.from_user.id
    session_string = client.session.save()
    me = await client.get_me()

    await db.save_session(user_id, session_string, me.id)
    _temp_clients.pop(user_id, None)

    # Пробный период (молча, только при первом подключении)
    await db.give_trial(user_id)

    # Реферальная награда для пригласившего
    data = await state.get_data()
    ref_code = data.get("ref_code")
    if ref_code:
        inviter_id = await db.use_invite(ref_code, user_id)
        if inviter_id:
            new_until = await db.extend_days(inviter_id, 7)
            from bot.client import bot as _bot
            dt = datetime.fromtimestamp(new_until).strftime("%d.%m.%Y")
            try:
                await _bot.send_message(
                    inviter_id,
                    f"🎁 Твой друг подключился! Тебе начислено <b>+7 дней</b>.\n"
                    f"Доступ активен до {dt}.",
                )
            except Exception:
                pass

    from userbot.client import start_client
    await start_client(user_id, session_string)

    await state.clear()
    premium = await db.is_premium(user_id)
    owner = user_id == config.owner_id
    days = await db.get_days_left(user_id)
    days_text = f" ({days} дн.)" if days > 0 else ""
    await _send_menu(
        msg,
        "✅ <b>Аккаунт подключён!</b>\n\n"
        "Бот теперь отслеживает твои переписки.\n"
        + (f"⭐ <b>Premium активен{days_text}</b> — все чаты под контролем."
           if premium else "🆓 <b>Бесплатный тариф:</b> только личные чаты.\n⭐ Нажми «Получить Premium» для групп и каналов."),
        main_menu_kb(premium, is_owner=owner),
    )


# ── Cancel auth ───────────────────────────────────────────────────────────────

@router.callback_query(F.data == "auth:cancel")
async def auth_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    client = _temp_clients.pop(cb.from_user.id, None)
    if client:
        try:
            await client.disconnect()
        except Exception:
            pass
    await state.clear()
    await cb.message.edit_text("❌ Авторизация отменена. /start — начать заново.")
    await cb.answer()


# ── /status ───────────────────────────────────────────────────────────────────

@router.message(Command("menu"))
async def cmd_menu(msg: Message) -> None:
    user_id = msg.from_user.id
    await db.ensure_user(user_id)
    premium = await db.is_premium(user_id)
    premium_plus = await db.is_premium_plus(user_id)
    owner = user_id == config.owner_id
    session = await db.get_session(user_id)
    if not session:
        await msg.answer(
            "🔌 Аккаунт не подключён. Используй /start для подключения."
        )
        return
    header = await _menu_header(user_id)
    await _send_menu(msg, header, main_menu_kb(premium, is_owner=owner, is_premium_plus=premium_plus))


@router.message(Command("status"))
@router.callback_query(F.data == "status")
async def cmd_status(event, **_) -> None:
    msg = event if isinstance(event, Message) else event.message
    user_id = event.from_user.id

    premium = await db.is_premium(user_id)
    until = await db.get_premium_until(user_id)
    days = await db.get_days_left(user_id)
    session = await db.get_session(user_id)

    from userbot.client import get_client
    active = get_client(user_id) is not None

    if until == -1:
        plan_text = "⭐ <b>Premium (владелец)</b> — навсегда"
    elif days > 0:
        dt = datetime.fromtimestamp(until).strftime("%d.%m.%Y")
        plan_text = f"⭐ <b>Premium активен</b> до {dt} ({days} дн.)"
    else:
        plan_text = "🆓 <b>Бесплатный тариф</b> (только личные чаты)"

    conn_text = "🟢 Аккаунт подключён и работает" if (session and active) else (
        "🟡 Сессия сохранена, но не активна" if session else "🔴 Аккаунт не подключён"
    )

    text = f"{plan_text}\n{conn_text}"
    if isinstance(event, CallbackQuery):
        await msg.edit_text(text, reply_markup=status_kb(premium))
        await event.answer()
    else:
        await msg.answer(text, reply_markup=status_kb(premium))


@router.callback_query(F.data == "back_menu")
async def back_menu(cb: CallbackQuery) -> None:
    user_id = cb.from_user.id
    premium = await db.is_premium(user_id)
    premium_plus = await db.is_premium_plus(user_id)
    owner = user_id == config.owner_id
    header = await _menu_header(user_id)
    kb = main_menu_kb(premium, is_owner=owner, is_premium_plus=premium_plus)
    try:
        await cb.message.edit_text(header, reply_markup=kb)
        _menu_msgs[user_id] = (cb.message.chat.id, cb.message.message_id)
    except Exception:
        from bot.client import bot as _bot
        try:
            await cb.message.delete()
        except Exception:
            pass
        sent = await _bot.send_message(cb.message.chat.id, header, reply_markup=kb)
        _menu_msgs[user_id] = (cb.message.chat.id, sent.message_id)
    await cb.answer()


# ── Account settings ──────────────────────────────────────────────────────────

@router.callback_query(F.data == "account_settings")
async def account_settings(cb: CallbackQuery) -> None:
    user_id = cb.from_user.id
    await cb.message.edit_text(
        f"⚙️ <b>Настройки аккаунта</b>\n\n"
        f"🆔 Ваш ID: <code>{user_id}</code>",
        reply_markup=account_settings_kb(),
    )
    await cb.answer()


# ── Disconnect ────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "disconnect")
async def disconnect(cb: CallbackQuery) -> None:
    user_id = cb.from_user.id
    from userbot.client import stop_client
    await stop_client(user_id)
    await db.delete_session(user_id)
    from aiogram.utils.keyboard import InlineKeyboardBuilder as _IKB
    reconnect_kb = _IKB()
    reconnect_kb.button(text="🔌 Подключить снова", callback_data="reconnect")
    await cb.message.edit_text(
        "🔌 <b>Аккаунт отключён.</b> Мониторинг остановлен.\n"
        "Данные аккаунта удалены.",
        reply_markup=reconnect_kb.as_markup(),
    )
    await cb.answer()


@router.callback_query(F.data == "reconnect")
async def reconnect(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.message.edit_text(
        "🔌 <b>Подключение аккаунта</b>\n\nВведи номер телефона или нажми кнопку:",
    )
    await cb.message.answer(
        "Нажми кнопку ниже или введи номер вручную (например: <code>+79001234567</code>)",
        reply_markup=request_phone_kb(),
    )
    await state.set_state(AuthState.waiting_phone)
    await cb.answer()


# ── Delete data ───────────────────────────────────────────────────────────────

@router.message(Command("delete_my_data"))
@router.callback_query(F.data == "delete_data")
async def delete_data_ask(event, **_) -> None:
    msg = event if isinstance(event, Message) else event.message
    await msg.answer(
        "⚠️ <b>Удаление всех данных</b>\n\n"
        "Будут удалены:\n"
        "• Кеш сообщений\n"
        "• История правок\n"
        "• Сессия аккаунта\n"
        "• Настройки\n\n"
        "Это действие необратимо. Продолжить?",
        reply_markup=confirm_delete_kb(),
    )
    if isinstance(event, CallbackQuery):
        await event.answer()


@router.callback_query(F.data == "delete_data:confirm")
async def delete_data_confirm(cb: CallbackQuery, state: FSMContext) -> None:
    user_id = cb.from_user.id
    from userbot.client import stop_client
    await stop_client(user_id)
    await db.delete_user_data(user_id)
    await state.clear()
    await cb.message.edit_text(
        "✅ <b>Все данные удалены.</b>\n\n"
        "Если захочешь снова — /start"
    )
    await cb.answer()


# ── Инвайт-ссылка ────────────────────────────────────────────────────────────

@router.callback_query(F.data == "invite:get_link")
async def invite_get_link(cb: CallbackQuery) -> None:
    user_id = cb.from_user.id
    code = await db.create_invite(user_id)
    from bot.client import bot as _bot
    me = await _bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{code}"

    # Текст для друга (уходит через share)
    share_text = (
        "👁 Твой друг приглашает тебя в Massage Phantom\n\n"
        "Бот, который запоминает то, что другие хотят скрыть:\n"
        "• 🗑 удалённые сообщения\n"
        "• ✏️ отредактированные сообщения\n"
        "• 👁 одноразовые медиа\n\n"
        "Подключи свой аккаунт Telegram — и ничего не упустишь.\n\n"
        "🎁 За регистрацию по этой ссылке твой друг получит +7 дней бесплатно"
    )

    import urllib.parse
    share_url = f"https://t.me/share/url?url={urllib.parse.quote(link)}&text={urllib.parse.quote(share_text)}"

    # Текст для инвайтера
    caption = (
        "🔗 <b>Твоя реферальная ссылка</b>\n\n"
        "За каждого друга, который подключится по ней — ты получишь <b>+7 дней</b> бесплатно.\n\n"
        "Нажми кнопку ниже, чтобы отправить другу 👇"
    )

    from pathlib import Path
    from aiogram.utils.keyboard import InlineKeyboardBuilder as _IKB
    from aiogram.types import InlineKeyboardButton
    kb = _IKB()
    kb.row(InlineKeyboardButton(text="📤 Отправить другу", url=share_url))
    kb.row(InlineKeyboardButton(text="◀️ В меню", callback_data="back_menu"))

    promo = Path("/app/promo.jpg")
    if promo.exists():
        from aiogram.types import FSInputFile
        await cb.message.answer_photo(FSInputFile(str(promo)), caption=caption, reply_markup=kb.as_markup())
    else:
        await cb.message.answer(caption, reply_markup=kb.as_markup())
    await cb.answer()


# ── Промокод ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "promo:enter")
async def promo_enter(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.message.answer("🎟 Введи промокод:")
    await state.set_state(PromoState.waiting_code)
    await cb.answer()


@router.message(PromoState.waiting_code)
async def promo_code_input(msg: Message, state: FSMContext) -> None:
    code = msg.text.strip().upper()
    user_id = msg.from_user.id

    promo = await db.use_promo(code, user_id)

    if not promo:
        await state.clear()
        await msg.answer(
            "❌ Промокод недействителен, уже использован или истёк.\n"
            "Проверь правильность и попробуй снова.\n\n"
            "Введи другой код или нажми /menu чтобы выйти.",
        )
        return

    await state.clear()

    months = promo["months"]
    new_until = await db.set_premium(user_id, months)
    dt = datetime.fromtimestamp(new_until).strftime("%d.%m.%Y")
    await msg.answer(
        f"✅ <b>Промокод активирован!</b>\n\n"
        f"Начислено: <b>{months} мес. Premium</b>\n"
        f"Доступ активен до {dt}.",
    )


# ── Временное хранилище клиентов для авторизации ──────────────────────────────
_temp_clients: dict[int, object] = {}

# ── Трекинг последнего меню-сообщения для авто-удаления ──────────────────────
_menu_msgs: dict[int, tuple[int, int]] = {}  # user_id → (chat_id, message_id)


async def _menu_header(user_id: int) -> str:
    from userbot.client import get_client
    session = await db.get_session(user_id)
    active = get_client(user_id) is not None
    until = await db.get_premium_until(user_id)
    days = await db.get_days_left(user_id)
    premium_plus = await db.is_premium_plus(user_id)

    conn = "🟢 Подключён" if (session and active) else ("🟡 Не активен" if session else "🔴 Не подключён")

    if until == -1:
        plan = "⭐ Premium навсегда"
    elif days > 0:
        plan = f"{'🌟 Premium Plus' if premium_plus else '⭐ Premium'} · {days} дн."
    else:
        plan = "🆓 Бесплатный"

    return f"{conn} · {plan}\n\n<b>Главное меню:</b>"


async def _send_menu(msg: Message, text: str, markup) -> None:
    """Удаляет предыдущее меню-сообщение и отправляет новое."""
    from bot.client import bot as _bot
    uid = msg.from_user.id
    prev = _menu_msgs.get(uid)
    if prev:
        try:
            await _bot.delete_message(prev[0], prev[1])
        except Exception:
            pass
    sent = await msg.answer(text, reply_markup=markup)
    _menu_msgs[uid] = (sent.chat.id, sent.message_id)
