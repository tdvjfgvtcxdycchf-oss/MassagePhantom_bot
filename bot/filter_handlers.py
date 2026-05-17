import db
from aiogram import Router, F
from aiogram.types import CallbackQuery
from bot.keyboards import filters_main_kb, filter_type_kb, exceptions_list_kb, recent_chats_kb

router = Router()

_TYPE_LABELS = {
    "group":   "👥 Группы",
    "channel": "📢 Каналы",
}

_MODE_LABELS = {
    "all":  "🟢 Получать всё (кроме исключений)",
    "none": "🔴 Не получать (кроме исключений)",
}


def _exc_desc(mode: str, type_label: str) -> str:
    if mode == "all":
        return f"<b>{type_label}</b>\n\nРежим: {_MODE_LABELS['all']}\n"
    return f"<b>{type_label}</b>\n\nРежим: {_MODE_LABELS['none']}\n"


@router.callback_query(F.data == "filters:main")
async def filters_main(cb: CallbackQuery) -> None:
    uid = cb.from_user.id
    gm = await db.get_filter_mode(uid, "group")
    cm = await db.get_filter_mode(uid, "channel")
    await cb.message.edit_text(
        "⚙️ <b>Фильтры уведомлений</b>\n\n"
        "Личные чаты отслеживаются всегда.\n"
        "Для групп и каналов выбери режим:",
        reply_markup=filters_main_kb(gm, cm),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("filters:type:"))
async def filters_type(cb: CallbackQuery) -> None:
    chat_type = cb.data.split(":")[2]
    uid = cb.from_user.id
    mode = await db.get_filter_mode(uid, chat_type)
    exceptions = await db.get_exceptions(uid, chat_type)
    type_label = _TYPE_LABELS.get(chat_type, chat_type)
    exc_word = "заглушено" if mode == "all" else "разрешено"
    await cb.message.edit_text(
        _exc_desc(mode, type_label) + f"Исключений ({exc_word}): {len(exceptions)}",
        reply_markup=filter_type_kb(chat_type, mode, len(exceptions)),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("filters:mode:"))
