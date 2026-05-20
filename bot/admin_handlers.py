import logging
from datetime import datetime

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery

import db
from config import config
from bot.keyboards import (
    admin_main_kb, admin_users_kb, admin_user_kb,
    admin_broadcast_kb, admin_bc_confirm_kb,
    admin_promos_kb, promo_months_kb, promo_type_kb, admin_cancel_kb,
)

logger = logging.getLogger(__name__)
router = Router()

PER_PAGE = 10

STATUS_LABEL = {
    "owner":   "♾️ Владелец",
    "premium": "⭐ Premium",
    "trial":   "🎁 Пробный",
    "free":    "🆓 Бесплатный",
}


def _owner_only(user_id: int) -> bool:
    return user_id == config.owner_id


class AdminState(StatesGroup):
    waiting_give_months = State()
    waiting_broadcast_text = State()
    waiting_search_id = State()
    waiting_promo_code = State()
    waiting_promo_type = State()
    waiting_promo_months = State()
    waiting_promo_uses = State()


# ── /admin ────────────────────────────────────────────────────────────────────

@router.message(Command("admin"))
async def cmd_admin(msg: Message) -> None:
    if not _owner_only(msg.from_user.id):
        return
    await _show_dashboard(msg)


@router.callback_query(F.data == "adm:main")
async def adm_main(cb: CallbackQuery) -> None:
    if not _owner_only(cb.from_user.id):
        return
    await _show_dashboard(cb.message, edit=True)
    await cb.answer()


async def _show_dashboard(msg: Message, edit: bool = False) -> None:
    s = await db.admin_overview()
    from userbot.client import active_count
    active = active_count()
    text = (
        "🔧 <b>Админ-панель</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Пользователей: <b>{s['total']}</b>  (+{s['new_today']} сегодня)\n"
        f"🟢 Активных сессий: <b>{active}</b> / {s['sessions']}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"⭐ Premium: <b>{s['premium']}</b>\n"
        f"🎁 Пробный: <b>{s['trial']}</b>\n"
        f"🆓 Бесплатных: <b>{s['free']}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Выручка: <b>{s['revenue']} ⭐</b>"
    )
    if edit:
        await msg.edit_text(text, reply_markup=admin_main_kb())
    else:
        await msg.answer(text, reply_markup=admin_main_kb())


# ── Список пользователей ──────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("adm:users:"))
async def adm_users(cb: CallbackQuery) -> None:
    if not _owner_only(cb.from_user.id):
        return
    page = int(cb.data.split(":")[2])
    users, total = await db.admin_users_page(page, PER_PAGE)
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    text = (
        f"👥 <b>Пользователи</b> — стр. {page+1}/{total_pages} (всего {total})\n\n"
        "Тап на пользователя для управления:"
    )
    await cb.message.edit_text(text, reply_markup=admin_users_kb(users, page, total, PER_PAGE))
    await cb.answer()


# ── Детали пользователя ───────────────────────────────────────────────────────

async def _render_user_detail(user_id: int) -> tuple[str, bool]:
    """Возвращает (текст, has_session) для карточки пользователя."""
    u = await db.admin_user_detail(user_id)
    if not u:
        return f"❌ Пользователь <code>{user_id}</code> не найден", False
    name = u.get("display_name") or f"id{user_id}"
    status_label = STATUS_LABEL.get(u["status"], u["status"])
    reg_dt = datetime.fromtimestamp(u["created_at"]).strftime("%d.%m.%Y")
    days = u["days_left"]
    until = u.get("until", 0)
    until_str = datetime.fromtimestamp(until).strftime("%d.%m.%Y") if until > 0 else "—"
    has_session = u.get("account_tg_id") is not None
    text = (
        f"👤 <b>{name}</b>\n"
        f"ID: <code>{user_id}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"Статус: {status_label}\n"
        f"Дней осталось: <b>{days if days >= 0 else '∞'}</b>\n"
        f"Истекает: {until_str}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"Регистрация: {reg_dt}\n"
        f"Платежей: {u['payment_count']} ({u['total_spent']} ⭐)\n"
        f"Пригласил: {u['invites_sent']} чел.\n"
        f"Сессия: {'🟢 активна' if has_session else '🔴 нет'}"
    )
    return text, has_session


