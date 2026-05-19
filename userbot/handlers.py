import io
import logging
import time
from datetime import datetime

from telethon import TelegramClient, events
from telethon.tl.types import (
    MessageMediaPhoto, MessageMediaDocument,
    DocumentAttributeVideo, DocumentAttributeAudio,
    DocumentAttributeSticker, DocumentAttributeAnimated,
)

import db

logger = logging.getLogger(__name__)

CHAT_TYPE_LABELS = {
    "private":    "💬 Личные",
    "group":      "👥 Группа",
    "channel":    "📢 Канал",
}

MEDIA_TYPE_LABELS = {
    "photo":      "🖼 Фото",
    "video":      "🎥 Видео",
    "video_note": "⭕ Видеосообщение",
    "voice":      "🎤 Голосовое",
    "audio":      "🎵 Аудио",
    "document":   "📎 Документ",
    "sticker":    "🎭 Стикер",
    "animation":  "🎞 GIF",
}


def _chat_type(event) -> str:
    if event.is_private:
        return "private"
    # is_group=True для обычных групп И supergroups; is_channel=True только для broadcast
    if event.is_group:
        return "group"
    if event.is_channel:
        return "channel"
    return "group"


def _media_type(msg) -> str | None:
    if not msg.media:
        return None
    if isinstance(msg.media, MessageMediaPhoto):
        return "photo"
    if isinstance(msg.media, MessageMediaDocument):
        doc = msg.media.document
        for attr in doc.attributes:
            if isinstance(attr, DocumentAttributeVideo):
                return "video_note" if attr.round_message else "video"
            if isinstance(attr, DocumentAttributeAudio):
                return "voice" if attr.voice else "audio"
            if isinstance(attr, DocumentAttributeSticker):
                return "sticker"
            if isinstance(attr, DocumentAttributeAnimated):
                return "animation"
        return "document"
    return None


def _is_viewonce(msg) -> bool:
    return bool(msg.media and getattr(msg.media, "ttl_seconds", None))


