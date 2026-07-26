"""FastAPI backend for Telegram Mini App."""

import hashlib
import hmac
import json
import os
from datetime import date, datetime
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import database as db
from config import BOT_TOKEN, SLOT_DURATION_MIN, WORK_START_HOUR, WORK_END_HOUR

app = FastAPI(title="Car Wash Mini App")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Telegram WebApp data validation ──────────────────────

def validate_init_data(init_data: str) -> dict | None:
    """Validate Telegram WebApp initData and return user dict."""
    try:
        parsed = {}
        for pair in init_data.split("&"):
            k, v = pair.split("=", 1)
            parsed[k] = unquote(v)

        data_check = parsed.pop("hash", "")
        sorted_str = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))

        secret = hmac.new("WebAppData".encode(), BOT_TOKEN.encode(), hashlib.sha256).digest()
        computed = hmac.new(secret, sorted_str.encode(), hashlib.sha256).hexdigest()

        if not hmac.compare_digest(computed, data_check):
            return None

        user = json.loads(parsed.get("user", "{}"))
        return user
    except Exception:
        return None


# ── Pydantic models ──────────────────────────────────────

class BookingRequest(BaseModel):
    init_data: str
    service_id: int
    booking_date: str
    slot_start: str
    remind_before: int = 0


class CancelRequest(BaseModel):
    init_data: str
    booking_id: int


class ReminderRequest(BaseModel):
    init_data: str
    booking_id: int
    remind_before: int


# ── Routes ───────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    return FileResponse("webapp/index.html")


@app.get("/api/services")
async def get_services():
    return db.get_services()


@app.get("/api/slots/{service_id}/{booking_date}")
async def get_slots(service_id: int, booking_date: str):
    # Validate date
    try:
        d = date.fromisoformat(booking_date)
    except ValueError:
        raise HTTPException(400, "Invalid date format")

    if d < date.today():
        raise HTTPException(400, "Date is in the past")

    slots = db.get_available_slots(booking_date, service_id)
    return {"date": booking_date, "service_id": service_id, "slots": slots}


@app.post("/api/book")
async def create_booking(req: BookingRequest):
    user = validate_init_data(req.init_data)
    if not user:
        raise HTTPException(401, "Invalid init data")

    user_id = user.get("id")
    user_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()

    # Validate date
    try:
        d = date.fromisoformat(req.booking_date)
    except ValueError:
        raise HTTPException(400, "Invalid date format")

    if d < date.today():
        raise HTTPException(400, "Date is in the past")

    booking_id = db.create_booking(
        user_id=user_id,
        user_name=user_name,
        service_id=req.service_id,
        booking_date=req.booking_date,
        slot_start=req.slot_start,
        remind_before=req.remind_before,
    )

    if not booking_id:
        raise HTTPException(409, "Slot already taken")

    return {"booking_id": booking_id, "status": "confirmed"}


@app.get("/api/mybookings")
async def get_my_bookings(init_data: str):
    user = validate_init_data(init_data)
    if not user:
        raise HTTPException(401, "Invalid init data")

    bookings = db.get_user_bookings(user.get("id"))
    return bookings


@app.post("/api/cancel")
async def cancel_booking(req: CancelRequest):
    user = validate_init_data(req.init_data)
    if not user:
        raise HTTPException(401, "Invalid init data")

    ok = db.cancel_booking(req.booking_id, user.get("id"))
    if not ok:
        raise HTTPException(404, "Booking not found")

    return {"status": "cancelled"}


@app.get("/api/config")
async def get_config():
    return {
        "slot_duration": SLOT_DURATION_MIN,
        "work_start": WORK_START_HOUR,
        "work_end": WORK_END_HOUR,
    }


@app.post("/api/set_reminder")
async def set_reminder(req: ReminderRequest):
    user = validate_init_data(req.init_data)
    if not user:
        raise HTTPException(401, "Invalid init data")

    ok = db.set_reminder(req.booking_id, user.get("id"), req.remind_before)
    if not ok:
        raise HTTPException(404, "Booking not found")

    return {"status": "ok"}