@router.callback_query(F.data.startswith("adm:user:"))
async def adm_user_detail(cb: CallbackQuery) -> None:
    if not _owner_only(cb.from_user.id):
        return
    user_id = int(cb.data.split(":")[2])
    text, has_session = await _render_user_detail(user_id)
    await cb.message.edit_text(text, reply_markup=admin_user_kb(user_id, has_session))
    await cb.answer()


@router.callback_query(F.data == "noop")
async def noop_cb(cb: CallbackQuery) -> None:
    await cb.answer()


# ── Выдать Premium ────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("adm:give:"))
async def adm_give_start(cb: CallbackQuery, state: FSMContext) -> None:
    if not _owner_only(cb.from_user.id):
        return
    user_id = int(cb.data.split(":")[2])
    await state.update_data(target_user_id=user_id)
    await state.set_state(AdminState.waiting_give_months)
    await cb.message.answer(
        f"Сколько месяцев выдать пользователю <code>{user_id}</code>?\n"
        "Введи число (например: <code>1</code>, <code>3</code>, <code>12</code>):",
        reply_markup=admin_cancel_kb(),
    )
    await cb.answer()


@router.message(AdminState.waiting_give_months)
async def adm_give_months(msg: Message, state: FSMContext) -> None:
    if not _owner_only(msg.from_user.id):
        return
    try:
        months = int(msg.text.strip())
        if months < 1 or months > 120:
            raise ValueError
    except ValueError:
        await msg.answer("Введи число месяцев от 1 до 120:")
        return

    data = await state.get_data()
    target_id = data["target_user_id"]
    await state.clear()

    expires = await db.set_premium(target_id, months=months)
    dt = datetime.fromtimestamp(expires).strftime("%d.%m.%Y")
    await msg.answer(f"✅ Premium выдан <code>{target_id}</code> на {months} мес. до {dt}")
    try:
        from bot.client import bot
        await bot.send_message(
            target_id,
            f"🎁 Тебе выдан Premium на {months} мес. (до {dt})!"
        )
    except Exception:
        pass


# ── Сброс дней (тест) ────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("adm:resetdays:"))
async def adm_reset_days(cb: CallbackQuery) -> None:
    if not _owner_only(cb.from_user.id):
        return
    user_id = int(cb.data.split(":")[2])
    await db.reset_days(user_id)
    text, has_session = await _render_user_detail(user_id)
    await cb.message.edit_text(text, reply_markup=admin_user_kb(user_id, has_session))
    await cb.answer("✅ Дни сброшены — пользователь в бесплатном режиме", show_alert=True)


# ── Отозвать Premium ──────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("adm:revoke:"))
async def adm_revoke(cb: CallbackQuery) -> None:
    if not _owner_only(cb.from_user.id):
        return
    user_id = int(cb.data.split(":")[2])
    await db.revoke_premium(user_id)
    text, has_session = await _render_user_detail(user_id)
    await cb.message.edit_text(text, reply_markup=admin_user_kb(user_id, has_session))
    await cb.answer("✅ Premium отозван", show_alert=True)


# ── Вернуть Stars ─────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("adm:refund:"))
async def adm_refund(cb: CallbackQuery) -> None:
    if not _owner_only(cb.from_user.id):
        return
    user_id = int(cb.data.split(":")[2])
    payment = await db.get_last_payment(user_id)
    if not payment:
        await cb.answer("Нет активных платежей", show_alert=True)
        return
    from bot.client import bot
    try:
        await bot.refund_star_payment(user_id, payment["charge_id"])
        await db.mark_refunded(payment["charge_id"])
        await db.revoke_premium(user_id)
        try:
            await bot.send_message(user_id, f"💫 Тебе возвращено {payment['amount']} Stars. Premium деактивирован.")
        except Exception:
            pass
        text, has_session = await _render_user_detail(user_id)
        await cb.message.edit_text(text, reply_markup=admin_user_kb(user_id, has_session))
        await cb.answer(f"✅ Возвращено {payment['amount']} ⭐", show_alert=True)
    except Exception as e:
        await cb.answer(f"Ошибка: {e}", show_alert=True)


# ── Отключить аккаунт пользователя ───────────────────────────────────────────

