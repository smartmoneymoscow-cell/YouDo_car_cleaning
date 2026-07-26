"""Combined server: Telegram webhook + FastAPI for Mini App."""

import os
import logging
import asyncio
from datetime import datetime, timedelta

import httpx

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
    try:
        data = await request.json()
        update = Update.de_json(data, ptb_app.bot)
        await ptb_app.process_update(update)
    except Exception as e:
        logger.error(f"Error processing update: {e}", exc_info=True)
    return JSONResponse({"ok": True})


@web_app.on_event("startup")
async def on_startup():
    """Initialize DB, set webhook, restore reminders."""
    db.init_db()
    logger.info("Database initialized")

    await ptb_app.initialize()
    await ptb_app.start()

    # Auto-detect Render external URL
    render_url = os.getenv("RENDER_EXTERNAL_URL", "")
    if not render_url:
        # Fallback: construct from RENDER_EXTERNAL_HOSTNAME (always set on Render Web Services)
        hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME", "")
        if hostname:
            render_url = f"https://{hostname}"
            logger.info(f"Constructed URL from RENDER_EXTERNAL_HOSTNAME: {render_url}")

    if render_url:
        webhook_url = f"{render_url}{WEBHOOK_PATH}"
        await ptb_app.bot.set_webhook(webhook_url, drop_pending_updates=True)
        logger.info(f"Webhook set: {webhook_url}")
    else:
        logger.error(
            "Cannot set webhook: RENDER_EXTERNAL_URL and RENDER_EXTERNAL_HOSTNAME are both missing! "
            "Ensure this is deployed as a Render Web Service (not a Worker). "
            "Bot will NOT receive messages."
        )

    # Restore reminders
    try:
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
                _schedule_reminder(ptb_app.job_queue, r["id"], r["user_id"],
                                   r["booking_date"], r["slot_start"], r["remind_before"])
                restored += 1
        if restored:
            logger.info(f"Restored {restored} pending reminders")
    except Exception as e:
        logger.error(f"Failed to restore reminders: {e}")

    # Start keep-alive background task
    asyncio.create_task(_keep_alive())
    logger.info("Keep-alive task started (ping every 3 min)")


@web_app.on_event("shutdown")
async def on_shutdown():
    await ptb_app.stop()
    await ptb_app.shutdown()


# ── Keep-alive ping (Render free tier sleeps after 15 min idle) ──

async def _keep_alive():
    """Ping own URL every 3 min to prevent Render free tier from sleeping."""
    await asyncio.sleep(5)  # wait for server to fully start
    while True:
        try:
            render_url = os.getenv("RENDER_EXTERNAL_URL", "")
            if not render_url:
                hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME", "")
                if hostname:
                    render_url = f"https://{hostname}"
            if render_url:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(f"{render_url}/")
                    logger.info(f"Keep-alive ping: {resp.status_code}")
        except Exception as e:
            logger.warning(f"Keep-alive ping failed: {e}")
        await asyncio.sleep(180)  # every 3 minutes


def main():
    import uvicorn
    logger.info(f"Starting server on port {PORT}")
    uvicorn.run(web_app, host="0.0.0.0", port=PORT, log_level="info")


if __name__ == "__main__":
    main()
