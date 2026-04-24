# browser_agent.py  — Windows-definitive fix
import asyncio
import re
import sys
import traceback
from typing import List
from travel_workflow import FlightOption, _minutes_to_str, _to_float


def _parse_ampm(time_str: str) -> str:
    """'2:35 PM' → '14:35'"""
    m = re.match(r'(\d{1,2}):(\d{2})\s*(AM|PM)', time_str.strip(), re.IGNORECASE)
    if not m:
        return "10:00"
    h, mins, ampm = int(m.group(1)), m.group(2), m.group(3).upper()
    if ampm == "PM" and h != 12:
        h += 12
    if ampm == "AM" and h == 12:
        h = 0
    return f"{h:02d}:{mins}"


# Regex to detect lines that start with a time (e.g. "12:55 AM", "06:50 PM+1")
TIME_PATTERN = re.compile(r'^\d{1,2}:\d{2}')

CARD_SELECTORS = [
    "[data-ved] li[jsname]",
    "ul.Rk10dc li",
    "[jscontroller] li[data-ved]",
    "div[jsname='IWWDBc']",
    "li[jscontroller]",
]


async def _scrape_async(
    origin_iata: str,
    dest_iata: str,
    dep_date: str,
    travel_class: str,
) -> List[FlightOption]:
    """
    Pure async Playwright scrape.
    Called via asyncio.run() inside a dedicated thread — this completely
    bypasses the sync_playwright greenlet/SelectorEventLoop problem on Windows.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("  ❌ Browser agent: playwright not installed — run: pip install playwright && playwright install chromium")
        return []

    results: List[FlightOption] = []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-extensions",
                ],
            )
            ctx = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
                locale="en-US",
                timezone_id="America/New_York",
                java_script_enabled=True,
            )

            await ctx.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'plugins',   { get: () => [1, 2, 3] });
                Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            """)

            page = await ctx.new_page()

            gf_url = (
                f"https://www.google.com/travel/flights?"
                f"q=flights+from+{origin_iata}+to+{dest_iata}+on+{dep_date}"
                f"&curr=USD&hl=en&gl=us"
            )
            print(f"  🌐 Browser agent: {origin_iata}→{dest_iata} | {dep_date}")

            try:
                await page.goto(gf_url, wait_until="domcontentloaded", timeout=30_000)
            except Exception as nav_err:
                print(f"  ❌ Browser agent: navigation failed — {nav_err}")
                await browser.close()
                return []

            await page.wait_for_timeout(4_000)

            # ── CAPTCHA / consent wall check ─────────────────────────────────
            page_text = await page.inner_text("body") or ""
            if any(kw in page_text.lower() for kw in [
                "captcha", "i'm not a robot", "unusual traffic",
                "consent", "before you continue",
            ]):
                print("  ❌ Browser agent: blocked by CAPTCHA or consent wall")
                await browser.close()
                return []

            # ── Try each selector until cards are found ───────────────────────
            cards = []
            for selector in CARD_SELECTORS:
                try:
                    found = await page.query_selector_all(selector)
                    if found:
                        cards = found
                        print(f"  🎯 Browser agent: '{selector}' → {len(found)} cards")
                        break
                except Exception:
                    continue

            if not cards:
                snippet = ""
                try:
                    snippet = (await page.content())[:1500]
                except Exception:
                    pass
                print("  ❌ Browser agent: 0 cards matched any selector")
                if snippet:
                    print(f"  📄 HTML snippet:\n{snippet}\n")
                await browser.close()
                return []

            # ── Parse cards ───────────────────────────────────────────────────
            for card in cards[:10]:
                try:
                    text = await card.inner_text()
                    if not text or len(text) < 10:
                        continue

                    lines = [l.strip() for l in text.split("\n") if l.strip()]

                    # Skip leading lines that look like times ("12:55 AM", "06:50 PM+1")
                    # or are too short / too long to be an airline name
                    airline = None
                    for line in lines:
                        if not TIME_PATTERN.match(line) and 2 < len(line) <= 40:
                            airline = line
                            break

                    if not airline:
                        continue

                    price_match = re.search(r"\$[\d,]+", text)
                    if not price_match:
                        continue
                    price_num = _to_float(price_match.group())
                    if price_num <= 0:
                        continue

                    dur_match = re.search(r"(\d+)\s*hr\s*(\d+)?\s*min", text, re.IGNORECASE)
                    if not dur_match:
                        continue
                    dur_minutes = int(dur_match.group(1)) * 60 + int(dur_match.group(2) or 0)

                    all_times = re.findall(r"(\d{1,2}:\d{2}\s*[AP]M)", text, re.IGNORECASE)
                    dep_time_raw = all_times[0] if all_times else "10:00 AM"
                    arr_time_raw = all_times[1] if len(all_times) > 1 else dep_time_raw

                    nonstop = "nonstop" in text.lower() or "non-stop" in text.lower()
                    stops   = 0 if nonstop else (1 if "1 stop" in text.lower() else 2)

                    # Try to extract a flight number (e.g. "6E204", "AI101")
                    flight_num_match = re.search(r'\b([A-Z]{2}\d{3,4})\b', text)
                    flight_number = flight_num_match.group(1) if flight_num_match else None

                    results.append(
                        FlightOption(
                            airline=airline,
                            flight_number=flight_number,
                            price=f"${int(price_num):,} USD",
                            departure_time=f"{dep_date}T{_parse_ampm(dep_time_raw)}",
                            arrival_time=f"{dep_date}T{_parse_ampm(arr_time_raw)}",
                            duration=_minutes_to_str(dur_minutes),
                            duration_minutes=dur_minutes,
                            stops=stops,
                            live_status="scraped",
                            cabin_class=travel_class.title(),
                            data_quality="scraped",
                        )
                    )
                except Exception as card_err:
                    print(f"  ⚠ Card parse error — {card_err}")
                    continue

            await browser.close()

    except Exception as e:
        print(f"  ❌ Browser agent error: {e}")
        traceback.print_exc()

    print(f"  Browser agent: {len(results)} flights scraped from Google Flights")
    return results


