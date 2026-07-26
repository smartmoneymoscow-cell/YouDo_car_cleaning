"""Inline keyboards: calendar with pagination, services, time slots."""

from datetime import date, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import calendar


MONTHS_RU = [
    "", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]
WEEKDAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def calendar_keyboard(year: int, month: int) -> InlineKeyboardMarkup:
    """
    Build a calendar grid for the given month with prev/next pagination.
    Callback data format: cal|YYYY-MM-DD  (day pressed)
                          cal_nav|YYYY-MM  (prev/next month)
    """
    today = date.today()
    first = date(year, month, 1)
    # weekday of first day (Mon=0 … Sun=6)
    start_wd = first.weekday()
    num_days = calendar.monthrange(year, month)[1]

    rows: list[list[InlineKeyboardButton]] = []

    # Header: « Month Year »
    rows.append([
        InlineKeyboardButton("«", callback_data=f"cal_nav|{year}-{month - 1:02d}"),
        InlineKeyboardButton(f"{MONTHS_RU[month]} {year}", callback_data="cal_ignore"),
        InlineKeyboardButton("»", callback_data=f"cal_nav|{year}-{month + 1:02d}"),
    ])

    # Weekday labels
    rows.append([InlineKeyboardButton(w, callback_data="cal_ignore") for w in WEEKDAYS_RU])

    # Day grid
    row: list[InlineKeyboardButton] = []
    # Empty cells before first day
    for _ in range(start_wd):
        row.append(InlineKeyboardButton(" ", callback_data="cal_ignore"))

    for day in range(1, num_days + 1):
        d = date(year, month, day)
        if d < today:
            # Past days — non-clickable
            row.append(InlineKeyboardButton("·", callback_data="cal_ignore"))
        else:
            label = f"•{day}" if d == today else str(day)
            row.append(InlineKeyboardButton(label, callback_data=f"cal|{d.isoformat()}"))

        if len(row) == 7:
            rows.append(row)
            row = []

    if row:
        while len(row) < 7:
            row.append(InlineKeyboardButton(" ", callback_data="cal_ignore"))
        rows.append(row)

    return InlineKeyboardMarkup(rows)


def services_keyboard(services: list[dict]) -> InlineKeyboardMarkup:
    """List of services as buttons. Callback: svc|<id>"""
    rows = []
    for s in services:
        dur = s["slots"] * 30
        text = f"{s['name']}  —  {s['price']}₽  ({dur} мин)"
        rows.append([InlineKeyboardButton(text, callback_data=f"svc|{s['id']}")])
    return InlineKeyboardMarkup(rows)


def slots_keyboard(slots: list[str], booking_date: str, service_id: int) -> InlineKeyboardMarkup:
    """Available time slots. Callback: slot|<date>|<service_id>|<HH:MM>"""
    rows = []
    row = []
    for t in slots:
        row.append(InlineKeyboardButton(t, callback_data=f"slot|{booking_date}|{service_id}|{t}"))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    # Back button
    rows.append([InlineKeyboardButton("🔙 Назад", callback_data=f"back_to_cal|{service_id}")])
    return InlineKeyboardMarkup(rows)


def confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Подтвердить", callback_data="confirm|yes"),
            InlineKeyboardButton("❌ Отмена", callback_data="confirm|no"),
        ]
    ])


def my_bookings_keyboard(bookings: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for b in bookings:
        text = f"{b['booking_date']} {b['slot_start']} — {b['service_name']}"
        rows.append([InlineKeyboardButton(text, callback_data=f"mybk|{b['id']}")])
    rows.append([InlineKeyboardButton("🔙 Меню", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(rows)


def cancel_booking_keyboard(booking_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Да, отменить", callback_data=f"cancelbk|{booking_id}"),
            InlineKeyboardButton("🔙 Нет", callback_data="back_to_menu"),
        ]
    ])


def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Записи на сегодня", callback_data="admin|today")],
        [InlineKeyboardButton("📅 Записи на дату", callback_data="admin|pick_date")],
        [InlineKeyboardButton("🔧 Услуги", callback_data="admin|services")],
    ])