@router.callback_query(F.data.startswith("adm:disconnect:"))
async def adm_disconnect(cb: CallbackQuery) -> None:
    if not _owner_only(cb.from_user.id):
        return
    user_id = int(cb.data.split(":")[2])
    from userbot.client import stop_client
    await stop_client(user_id)
    await db.delete_session(user_id)
    text, has_session = await _render_user_detail(user_id)
    await cb.message.edit_text(text, reply_markup=admin_user_kb(user_id, has_session))
    await cb.answer("✅ Аккаунт отключён", show_alert=True)


# ── Рассылка ──────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "adm:broadcast")
async def adm_broadcast_menu(cb: CallbackQuery) -> None:
    if not _owner_only(cb.from_user.id):
        return
    await cb.message.edit_text(
        "📢 <b>Рассылка</b>\n\nКому отправить сообщение?",
        reply_markup=admin_broadcast_kb(),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("adm:bc:confirm:"))
async def adm_bc_send(cb: CallbackQuery, state: FSMContext) -> None:
    if not _owner_only(cb.from_user.id):
        return
    target = cb.data.split(":")[3]
    data = await state.get_data()
    text = data.get("bc_text", "")
    await state.clear()

    user_ids = await db.admin_all_user_ids(None if target == "all" else target)
    from bot.client import bot
    sent, failed = 0, 0
    for uid in user_ids:
        try:
            await bot.send_message(uid, text)
            sent += 1
        except Exception:
            failed += 1
    await cb.message.edit_text(
        f"✅ <b>Рассылка завершена</b>\n\n"
        f"Отправлено: {sent}\nОшибок: {failed}",
        reply_markup=admin_main_kb(),
    )
    await cb.answer()


@router.callback_query(F.data.in_({"adm:bc:all", "adm:bc:premium", "adm:bc:trial", "adm:bc:free"}))
async def adm_bc_select_target(cb: CallbackQuery, state: FSMContext) -> None:
    if not _owner_only(cb.from_user.id):
        return
    target = cb.data.split(":")[2]
    labels = {"all": "всем", "premium": "Premium", "trial": "Trial", "free": "бесплатным"}
    await state.update_data(bc_target=target)
    await state.set_state(AdminState.waiting_broadcast_text)
    await cb.message.answer(
        f"📢 Введи текст для рассылки <b>{labels.get(target, target)}</b>:\n\n"
        "<i>(поддерживается HTML-форматирование)</i>",
        reply_markup=admin_cancel_kb(),
    )
    await cb.answer()


@router.message(AdminState.waiting_broadcast_text)
async def adm_bc_preview(msg: Message, state: FSMContext) -> None:
    if not _owner_only(msg.from_user.id):
        return
    data = await state.get_data()
    target = data.get("bc_target", "all")
    user_ids = await db.admin_all_user_ids(None if target == "all" else target)
    await state.update_data(bc_text=msg.text)
    await msg.answer(
        f"📢 <b>Предпросмотр рассылки</b> ({len(user_ids)} получателей):\n\n"
        f"{msg.text}\n\n"
        "Отправить?",
        reply_markup=admin_bc_confirm_kb(target),
    )


# ── Поиск по ID ───────────────────────────────────────────────────────────────

@router.callback_query(F.data == "adm:search")
async def adm_search_start(cb: CallbackQuery, state: FSMContext) -> None:
    if not _owner_only(cb.from_user.id):
        return
    await state.set_state(AdminState.waiting_search_id)
    await cb.message.answer("🔍 Введи user_id для поиска:", reply_markup=admin_cancel_kb())
    await cb.answer()


@router.message(AdminState.waiting_search_id)
async def adm_search_result(msg: Message, state: FSMContext) -> None:
    if not _owner_only(msg.from_user.id):
        return
    await state.clear()
    try:
        user_id = int(msg.text.strip())
    except ValueError:
        await msg.answer("user_id должен быть числом")
        return
    text, has_session = await _render_user_detail(user_id)
    await msg.answer(text, reply_markup=admin_user_kb(user_id, has_session))


# ── Промокоды ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "adm:promos")
async def adm_promos(cb: CallbackQuery) -> None:
    if not _owner_only(cb.from_user.id):
        return
    promos = await db.get_promos()
    text = "🎟 <b>Промокоды</b>\n\nНажми на промокод чтобы удалить."
    if not promos:
        text += "\n\n<i>(список пуст)</i>"
    await cb.message.edit_text(text, reply_markup=admin_promos_kb(promos))
    await cb.answer()


