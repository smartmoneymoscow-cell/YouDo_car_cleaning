"""Message and callback query handlers."""

from datetime import date, datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

import database as db
from config import ADMIN_IDS, MAX_ADVANCE_DAYS, SLOT_DURATION_MIN
from keyboards import (
    calendar_keyboard, services_keyboard, slots_keyboard,
    confirm_keyboard, reminder_keyboard, reminder_time_keyboard,
    my_bookings_keyboard, cancel_booking_keyboard,
    admin_keyboard,
)


# ── Reminder scheduler ────────────────────────────────────

def _schedule_reminder(context: ContextTypes.DEFAULT_TYPE, booking_id: int,
                       user_id: int, booking_date: str, slot_start: str, remind_before: int):
    """Schedule a reminder for a booking."""
    dt = datetime.strptime(f"{booking_date} {slot_start}", "%Y-%m-%d %H:%M")
    remind_at = dt - timedelta(minutes=remind_before)
    now = datetime.now()
    delay = (remind_at - now).total_seconds()
    if delay <= 0:
        return  # too late

    job_name = f"remind_{booking_id}"
    # Remove existing job with same name
    for job in context.job_queue.get_jobs_by_name(job_name):
        job.schedule_removal()

    async def _send_reminder(ctx: ContextTypes.DEFAULT_TYPE):
        svc = db.get_booking(booking_id)
        if not svc or svc["status"] != "confirmed":
            return
        text = (
            f"⏰ <b>Напоминание!</b>\n\n"
            f"🚿 {svc['service_name']}\n"
            f"📅 {svc['booking_date']}  🕐 {svc['slot_start']}–{svc['slot_end']}\n\n"
            f"До встречи через {remind_before} мин! 🚗"
        )
        await ctx.bot.send_message(chat_id=user_id, text=text, parse_mode=ParseMode.HTML)

    context.job_queue.run_once(_send_reminder, delay, name=job_name)


# ── Helper ────────────────────────────────────────────────

def _user_display(update: Update) -> str:
    u = update.effective_user
    parts = [u.first_name or "", u.last_name or ""]
    return " ".join(p for p in parts if p).strip() or u.username or str(u.id)


async def _edit_or_send(query, text: str, reply_markup=None, **kwargs):
    """Edit message if possible, otherwise send new."""
    try:
        await query.edit_message_text(text, reply_markup=reply_markup, **kwargs)
    except Exception:
        await query.message.reply_text(text, reply_markup=reply_markup, **kwargs)


# ── /start ────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    text = (
        "🚗 <b>Добро пожаловать в автомойку!</b>\n\n"
        "Выберите действие:"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Записаться", callback_data="new_booking")],
        [InlineKeyboardButton("📋 Мои записи", callback_data="show_my_bookings")],
        [InlineKeyboardButton("ℹ️ Помощь", callback_data="help")],
    ])
    if update.message:
        await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    elif update.callback_query:
        await _edit_or_send(update.callback_query, text, reply_markup=kb, parse_mode=ParseMode.HTML)


# ── /help ─────────────────────────────────────────────────

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "ℹ️ <b>Как записаться:</b>\n\n"
        "1️⃣ Нажмите «📝 Записаться» или /start\n"
        "2️⃣ Выберите услугу\n"
        "3️⃣ Выберите дату в календаре (можно листать месяцы)\n"
        "4️⃣ Выберите свободное время\n"
        "5️⃣ Подтвердите запись\n\n"
        "📋 /mybookings — мои записи\n"
        "❌ /cancel — отменить запись"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ── /mybookings ───────────────────────────────────────────

async def cmd_mybookings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _show_my_bookings(update.effective_user.id, update.message.reply_text)


