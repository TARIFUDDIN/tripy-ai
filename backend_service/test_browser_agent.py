"""
test_browser_agent.py — standalone test for browser automation
Run: python test_browser_agent.py

Tests 3 things in order:
  1. Basic browser launch (Playwright works at all)
  2. Page navigation + screenshot (can reach a real URL)
  3. Google Flights scrape (actual flight data extraction)

Each test prints PASS / FAIL with reason so you know exactly where it breaks.
"""

import asyncio
import re
import os
from datetime import datetime, timedelta

# ─── ANSI colors for terminal output ─────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

def ok(msg):   print(f"  {GREEN}✅ PASS{RESET} — {msg}")
def fail(msg): print(f"  {RED}❌ FAIL{RESET} — {msg}")
def info(msg): print(f"  {CYAN}ℹ  {msg}{RESET}")
def head(msg): print(f"\n{BOLD}{YELLOW}{'─'*55}{RESET}\n{BOLD} {msg}{RESET}\n{BOLD}{YELLOW}{'─'*55}{RESET}")


# ─── TEST 1: Basic browser launch ────────────────────────────────────────────

async def test_1_launch():
    head("TEST 1 — Browser launch")
    from playwright.async_api import async_playwright
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            page = await browser.new_page()
            await page.set_content("<h1>Hello</h1>")
            title = await page.title()
            await browser.close()
        ok(f"Chromium launched and closed cleanly (page title: '{title}')")
        return True
    except Exception as e:
        fail(f"Browser launch failed: {e}")
        info("Fix: run  playwright install chromium")
        return False


# ─── TEST 2: Navigate to a real URL + take screenshot ────────────────────────

async def test_2_navigation():
    head("TEST 2 — Navigate to real URL")
    from playwright.async_api import async_playwright
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            ctx = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
            )
            page = await ctx.new_page()

            info("Navigating to example.com ...")
            await page.goto("https://example.com", wait_until="domcontentloaded", timeout=15000)
            title = await page.title()

            # Take a screenshot as proof
            screenshot_path = "/tmp/test_browser_screenshot.png"
            await page.screenshot(path=screenshot_path)

            await browser.close()

        ok(f"Navigated successfully — title: '{title}'")
        ok(f"Screenshot saved → {screenshot_path}")
        return True

    except Exception as e:
        fail(f"Navigation failed: {e}")
        info("Likely cause: no internet access in this environment")
        return False


# ─── TEST 3: Google Flights scrape ───────────────────────────────────────────

def _parse_ampm(time_str: str) -> str:
    m = re.match(r'(\d{1,2}):(\d{2})\s*(AM|PM)', time_str.strip(), re.IGNORECASE)
    if not m:
        return "10:00"
    h, mins, ampm = int(m.group(1)), m.group(2), m.group(3).upper()
    if ampm == "PM" and h != 12: h += 12
    if ampm == "AM" and h == 12: h = 0
    return f"{h:02d}:{mins}"


async def test_3_google_flights():
    head("TEST 3 — Google Flights scrape (BOM → DXB)")
    from playwright.async_api import async_playwright

    dep_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    origin, dest = "BOM", "DXB"

    info(f"Searching {origin} → {dest} on {dep_date}")
    info("This takes ~15 seconds (waiting for JS render)...")

    results = []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                ]
            )
            ctx = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 900},
                locale="en-US",
            )
            page = await ctx.new_page()

            # Simple query URL — works reliably across Google regions
            url = (
                f"https://www.google.com/travel/flights?"
                f"q=flights+from+{origin}+to+{dest}+on+{dep_date}"
                f"&curr=USD&hl=en&gl=us"
            )
            info(f"URL: {url}")

            await page.goto(url, wait_until="networkidle", timeout=40000)
            await page.wait_for_timeout(4000)   # wait for React/JS to render flights

            # Save debug screenshot
            await page.screenshot(path="/tmp/gf_debug.png", full_page=False)
            info("Debug screenshot → /tmp/gf_debug.png")

            # Get full page text — most reliable extraction method
            body_text = await page.inner_text("body")
            info(f"Page text length: {len(body_text)} chars")

            # ── Parse prices ──────────────────────────────────────────────
            prices = re.findall(r'\$[\d,]{2,6}', body_text)
            info(f"Prices found in page: {prices[:10]}")

            # ── Parse durations ───────────────────────────────────────────
            durations = re.findall(r'\d+\s*hr\s*\d*\s*min', body_text, re.IGNORECASE)
            info(f"Durations found: {durations[:6]}")

            # ── Parse airline names (known list) ──────────────────────────
            known_airlines = [
                "Air India", "IndiGo", "Emirates", "Flydubai", "SpiceJet",
                "Vistara", "Air Arabia", "Oman Air", "Etihad", "Qatar Airways",
                "GoFirst", "Akasa", "InterGlobe"
            ]
            found_airlines = [a for a in known_airlines if a.lower() in body_text.lower()]
            info(f"Airlines found: {found_airlines}")

            # ── Build results from what we found ─────────────────────────
            for i, (price, dur) in enumerate(zip(prices[:5], durations[:5])):
                price_num = float(price.replace("$", "").replace(",", ""))
                dur_match = re.match(r'(\d+)\s*hr\s*(\d*)\s*min', dur, re.IGNORECASE)
                if not dur_match:
                    continue
                dur_h = int(dur_match.group(1))
                dur_m = int(dur_match.group(2) or 0)
                dur_minutes = dur_h * 60 + dur_m

                # Sanity gate for BOM→DXB (max 6h)
                if dur_minutes > 360:
                    info(f"  Skipping {dur} — exceeds BOM→DXB max duration")
                    continue
                if price_num < 50 or price_num > 2000:
                    info(f"  Skipping ${price_num} — outside realistic range")
                    continue

                airline = found_airlines[i] if i < len(found_airlines) else "Unknown Airline"
                results.append({
                    "airline":   airline,
                    "price":     price,
                    "duration":  dur,
                    "dur_min":   dur_minutes,
                    "stops":     0,
                })

            await browser.close()

    except Exception as e:
        fail(f"Scrape failed: {e}")
        info("Check /tmp/gf_debug.png to see what the browser actually loaded")
        return False

    # ── Report results ────────────────────────────────────────────────────────
    if results:
        ok(f"Scraped {len(results)} flight(s):")
        for r in results:
            print(f"      ✈  {r['airline']:<20} {r['price']:<10} {r['duration']}")
        return True
    else:
        fail("No flights extracted from page")
        info("This is normal if Google blocked the headless browser or showed a CAPTCHA")
        info("Check /tmp/gf_debug.png — if it shows a CAPTCHA, use a different target site")
        info("Alternative targets: skyscanner.com, makemytrip.com (better for demo)")
        return False