@router.callback_query(F.data.startswith("adm:promo:del:"))
async def adm_promo_delete(cb: CallbackQuery) -> None:
    if not _owner_only(cb.from_user.id):
        return
    code = cb.data.split(":", 3)[3]
    await db.delete_promo(code)
    promos = await db.get_promos()
    await cb.message.edit_text(
        "🎟 <b>Промокоды</b>\n\nНажми на промокод чтобы удалить.",
        reply_markup=admin_promos_kb(promos),
    )
    await cb.answer(f"✅ Промокод {code} удалён", show_alert=True)


@router.callback_query(F.data == "adm:cancel")
async def adm_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    if not _owner_only(cb.from_user.id):
        return
    await state.clear()
    await _show_dashboard(cb.message, edit=False)
    await cb.answer()


@router.callback_query(F.data == "adm:promo:create")
async def adm_promo_create_start(cb: CallbackQuery, state: FSMContext) -> None:
    if not _owner_only(cb.from_user.id):
        return
    await state.set_state(AdminState.waiting_promo_code)
    await cb.message.answer(
        "🎟 Введи текст промокода (только латиница/цифры, например <code>SUMMER25</code>):",
        reply_markup=admin_cancel_kb(),
    )
    await cb.answer()


@router.message(AdminState.waiting_promo_code)
async def adm_promo_code_input(msg: Message, state: FSMContext) -> None:
    if not _owner_only(msg.from_user.id):
        return
    code = msg.text.strip().upper()
    if not code.replace("_", "").replace("-", "").isalnum():
        await msg.answer("❌ Промокод должен содержать только буквы, цифры, - или _. Попробуй снова:")
        return
    await state.update_data(promo_code=code)
    await state.set_state(AdminState.waiting_promo_type)
    await msg.answer(f"✅ Код: <code>{code}</code>\n\nВыбери тип подписки:", reply_markup=promo_type_kb())


@router.callback_query(F.data.startswith("adm:promo:type:"), AdminState.waiting_promo_type)
async def adm_promo_type(cb: CallbackQuery, state: FSMContext) -> None:
    if not _owner_only(cb.from_user.id):
        return
    promo_type = cb.data.split(":")[3]
    await state.update_data(promo_type=promo_type)
    await state.set_state(AdminState.waiting_promo_months)
    type_label = "🌟 Premium Plus" if promo_type == "premium_plus" else "⭐ Premium"
    await cb.message.answer(f"Тип: <b>{type_label}</b>\n\nВыбери срок действия:", reply_markup=promo_months_kb())
    await cb.answer()


@router.callback_query(F.data.startswith("adm:promo:months:"), AdminState.waiting_promo_months)
async def adm_promo_months(cb: CallbackQuery, state: FSMContext) -> None:
    if not _owner_only(cb.from_user.id):
        return
    months = int(cb.data.split(":")[3])
    await state.update_data(promo_months=months)
    await state.set_state(AdminState.waiting_promo_uses)
    await cb.message.answer(
        f"Срок: <b>{months} мес.</b>\n\n"
        "Сколько раз можно использовать?\n"
        "Введи число (например <code>5</code>) или <code>0</code> для безлимита:",
        reply_markup=admin_cancel_kb(),
    )
    await cb.answer()


@router.message(AdminState.waiting_promo_uses)
async def adm_promo_uses(msg: Message, state: FSMContext) -> None:
    if not _owner_only(msg.from_user.id):
        return
    try:
        n = int(msg.text.strip())
        if n < 0:
            raise ValueError
    except ValueError:
        await msg.answer("❌ Введи целое число ≥ 0 (0 = безлимит):")
        return

    max_uses = 999 if n == 0 else n
    data = await state.get_data()
    code = data["promo_code"]
    months = data["promo_months"]
    promo_type = data.get("promo_type", "premium")
    await state.clear()

    await db.create_promo(code, months, max_uses, promo_type=promo_type)
    uses_label = "безлимит" if max_uses == 999 else str(max_uses)
    type_label = "🌟 Premium Plus" if promo_type == "premium_plus" else "⭐ Premium"
    await msg.answer(
        f"✅ <b>Промокод создан!</b>\n\n"
        f"Код: <code>{code}</code>\n"
        f"Тип: {type_label}\n"
        f"Срок: {months} мес.\n"
        f"Использований: {uses_label}",
        reply_markup=admin_main_kb(),
    )


