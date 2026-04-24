# telegram_notifier.py
import os
import httpx
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID")

FRONTEND_URL = "https://b397-2409-40e1-1000-b2b8-81dd-8f4-c592-ce6c.ngrok-free.app"

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


# ============================================================================
# CORE SENDER
# ============================================================================

async def send_telegram(message: str) -> bool:
    """Send a plain-text / HTML message to your Telegram chat."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠ Telegram not configured — skipping notification")
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{TELEGRAM_API}/sendMessage",
                json={
                    "chat_id":                  TELEGRAM_CHAT_ID,
                    "text":                     message,
                    "parse_mode":               "HTML",
                    "disable_web_page_preview": True,
                },
            )
            resp.raise_for_status()
            print("✅ Telegram notification sent")
            return True
    except Exception as e:
        print(f"❌ Telegram error: {e}")
        return False


# ============================================================================
# v2.3 — PDF TICKET PARSE NOTIFICATION
# ============================================================================

async def notify_booking_parsed(booking: dict, addons_catalog: list) -> None:
    """
    Fires after /ticket/parse succeeds.
    Shows passenger, route, suggested add-ons, and a deep-link to the booking page.
    """
    suggested_ids = booking.get("suggested_addons", [])
    suggested     = [a for a in addons_catalog if a["id"] in suggested_ids]

    lines = [
        f"✈️ <b>New ticket parsed — #{booking['id']}</b>",
        f"",
        f"👤 {booking.get('name', 'Unknown')}",
        f"🛫 {booking.get('flight_number', '—')}  |  PNR: <code>{booking.get('pnr', '—')}</code>",
        f"📍 {booking.get('origin_city', booking.get('origin', '?'))} → "
        f"{booking.get('destination_city', booking.get('destination', '?'))}",
        f"📅 {booking.get('departure_date', '—')}  {booking.get('departure_time', '')}".strip(),
        f"",
        f"━━━━━━━━━━━━━━━",
        f"🎁 <b>Recommended add-ons</b>",
        f"",
    ]

    total_comm = 0
    for a in suggested:
        reason = booking.get("suggested_addon_reasons", {}).get(a["id"], "")
        lines.append(
            f"{a['icon']} {a['name']} — ${a['price']}"
            f"  (+${a['commission']} commission)"
            + (f"\n   <i>{reason}</i>" if reason else "")
        )
        total_comm += a["commission"]

    booking_link = f"{FRONTEND_URL}/booking/{booking['id']}"

    lines += [
        f"",
        f"💰 You earn <b>${total_comm}</b> if all selected",
        f"",
        f"━━━━━━━━━━━━━━━",
        f'👉 <b><a href="{booking_link}">View booking &amp; upsell add-ons</a></b>',
    ]

    await send_telegram("\n".join(lines))


# ============================================================================
# LEGACY / CHATBOT — ITINERARY NOTIFICATION  (matches your existing format)
# ============================================================================

async def notify_itinerary(structured_data: dict, thread_id: str = "") -> None:
    """
    Fires after the chatbot agent returns a full itinerary.
    Reproduces the rich format your bot was already sending:

        ✈️ New itinerary: Mumbai → Tokyo
        📅 2026-06-20 → 2026-06-25  |  1 adult(s)
        Best flight: ANA  $661 USD
          Dep 2026-06-20T19:30  →  Arr 2026-06-21T04:10
        Top hotel: APA Hotel Shinjuku  (3-star)
          $85 USD / night
        Activities: teamLab Planets, Senso-ji Temple, ...

    Reads from the same structured_data dict your agent already produces.
    All fields are optional — missing ones are skipped cleanly.
    """

    # ── Route / dates ────────────────────────────────────────────────────────
    origin      = structured_data.get("origin")      or structured_data.get("from")        or "?"
    destination = structured_data.get("destination") or structured_data.get("to")          or "?"
    start_date  = structured_data.get("start_date")  or structured_data.get("depart_date") or ""
    end_date    = structured_data.get("end_date")    or structured_data.get("return_date")  or ""
    adults      = structured_data.get("adults")      or structured_data.get("passengers")  or 1

    lines = [f"✈️ <b>New itinerary: {origin} → {destination}</b>", ""]

    # Date / pax line
    date_str = f"{start_date} → {end_date}" if start_date and end_date else start_date or end_date or "—"
    lines.append(f"📅 {date_str}  |  {adults} adult(s)")
    lines.append("")

    # ── Best flight ──────────────────────────────────────────────────────────
    flight = (
        structured_data.get("best_flight")
        or structured_data.get("flight")
        or (structured_data.get("flights") or [None])[0]   # first item if list
    )
    if flight:
        airline   = flight.get("airline")   or flight.get("carrier")       or "—"
        price     = flight.get("price")     or flight.get("total_price")   or "—"
        currency  = flight.get("currency")                                  or "USD"
        dep_time  = flight.get("departure") or flight.get("depart_time")   or ""
        arr_time  = flight.get("arrival")   or flight.get("arrive_time")   or ""

        lines.append(f"Best flight: <b>{airline}</b>  ${price} {currency}")
        if dep_time or arr_time:
            lines.append(f"  Dep {dep_time}  →  Arr {arr_time}")
        lines.append("")

    # ── Top hotel ────────────────────────────────────────────────────────────
    hotel = (
        structured_data.get("top_hotel")
        or structured_data.get("hotel")
        or (structured_data.get("hotels") or [None])[0]
    )
    if hotel:
        hotel_name  = hotel.get("name")         or hotel.get("hotel_name")  or "—"
        stars       = hotel.get("stars")        or hotel.get("rating")      or ""
        night_price = hotel.get("price_per_night") or hotel.get("price")    or "—"
        currency    = hotel.get("currency")                                  or "USD"

        star_str = f"({stars}-star)" if stars else ""
        lines.append(f"Top hotel: <b>{hotel_name}</b>  {star_str}".strip())
        lines.append(f"  ${night_price} {currency} / night")
        lines.append("")

    # ── Activities ───────────────────────────────────────────────────────────
    activities = structured_data.get("activities") or structured_data.get("things_to_do") or []
    if activities:
        # Accept either a list of strings or a list of dicts with a "name" key
        act_names = [
            a if isinstance(a, str) else a.get("name") or a.get("title") or str(a)
            for a in activities
        ]
        lines.append(f"Activities: {', '.join(act_names)}")
        lines.append("")

    # ── Optional deep-link ───────────────────────────────────────────────────
    if thread_id:
        lines += [
            "━━━━━━━━━━━━━━━",
            f'👉 <b><a href="{FRONTEND_URL}/chat/{thread_id}">Open conversation</a></b>',
        ]

    await send_telegram("\n".join(lines))


# ============================================================================
# CHATBOT QUERY ROUTER  —  call this from run_agent_in_background
# ============================================================================

async def notify_chat_query(
    thread_id:       str,
    message:         str,
    reply:           str,
    structured_data: dict | None,
) -> None:
    """
    Entry point called from run_agent_in_background after the agent finishes.

    - If structured_data looks like a full itinerary  → notify_itinerary()
      (reproduces your existing rich format exactly)
    - If it looks like a hotel-only or flight-only search → simpler notify
    - Otherwise silently does nothing (no spam for unrelated messages)
    """
    sd = structured_data or {}

    # ── Case 1: full itinerary (flight + hotel both present) ─────────────────
    has_flight = bool(
        sd.get("best_flight") or sd.get("flight") or sd.get("flights")
    )
    has_hotel = bool(
        sd.get("top_hotel") or sd.get("hotel") or sd.get("hotels")
    )

    if has_flight or has_hotel:
        await notify_itinerary(sd, thread_id)   # ← only 2 args, not 4
        return

    # ── Case 2: destination-only query (no flights/hotels yet) ───────────────
    destination     = sd.get("destination") or sd.get("to")
    is_travel_query = any(k in message.lower() for k in [
        "travel", "trip", "visit", "destination", "go to",
        "holiday", "vacation", "tour", "explore", "flight", "hotel",
    ])

    if destination and is_travel_query:
        lines = [
            f"🗺️ <b>Destination query</b>",
            f"",
            f"📍 {destination}",
            f"💬 <i>{message[:140]}</i>",
            f"",
            f"━━━━━━━━━━━━━━━",
            f'👉 <b><a href="{FRONTEND_URL}/chat/{thread_id}">Open conversation</a></b>',
        ]
        await send_telegram("\n".join(lines))
        return

    # ── Case 3: nothing travel-related → skip silently ───────────────────────