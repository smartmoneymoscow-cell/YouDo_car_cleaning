"""Main entry point: Telegram bot (polling) + FastAPI web server."""

import os
import logging
import threading
from datetime import datetime, timedelta

import uvicorn
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, Defaults,
)
from telegram.constants import ParseMode

from config import BOT_TOKEN, PORT
import database as db
from handlers import cmd_start, cmd_help, cmd_mybookings, cmd_cancel, cmd_admin, callback_handler, _schedule_reminder
from api import app as web_app

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("carwash")


async def post_init(app):
    """Restore pending reminders after bot restart."""
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
            _schedule_reminder(app, r["id"], r["user_id"],
                               r["booking_date"], r["slot_start"], r["remind_before"])
            restored += 1
    if restored:
        logger.info(f"Restored {restored} pending reminders")


def run_bot():
    """Run Telegram bot in polling mode (background thread)."""
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .defaults(Defaults(parse_mode=ParseMode.HTML))
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("mybookings", cmd_mybookings))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CallbackQueryHandler(callback_handler))

    logger.info("Bot starting (polling mode)")
    app.run_polling(drop_pending_updates=True)


def main():
    db.init_db()
    logger.info("Database initialized")

    # Start bot polling in background thread
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()

    # Start FastAPI web server (main thread — Render health checks hit this)
    logger.info(f"Web server starting on port {PORT}")
    uvicorn.run(web_app, host="0.0.0.0", port=PORT, log_level="info")


if __name__ == "__main__":
    main()