async def _show_my_bookings(user_id: int, reply_fn):
    bookings = db.get_user_bookings(user_id)
    if not bookings:
        await reply_fn("У вас пока нет активных записей.")
        return

    text = "📋 <b>Ваши записи:</b>\n\n"
    for b in bookings:
        text += (
            f"📅 {b['booking_date']}  🕐 {b['slot_start']}–{b['slot_end']}\n"
            f"   🚿 {b['service_name']}  —  {b['price']}₽\n\n"
        )
    text += "Нажмите на запись, чтобы отменить:"
    await reply_fn(text, reply_markup=my_bookings_keyboard(bookings), parse_mode=ParseMode.HTML)


# ── /cancel ───────────────────────────────────────────────

async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _show_my_bookings(update.effective_user.id, update.message.reply_text)


# ── /admin ────────────────────────────────────────────────

async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Нет доступа.")
        return
    await update.message.reply_text("🔧 <b>Панель администратора</b>", reply_markup=admin_keyboard(), parse_mode=ParseMode.HTML)


# ── Callback router ───────────────────────────────────────

async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    uid = query.from_user.id

    # ── New booking flow ──────────────────────────────────
    if data == "new_booking":
        services = db.get_services()
        if not services:
            await _edit_or_send(query, "😕 Нет доступных услуг.")
            return
        ctx.user_data["flow"] = "booking"
        await _edit_or_send(
            query,
            "🚿 <b>Выберите услугу:</b>",
            reply_markup=services_keyboard(services),
            parse_mode=ParseMode.HTML,
        )

    elif data.startswith("svc|"):
        service_id = int(data.split("|")[1])
        svc = db.get_service(service_id)
        if not svc:
            await _edit_or_send(query, "Услуга не найдена.")
            return
        ctx.user_data["service_id"] = service_id
        today = date.today()
        await _edit_or_send(
            query,
            f"📅 <b>Выберите дату</b>  (услуга: {svc['name']})",
            reply_markup=calendar_keyboard(today.year, today.month, service_id),
            parse_mode=ParseMode.HTML,
        )

    elif data.startswith("cal_nav|"):
        _, ym = data.split("|")
        year, month = int(ym[:4]), int(ym[5:7])
        # Clamp to valid range
        today = date.today()
        if month < 1:
            year -= 1
            month = 12
        elif month > 12:
            year += 1
            month = 1
        # Don't go into the past
        if (year, month) < (today.year, today.month):
            year, month = today.year, today.month
        # Don't go too far ahead
        max_d = today + timedelta(days=MAX_ADVANCE_DAYS)
        if (year, month) > (max_d.year, max_d.month):
            year, month = max_d.year, max_d.month

        service_id = ctx.user_data.get("service_id")
        svc = db.get_service(service_id) if service_id else None
        label = svc["name"] if svc else "—"
        await _edit_or_send(
            query,
            f"📅 <b>Выберите дату</b>  (услуга: {label})",
            reply_markup=calendar_keyboard(year, month, service_id or 0),
            parse_mode=ParseMode.HTML,
        )

    elif data.startswith("cal|"):
        _, iso_date = data.split("|")
        d = date.fromisoformat(iso_date)
        service_id = ctx.user_data.get("service_id")
        if not service_id:
            await _edit_or_send(query, "⚠️ Сначала выберите услугу.")
            return

        svc = db.get_service(service_id)
        slots = db.get_available_slots(iso_date, service_id)
        if not slots:
            await _edit_or_send(
                query,
                f"😕 Нет свободных окон на {d.strftime('%d.%m.%Y')} для «{svc['name']}».\n"
                "Попробуйте другую дату.",
                reply_markup=calendar_keyboard(d.year, d.month),
            )
            return

        ctx.user_data["booking_date"] = iso_date
        wd = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][d.weekday()]
        await _edit_or_send(
            query,
            f"🕐 <b>Свободные окна</b>\n"
            f"{wd}, {d.strftime('%d.%m.%Y')}  •  {svc['name']} ({svc['slots'] * 30} мин)",
            reply_markup=slots_keyboard(slots, iso_date, service_id),
            parse_mode=ParseMode.HTML,
        )

    elif data.startswith("back_to_cal|"):
        service_id = int(data.split("|")[1])
        ctx.user_data["service_id"] = service_id
        today = date.today()
        svc = db.get_service(service_id)
        await _edit_or_send(
            query,
            f"📅 <b>Выберите дату</b>  (услуга: {svc['name']})",
            reply_markup=calendar_keyboard(today.year, today.month, service_id),
            parse_mode=ParseMode.HTML,
        )

    elif data.startswith("slot|"):
        _, iso_date, service_id_str, slot_time = data.split("|")
        service_id = int(service_id_str)
        svc = db.get_service(service_id)
        d = date.fromisoformat(iso_date)
        ctx.user_data["booking_date"] = iso_date
        ctx.user_data["service_id"] = service_id
        ctx.user_data["slot_start"] = slot_time

        # Compute end time
        slots_needed = svc["slots"]
        start_h, start_m = map(int, slot_time.split(":"))
        total_end = start_h * 60 + start_m + slots_needed * SLOT_DURATION_MIN
        end_h, end_m = divmod(total_end, 60)
        slot_end = f"{end_h:02d}:{end_m:02d}"

        wd = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][d.weekday()]
        text = (
            f"📋 <b>Подтвердите запись:</b>\n\n"
            f"🚿 Услуга: <b>{svc['name']}</b>\n"
            f"📅 Дата: <b>{wd}, {d.strftime('%d.%m.%Y')}</b>\n"
            f"🕐 Время: <b>{slot_time} – {slot_end}</b>\n"
            f"💰 Стоимость: <b>{svc['price']} ₽</b>\n"
        )
        await _edit_or_send(query, text, reply_markup=confirm_keyboard(service_id, iso_date), parse_mode=ParseMode.HTML)

    elif data == "confirm|yes":
        service_id = ctx.user_data.get("service_id")
        booking_date = ctx.user_data.get("booking_date")
        slot_start = ctx.user_data.get("slot_start")
        if not all([service_id, booking_date, slot_start]):
            await _edit_or_send(query, "⚠️ Данные сессии устарели. Начните заново: /start")
            return

        booking_id = db.create_booking(
            user_id=uid,
            user_name=_user_display(update),
            service_id=service_id,
            booking_date=booking_date,
            slot_start=slot_start,
        )
        if not booking_id:
            await _edit_or_send(query, "❌ К сожалению, это время уже занято. Попробуйте выбрать другое.")
            return

        # Save booking_id for reminder flow
        ctx.user_data["last_booking_id"] = booking_id
        svc = db.get_service(service_id)
        d = date.fromisoformat(booking_date)
        slots_needed = svc["slots"]
        sh, sm = map(int, slot_start.split(":"))
        te = sh * 60 + sm + slots_needed * SLOT_DURATION_MIN
        eh, em = divmod(te, 60)

        # Ask about reminder
        text = (
            f"✅ <b>Запись подтверждена!</b>\n\n"
            f"🚿 {svc['name']}\n"
            f"📅 {d.strftime('%d.%m.%Y')}  🕐 {slot_start}–{eh:02d}:{em:02d}\n"
            f"💰 {svc['price']} ₽\n"
            f"Номер записи: <b>#{booking_id}</b>\n\n"
            f"⏰ Хотите получить напоминание перед мойкой?"
        )
        await _edit_or_send(query, text, reply_markup=reminder_keyboard(booking_id), parse_mode=ParseMode.HTML)

    # ── Reminder flow ──────────────────────────────────────
    elif data.startswith("remind|"):
        parts = data.split("|")
        booking_id = int(parts[1])
        action = parts[2]

        def _booking_summary(bk: dict, remind_label: str = "") -> str:
            d = date.fromisoformat(bk["booking_date"])
            wd = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][d.weekday()]
            text = (
                f"✅ <b>Вы успешно записаны на мойку!</b>\n\n"
                f"🆔 Номер записи: <b>#{bk['id']}</b>\n"
                f"🚿 Услуга: <b>{bk['service_name']}</b>\n"
                f"📅 Дата: <b>{wd}, {d.strftime('%d.%m.%Y')}</b>\n"
                f"🕐 Время: <b>{bk['slot_start']} – {bk['slot_end']}</b>\n"
                f"💰 Стоимость: <b>{bk['price']} ₽</b>\n"
            )
            if remind_label:
                text += f"⏰ Напоминание: за <b>{remind_label}</b>\n"
            text += "\nДо встречи! 🚗"
            return text

        if action == "no":
            bk = db.get_booking(booking_id)
            if bk:
                text = _booking_summary(bk)
            else:
                text = "✅ Запись оформлена. До встречи! 🚗"
            ctx.user_data.clear()
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Меню", callback_data="back_to_menu")]])
            await _edit_or_send(query, text, reply_markup=kb, parse_mode=ParseMode.HTML)

        elif action == "ask":
            await _edit_or_send(query, "⏰ <b>За сколько напомнить?</b>", reply_markup=reminder_time_keyboard(booking_id), parse_mode=ParseMode.HTML)

        elif action.isdigit():
            remind_before = int(action)
            db.set_reminder(booking_id, uid, remind_before)

            bk = db.get_booking(booking_id)
            if bk:
                _schedule_reminder(ctx, booking_id, uid,
                                   bk["booking_date"], bk["slot_start"], remind_before)

            label = {30: "30 минут", 60: "1 час", 120: "2 часа", 1440: "день"}.get(remind_before, f"{remind_before} мин")
            if bk:
                text = _booking_summary(bk, remind_label=label)
            else:
                text = f"✅ Напоминание установлено за <b>{label}</b>. До встречи! 🚗"
            ctx.user_data.clear()
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Меню", callback_data="back_to_menu")]])
            await _edit_or_send(query, text, reply_markup=kb, parse_mode=ParseMode.HTML)

    elif data == "confirm|no":
        ctx.user_data.clear()
        await cmd_start(update, ctx)

    # ── Back buttons ──────────────────────────────────────
    elif data == "back_to_services":
        services = db.get_services()
        await _edit_or_send(
            query,
            "🚿 <b>Выберите услугу:</b>",
            reply_markup=services_keyboard(services),
            parse_mode=ParseMode.HTML,
        )

    elif data.startswith("back_to_slots|"):
        _, service_id_str, booking_date = data.split("|")
        service_id = int(service_id_str)
        svc = db.get_service(service_id)
        slots = db.get_available_slots(booking_date, service_id)
        if not slots:
            await _edit_or_send(query, "😕 Нет свободных окон на эту дату.")
            return
        d = date.fromisoformat(booking_date)
        wd = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][d.weekday()]
        await _edit_or_send(
            query,
            f"🕐 <b>Свободные окна</b>\n"
            f"{wd}, {d.strftime('%d.%m.%Y')}  •  {svc['name']} ({svc['slots'] * SLOT_DURATION_MIN} мин)",
            reply_markup=slots_keyboard(slots, booking_date, service_id),
            parse_mode=ParseMode.HTML,
        )

    # ── My bookings ───────────────────────────────────────
    elif data == "show_my_bookings":
        bookings = db.get_user_bookings(uid)
        if not bookings:
            await _edit_or_send(query, "У вас пока нет активных записей.")
            return
        text = "📋 <b>Ваши записи:</b>\n\n"
        for b in bookings:
            text += (
                f"📅 {b['booking_date']}  🕐 {b['slot_start']}–{b['slot_end']}\n"
                f"   🚿 {b['service_name']}  —  {b['price']}₽\n\n"
            )
        text += "Нажмите на запись, чтобы отменить:"
        await _edit_or_send(query, text, reply_markup=my_bookings_keyboard(bookings), parse_mode=ParseMode.HTML)

    elif data.startswith("mybk|"):
        booking_id = int(data.split("|")[1])
        await _edit_or_send(
            query,
            "❓ Вы уверены, что хотите отменить эту запись?",
            reply_markup=cancel_booking_keyboard(booking_id),
        )

    elif data.startswith("cancelbk|"):
        booking_id = int(data.split("|")[1])
        ok = db.cancel_booking(booking_id, uid)
        if ok:
            text = "✅ Запись отменена."
        else:
            text = "⚠️ Не удалось отменить запись."
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Меню", callback_data="back_to_menu")]])
        await _edit_or_send(query, text, reply_markup=kb)

    elif data == "back_to_menu":
        ctx.user_data.clear()
        await cmd_start(update, ctx)

    elif data == "help":
        text = (
            "ℹ️ <b>Как записаться:</b>\n\n"
            "1️⃣ Нажмите «📝 Записаться»\n"
            "2️⃣ Выберите услугу\n"
            "3️⃣ Выберите дату в календаре\n"
            "4️⃣ Выберите свободное время\n"
            "5️⃣ Подтвердите запись\n\n"
            "📋 /mybookings — мои записи\n"
            "❌ /cancel — отменить запись"
        )
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Меню", callback_data="back_to_menu")]])
        await _edit_or_send(query, text, reply_markup=kb, parse_mode=ParseMode.HTML)

    # ── Admin ─────────────────────────────────────────────
    elif data.startswith("admin|"):
        if uid not in ADMIN_IDS:
            await _edit_or_send(query, "⛔ Нет доступа.")
            return

        action = data.split("|")[1]

        if action == "today":
            today_str = date.today().isoformat()
            bookings = db.get_all_bookings_for_date(today_str)
            if not bookings:
                text = f"📋 Записи на {date.today().strftime('%d.%m.%Y')}: нет записей"
            else:
                text = f"📋 <b>Записи на {date.today().strftime('%d.%m.%Y')}:</b>\n\n"
                for b in bookings:
                    text += (
                        f"🕐 {b['slot_start']}–{b['slot_end']}  "
                        f"👤 {b['user_name']} (id:{b['user_id']})\n"
                        f"   🚿 {b['service_name']}  💰 {b['price']}₽\n\n"
                    )
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="admin_back")]])
            await _edit_or_send(query, text, reply_markup=kb, parse_mode=ParseMode.HTML)

        elif action == "pick_date":
            today = date.today()
            await _edit_or_send(
                query,
                "📅 Выберите дату для просмотра записей:",
                reply_markup=calendar_keyboard(today.year, today.month),
            )
            ctx.user_data["admin_flow"] = True

        elif action == "services":
            services = db.get_services(active_only=False)
            text = "🔧 <b>Услуги:</b>\n\n"
            for s in services:
                status = "✅" if s["active"] else "❌"
                text += f"{status} #{s['id']} {s['name']} — {s['price']}₽ ({s['slots'] * 30} мин)\n"
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="admin_back")]])
            await _edit_or_send(query, text, reply_markup=kb, parse_mode=ParseMode.HTML)

    elif data == "admin_back":
        if uid not in ADMIN_IDS:
            return
        await _edit_or_send(query, "🔧 <b>Панель администратора</b>", reply_markup=admin_keyboard(), parse_mode=ParseMode.HTML)

    elif data == "cal_ignore":
        pass  # non-clickable calendar cell

    else:
        # If admin is picking a date for viewing bookings
        if ctx.user_data.get("admin_flow") and data.startswith("cal|"):
            if uid not in ADMIN_IDS:
                return
            _, iso_date = data.split("|")
            bookings = db.get_all_bookings_for_date(iso_date)
            d = date.fromisoformat(iso_date)
            if not bookings:
                text = f"📋 Записи на {d.strftime('%d.%m.%Y')}: нет записей"
            else:
                text = f"📋 <b>Записи на {d.strftime('%d.%m.%Y')}:</b>\n\n"
                for b in bookings:
                    text += (
                        f"🕐 {b['slot_start']}–{b['slot_end']}  "
                        f"👤 {b['user_name']} (id:{b['user_id']})\n"
                        f"   🚿 {b['service_name']}  💰 {b['price']}₽\n\n"
                    )
            ctx.user_data.pop("admin_flow", None)
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="admin_back")]])
            await _edit_or_send(query, text, reply_markup=kb, parse_mode=ParseMode.HTML)
