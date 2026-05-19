from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import config


def consent_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Принимаю", callback_data="consent:accept")
    builder.button(text="❌ Отказываюсь", callback_data="consent:decline")
    builder.adjust(2)
    return builder.as_markup()


def main_menu_kb(is_premium: bool, is_owner: bool = False, is_premium_plus: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if is_owner:
        builder.button(text="🔧 Админ-панель", callback_data="adm:main")
    if not is_premium:
        builder.button(text="⭐ Получить Premium", callback_data="premium:info")
    else:
        # builder.button(text="⚙️ Фильтры уведомлений", callback_data="filters:main")
        if not is_premium_plus:
            builder.button(text="🌟 Premium Plus (публичные группы)", callback_data="premium_plus:info")
        else:
            builder.button(text="🌐 Публичные группы", callback_data="pubgroups:list")
        builder.button(text="⭐ Продлить Premium", callback_data="premium:info")
    builder.button(text="🔗 Пригласить друга (+7 дней)", callback_data="invite:get_link")
    builder.button(text="🎟 Ввести промокод", callback_data="promo:enter")
    builder.button(text="⚙️ Аккаунт", callback_data="account_settings")
    builder.adjust(1)
    return builder.as_markup()


def account_settings_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔌 Отключить аккаунт", callback_data="disconnect")
    builder.button(text="🗑 Удалить мои данные", callback_data="delete_data")
    builder.button(text="◀️ Назад", callback_data="back_menu")
    builder.adjust(1)
    return builder.as_markup()


def _premium_tiers() -> list[tuple[int, int, str]]:
    base = config.premium_price
    return [
        (1,  base,               "1 месяц"),
        (3,  round(base * 2.5),  "3 месяца"),
        (6,  round(base * 4.5),  "6 месяцев"),
        (12, round(base * 8),    "12 месяцев"),
    ]


def premium_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for months, price, label in _premium_tiers():
        builder.button(text=f"🛒 {label} — {price} ⭐", callback_data=f"premium:buy:{months}")
    builder.button(text="◀️ Назад", callback_data="back_menu")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def premium_tiers() -> list[tuple[int, int, str]]:
    return _premium_tiers()


def _premium_plus_tiers() -> list[tuple[int, int, str]]:
    base = config.premium_plus_price
    return [
        (1,  base,               "1 месяц"),
        (3,  round(base * 2.5),  "3 месяца"),
        (6,  round(base * 4.5),  "6 месяцев"),
        (12, round(base * 8),    "12 месяцев"),
    ]


def premium_plus_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for months, price, label in _premium_plus_tiers():
        builder.button(text=f"🛒 {label} — {price} ⭐", callback_data=f"premium_plus:buy:{months}")
    builder.button(text="◀️ Назад", callback_data="back_menu")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def premium_plus_tiers() -> list[tuple[int, int, str]]:
    return _premium_plus_tiers()


# ── Админ-панель ──────────────────────────────────────────────────────────────

def admin_main_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="👥 Пользователи", callback_data="adm:users:0")
    builder.button(text="📢 Рассылка", callback_data="adm:broadcast")
    builder.button(text="🔍 Найти по ID", callback_data="adm:search")
    builder.button(text="🎟 Промокоды", callback_data="adm:promos")
    builder.button(text="🌳 Дерево приглашений", callback_data="adm:invite_tree")
    builder.button(text="🔄 Обновить", callback_data="adm:main")
    builder.button(text="◀️ Назад", callback_data="back_menu")
    builder.adjust(2, 2, 1, 2)
    return builder.as_markup()


def admin_promos_kb(promos: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for p in promos:
        uses = f"{p['used_count']}/{p['max_uses']}"
        label = f"🎟 {p['code']} · {p['months']}мес · {uses}"
        builder.button(text=label, callback_data=f"adm:promo:del:{p['code']}")
    builder.button(text="➕ Создать промокод", callback_data="adm:promo:create")
    builder.button(text="◀️ Назад", callback_data="adm:main")
    builder.adjust(1)
    return builder.as_markup()


def promo_months_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for m, label in [(1, "1 месяц"), (3, "3 месяца"), (6, "6 месяцев"), (12, "12 месяцев")]:
        builder.button(text=label, callback_data=f"adm:promo:months:{m}")
    builder.adjust(2)
    return builder.as_markup()


def admin_users_kb(users: list, page: int, total: int, per_page: int = 10) -> InlineKeyboardMarkup:
    STATUS_ICON = {"premium": "⭐", "trial": "🎁", "free": "🆓"}
    builder = InlineKeyboardBuilder()
    for u in users:
        icon = STATUS_ICON.get(u["status"], "🆓")
        name = (u.get("display_name") or str(u["user_id"]))[:20]
        days = f" {u['days_left']}д" if u["days_left"] > 0 else ""
        builder.button(text=f"{icon} {name}{days}", callback_data=f"adm:user:{u['user_id']}")
    builder.adjust(1)
    # Пагинация
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"adm:users:{page-1}"))
    total_pages = max(1, (total + per_page - 1) // per_page)
    nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
    if (page + 1) * per_page < total:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"adm:users:{page+1}"))
    builder.row(*nav)
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="adm:main"))
    return builder.as_markup()


