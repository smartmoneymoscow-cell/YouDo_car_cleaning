"""Main entry point for Car Wash Telegram Bot."""

import os
import logging
from datetime import datetime, timedelta
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, Defaults,
)
from telegram.constants import ParseMode

from config import BOT_TOKEN, PORT
import database as db
from handlers import cmd_start, cmd_help, cmd_mybookings, cmd_cancel, cmd_admin, callback_handler, _schedule_reminder

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


def main():
    db.init_db()
    logger.info("Database initialized")

    mode = os.getenv("BOT_MODE", "webhook")  # webhook or polling
    render_url = os.getenv("RENDER_EXTERNAL_URL", "")  # auto-set by Render

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .defaults(Defaults(parse_mode=ParseMode.HTML))
        .post_init(post_init)
        .build()
    )

    # Register handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("mybookings", cmd_mybookings))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CallbackQueryHandler(callback_handler))

    if mode == "webhook" and render_url:
        webhook_path = f"/webhook/{BOT_TOKEN}"
        webhook_url = f"{render_url}{webhook_path}"
        logger.info(f"Starting webhook mode on port {PORT}")
        logger.info(f"Webhook URL: {webhook_url}")
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=webhook_path,
            webhook_url=webhook_url,
            drop_pending_updates=True,
        )
    else:
        logger.info("Starting polling mode")
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
