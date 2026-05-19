import logging
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

import db
from db import PUBLIC_GROUP_LIMIT

logger = logging.getLogger(__name__)
router = Router()


class AddGroupState(StatesGroup):
    waiting_username = State()


def _groups_kb(groups: list[dict], can_add: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for g in groups:
        title = g.get("chat_title") or g.get("chat_username") or str(g["chat_id"])
        builder.button(text=f"❌ {title}", callback_data=f"pubgroups:remove:{g['chat_id']}")
    if can_add:
        builder.button(text="➕ Добавить группу", callback_data="pubgroups:add")
    builder.button(text="◀️ Назад", callback_data="back_menu")
    builder.adjust(1)
    return builder.as_markup()


@router.callback_query(F.data == "pubgroups:list")
async def pubgroups_list(cb: CallbackQuery) -> None:
    user_id = cb.from_user.id
    if not await db.is_premium_plus(user_id):
        await cb.answer("Требуется Premium Plus", show_alert=True)
        return
    groups = await db.get_public_groups(user_id)
    can_add = len(groups) < PUBLIC_GROUP_LIMIT
    lines = [f"• @{g['chat_username']} — {g.get('chat_title', '')}" for g in groups] or ["Нет добавленных групп"]
    await cb.message.edit_text(
        f"🌐 <b>Публичные группы</b> ({len(groups)}/{PUBLIC_GROUP_LIMIT})\n\n"
        + "\n".join(lines)
        + "\n\nНажми ❌ рядом с группой чтобы удалить, или добавь новую.",
        reply_markup=_groups_kb(groups, can_add),
    )
    await cb.answer()


@router.callback_query(F.data == "pubgroups:add")
async def pubgroups_add_start(cb: CallbackQuery, state: FSMContext) -> None:
    user_id = cb.from_user.id
    groups = await db.get_public_groups(user_id)
    if len(groups) >= PUBLIC_GROUP_LIMIT:
        await cb.answer(f"Лимит {PUBLIC_GROUP_LIMIT} группы достигнут", show_alert=True)
        return
    await state.set_state(AddGroupState.waiting_username)
    await cb.message.answer(
        "Отправь @username публичной группы которую хочешь мониторить.\n\n"
        "Ты должен быть участником этой группы."
    )
    await cb.answer()


@router.message(AddGroupState.waiting_username)
async def pubgroups_add_username(msg: Message, state: FSMContext) -> None:
    await state.clear()
    user_id = msg.from_user.id

    text = (msg.text or "").strip().lstrip("@")
    if not text:
        await msg.answer("❌ Неверный формат. Отправь @username группы.")
        return

    from userbot.client import get_client
    client = get_client(user_id)
    if not client:
        await msg.answer("❌ Твой аккаунт не подключён.")
        return

    try:
        entity = await client.get_entity(text)
    except Exception as e:
        await msg.answer(f"❌ Не удалось найти группу @{text}.\nПроверь username и убедись что ты участник.")
        logger.error("get_entity error user=%s username=%s: %s", user_id, text, e)
        return

    chat_id = entity.id
    username = getattr(entity, "username", None)
    title = getattr(entity, "title", text)

    if not username:
        await msg.answer("❌ Это закрытая группа. Добавлять можно только публичные (с @username).")
        return

    if not getattr(entity, "megagroup", False) and not getattr(entity, "gigagroup", False):
        await msg.answer("❌ Это не группа. Каналы не поддерживаются.")
        return

    added = await db.add_public_group(user_id, chat_id, username, title)
    if not added:
        groups = await db.get_public_groups(user_id)
        if any(g["chat_id"] == chat_id for g in groups):
            await msg.answer("⚠️ Эта группа уже добавлена.")
        else:
            await msg.answer(f"❌ Лимит {PUBLIC_GROUP_LIMIT} группы достигнут.")
        return

    groups = await db.get_public_groups(user_id)
    can_add = len(groups) < PUBLIC_GROUP_LIMIT
    await msg.answer(
        f"✅ @{username} добавлена!\n\nТеперь ты будешь видеть удалённые и отредактированные сообщения в этой группе.",
        reply_markup=_groups_kb(groups, can_add),
    )


@router.callback_query(F.data.startswith("pubgroups:remove:"))
async def pubgroups_remove(cb: CallbackQuery) -> None:
    user_id = cb.from_user.id
    chat_id = int(cb.data.split(":")[2])
    await db.remove_public_group(user_id, chat_id)
    groups = await db.get_public_groups(user_id)
    can_add = len(groups) < PUBLIC_GROUP_LIMIT
    lines = [f"• @{g['chat_username']} — {g.get('chat_title', '')}" for g in groups] or ["Нет добавленных групп"]
    await cb.message.edit_text(
        f"🌐 <b>Публичные группы</b> ({len(groups)}/{PUBLIC_GROUP_LIMIT})\n\n"
        + "\n".join(lines)
        + "\n\nНажми ❌ рядом с группой чтобы удалить, или добавь новую.",
        reply_markup=_groups_kb(groups, can_add),
    )
    await cb.answer("Удалено")
