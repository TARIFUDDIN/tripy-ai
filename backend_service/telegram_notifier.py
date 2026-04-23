# telegram_notifier.py
import os
import httpx
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID")

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


async def send_telegram(message: str) -> bool:
    """Send a message to your Telegram chat. Returns True on success."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠ Telegram not configured — skipping notification")
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{TELEGRAM_API}/sendMessage",
                json={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": message,
                    "parse_mode": "HTML",   # lets you use <b>, <i> in messages
                }
            )
            resp.raise_for_status()
            print("✅ Telegram notification sent")
            return True
    except Exception as e:
        print(f"❌ Telegram error: {e}")
        return False


async def notify_itinerary(plan, flights, hotels, activities) -> None:
    """
    Format a concise itinerary summary and push it to Telegram.
    Called from TravelAgent.ainvoke() after search results are ready.
    """
    origin = plan.origin or "?"
    dest   = plan.destination

    lines = [
        f"✈️ <b>New itinerary: {origin} → {dest}</b>",
        f"📅 {plan.departure_date} → {plan.return_date}  |  {plan.adults} adult(s)",
    ]

    if plan.total_budget:
        lines.append(f"💰 Budget: ${plan.total_budget:,.0f}")

    if flights:
        f = flights[0]
        lines.append(f"\n<b>Best flight:</b> {f.airline}  {f.price}")
        lines.append(f"  Dep {f.departure_time[:16]}  →  Arr {f.arrival_time[:16]}")

    if hotels:
        h = hotels[0]
        lines.append(f"\n<b>Top hotel:</b> {h.name}  ({h.category})")
        lines.append(f"  {h.price_per_night} / night")

    if activities:
        top = activities[:3]
        lines.append(f"\n<b>Activities:</b> " + ", ".join(a.name for a in top))

    await send_telegram("\n".join(lines))