def _run_scrape_in_thread(
    origin_iata: str,
    dest_iata: str,
    dep_date: str,
    travel_class: str,
) -> List[FlightOption]:
    """
    Runs _scrape_async inside a BRAND NEW ProactorEventLoop (Windows) or
    SelectorEventLoop (Unix) that is completely isolated from FastAPI's loop.

    WHY THIS WORKS:
    ---------------
    asyncio.run() always creates a fresh event loop, sets it as current,
    runs the coroutine to completion, then closes it. On Windows we
    explicitly pass a ProactorEventLoop because that's the only loop type
    that supports subprocess creation (which Playwright needs to launch
    Chromium). This is called from run_in_executor so FastAPI's main loop
    is never touched.
    """
    if sys.platform == "win32":
        loop = asyncio.ProactorEventLoop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(
                _scrape_async(origin_iata, dest_iata, dep_date, travel_class)
            )
        finally:
            loop.close()
    else:
        # Unix: asyncio.run() is fine — SelectorEventLoop supports subprocesses
        return asyncio.run(
            _scrape_async(origin_iata, dest_iata, dep_date, travel_class)
        )


async def scrape_google_flights(
    origin_iata: str,
    dest_iata: str,
    dep_date: str,
    travel_class: str = "ECONOMY",
    adults: int = 1,
    route_key: str = "longhaul",
) -> List[FlightOption]:
    """
    Async entry-point called by the travel workflow orchestrator.
    Offloads the blocking Playwright work to a thread so FastAPI's
    event loop is never blocked.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        _run_scrape_in_thread,
        origin_iata,
        dest_iata,
        dep_date,
        travel_class,
    )