# ─── TEST 4: MakeMyTrip as fallback target ───────────────────────────────────

async def test_4_makemytrip():
    head("TEST 4 — MakeMyTrip scrape (Mumbai → Dubai)")
    from playwright.async_api import async_playwright

    dep_date = (datetime.now() + timedelta(days=30)).strftime("%Y%m%d")
    info(f"Date param: {dep_date}")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            ctx = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1440, "height": 900},
            )
            page = await ctx.new_page()

            url = (
                f"https://www.makemytrip.com/flight/search?"
                f"itinerary=BOM-DXB-{dep_date}&tripType=O&paxType=A-1_C-0_I-0"
                f"&intl=true&cabinClass=E&lang=eng"
            )
            info(f"URL: {url}")
            await page.goto(url, wait_until="networkidle", timeout=40000)
            await page.wait_for_timeout(5000)

            await page.screenshot(path="/tmp/mmt_debug.png", full_page=False)
            info("Debug screenshot → /tmp/mmt_debug.png")

            body_text = await page.inner_text("body")
            info(f"Page text length: {len(body_text)} chars")

            prices    = re.findall(r'₹[\d,]+', body_text)
            durations = re.findall(r'\d+h\s*\d*m', body_text)
            info(f"Prices (INR): {prices[:6]}")
            info(f"Durations:    {durations[:6]}")

            await browser.close()

        if prices or durations:
            ok(f"MakeMyTrip loaded — found {len(prices)} prices, {len(durations)} durations")
            return True
        else:
            fail("No data extracted — site may require JS interaction or login")
            return False

    except Exception as e:
        fail(f"MakeMyTrip scrape failed: {e}")
        return False


# ─── RUNNER ──────────────────────────────────────────────────────────────────

async def main():
    print(f"\n{BOLD}{'='*55}")
    print(" Browser Automation Test Suite")
    print(f"{'='*55}{RESET}")

    results = {}

    results["launch"]     = await test_1_launch()
    results["navigation"] = await test_2_navigation()

    if results["navigation"]:
        results["google_flights"] = await test_3_google_flights()
        results["makemytrip"]     = await test_4_makemytrip()
    else:
        info("Skipping scrape tests — no internet access")
        results["google_flights"] = False
        results["makemytrip"]     = False

    # ── Summary ───────────────────────────────────────────────────────────────
    head("SUMMARY")
    for name, passed in results.items():
        status = f"{GREEN}PASS{RESET}" if passed else f"{RED}FAIL{RESET}"
        print(f"  {status}  {name}")

    passed_count = sum(results.values())
    total = len(results)
    print(f"\n  {BOLD}{passed_count}/{total} tests passed{RESET}")

    if results["launch"] and not results["navigation"]:
        print(f"\n  {YELLOW}Next step:{RESET} Browser works but no internet.")
        print(f"  Test on your local machine with: python test_browser_agent.py")

    if results["google_flights"]:
        print(f"\n  {GREEN}Browser agent is working!{RESET}")
        print(f"  You can now integrate browser_agent.py into search_flights()")
    elif results["launch"]:
        print(f"\n  {YELLOW}Browser works but scraping was blocked.")
        print(f"  Check screenshots: /tmp/gf_debug.png and /tmp/mmt_debug.png{RESET}")
        print(f"  If CAPTCHA shown → use Skyscanner or MakeMyTrip instead")


if __name__ == "__main__":
    asyncio.run(main())