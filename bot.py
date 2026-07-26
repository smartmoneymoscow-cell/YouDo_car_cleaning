"""Combined server: Telegram webhook + FastAPI for Mini App."""

import os
import logging
from datetime import datetime, timedelta

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, Defaults,
)
from telegram.constants import ParseMode

from config import BOT_TOKEN, PORT
import database as db
from handlers import cmd_start, cmd_help, cmd_mybookings, cmd_cancel, cmd_admin, callback_handler, _schedule_reminder

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", level=logging.INFO)
logger = logging.getLogger("carwash")

# ── Build Telegram Application ────────────────────────────

ptb_app = (
    ApplicationBuilder()
    .token(BOT_TOKEN)
    .defaults(Defaults(parse_mode=ParseMode.HTML))
    .build()
)

ptb_app.add_handler(CommandHandler("start", cmd_start))
ptb_app.add_handler(CommandHandler("help", cmd_help))
ptb_app.add_handler(CommandHandler("mybookings", cmd_mybookings))
ptb_app.add_handler(CommandHandler("cancel", cmd_cancel))
ptb_app.add_handler(CommandHandler("admin", cmd_admin))
ptb_app.add_handler(CallbackQueryHandler(callback_handler))

# ── FastAPI app ───────────────────────────────────────────

from api import app as web_app  # noqa: E402 — import after db init


WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"


@web_app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    """Receive Telegram updates and process them."""
    data = await request.json()
    update = Update.de_json(data, ptb_app.bot)
    await ptb_app.process_update(update)
    return JSONResponse({"ok": True})


@web_app.on_event("startup")
async def on_startup():
    """Initialize DB, set webhook, restore reminders."""
    db.init_db()
    logger.info("Database initialized")

    await ptb_app.bot.initialize()
    await ptb_app.start()

    render_url = os.getenv("RENDER_EXTERNAL_URL", "")
    if render_url:
        webhook_url = f"{render_url}{WEBHOOK_PATH}"
        await ptb_app.bot.set_webhook(webhook_url, drop_pending_updates=True)
        logger.info(f"Webhook set: {webhook_url}")

    # Restore reminders
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT id, user_id, booking_date, slot_start, remind_before "
        "FROM bookings WHERE status='confirmed' AND remind_before > 0"
    ).fetchall()
    conn.close()
    restored = 0
    for r in rows:
        dt = datetime.strptime(f"{r['booking_date']} {r['slot_start']}", "%Y-%m-%d %H:%M")
        remind_at = dt - timedelta(minutes=r["remind_before"])
        if remind_at > datetime.now():
            _schedule_reminder(ptb_app, r["id"], r["user_id"],
                               r["booking_date"], r["slot_start"], r["remind_before"])
            restored += 1
    if restored:
        logger.info(f"Restored {restored} pending reminders")


@web_app.on_event("shutdown")
async def on_shutdown():
    await ptb_app.stop()
    await ptb_app.shutdown()


def main():
    import uvicorn
    logger.info(f"Starting server on port {PORT}")
    uvicorn.run(web_app, host="0.0.0.0", port=PORT, log_level="info")


if __name__ == "__main__":
    main()