# ── Дерево приглашений ────────────────────────────────────────────────────────

def _build_invite_tree_html(users: list[dict]) -> str:
    import time as _time
    now = int(_time.time())
    by_id = {u["user_id"]: u for u in users}
    children: dict[int, list[int]] = {}
    roots: list[int] = []

    for u in users:
        parent = u.get("invited_by")
        if parent and parent in by_id:
            children.setdefault(parent, []).append(u["user_id"])
        else:
            roots.append(u["user_id"])

    def node_status(u: dict) -> tuple[str, str]:
        pu = u.get("premium_until") or 0
        tu = u.get("trial_until") or 0
        if pu > now: return "premium", "⭐"
        if tu > now: return "trial", "🎁"
        return "free", "🆓"

    def count_all(uid: int) -> int:
        kids = children.get(uid, [])
        return len(kids) + sum(count_all(k) for k in kids)

    def render(uid: int) -> str:
        u = by_id.get(uid)
        if not u:
            return ""
        cls, icon = node_status(u)
        name = (u.get("display_name") or f"id{uid}").replace("<", "&lt;").replace(">", "&gt;")
        reg = datetime.fromtimestamp(u["created_at"]).strftime("%d.%m.%Y")
        kids = children.get(uid, [])
        direct = len(kids)
        total = count_all(uid)
        if direct > 0:
            invite_badge = f' <span class="badge">{direct} приг.' + (f' / {total} всего' if total != direct else '') + '</span>'
        else:
            invite_badge = ""
        sub = ""
        if kids:
            sub = "<ul class='tree'>" + "".join(f"<li>{render(c)}</li>" for c in kids) + "</ul>"
        return (
            f'<div class="node {cls}">'
            f'<span class="icon">{icon}</span>'
            f'<span class="name">{name}</span>'
            f'<span class="meta">id{uid} · {reg}</span>'
            f'{invite_badge}'
            f'</div>{sub}'
        )

    body = "<ul class='tree root'>" + "".join(f"<li>{render(uid)}</li>" for uid in roots) + "</ul>"
    total = len(users)
    ts = datetime.now().strftime("%d.%m.%Y %H:%M")

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>Дерево приглашений</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;
     background:#0d0d1a;color:#dde;padding:28px;min-height:100vh}}
h1{{color:#7b8cde;font-size:20px;margin-bottom:4px}}
.meta-header{{color:#666;font-size:13px;margin-bottom:20px}}
ul.tree{{list-style:none;padding-left:28px;border-left:2px solid #1e1e35;margin:4px 0}}
ul.root{{border-left:none;padding-left:0}}
ul.tree li{{margin:6px 0;padding-left:14px;position:relative}}
ul.tree li::before{{content:"";position:absolute;left:-2px;top:18px;
  width:14px;height:2px;background:#1e1e35}}
.node{{display:inline-flex;align-items:center;gap:8px;
       background:#14142b;border-radius:8px;padding:6px 14px;
       border-left:3px solid #333;max-width:420px}}
.node.premium{{border-left-color:#ffd700}}
.node.trial{{border-left-color:#4caf50}}
.node.free{{border-left-color:#444}}
.icon{{font-size:15px}}
.name{{font-weight:600;font-size:14px;color:#eef}}
.meta{{color:#777;font-size:12px;margin-left:4px}}
.badge{{background:#1e2a4a;color:#7b8cde;font-size:11px;padding:2px 8px;border-radius:12px;margin-left:8px;white-space:nowrap}}
</style>
</head>
<body>
<h1>🌳 Дерево приглашений</h1>
<div class="meta-header">Всего пользователей: {total} · Экспорт: {ts}</div>
{body}
</body>
</html>"""


@router.callback_query(F.data == "adm:invite_tree")
async def adm_invite_tree(cb: CallbackQuery) -> None:
    if not _owner_only(cb.from_user.id):
        return
    await cb.answer("Генерирую дерево...")

    users = await db.get_invite_tree()
    html = _build_invite_tree_html(users)

    from aiogram.types import BufferedInputFile
    file = BufferedInputFile(html.encode("utf-8"), filename="invite_tree.html")
    await cb.message.answer_document(
        file,
        caption=f"🌳 <b>Дерево приглашений</b>\nПользователей: {len(users)}\n\nОткрой в браузере.",
    )
