import logging
import re

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
    waiting_chat = State()


def _groups_kb(groups: list[dict], can_add: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for g in groups:
        title = g.get("chat_title") or g.get("chat_username") or str(g["chat_id"])
        builder.button(text=f"❌ {title}", callback_data=f"pubgroups:remove:{g['chat_id']}")
    if can_add:
        builder.button(text="➕ Добавить чат", callback_data="pubgroups:add")
    builder.button(text="◀️ Назад", callback_data="back_menu")
    builder.adjust(1)
    return builder.as_markup()


def _chat_display(g: dict) -> str:
    username = g.get("chat_username") or ""
    title = g.get("chat_title") or str(g["chat_id"])
    if username:
        return f"• @{username} — {title}"
    return f"• 🔒 {title}"


@router.callback_query(F.data == "pubgroups:list")
async def pubgroups_list(cb: CallbackQuery) -> None:
    user_id = cb.from_user.id
    if not await db.is_premium_plus(user_id):
        await cb.answer("Требуется Pro Plus", show_alert=True)
        return
    groups = await db.get_public_groups(user_id)
    can_add = len(groups) < PUBLIC_GROUP_LIMIT
    lines = [_chat_display(g) for g in groups] or ["Нет добавленных чатов"]
    await cb.message.edit_text(
        f"🌐 <b>Мои чаты для мониторинга</b> ({len(groups)}/{PUBLIC_GROUP_LIMIT})\n\n"
        + "\n".join(lines)
        + "\n\nНажми ❌ рядом с чатом чтобы удалить, или добавь новый.",
        reply_markup=_groups_kb(groups, can_add),
    )
    await cb.answer()


@router.callback_query(F.data == "pubgroups:add")
async def pubgroups_add_start(cb: CallbackQuery, state: FSMContext) -> None:
    user_id = cb.from_user.id
    groups = await db.get_public_groups(user_id)
    if len(groups) >= PUBLIC_GROUP_LIMIT:
        await cb.answer(f"Лимит {PUBLIC_GROUP_LIMIT} чата достигнут", show_alert=True)
        return
    await state.set_state(AddGroupState.waiting_chat)
    from aiogram.utils.keyboard import InlineKeyboardBuilder as _IKB
    cancel_kb = _IKB()
    cancel_kb.button(text="❌ Отмена", callback_data="pubgroups:list")
    await cb.message.answer(
        "Отправь одно из:\n\n"
        "• <b>@username</b> публичного чата или канала\n"
        "• <b>Ссылку-приглашение</b> <code>t.me/+xxxx</code>\n"
        "• <b>Ссылку на сообщение</b> <code>t.me/c/xxx/1</code>\n"
        "• <b>Пересланное сообщение</b> из нужного чата\n\n"
        "Ты должен быть участником этого чата.",
        reply_markup=cancel_kb.as_markup(),
    )
    await cb.answer()


@router.message(AddGroupState.waiting_chat)
async def pubgroups_add_chat(msg: Message, state: FSMContext) -> None:
    await state.clear()
    user_id = msg.from_user.id

    from userbot.client import get_client
    client = get_client(user_id)
    if not client:
        await msg.answer("❌ Твой аккаунт не подключён.")
        return

    from telethon import utils as tl_utils

    chat_id: int | None = None
    username: str = ""
    title: str = ""

    # 1. Пересланное сообщение
    if msg.forward_from_chat:
        fwd = msg.forward_from_chat
        username = fwd.username or ""
        title = fwd.title or str(fwd.id)
        try:
            entity = await client.get_entity(fwd.id)
            chat_id = tl_utils.get_peer_id(entity)
        except Exception as e:
            logger.error("get_entity fwd error user=%s id=%s: %s", user_id, fwd.id, e)
            await msg.answer("❌ Не удалось получить доступ к этому чату. Убедись что ты его участник.")
            return

    else:
        text = (msg.text or "").strip()
        if not text:
            await msg.answer("❌ Неверный формат. Отправь @username, ссылку или перешли сообщение из нужного чата.")
            return

        # 2. Инвайт-ссылка t.me/+ или t.me/joinchat/
        m_invite = re.search(r"(?:t\.me/\+|t\.me/joinchat/)([A-Za-z0-9_-]+)", text)
        if m_invite:
            invite_hash = m_invite.group(1)
            try:
                from telethon.tl.functions.messages import CheckChatInviteRequest
                from telethon.tl.types import ChatInviteAlready, ChatInvitePeek
                result = await client(CheckChatInviteRequest(hash=invite_hash))
                if not isinstance(result, (ChatInviteAlready, ChatInvitePeek)):
                    await msg.answer("❌ Ты не участник этого чата. Вступи в него в Telegram, затем добавь сюда.")
                    return
                entity = result.chat
                chat_id = tl_utils.get_peer_id(entity)
                username = getattr(entity, "username", None) or ""
                title = getattr(entity, "title", str(chat_id))
            except Exception as e:
                logger.error("invite check error user=%s hash=%s: %s", user_id, invite_hash, e)
                await msg.answer("❌ Не удалось проверить ссылку. Убедись что ты участник этого чата.")
                return

        # 3. Ссылка t.me/c/CHAT_ID/...
        elif "t.me/c/" in text:
            m_link = re.search(r"t\.me/c/(\d+)", text)
            if not m_link:
                await msg.answer("❌ Неверный формат ссылки.")
                return
            raw_id = int(f"-100{m_link.group(1)}")
            try:
                entity = await client.get_entity(raw_id)
                chat_id = tl_utils.get_peer_id(entity)
                username = getattr(entity, "username", None) or ""
                title = getattr(entity, "title", str(chat_id))
            except Exception as e:
                logger.error("t.me/c/ error user=%s: %s", user_id, e)
                await msg.answer("❌ Не удалось найти чат. Убедись что ты его участник.")
                return

        # 4. @username
        else:
            username_clean = text.lstrip("@")
            try:
                entity = await client.get_entity(username_clean)
                chat_id = tl_utils.get_peer_id(entity)
                username = getattr(entity, "username", None) or ""
                title = getattr(entity, "title", username_clean)
            except Exception as e:
                logger.error("get_entity error user=%s username=%s: %s", user_id, username_clean, e)
                await msg.answer(f"❌ Не удалось найти чат @{username_clean}.\nПроверь правильность и убедись что ты участник.")
                return

    added = await db.add_public_group(user_id, chat_id, username, title)
    if not added:
        groups = await db.get_public_groups(user_id)
        if any(g["chat_id"] == chat_id for g in groups):
            await msg.answer("⚠️ Этот чат уже добавлен.")
        else:
            await msg.answer(f"❌ Лимит {PUBLIC_GROUP_LIMIT} чата достигнут.")
        return

    groups = await db.get_public_groups(user_id)
    can_add = len(groups) < PUBLIC_GROUP_LIMIT
    display = f"@{username}" if username else title
    await msg.answer(
        f"✅ {display} добавлен!\n\nТеперь ты будешь получать уведомления об удалённых и отредактированных сообщениях в этом чате.",
        reply_markup=_groups_kb(groups, can_add),
    )


@router.callback_query(F.data.startswith("pubgroups:remove:"))
async def pubgroups_remove(cb: CallbackQuery) -> None:
    user_id = cb.from_user.id
    chat_id = int(cb.data.split(":")[2])
    await db.remove_public_group(user_id, chat_id)
    groups = await db.get_public_groups(user_id)
    can_add = len(groups) < PUBLIC_GROUP_LIMIT
    lines = [_chat_display(g) for g in groups] or ["Нет добавленных чатов"]
    await cb.message.edit_text(
        f"🌐 <b>Мои чаты для мониторинга</b> ({len(groups)}/{PUBLIC_GROUP_LIMIT})\n\n"
        + "\n".join(lines)
        + "\n\nНажми ❌ рядом с чатом чтобы удалить, или добавь новый.",
        reply_markup=_groups_kb(groups, can_add),
    )
    await cb.answer("Удалено")
