"""Configuration for Car Wash Bot."""

import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "8802071427:AAErTdX2p9O5Pkwx0_dqbxuf5gAcclwP9Gg")

# Comma-separated admin chat IDs
_admin_raw = os.getenv("ADMIN_IDS", "")
ADMIN_IDS: list[int] = [int(x.strip()) for x in _admin_raw.split(",") if x.strip().isdigit()]

# Working hours
WORK_START_HOUR = 8   # 08:00
WORK_END_HOUR = 20    # 20:00
SLOT_DURATION_MIN = 40  # minutes per slot

# How many days ahead can customers book
MAX_ADVANCE_DAYS = 30

# Database
DB_PATH = os.getenv("DB_PATH", "carwash.db")

# Webhook port (Render sets PORT automatically)
PORT = int(os.getenv("PORT", "8443"))

# Default services (name, price_rub, duration_slots)
DEFAULT_SERVICES = [
    ("Экспресс мойка",       500,  1),  # 40 min
    ("Комплексная мойка",   1000,  2),  # 80 min
    ("Химчистка салона",    2500,  3),  # 120 min
    ("Полировка кузова",    3000,  3),  # 120 min
    ("Защитное покрытие",   4000,  5),  # 200 min
    ("Мойка двигателя",     1500,  2),  # 80 min
]
