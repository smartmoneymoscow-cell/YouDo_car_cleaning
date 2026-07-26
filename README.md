# 🚗 Car Wash Telegram Bot

Telegram bot for car wash appointment booking with calendar pagination, service selection, and time slot management.

## Features

- **Service selection** — choose from available car wash services
- **Calendar with pagination** — browse dates month by month
- **Time slot booking** — pick available time windows
- **Booking confirmation** — summary before finalizing
- **My bookings** — view and cancel your appointments
- **Admin panel** — manage services, slots, and view bookings

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Set your bot token:
```bash
export BOT_TOKEN="your-telegram-bot-token"
```

3. (Optional) Set admin chat IDs:
```bash
export ADMIN_IDS="123456789,987654321"
```

4. Run:
```bash
python bot.py
```

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Start booking |
| `/mybookings` | View your bookings |
| `/cancel` | Cancel a booking |
| `/admin` | Admin panel (admins only) |
| `/help` | Help message |

## Project Structure

```
carwash-bot/
├── bot.py              # Main bot entry point
├── database.py         # SQLite database layer
├── keyboards.py        # Inline keyboards (calendar, services, slots)
├── handlers.py         # Message & callback handlers
├── config.py           # Configuration
├── requirements.txt    # Python dependencies
└── README.md
```
