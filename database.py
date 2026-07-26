"""SQLite database layer."""

import sqlite3
from datetime import datetime, date, time, timedelta
from config import DB_PATH, DEFAULT_SERVICES, WORK_START_HOUR, WORK_END_HOUR, SLOT_DURATION_MIN


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create tables and seed default data."""
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS services (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            price       INTEGER NOT NULL,
            slots       INTEGER NOT NULL DEFAULT 1,
            active      INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS bookings (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER NOT NULL,
            user_name       TEXT NOT NULL DEFAULT '',
            service_id      INTEGER NOT NULL REFERENCES services(id),
            booking_date    TEXT NOT NULL,       -- YYYY-MM-DD
            slot_start      TEXT NOT NULL,        -- HH:MM
            slot_end        TEXT NOT NULL,        -- HH:MM
            status          TEXT NOT NULL DEFAULT 'confirmed',  -- confirmed / cancelled
            remind_before   INTEGER NOT NULL DEFAULT 0,  -- minutes before, 0 = no reminder
            created_at      TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_bookings_date_slot
            ON bookings(booking_date, slot_start, status);
        CREATE INDEX IF NOT EXISTS idx_bookings_user
            ON bookings(user_id, status);
    """)

    # Seed services if empty
    if conn.execute("SELECT count(*) FROM services").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO services (name, price, slots) VALUES (?, ?, ?)",
            DEFAULT_SERVICES,
        )

    # Migrate: add remind_before column if missing
    cols = {row[1] for row in conn.execute("PRAGMA table_info(bookings)").fetchall()}
    if "remind_before" not in cols:
        conn.execute("ALTER TABLE bookings ADD COLUMN remind_before INTEGER NOT NULL DEFAULT 0")

    conn.commit()
    conn.close()


# ── Services ──────────────────────────────────────────────

def get_services(active_only: bool = True) -> list[dict]:
    conn = get_conn()
    q = "SELECT * FROM services" + (" WHERE active=1" if active_only else "")
    rows = conn.execute(q).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_service(service_id: int) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM services WHERE id=?", (service_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def add_service(name: str, price: int, slots: int) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO services (name, price, slots) VALUES (?, ?, ?)",
        (name, price, slots),
    )
    conn.commit()
    conn.close()
    return cur.lastrowid


def toggle_service(service_id: int, active: bool):
    conn = get_conn()
    conn.execute("UPDATE services SET active=? WHERE id=?", (int(active), service_id))
    conn.commit()
    conn.close()


# ── Slots ─────────────────────────────────────────────────

def get_booked_slots(booking_date: str) -> list[dict]:
    """Return all confirmed bookings for a date."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT slot_start, slot_end, service_id FROM bookings "
        "WHERE booking_date=? AND status='confirmed'",
        (booking_date,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_available_slots(booking_date: str, service_id: int) -> list[str]:
    """Return list of available start times (HH:MM) for a given date + service."""
    service = get_service(service_id)
    if not service:
        return []

    needed = service["slots"]  # how many consecutive blocks needed
    needed_min = needed * SLOT_DURATION_MIN
    booked = get_booked_slots(booking_date)

    # Build occupied minute ranges
    occupied: set[int] = set()
    for b in booked:
        svc = get_service(b["service_id"])
        if not svc:
            continue
        start = _time_to_idx(b["slot_start"])
        for m in range(svc["slots"] * SLOT_DURATION_MIN):
            occupied.add(start + m)

    total_min = (WORK_END_HOUR - WORK_START_HOUR) * 60
    available = []
    for start in range(0, total_min - needed_min + 1, SLOT_DURATION_MIN):
        # Check if all needed minutes are free
        if all((start + m) not in occupied for m in range(needed_min)):
            available.append(_idx_to_time(start))

    return available


def _time_to_idx(hhmm: str) -> int:
    """Convert HH:MM to minute offset from work start."""
    h, m = map(int, hhmm.split(":"))
    return (h - WORK_START_HOUR) * 60 + m


def _idx_to_time(idx: int) -> str:
    """Convert minute offset from work start to HH:MM."""
    total_min = idx
    h = WORK_START_HOUR + total_min // 60
    m = total_min % 60
    return f"{h:02d}:{m:02d}"


def _slot_end_time(slot_start: str, slots: int) -> str:
    """Compute end time given start and number of SLOT_DURATION_MIN blocks."""
    h, m = map(int, slot_start.split(":"))
    total = h * 60 + m + slots * SLOT_DURATION_MIN
    return f"{total // 60:02d}:{total % 60:02d}"


# ── Bookings ──────────────────────────────────────────────

def create_booking(user_id: int, user_name: str, service_id: int,
                   booking_date: str, slot_start: str, remind_before: int = 0) -> int | None:
    """Create a booking. Returns booking id or None if slot was taken."""
    service = get_service(service_id)
    if not service:
        return None

    needed = service["slots"]
    slot_end = _slot_end_time(slot_start, needed)

    # Double-check availability
    available = get_available_slots(booking_date, service_id)
    if slot_start not in available:
        return None

    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO bookings (user_id, user_name, service_id, booking_date, slot_start, slot_end, remind_before) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, user_name, service_id, booking_date, slot_start, slot_end, remind_before),
    )
    conn.commit()
    booking_id = cur.lastrowid
    conn.close()
    return booking_id


def get_user_bookings(user_id: int) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT b.*, s.name as service_name, s.price "
        "FROM bookings b JOIN services s ON b.service_id=s.id "
        "WHERE b.user_id=? AND b.status='confirmed' "
        "ORDER BY b.booking_date, b.slot_start",
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def cancel_booking(booking_id: int, user_id: int) -> bool:
    conn = get_conn()
    cur = conn.execute(
        "UPDATE bookings SET status='cancelled' WHERE id=? AND user_id=? AND status='confirmed'",
        (booking_id, user_id),
    )
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


def get_all_bookings_for_date(booking_date: str) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT b.*, s.name as service_name, s.price "
        "FROM bookings b JOIN services s ON b.service_id=s.id "
        "WHERE b.booking_date=? AND b.status='confirmed' "
        "ORDER BY b.slot_start",
        (booking_date,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_reminder(booking_id: int, user_id: int, remind_before: int) -> bool:
    conn = get_conn()
    cur = conn.execute(
        "UPDATE bookings SET remind_before=? WHERE id=? AND user_id=? AND status='confirmed'",
        (remind_before, booking_id, user_id),
    )
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


def get_booking(booking_id: int) -> dict | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT b.*, s.name as service_name, s.price "
        "FROM bookings b JOIN services s ON b.service_id=s.id "
        "WHERE b.id=?",
        (booking_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_name(user_id: int) -> str:
    conn = get_conn()
    row = conn.execute(
        "SELECT user_name FROM bookings WHERE user_id=? ORDER BY id DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    conn.close()
    return row["user_name"] if row else ""