def admin_user_kb(user_id: int, has_session: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⭐ Выдать Premium", callback_data=f"adm:give:{user_id}")
    builder.button(text="❌ Отозвать Premium", callback_data=f"adm:revoke:{user_id}")
    builder.button(text="💸 Вернуть Stars", callback_data=f"adm:refund:{user_id}")
    builder.button(text="⏱ Сбросить дни (тест)", callback_data=f"adm:resetdays:{user_id}")
    if has_session:
        builder.button(text="🔌 Отключить аккаунт", callback_data=f"adm:disconnect:{user_id}")
    builder.button(text="◀️ Назад", callback_data="adm:users:0")
    builder.adjust(2, 1, 1, 1, 1)
    return builder.as_markup()


def admin_broadcast_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="👥 Всем", callback_data="adm:bc:all")
    builder.button(text="⭐ Premium", callback_data="adm:bc:premium")
    builder.button(text="🎁 Trial", callback_data="adm:bc:trial")
    builder.button(text="🆓 Бесплатным", callback_data="adm:bc:free")
    builder.button(text="◀️ Назад", callback_data="adm:main")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def admin_bc_confirm_kb(target: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Отправить", callback_data=f"adm:bc:confirm:{target}")
    builder.button(text="❌ Отмена", callback_data="adm:broadcast")
    builder.adjust(2)
    return builder.as_markup()


def expired_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⭐ Купить Premium", callback_data="premium:info")
    builder.button(text="🔗 Пригласить друга (+7 дней)", callback_data="invite:get_link")
    builder.adjust(1)
    return builder.as_markup()


def confirm_delete_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⚠️ Да, удалить всё", callback_data="delete_data:confirm")
    builder.button(text="◀️ Отмена", callback_data="back_menu")
    builder.adjust(2)
    return builder.as_markup()


def status_kb(is_premium: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    label = "⭐ Продлить Premium" if is_premium else "⭐ Купить Premium"
    builder.button(text=label, callback_data="premium:info")
    builder.button(text="🔗 Пригласить друга (+7 дней)", callback_data="invite:get_link")
    builder.button(text="🎟 Ввести промокод", callback_data="promo:enter")
    builder.button(text="◀️ Назад", callback_data="back_menu")
    builder.adjust(1)
    return builder.as_markup()


def cancel_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data="auth:cancel")
    return builder.as_markup()


def request_phone_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Отправить номер телефона", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def remove_kb() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()


# ── Фильтры ───────────────────────────────────────────────────────────────────

def filters_main_kb(groups_mode: str, channels_mode: str) -> InlineKeyboardMarkup:
    gm = "🟢 Всё" if groups_mode == "all" else "🔴 Ничего"
    cm = "🟢 Всё" if channels_mode == "all" else "🔴 Ничего"
    builder = InlineKeyboardBuilder()
    builder.button(text=f"👥 Группы: {gm}", callback_data="filters:type:group")
    builder.button(text=f"📢 Каналы: {cm}", callback_data="filters:type:channel")
    builder.button(text="◀️ Назад", callback_data="back_menu")
    builder.adjust(1)
    return builder.as_markup()


def filter_type_kb(chat_type: str, mode: str, exc_count: int) -> InlineKeyboardMarkup:
    new_mode = "none" if mode == "all" else "all"
    toggle_label = "🔄 Переключить на «Не получать»" if mode == "all" else "🔄 Переключить на «Получать всё»"
    builder = InlineKeyboardBuilder()
    builder.button(text=toggle_label, callback_data=f"filters:mode:{chat_type}:{new_mode}")
    builder.button(text=f"📋 Исключения ({exc_count})", callback_data=f"filters:exc:list:{chat_type}")
    builder.button(text="◀️ Назад", callback_data="filters:main")
    builder.adjust(1)
    return builder.as_markup()


def exceptions_list_kb(exceptions: list, chat_type: str, page: int = 0, per_page: int = 8) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    start = page * per_page
    for exc in exceptions[start:start + per_page]:
        title = (exc.get("chat_title") or str(exc["chat_id"]))[:30]
        builder.button(text=f"❌ {title}", callback_data=f"filters:exc:remove:{chat_type}:{exc['chat_id']}:{page}")
    builder.adjust(1)
    total_pages = max(1, (len(exceptions) + per_page - 1) // per_page)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"filters:exc:list:{chat_type}:{page-1}"))
    if total_pages > 1:
        nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
    if (page + 1) * per_page < len(exceptions):
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"filters:exc:list:{chat_type}:{page+1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="➕ Добавить чат", callback_data=f"filters:exc:pick:{chat_type}"))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data=f"filters:type:{chat_type}"))
    return builder.as_markup()


def recent_chats_kb(
    chats: list, exception_ids: set, chat_type: str,
    page: int = 0, per_page: int = 10,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    start = page * per_page
    for chat in chats[start:start + per_page]:
        cid = chat["chat_id"]
        title = (chat.get("chat_title") or str(cid))[:30]
        mark = "✅" if cid in exception_ids else "➕"
        builder.button(
            text=f"{mark} {title}",
            callback_data=f"filters:exc:toggle:{chat_type}:{cid}:{page}",
        )
    builder.adjust(1)

    total_pages = max(1, (len(chats) + per_page - 1) // per_page)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"filters:exc:pick:{chat_type}:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
    if (page + 1) * per_page < len(chats):
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"filters:exc:pick:{chat_type}:{page + 1}"))
    builder.row(*nav)
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data=f"filters:exc:list:{chat_type}"))
    return builder.as_markup()