def _fmt_time(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M, %d %b")


def _sender_str(name: str | None, username: str | None) -> str:
    name = name or "Неизвестно"
    return f"{name} @{username}" if username else name


def _chat_link(title: str, username: str | None, chat_type: str) -> str:
    if username:
        return f'<a href="https://t.me/{username}">{title}</a>'
    return title


async def _can_notify(owner_id: int, chat_type: str, chat_id: int = 0, is_viewonce: bool = False) -> bool:
    premium = await db.is_premium(owner_id)
    if is_viewonce and not premium:
        return False
    if chat_type == "private":
        logger.info("filter owner=%s type=private chat=%s → True (no filter)", owner_id, chat_id)
        return True
    if not premium:
        return False
    mode = await db.get_filter_mode(owner_id, chat_type)
    exc = await db.is_exception(owner_id, chat_id)
    result = (mode == "all") != exc
    logger.info("filter owner=%s type=%s chat=%s mode=%s exc=%s → %s",
                owner_id, chat_type, chat_id, mode, exc, result)
    return result


async def _send_viewonce(client: TelegramClient, owner_id: int, msg, media_type: str | None, caption: str) -> None:
    from bot.client import bot
    from aiogram.types import BufferedInputFile
    try:
        buf = io.BytesIO()
        await client.download_media(msg, file=buf)
        buf.seek(0)
        data = buf.read()
        if not data:
            raise ValueError("пустой файл")

        _EXT = {
            "photo": "jpg", "video": "mp4", "video_note": "mp4",
            "voice": "ogg", "audio": "mp3",
        }
        ext = _EXT.get(media_type or "", "bin")
        filename = f"viewonce.{ext}"
        file = BufferedInputFile(data, filename)

        if media_type == "photo":
            await bot.send_photo(owner_id, file, caption=caption)
        elif media_type == "video":
            await bot.send_video(owner_id, file, caption=caption)
        elif media_type == "video_note":
            await bot.send_video_note(owner_id, file)
            await bot.send_message(owner_id, caption)
        elif media_type == "voice":
            await bot.send_voice(owner_id, file, caption=caption)
        else:
            await bot.send_document(owner_id, file, caption=caption)
    except Exception as e:
        logger.error("Не удалось скачать view-once: %s", e)
        # Fallback — хотя бы уведомление
        await _notify(owner_id, caption + f"\n📎 {MEDIA_TYPE_LABELS.get(media_type or '', 'Медиа')} (не удалось скачать)")


async def _notify(owner_id: int, text: str) -> None:
    from bot.client import bot
    try:
        await bot.send_message(owner_id, text)
    except Exception as e:
        logger.error("Ошибка уведомления user=%s: %s", owner_id, e)


async def _notify_teaser_delete(owner_id: int, cached: dict) -> None:
    """Тизер для бесплатных пользователей — сообщение удалено в ЛС, контент скрыт."""
    from bot.client import bot
    from bot.keyboards import expired_kb
    sender_str = _sender_str(cached.get("from_name"), cached.get("from_username"))
    ts = cached.get("date", int(time.time()))
    try:
        await bot.send_message(
            owner_id,
            f"🗑 <b>Удалено</b> в личном чате\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 {sender_str}\n"
            f"🕐 {_fmt_time(ts)}\n\n"
            f"<i>Содержимое скрыто. Подключи Premium чтобы видеть удалённые сообщения.</i>",
            reply_markup=expired_kb(),
        )
    except Exception as e:
        logger.error("Ошибка teaser-уведомления user=%s: %s", owner_id, e)


def register(client: TelegramClient, owner_id: int) -> None:
    from config import config as _cfg
    _bot_id = int(_cfg.bot_token.split(":")[0])

    @client.on(events.NewMessage(incoming=True))
    async def on_message(event) -> None:
        msg = event.message
        if not msg or msg.out:
            return

        chat_type = _chat_type(event)

        # Только личка и непубличные группы
        if chat_type == "channel":
            return

        chat = await event.get_chat()

        if chat_type == "group" and getattr(chat, 'username', None):
            if not await db.is_premium_plus(owner_id):
                return
            if not await db.is_monitored_public_group(owner_id, event.chat_id):
                return

        # get_sender() надёжнее event.sender_id — в некоторых случаях
        # (каналы, боты) sender_id может вернуть peer_id вместо from_id
        sender = await event.get_sender()
        if getattr(sender, 'id', None) == _bot_id:
            return

        from_username = getattr(sender, "username", None)
        from_name = getattr(sender, "first_name", None) or getattr(sender, "title", "") or ""
        chat_title = getattr(chat, "title", None) or from_name
        chat_username = getattr(chat, "username", None)

        media_type = _media_type(msg)
        viewonce = _is_viewonce(msg)

        await db.save_message(
            owner_id=owner_id,
            chat_id=event.chat_id,
            message_id=msg.id,
            from_username=from_username,
            from_name=from_name,
            chat_title=chat_title,
            chat_username=chat_username,
            chat_type=chat_type,
            text=msg.message or None,  # msg.message надёжнее — всегда содержит текст/подпись
            caption=None,
            media_type=media_type,
            file_id=None,
            is_viewonce=viewonce,
            date=int(msg.date.timestamp()),
        )

        if viewonce and await _can_notify(owner_id, chat_type, event.chat_id, is_viewonce=True):
            media_label = MEDIA_TYPE_LABELS.get(media_type or "", "Медиа")
            chat_link = _chat_link(chat_title, chat_username, chat_type)
            caption = (
                f"👁 <b>Одноразовое</b> | {chat_link}\n"
                f"👤 {_sender_str(from_name, from_username)}\n"
                f"🕐 {_fmt_time(int(msg.date.timestamp()))}"
            )
            await _send_viewonce(client, owner_id, msg, media_type, caption)

    @client.on(events.MessageEdited(incoming=True))
    async def on_edit(event) -> None:
        msg = event.message
        if not msg or msg.out:
            return

        chat_type = _chat_type(event)

        # Только личка и непубличные группы
        if chat_type == "channel":
            return

        if chat_type == "group":
            _chat = await event.get_chat()
            if getattr(_chat, 'username', None):
                if not await db.is_premium_plus(owner_id):
                    return
                if not await db.is_monitored_public_group(owner_id, event.chat_id):
                    return

        try:
            _s = await event.get_sender()
            _sid = getattr(_s, 'id', event.sender_id)
        except Exception:
            _sid = event.sender_id
        if _sid == _bot_id:
            return

        logger.info("on_edit owner=%s chat_id=%s msg_id=%s is_private=%s is_group=%s is_channel=%s chat_type=%s",
                    owner_id, event.chat_id, msg.id, event.is_private, event.is_group, event.is_channel, chat_type)
        if not await _can_notify(owner_id, chat_type, event.chat_id):
            return

        cached = await db.get_message(owner_id, event.chat_id, msg.id)
        # Пропускаем если сообщение не было в кеше — нечего сравнивать
        if not cached:
            return

        old_text = cached.get("text") or cached.get("caption")
        new_text = msg.message or None

        if old_text == new_text:
            return

        await db.save_edit(owner_id, event.chat_id, msg.id, old_text, new_text)

        sender = await event.get_sender()
        chat = await event.get_chat()
        from_username = getattr(sender, "username", None)
        from_name = getattr(sender, "first_name", None) or getattr(sender, "title", "") or ""
        chat_title = getattr(chat, "title", None) or from_name
        chat_username = getattr(chat, "username", None)

        await db.save_message(
            owner_id=owner_id,
            chat_id=event.chat_id,
            message_id=msg.id,
            from_username=from_username,
            from_name=from_name,
            chat_title=chat_title,
            chat_username=chat_username,
            chat_type=chat_type,
            text=msg.message or None,
            caption=None,
            media_type=_media_type(msg),
            file_id=None,
            is_viewonce=False,
            date=int(msg.date.timestamp()),
        )

        chat_link = _chat_link(chat_title, chat_username, chat_type)
        await _notify(owner_id, (
            f"✏️ <b>Отредактировано</b> | {chat_link}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 {_sender_str(from_name, from_username)}\n"
            f"📝 <b>Было:</b> {old_text or '—'}\n"
            f"📝 <b>Стало:</b> {new_text or '—'}\n"
            f"🕐 {_fmt_time(int(time.time()))}"
        ))

    @client.on(events.MessageDeleted())
    async def on_delete(event) -> None:
        chat_id = event.chat_id

        for msg_id in event.deleted_ids:
            if chat_id:
                cached = await db.get_message(owner_id, chat_id, msg_id)
            else:
                cached = await db.find_by_msg_id(owner_id, msg_id)

            if not cached:
                continue

            chat_type = cached.get("chat_type", "private")
            logger.info("on_delete owner=%s event_chat=%s cached_chat=%s cached_type=%s msg_id=%s",
                        owner_id, chat_id, cached.get("chat_id"), chat_type, msg_id)
            premium = await db.is_premium(owner_id)

            if not premium:
                # Бесплатные: тизер только для ЛС
                if chat_type == "private":
                    await _notify_teaser_delete(owner_id, cached)
                continue

            if not await _can_notify(owner_id, chat_type, cached["chat_id"]):
                continue

            content = cached.get("text") or cached.get("caption")
            media_type = cached.get("media_type")

            if content:
                body = f"💬 {content}"
            elif media_type:
                body = f"📎 {MEDIA_TYPE_LABELS.get(media_type, 'Медиа')}"
            else:
                body = "❓ Пустое сообщение"

            ts = cached.get("date", int(time.time()))
            sender_str = _sender_str(cached.get("from_name"), cached.get("from_username"))
            chat_title = cached.get("chat_title") or CHAT_TYPE_LABELS.get(chat_type, "Чат")
            chat_link = _chat_link(chat_title, cached.get("chat_username"), chat_type)

            await _notify(owner_id, (
                f"🗑 <b>Удалено</b> | {chat_link}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 {sender_str}\n"
                f"{body}\n"
                f"🕐 {_fmt_time(ts)}"
            ))