async def filters_set_mode(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    chat_type, mode = parts[2], parts[3]
    uid = cb.from_user.id
    await db.set_filter_mode(uid, chat_type, mode)
    exceptions = await db.get_exceptions(uid, chat_type)
    type_label = _TYPE_LABELS.get(chat_type, chat_type)
    exc_word = "заглушено" if mode == "all" else "разрешено"
    await cb.message.edit_text(
        _exc_desc(mode, type_label) + f"Исключений ({exc_word}): {len(exceptions)}",
        reply_markup=filter_type_kb(chat_type, mode, len(exceptions)),
    )
    await cb.answer("✅ Режим обновлён")


@router.callback_query(F.data.startswith("filters:exc:list:"))
async def filters_exc_list(cb: CallbackQuery) -> None:
    chat_type = cb.data.split(":")[3]
    uid = cb.from_user.id
    mode = await db.get_filter_mode(uid, chat_type)
    exceptions = await db.get_exceptions(uid, chat_type)
    type_label = _TYPE_LABELS.get(chat_type, chat_type)
    if mode == "all":
        desc = "Режим «Всё» — эти чаты <b>заглушены</b>:"
    else:
        desc = "Режим «Ничего» — эти чаты <b>разрешены</b>:"
    text = f"📋 Исключения — {type_label}\n{desc}"
    if not exceptions:
        text += "\n\n<i>(список пуст)</i>"
    await cb.message.edit_text(text, reply_markup=exceptions_list_kb(exceptions, chat_type))
    await cb.answer()


@router.callback_query(F.data.startswith("filters:exc:remove:"))
async def filters_exc_remove(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    chat_type, chat_id = parts[3], int(parts[4])
    uid = cb.from_user.id
    await db.remove_exception(uid, chat_id)
    mode = await db.get_filter_mode(uid, chat_type)
    exceptions = await db.get_exceptions(uid, chat_type)
    type_label = _TYPE_LABELS.get(chat_type, chat_type)
    if mode == "all":
        desc = "Режим «Всё» — эти чаты <b>заглушены</b>:"
    else:
        desc = "Режим «Ничего» — эти чаты <b>разрешены</b>:"
    text = f"📋 Исключения — {type_label}\n{desc}"
    if not exceptions:
        text += "\n\n<i>(список пуст)</i>"
    await cb.message.edit_text(text, reply_markup=exceptions_list_kb(exceptions, chat_type))
    await cb.answer("✅ Удалено")


async def _get_dialogs(owner_id: int, chat_type: str) -> list[dict]:
    """Получает реальные группы/каналы пользователя через Telethon."""
    from userbot.client import get_client
    from telethon.tl.types import Chat, ChatForbidden, Channel
    client = get_client(owner_id)
    if not client:
        return []
    result = []
    async for dialog in client.iter_dialogs(limit=200):
        e = dialog.entity
        if chat_type == "group":
            is_group = isinstance(e, (Chat, ChatForbidden)) or (
                isinstance(e, Channel) and getattr(e, "megagroup", False)
            )
            if not is_group:
                continue
        elif chat_type == "channel":
            is_channel = isinstance(e, Channel) and getattr(e, "broadcast", False)
            if not is_channel:
                continue
        else:
            continue
        title = getattr(e, "title", None) or str(dialog.id)
        username = getattr(e, "username", None)
        result.append({
            "chat_id": dialog.id,
            "chat_title": title,
            "chat_username": username,
        })
    return result


@router.callback_query(F.data.startswith("filters:exc:pick:"))
async def filters_exc_pick(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    chat_type = parts[3]
    page = int(parts[4]) if len(parts) > 4 else 0
    uid = cb.from_user.id

    await cb.answer("Загружаю список чатов...")

    chats = await _get_dialogs(uid, chat_type)

    if not chats:
        # Фолбэк на кеш сообщений
        chats = await db.get_recent_chats(uid, chat_type)

    if not chats:
        await cb.message.answer(
            "❌ Нет доступных чатов. Убедись что аккаунт подключён."
        )
        return

    exceptions = await db.get_exceptions(uid, chat_type)
    exc_ids = {e["chat_id"] for e in exceptions}
    type_label = _TYPE_LABELS.get(chat_type, chat_type)
    await cb.message.edit_text(
        f"➕ Добавить исключение — {type_label}\n\n"
        "Выбери чаты (✅ = уже в исключениях):",
        reply_markup=recent_chats_kb(chats, exc_ids, chat_type, page=page),
    )


@router.callback_query(F.data.startswith("filters:exc:toggle:"))
async def filters_exc_toggle(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    chat_type = parts[3]
    chat_id = int(parts[4])
    page = int(parts[5]) if len(parts) > 5 else 0
    uid = cb.from_user.id

    if await db.is_exception(uid, chat_id):
        await db.remove_exception(uid, chat_id)
        await cb.answer("❌ Удалено из исключений")
    else:
        chats = await _get_dialogs(uid, chat_type)
        if not chats:
            chats = await db.get_recent_chats(uid, chat_type)
        info = next((c for c in chats if c["chat_id"] == chat_id), None)
        title = info["chat_title"] if info else str(chat_id)
        username = info.get("chat_username") if info else None
        await db.add_exception(uid, chat_id, title, username, chat_type)
        await cb.answer("✅ Добавлено в исключения")

    chats = await _get_dialogs(uid, chat_type)
    if not chats:
        chats = await db.get_recent_chats(uid, chat_type)
    exceptions = await db.get_exceptions(uid, chat_type)
    exc_ids = {e["chat_id"] for e in exceptions}
    type_label = _TYPE_LABELS.get(chat_type, chat_type)
    await cb.message.edit_text(
        f"➕ Добавить исключение — {type_label}\n\n"
        "Выбери чаты (✅ = уже в исключениях):",
        reply_markup=recent_chats_kb(chats, exc_ids, chat_type, page=page),
    )
