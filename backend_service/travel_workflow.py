"""
travel_agent.py — v6 (client-showcase hardened)

FIXES vs v5:
  1.  DURATION SANITY GATE: Per-route MAX duration enforced. Mumbai→Dubai 26h flight? Blocked.
  2.  CHEAPEST vs BEST-VALUE: User says "cheapest"/"budget"/"cheap" → pure price rank.
      Other intents → value score. Recommendation always matches the shown "recommended" flight.
  3.  SERPAPI PRICE OUTLIER FILTER: Prices >3x route median OR >$3000 economy → flagged/dropped.
  4.  NATURAL DATE PARSER: "next weekend", "this Saturday", "next Friday" all resolve correctly.
  5.  MISSING FIELD GUARD: Any SerpAPI result missing price/duration/departure → silently skipped.
  6.  STOPS INTEGRITY: SerpAPI stops count = len(legs)-1. Never trust stops field directly.
  7.  RECOMMENDATION ALIGNMENT: narrative always references the flight marked is_best_value=True.
  8.  CLIENT LABELS: flight.data_quality = "live" | "estimated" | "filtered". UI can trust this.
  9.  ROUTE MAX DURATION TABLE: Hard caps per route type — impossible outliers never shown.
  10. FALLBACK GUARANTEE: 3 results minimum always. Partial SerpAPI → merge with mock.
"""

import os, re, json, asyncio, random, math, time
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from langchain_core.messages import AIMessage, HumanMessage
import httpx
# travel_agent.py — add these 3 lines at the very top, before any imports
import sys
if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

GROQ_API_KEY       = os.getenv("GROQ_API_KEY")
GOOGLE_API_KEY     = os.getenv("GOOGLE_API_KEY")
AMADEUS_API_KEY    = os.getenv("AMADEUS_API_KEY")
AMADEUS_API_SECRET = os.getenv("AMADEUS_API_SECRET")
SERPAPI_KEY        = os.getenv("SERPAPI_KEY", "")
MAKCORPS_USERNAME  = os.getenv("MAKCORPS_USERNAME", "")
MAKCORPS_PASSWORD  = os.getenv("MAKCORPS_PASSWORD", "")
MAKCORPS_API_KEY   = os.getenv("MAKCORPS_API_KEY", "")
DEMO_MODE          = os.getenv("DEMO_MODE", "false").lower() == "true"

print(f"🔧 Config: DEMO_MODE={DEMO_MODE} | Groq={'✅' if GROQ_API_KEY else '❌'} | "
      f"SerpAPI={'✅' if SERPAPI_KEY else '❌'} | "
      f"Makcorps={'✅' if MAKCORPS_USERNAME else '❌'} | "
      f"Amadeus={'✅' if AMADEUS_API_KEY else '❌'}")

amadeus = None
try:
    from amadeus import Client, ResponseError
    if AMADEUS_API_KEY and AMADEUS_API_SECRET:
        amadeus = Client(client_id=AMADEUS_API_KEY, client_secret=AMADEUS_API_SECRET, hostname='test')
        print("✅ Amadeus client initialized")
except Exception as e:
    print(f"⚠️  Amadeus init: {e}")
    ResponseError = Exception


# ─────────────────────────────────────────────────────────────────────────────
# DATA MODELS
# ─────────────────────────────────────────────────────────────────────────────

class FlightOption(BaseModel):
    airline: str
    flight_number: Optional[str] = None
    price: str
    departure_time: str
    arrival_time: str
    duration: Optional[str] = None
    duration_minutes: int = 0
    stops: int = 0
    live_status: Optional[str] = None
    terminal: Optional[str] = None
    gate: Optional[str] = None
    delay_minutes: Optional[int] = None
    cabin_class: Optional[str] = None
    airline_logo: Optional[str] = None
    airplane: Optional[str] = None
    legroom: Optional[str] = None
    carbon_kg: Optional[int] = None
    data_quality: str = "estimated"   # "live" | "estimated" | "mock"

class HotelOption(BaseModel):
    name: str
    category: str
    price_per_night: str
    source: str
    rating: Optional[float] = None
    amenities: Optional[str] = None
    hotel_id: Optional[str] = None
    vendors: Optional[List[Dict]] = None
    area: Optional[str] = None

class ActivityOption(BaseModel):
    name: str
    description: str
    price: str
    location: Optional[str] = None
    duration: Optional[str] = None

class TravelPlan(BaseModel):
    origin: Optional[str] = None
    destination: str
    departure_date: Optional[str] = None
    return_date: Optional[str] = None
    duration_days: Optional[int] = None
    adults: int = 1
    travel_class: Optional[str] = "ECONOMY"
    total_budget: Optional[float] = None
    user_intent: str = "full_plan"
    price_priority: str = "balanced"   # "cheapest" | "balanced" | "best"


# ─────────────────────────────────────────────────────────────────────────────
# ── FIX #4: NATURAL LANGUAGE DATE PARSER ─────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

def _parse_natural_date(text: str, reference: datetime) -> Optional[str]:
    """
    Parse natural language dates like 'next weekend', 'this Saturday',
    'next Friday', 'tomorrow', 'in 2 weeks'.
    Returns YYYY-MM-DD string or None.
    """
    t = text.lower().strip()
    today = reference.date()

    if t in ("today",):
        return str(today + timedelta(days=1))  # can't fly today realistically

    if t in ("tomorrow",):
        return str(today + timedelta(days=1))

    # "next weekend" → coming Saturday
    if "next weekend" in t or "this weekend" in t:
        days_until_sat = (5 - today.weekday()) % 7
        if days_until_sat == 0:
            days_until_sat = 7
        return str(today + timedelta(days=days_until_sat))

    # "next Saturday", "this Friday" etc.
    day_map = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6,
    }
    for day_name, day_num in day_map.items():
        if day_name in t:
            prefix_next = "next " + day_name in t
            days_ahead = (day_num - today.weekday()) % 7
            if days_ahead == 0 or prefix_next:
                days_ahead += 7
            return str(today + timedelta(days=days_ahead))

    # "in X days/weeks"
    m = re.search(r'in\s+(\d+)\s+(day|week)', t)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        delta = timedelta(days=n) if unit == "day" else timedelta(weeks=n)
        return str(today + delta)

    return None


# ─────────────────────────────────────────────────────────────────────────────
# CORE MATH HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _to_float(price_str: str) -> float:
    if not price_str:
        return 0.0
    s = str(price_str)
    range_match = re.search(r'(\d[\d,]*)\s*[–\-]\s*(\d[\d,]*)', s)
    if range_match:
        lo = float(range_match.group(1).replace(',', ''))
        hi = float(range_match.group(2).replace(',', ''))
        return (lo + hi) / 2.0
    cleaned = re.sub(r'[^0-9.]', '', s.replace(',', ''))
    try:
        return float(cleaned) if cleaned else 0.0
    except ValueError:
        return 0.0


def _minutes_to_str(minutes: int) -> str:
    minutes = max(0, int(minutes))
    h, m = divmod(minutes, 60)
    return f"{h}h {m:02d}m"


def _str_to_minutes(duration_str: str) -> int:
    if not duration_str:
        return 9999
    m1 = re.match(r'(\d+)h\s*(\d+)m', str(duration_str))
    if m1:
        return int(m1.group(1)) * 60 + int(m1.group(2))
    m2 = re.match(r'(\d+)h', str(duration_str))
    if m2:
        return int(m2.group(1)) * 60
    m3 = re.match(r'(\d+)m', str(duration_str))
    if m3:
        return int(m3.group(1))
    return 9999


def _arrival_from_dep_and_duration(dep_iso: str, duration_minutes: int) -> str:
    dep_dt = datetime.fromisoformat(dep_iso.replace("Z", ""))
    arr_dt = dep_dt + timedelta(minutes=int(duration_minutes))
    return arr_dt.strftime("%Y-%m-%dT%H:%M:00")


def _hhmm(iso_str: str) -> str:
    try:
        return datetime.fromisoformat(iso_str.replace("Z", "")).strftime("%H:%M")
    except Exception:
        m = re.search(r'(\d{2}:\d{2})', str(iso_str))
        return m.group(1) if m else iso_str


def _fn_key(flight_number: str) -> str:
    return re.sub(r'[\s\-]', '', str(flight_number or '')).upper()


def _dep_bucket(dep_iso: str) -> str:
    try:
        dt = datetime.fromisoformat(dep_iso.replace("Z", ""))
        bucket_min = (dt.minute // 15) * 15
        return f"{dt.date()}T{dt.hour:02d}:{bucket_min:02d}"
    except Exception:
        return dep_iso[:16]


def _day_offset(dep_iso: str, arr_iso: str) -> int:
    try:
        dep = datetime.fromisoformat(dep_iso.replace("Z", ""))
        arr = datetime.fromisoformat(arr_iso.replace("Z", ""))
        return (arr.date() - dep.date()).days
    except Exception:
        return 0


def _carbon_estimate_kg(duration_minutes: int, cabin_class: str) -> int:
    hours = duration_minutes / 60.0
    base_kg_per_hour = 90 if hours <= 6 else 70
    multiplier = {"ECONOMY": 1.0, "PREMIUM_ECONOMY": 1.6, "BUSINESS": 2.9, "FIRST": 4.0}
    mult = multiplier.get((cabin_class or "ECONOMY").upper(), 1.0)
    return max(10, int(hours * base_kg_per_hour * mult))


# ─────────────────────────────────────────────────────────────────────────────
# ── FIX #1: ROUTE MAX DURATION TABLE ─────────────────────────────────────────
# Any flight exceeding these limits is garbage data and gets blocked.
# ─────────────────────────────────────────────────────────────────────────────

ROUTE_MAX_DURATION_MINUTES: Dict[str, int] = {
    "india_dom":  240,    # 4h max for any Indian domestic
    "india_me":   360,    # 6h max India↔Middle East (direct ~4h, max 1-stop)
    "india_sea":  600,    # 10h max India↔SE Asia
    "india_ea":   900,    # 15h max India↔East Asia
    "india_eu":   960,    # 16h max India↔Europe
    "india_us":  1440,    # 24h max India↔USA
    "sea_sea":    360,    # 6h max within SE Asia
    "me_eu":      600,    # 10h max ME↔Europe
    "me_us":      960,    # 16h max ME↔USA
    "eu_eu":      300,    # 5h max within Europe
    "transatl":   720,    # 12h max transatlantic
    "us_dom":     480,    # 8h max US domestic
    "aus_sea":    720,    # 12h max Australia↔SE Asia
    "africa":     900,    # 15h max Africa routes
    "ea_eu":      960,    # 16h max East Asia↔Europe
    "ea_us":      960,    # 16h max East Asia↔USA
    "longhaul":  1200,    # 20h max generic longhaul
}

# ── FIX #3: ROUTE EXPECTED PRICE RANGES (economy, per person) ─────────────
# Used to detect and flag wildly wrong SerpAPI prices.
ROUTE_PRICE_RANGE: Dict[str, Tuple[int, int]] = {
    "india_dom":  (30,  500),
    "india_me":   (80,  800),
    "india_sea":  (100, 900),
    "india_ea":   (200, 1500),
    "india_eu":   (300, 2000),
    "india_us":   (500, 3000),
    "sea_sea":    (30,  600),
    "me_eu":      (150, 1200),
    "me_us":      (300, 2000),
    "eu_eu":      (30,  800),
    "transatl":   (300, 2500),
    "us_dom":     (50,  800),
    "aus_sea":    (100, 1000),
    "africa":     (200, 2000),
    "ea_eu":      (300, 2500),
    "ea_us":      (400, 2500),
    "longhaul":   (300, 3000),
}


def _price_is_realistic(price: float, route_key: str, travel_class: str) -> bool:
    """Return False if price looks like sandbox/test data or obvious garbage."""
    lo, hi = ROUTE_PRICE_RANGE.get(route_key, (50, 5000))
    # Scale for cabin class
    class_mult = {"ECONOMY": 1.0, "PREMIUM_ECONOMY": 2.0, "BUSINESS": 4.0, "FIRST": 7.0}
    mult = class_mult.get((travel_class or "ECONOMY").upper(), 1.0)
    effective_hi = hi * mult * 1.5   # 50% buffer above upper bound
    effective_lo = lo * 0.5           # 50% buffer below lower bound
    return effective_lo <= price <= effective_hi


# ─────────────────────────────────────────────────────────────────────────────
# AIRPORT / CITY LOOKUPS
# ─────────────────────────────────────────────────────────────────────────────

CITY_TO_AIRPORT: Dict[str, str] = {
    "mumbai": "BOM", "delhi": "DEL", "new delhi": "DEL",
    "bangalore": "BLR", "bengaluru": "BLR",
    "kolkata": "CCU", "calcutta": "CCU",
    "chennai": "MAA", "madras": "MAA",
    "hyderabad": "HYD", "ahmedabad": "AMD", "goa": "GOI",
    "pune": "PNQ", "jaipur": "JAI", "kochi": "COK", "cochin": "COK",
    "lucknow": "LKO", "varanasi": "VNS", "amritsar": "ATQ",
    "nagpur": "NAG", "bhopal": "BHO", "chandigarh": "IXC",
    "indore": "IDR", "coimbatore": "CJB", "visakhapatnam": "VTZ",
    "dubai": "DXB", "abu dhabi": "AUH", "doha": "DOH", "qatar": "DOH",
    "riyadh": "RUH", "jeddah": "JED", "muscat": "MCT", "kuwait": "KWI",
    "bahrain": "BAH", "sharjah": "SHJ",
    "bangkok": "BKK", "singapore": "SIN", "kuala lumpur": "KUL", "kl": "KUL",
    "bali": "DPS", "denpasar": "DPS", "phuket": "HKT", "chiang mai": "CNX",
    "jakarta": "CGK", "manila": "MNL", "hanoi": "HAN",
    "ho chi minh": "SGN", "ho chi minh city": "SGN", "saigon": "SGN",
    "yangon": "RGN", "phnom penh": "PNH", "colombo": "CMB",
    "male": "MLE", "maldives": "MLE",
    "tokyo": "NRT", "osaka": "KIX", "seoul": "ICN", "incheon": "ICN",
    "beijing": "PEK", "shanghai": "PVG", "hong kong": "HKG", "taipei": "TPE",
    "guangzhou": "CAN", "chengdu": "CTU", "shenzhen": "SZX",
    "london": "LHR", "paris": "CDG", "frankfurt": "FRA", "amsterdam": "AMS",
    "rome": "FCO", "milan": "MXP", "madrid": "MAD", "barcelona": "BCN",
    "zurich": "ZRH", "vienna": "VIE", "lisbon": "LIS", "istanbul": "IST",
    "athens": "ATH", "brussels": "BRU", "copenhagen": "CPH",
    "stockholm": "ARN", "oslo": "OSL", "helsinki": "HEL",
    "munich": "MUC", "berlin": "BER", "prague": "PRG",
    "warsaw": "WAW", "budapest": "BUD", "dublin": "DUB",
    "manchester": "MAN", "edinburgh": "EDI", "nice": "NCE",
    "venice": "VCE", "naples": "NAP", "porto": "OPO",
    "new york": "JFK", "new york city": "JFK", "nyc": "JFK",
    "los angeles": "LAX", "la": "LAX",
    "chicago": "ORD", "miami": "MIA", "san francisco": "SFO",
    "boston": "BOS", "atlanta": "ATL", "dallas": "DFW",
    "seattle": "SEA", "houston": "IAH", "denver": "DEN",
    "las vegas": "LAS", "phoenix": "PHX", "minneapolis": "MSP",
    "toronto": "YYZ", "vancouver": "YVR", "montreal": "YUL",
    "mexico city": "MEX", "cancun": "CUN",
    "sao paulo": "GRU", "rio de janeiro": "GIG", "rio": "GIG",
    "buenos aires": "EZE", "bogota": "BOG", "lima": "LIM", "santiago": "SCL",
    "sydney": "SYD", "melbourne": "MEL", "brisbane": "BNE",
    "perth": "PER", "auckland": "AKL",
    "johannesburg": "JNB", "cape town": "CPT", "nairobi": "NBO",
    "cairo": "CAI", "casablanca": "CMN", "lagos": "LOS", "addis ababa": "ADD",
}

CITY_TO_COORDS: Dict[str, Tuple[float, float]] = {
    "mumbai": (19.0760, 72.8777), "delhi": (28.6139, 77.2090),
    "bangalore": (12.9716, 77.5946), "bengaluru": (12.9716, 77.5946),
    "kolkata": (22.5726, 88.3639), "calcutta": (22.5726, 88.3639),
    "chennai": (13.0827, 80.2707), "hyderabad": (17.3850, 78.4867),
    "goa": (15.2993, 74.1240), "dubai": (25.2048, 55.2708),
    "doha": (25.2854, 51.5310), "qatar": (25.2854, 51.5310),
    "abu dhabi": (24.4539, 54.3773), "bangkok": (13.7563, 100.5018),
    "singapore": (1.3521, 103.8198), "kuala lumpur": (3.1390, 101.6869),
    "bali": (-8.3405, 115.0920), "phuket": (7.8804, 98.3923),
    "chiang mai": (18.7883, 98.9853), "tokyo": (35.6762, 139.6503),
    "osaka": (34.6937, 135.5023), "seoul": (37.5665, 126.9780),
    "beijing": (39.9042, 116.4074), "shanghai": (31.2304, 121.4737),
    "hong kong": (22.3193, 114.1694), "london": (51.5074, -0.1278),
    "paris": (48.8566, 2.3522), "frankfurt": (50.1109, 8.6821),
    "amsterdam": (52.3676, 4.9041), "rome": (41.9028, 12.4964),
    "istanbul": (41.0082, 28.9784), "madrid": (40.4168, -3.7038),
    "barcelona": (41.3851, 2.1734), "new york": (40.7128, -74.0060),
    "los angeles": (34.0522, -118.2437), "chicago": (41.8781, -87.6298),
    "miami": (25.7617, -80.1918), "sydney": (-33.8688, 151.2093),
    "toronto": (43.6532, -79.3832), "johannesburg": (-26.2041, 28.0473),
    "cairo": (30.0444, 31.2357), "nairobi": (-1.2921, 36.8219),
    "zurich": (47.3769, 8.5417), "vienna": (48.2082, 16.3738),
    "lisbon": (38.7169, -9.1399), "athens": (37.9838, 23.7275),
    "brussels": (50.8503, 4.3517), "copenhagen": (55.6761, 12.5683),
    "stockholm": (59.3293, 18.0686), "oslo": (59.9139, 10.7522),
    "helsinki": (60.1699, 24.9384), "munich": (48.1351, 11.5820),
    "berlin": (52.5200, 13.4050), "prague": (50.0755, 14.4378),
    "warsaw": (52.2297, 21.0122), "budapest": (47.4979, 19.0402),
    "dublin": (53.3498, -6.2603),
}


# ─────────────────────────────────────────────────────────────────────────────
# TRANSIT HUB WHITELIST
# ─────────────────────────────────────────────────────────────────────────────

VALID_TRANSIT_HUBS: set = {
    "DXB", "DOH", "AUH", "RUH", "KWI", "BAH", "MCT", "SHJ", "AMM", "BEY",
    "SIN", "KUL", "BKK", "CGK", "MNL", "SGN", "HAN", "RGN", "PNH", "CMB",
    "HKG", "NRT", "HND", "KIX", "ICN", "GMP", "PEK", "PVG", "TPE", "CAN", "CTU", "CKG",
    "BOM", "DEL", "BLR", "MAA", "CCU", "HYD", "CMB",
    "LHR", "LGW", "CDG", "ORY", "FRA", "AMS", "IST", "SAW", "FCO", "MAD",
    "BCN", "ZRH", "VIE", "MUC", "BRU", "ARN", "CPH", "OSL", "HEL", "ATH",
    "LIS", "WAW", "BUD", "PRG", "DUB", "MAN", "EDI",
    "JFK", "EWR", "LAX", "ORD", "MIA", "YYZ", "YVR", "GRU", "EZE", "SFO",
    "ATL", "DFW", "DEN", "BOS", "SEA", "IAH",
    "ADD", "NBO", "JNB", "CAI", "CMN",
    "SYD", "MEL", "BNE", "PER", "AKL",
}

REGIONAL_FRAGMENTS = {
    "bhubaneswar", "biju patnaik", "patna", "varanasi", "lucknow", "amritsar",
    "chandigarh", "nagpur", "bhopal", "indore", "coimbatore", "visakhapatnam",
    "vizag", "tiruchirappalli", "trichy", "calicut", "kozhikode", "mangalore",
    "srinagar", "jammu", "dehradun", "agra", "jodhpur", "udaipur",
    "ranchi", "guwahati", "imphal", "dibrugarh", "raipur",
    "lombok", "surabaya", "yogyakarta", "padang", "medan",
    "charleroi", "beauvais", "bergamo", "girona", "weeze", "eindhoven",
    "katowice", "poznan", "gdansk", "wroclaw",
    "thiruvananthapuram", "trivandrum", "kannur",
}


def _is_valid_transit(iata: str, airport_name: str) -> bool:
    if iata and iata.upper() in VALID_TRANSIT_HUBS:
        return True
    name_lower = (airport_name or "").lower()
    for frag in REGIONAL_FRAGMENTS:
        if frag in name_lower:
            return False
    if iata and len(iata) == 3 and iata.upper() not in VALID_TRANSIT_HUBS:
        return False
    return True


# ─────────────────────────────────────────────────────────────────────────────
# AIRLINE REGISTRY
# ─────────────────────────────────────────────────────────────────────────────

DOMESTIC_ONLY: set = {
    "Akasa Air", "GoFirst", "Go First", "Star Air", "Blue Dart Aviation",
    "Ryanair", "EasyJet", "Wizz Air", "Vueling", "Transavia", "Pegasus",
    "Southwest", "Frontier", "Spirit", "Allegiant", "Avelo",
    "Thai Lion Air", "Batik Air Indonesia", "Citilink", "Wings Air",
    "Flybe", "Loganair", "Eastern Airways",
}

CORRIDOR_AIRLINES: Dict[str, set] = {
    "IndiGo":        {"india_dom", "india_me", "india_sea"},
    "SpiceJet":      {"india_dom", "india_me"},
    "Vistara":       {"india_dom", "india_me", "india_sea"},
    "AirAsia India": {"india_dom", "india_sea"},
    "Air Arabia":    {"india_me", "me_eu", "india_sea"},
    "Flydubai":      {"india_me", "me_eu", "me_us"},
    "AirAsia":       {"sea_sea", "india_sea", "aus_sea"},
    "Scoot":         {"sea_sea", "india_sea", "aus_sea", "india_ea"},
    "Jetstar":       {"aus_sea", "aus_pac"},
    "Cebu Pacific":  {"sea_sea"},
}

AIRLINE_CODES: Dict[str, str] = {
    "Air India": "AI", "IndiGo": "6E", "SpiceJet": "SG", "Vistara": "UK",
    "GoFirst": "G8", "AirAsia India": "I5", "Akasa Air": "QP",
    "Emirates": "EK", "Qatar Airways": "QR", "Etihad": "EY", "Flydubai": "FZ",
    "Air Arabia": "G9", "Oman Air": "WY",
    "Singapore Airlines": "SQ", "Thai AirAsia": "FD", "AirAsia": "AK",
    "Scoot": "TR", "Thai Lion Air": "SL", "Malaysia Airlines": "MH",
    "Thai Airways": "TG", "Vietnam Airlines": "VN",
    "Cathay Pacific": "CX", "China Eastern": "MU", "China Southern": "CZ",
    "ANA": "NH", "Japan Airlines": "JL", "Korean Air": "KE", "Asiana": "OZ",
    "British Airways": "BA", "Virgin Atlantic": "VS", "Lufthansa": "LH",
    "Air France": "AF", "KLM": "KL", "Turkish Airlines": "TK",
    "Iberia": "IB", "SWISS": "LX", "Austrian Airlines": "OS",
    "Finnair": "AY", "SAS": "SK",
    "Delta": "DL", "United Airlines": "UA", "American Airlines": "AA",
    "Southwest": "WN", "Alaska Airlines": "AS", "JetBlue": "B6",
    "Qantas": "QF", "Jetstar": "JQ", "Air New Zealand": "NZ",
    "Ethiopian Airlines": "ET", "Kenya Airways": "KQ",
    "South African Airways": "SA", "Egypt Air": "MS",
    "SriLankan Airlines": "UL", "Gulf Air": "GF",
}

AIRLINE_QUALITY: Dict[str, int] = {
    "Singapore Airlines": 10, "ANA": 10, "Japan Airlines": 9,
    "Cathay Pacific": 9, "Emirates": 9, "Qatar Airways": 9,
    "Qantas": 8, "Korean Air": 8, "Etihad": 8, "SWISS": 8,
    "British Airways": 7, "Virgin Atlantic": 7, "Lufthansa": 7,
    "Air France": 7, "KLM": 7, "Turkish Airlines": 7,
    "Finnair": 7, "Austrian Airlines": 7, "Air New Zealand": 7,
    "SAS": 6, "Air India": 6, "Vietnam Airlines": 6,
    "Thai Airways": 6, "Malaysia Airlines": 6, "Oman Air": 6,
    "Delta": 6, "United Airlines": 6, "American Airlines": 6,
    "Ethiopian Airlines": 6, "Kenya Airways": 5,
    "IndiGo": 4, "SpiceJet": 3, "AirAsia": 4, "Scoot": 4,
    "Flydubai": 4, "Air Arabia": 4, "SriLankan Airlines": 4, "Gulf Air": 5,
    "Ryanair": 3, "EasyJet": 4, "JetBlue": 5,
    "Alaska Airlines": 6,
}


# ─────────────────────────────────────────────────────────────────────────────
# ROUTE CLASSIFICATION + DATA
# ─────────────────────────────────────────────────────────────────────────────

def _classify_route(oc: str, dc: str) -> str:
    india = {"mumbai","delhi","new delhi","bangalore","bengaluru","kolkata","calcutta",
             "chennai","hyderabad","ahmedabad","goa","pune","jaipur","kochi","cochin"}
    me    = {"dubai","abu dhabi","doha","qatar","riyadh","jeddah","muscat","kuwait",
             "bahrain","sharjah"}
    sea   = {"bangkok","singapore","kuala lumpur","kl","bali","phuket","jakarta",
             "manila","hanoi","ho chi minh","ho chi minh city","chiang mai",
             "colombo","male","maldives","yangon","phnom penh"}
    ea    = {"tokyo","osaka","seoul","incheon","beijing","shanghai","hong kong",
             "taipei","guangzhou","chengdu","shenzhen"}
    eu    = {"london","paris","frankfurt","amsterdam","rome","milan","madrid",
             "barcelona","zurich","vienna","lisbon","istanbul","athens","brussels",
             "copenhagen","stockholm","oslo","helsinki","munich","berlin","prague",
             "warsaw","budapest","dublin","manchester","edinburgh","nice"}
    us    = {"new york","new york city","nyc","los angeles","la","chicago","miami",
             "san francisco","boston","dallas","seattle","houston","denver",
             "las vegas","toronto","vancouver","montreal"}
    aus   = {"sydney","melbourne","brisbane","perth","auckland"}
    afr   = {"johannesburg","cape town","nairobi","cairo","casablanca","lagos",
             "addis ababa"}

    if oc in india and dc in india: return "india_dom"
    if (oc in india) != (dc in india) and (oc in me or dc in me): return "india_me"
    if (oc in india) != (dc in india) and (oc in sea or dc in sea): return "india_sea"
    if (oc in india) != (dc in india) and (oc in ea or dc in ea): return "india_ea"
    if (oc in india) != (dc in india) and (oc in eu or dc in eu): return "india_eu"
    if (oc in india) != (dc in india) and (oc in us or dc in us): return "india_us"
    if oc in sea and dc in sea: return "sea_sea"
    if (oc in me and dc in eu) or (oc in eu and dc in me): return "me_eu"
    if (oc in me and dc in us) or (oc in us and dc in me): return "me_us"
    if oc in eu and dc in eu: return "eu_eu"
    if (oc in us and dc in eu) or (oc in eu and dc in us): return "transatl"
    if oc in us and dc in us: return "us_dom"
    if (oc in aus and dc in sea) or (oc in sea and dc in aus): return "aus_sea"
    if oc in afr or dc in afr: return "africa"
    if (oc in ea and dc in eu) or (oc in eu and dc in ea): return "ea_eu"
    if (oc in ea and dc in us) or (oc in us and dc in ea): return "ea_us"
    return "longhaul"


ROUTE_DATA: Dict[str, Dict] = {
    "india_dom": {
        "airlines": ["IndiGo", "Air India", "SpiceJet", "Vistara", "AirAsia India"],
        "duration": (1.5, 2.5), "stops": 0, "via": [], "non_stop_only": True,
    },
    "india_me": {
        "airlines": ["Air India", "Emirates", "Qatar Airways", "Etihad", "IndiGo",
                     "Flydubai", "Oman Air"],
        "duration": (3.5, 4.5), "stops": 0, "via": [], "non_stop_only": True,
    },
    "india_sea": {
        "airlines": ["Air India", "Singapore Airlines", "IndiGo", "Thai Airways",
                     "Malaysia Airlines"],
        "duration": (4.0, 6.0), "stops": 0, "via": [], "non_stop_only": True,
    },
    "india_ea": {
        "airlines": ["Air India", "Singapore Airlines", "Cathay Pacific",
                     "China Eastern", "Korean Air"],
        "duration": (6.5, 9.0), "stops": 1,
        "via": ["Singapore Changi Airport", "Kuala Lumpur International Airport",
                "Hong Kong International Airport", "Suvarnabhumi Airport"],
        "non_stop_only": False,
    },
    "india_eu": {
        "airlines": ["Air India", "British Airways", "Lufthansa", "Emirates",
                     "Qatar Airways", "Turkish Airlines", "Etihad", "SWISS",
                     "KLM", "Air France"],
        "duration": (9.5, 13.5), "stops": 1,
        "via": ["Dubai International Airport", "Hamad International Airport",
                "Istanbul Airport", "Frankfurt Airport", "Heathrow Airport",
                "Zayed International Airport"],
        "non_stop_only": False,
    },
    "india_us": {
        "airlines": ["Air India", "Emirates", "Qatar Airways", "Lufthansa",
                     "United Airlines", "American Airlines", "Virgin Atlantic"],
        "duration": (17.0, 22.0), "stops": 1,
        "via": ["Dubai International Airport", "Hamad International Airport",
                "Heathrow Airport", "Frankfurt Airport"],
        "non_stop_only": False,
    },
    "sea_sea": {
        "airlines": ["AirAsia", "Singapore Airlines", "Scoot", "Malaysia Airlines",
                     "Vietnam Airlines", "Thai Airways"],
        "duration": (2.0, 4.0), "stops": 0, "via": [], "non_stop_only": True,
    },
    "me_eu": {
        "airlines": ["Emirates", "Qatar Airways", "Etihad", "Turkish Airlines",
                     "Flydubai", "Oman Air"],
        "duration": (6.0, 8.5), "stops": 0, "via": [], "non_stop_only": True,
    },
    "me_us": {
        "airlines": ["Emirates", "Qatar Airways", "Etihad", "American Airlines",
                     "Delta", "United Airlines"],
        "duration": (13.0, 16.0), "stops": 0, "via": [], "non_stop_only": True,
    },
    "eu_eu": {
        "airlines": ["Lufthansa", "Air France", "KLM", "British Airways", "Iberia",
                     "SWISS", "Austrian Airlines", "Finnair", "SAS"],
        "duration": (2.0, 3.5), "stops": 0, "via": [], "non_stop_only": True,
    },
    "transatl": {
        "airlines": ["Delta", "United Airlines", "American Airlines", "British Airways",
                     "Lufthansa", "Air France", "Virgin Atlantic"],
        "duration": (8.0, 10.0), "stops": 0, "via": [], "non_stop_only": True,
    },
    "us_dom": {
        "airlines": ["Delta", "United Airlines", "American Airlines", "Alaska Airlines",
                     "JetBlue", "Southwest"],
        "duration": (3.0, 6.0), "stops": 0, "via": [], "non_stop_only": True,
    },
    "aus_sea": {
        "airlines": ["Qantas", "Singapore Airlines", "Malaysia Airlines", "AirAsia",
                     "Jetstar"],
        "duration": (7.0, 9.0), "stops": 0, "via": [], "non_stop_only": True,
    },
    "africa": {
        "airlines": ["Ethiopian Airlines", "Kenya Airways", "South African Airways",
                     "Emirates", "Qatar Airways"],
        "duration": (7.0, 12.0), "stops": 1,
        "via": ["Addis Ababa Bole International Airport",
                "Jomo Kenyatta International Airport",
                "Dubai International Airport"],
        "non_stop_only": False,
    },
    "ea_eu": {
        "airlines": ["Cathay Pacific", "Singapore Airlines", "Lufthansa",
                     "British Airways", "ANA", "Japan Airlines", "Korean Air"],
        "duration": (11.0, 13.5), "stops": 1,
        "via": ["Dubai International Airport", "Hong Kong International Airport",
                "Changi Airport Singapore", "Istanbul Airport"],
        "non_stop_only": False,
    },
    "ea_us": {
        "airlines": ["ANA", "Japan Airlines", "Korean Air", "United Airlines",
                     "Delta", "Cathay Pacific", "American Airlines"],
        "duration": (12.0, 15.0), "stops": 0, "via": [], "non_stop_only": True,
    },
    "longhaul": {
        "airlines": ["Emirates", "Qatar Airways", "Singapore Airlines",
                     "Turkish Airlines", "Cathay Pacific", "Lufthansa"],
        "duration": (12.0, 18.0), "stops": 1,
        "via": ["Dubai International Airport", "Hamad International Airport",
                "Singapore Changi Airport", "Istanbul Airport"],
        "non_stop_only": False,
    },
}

TRAVEL_CLASS_MAP = {
    "ECONOMY": "1", "PREMIUM_ECONOMY": "2", "BUSINESS": "3", "FIRST": "4",
}


# ─────────────────────────────────────────────────────────────────────────────
# PRICE ESTIMATION
# ─────────────────────────────────────────────────────────────────────────────

def _price_usd(duration_h: float, travel_class: str, stops: int,
               airline: str, seed: int = 0) -> int:
    if   duration_h <= 2:   base = 40
    elif duration_h <= 4:   base = 32
    elif duration_h <= 6:   base = 26
    elif duration_h <= 9:   base = 20
    elif duration_h <= 13:  base = 16
    elif duration_h <= 17:  base = 13
    else:                   base = 10

    mid_price = base * max(duration_h, 1.5)
    if stops > 0:
        mid_price *= 0.82

    class_mult = {
        "ECONOMY": 1.0, "PREMIUM_ECONOMY": 2.1,
        "BUSINESS": 4.5, "FIRST": 7.5,
    }.get((travel_class or "ECONOMY").upper(), 1.0)
    mid_price *= class_mult

    quality = AIRLINE_QUALITY.get(airline, 5)
    tier_mult = 0.80 + (quality / 10) * 0.40
    mid_price *= tier_mult

    variation = 1.0 + ((seed % 17 - 8) / 68.0)
    mid_price *= variation

    return max(int(round(mid_price / 5) * 5), 50)


# ─────────────────────────────────────────────────────────────────────────────
# AIRLINE VALIDATION
# ─────────────────────────────────────────────────────────────────────────────

def _airline_valid_for_route(airline: str, route_key: str) -> bool:
    if airline in DOMESTIC_ONLY:
        allowed = {"india_dom", "eu_eu", "sea_sea", "us_dom", "aus_sea"}
        if route_key not in allowed:
            print(f"  🚫 Blocked {airline} on {route_key} (domestic-only carrier)")
            return False
    if airline in CORRIDOR_AIRLINES:
        if route_key not in CORRIDOR_AIRLINES[airline]:
            print(f"  🚫 Blocked {airline} on {route_key} (not in corridor whitelist)")
            return False
    return True


# ─────────────────────────────────────────────────────────────────────────────
# ── FIX #2: INTENT-AWARE FLIGHT SCORING ──────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

def _score_flight(f: FlightOption, price_priority: str = "balanced") -> float:
    """
    price_priority = "cheapest" → pure price rank (user said cheapest/budget/cheap)
    price_priority = "best"     → quality-biased (user said best/comfort/luxury)
    price_priority = "balanced" → price + duration + quality blend
    """
    price   = _to_float(f.price)
    dur_h   = f.duration_minutes / 60.0
    quality = AIRLINE_QUALITY.get(f.airline, 5)

    if price_priority == "cheapest":
        # Only rank by price; small penalty for >2 stops to avoid garbage results
        stops_penalty = f.stops * 50.0
        return price + stops_penalty

    if price_priority == "best":
        dur_penalty  = max(0.0, dur_h - 10.0) * 10.0
        stops_penalty = f.stops * 120.0
        quality_bonus = quality * 30.0
        return price + dur_penalty + stops_penalty - quality_bonus

    # balanced (default)
    dur_penalty  = max(0.0, dur_h - 10.0) * 10.0
    stops_penalty = f.stops * 120.0
    quality_bonus = quality * 18.0
    return price + dur_penalty + stops_penalty - quality_bonus


# ─────────────────────────────────────────────────────────────────────────────
# MOCK FLIGHT GENERATOR
# ─────────────────────────────────────────────────────────────────────────────

_DEP_SLOTS = [(1, 30), (6, 15), (10, 30), (14, 45), (18, 0), (22, 30)]

def _mock_flights(origin_city: str, dest_city: str, dep_date: str,
                  travel_class: str = "ECONOMY", adults: int = 1) -> List[FlightOption]:
    oc = origin_city.lower().strip()
    dc = dest_city.lower().strip()
    route_key = _classify_route(oc, dc)
    rd = ROUTE_DATA[route_key]
    non_stop_only = rd.get("non_stop_only", False)

    valid_airlines = [a for a in rd["airlines"] if _airline_valid_for_route(a, route_key)]
    if not valid_airlines:
        valid_airlines = rd["airlines"][:3]

    dur_min_h, dur_max_h = rd["duration"]
    base_stops = rd["stops"]
    via_airports = rd["via"]

    dep_dt = datetime.strptime(dep_date, "%Y-%m-%d")
    candidates = valid_airlines[:5]
    if len(candidates) < 3 and len(valid_airlines) >= 3:
        candidates = valid_airlines[:3]

    options: List[FlightOption] = []
    seen_fn: set = set()
    seen_prices: set = set()

    for i, airline in enumerate(candidates):
        if non_stop_only:
            stops = 0
        elif i < 2:
            stops = base_stops
        else:
            stops = min(base_stops + 1, 2)

        frac = i / max(len(candidates) - 1, 1) if len(candidates) > 1 else 0
        dur_h_base = dur_min_h + (dur_max_h - dur_min_h) * frac * 0.70
        if stops > 0:
            dur_h_base += 1.5 + (stops * 0.5)
        dur_h = round(dur_h_base, 1)
        dur_minutes = int(dur_h * 60)

        h_slot, m_slot = _DEP_SLOTS[i % len(_DEP_SLOTS)]
        dep = dep_dt.replace(hour=h_slot, minute=m_slot, second=0, microsecond=0)
        arr_iso = _arrival_from_dep_and_duration(
            dep.strftime("%Y-%m-%dT%H:%M:00"), dur_minutes
        )
        dep_iso = dep.strftime("%Y-%m-%dT%H:%M:00")

        seed = i * 7 + len(airline) + len(route_key) + i * 3
        price = _price_usd(dur_h, travel_class, stops, airline, seed=seed)

        attempts = 0
        while price in seen_prices and attempts < 10:
            price += 5
            attempts += 1
        seen_prices.add(price)

        iata = AIRLINE_CODES.get(airline, airline[:2].upper())
        fn_hash = abs(hash(f"{airline}{dep_date}{i}{route_key}"))
        fn_num = 100 + (fn_hash % 800)
        fn = f"{iata}{fn_num}"
        attempts = 0
        while _fn_key(fn) in seen_fn:
            fn_num = (fn_num + 13) % 900 + 100
            fn = f"{iata}{fn_num}"
            attempts += 1
            if attempts > 30:
                fn = f"{iata}{fn_num + i * 100}"
                break
        seen_fn.add(_fn_key(fn))

        via_note = None
        if stops > 0 and via_airports:
            via_note = f"via {via_airports[i % len(via_airports)]}"

        carbon = _carbon_estimate_kg(dur_minutes, travel_class)

        options.append(FlightOption(
            airline=airline,
            flight_number=fn,
            price=f"${price:,} USD",
            departure_time=dep_iso,
            arrival_time=arr_iso,
            duration=_minutes_to_str(dur_minutes),
            duration_minutes=dur_minutes,
            stops=stops,
            live_status="estimated",
            cabin_class=(travel_class or "ECONOMY").title(),
            terminal=via_note,
            carbon_kg=carbon,
            data_quality="mock",
        ))

    print(f"⚡ Mock [{route_key}]: {oc}→{dc} | "
          f"{len(options)} flights | "
          f"duration {dur_min_h}–{dur_max_h}h | non_stop_only={non_stop_only}")
    return options


# ─────────────────────────────────────────────────────────────────────────────
# CITY → IATA
# ─────────────────────────────────────────────────────────────────────────────

def city_to_iata(city: str) -> str:
    if not city:
        return ""
    s = city.strip()
    if re.match(r'^[A-Z]{3}$', s):
        return s
    key = s.lower().strip()
    if key in CITY_TO_AIRPORT:
        return CITY_TO_AIRPORT[key]
    for k, v in CITY_TO_AIRPORT.items():
        if k in key or key in k:
            return v
    return s[:3].upper()


# ─────────────────────────────────────────────────────────────────────────────
# LLM BACKENDS
# ─────────────────────────────────────────────────────────────────────────────

GROQ_MODEL = "llama-3.3-70b-versatile"

async def _llm_call(prompt: str, system: str = "You are a helpful AI assistant.",
                    max_retries: int = 3) -> str:
    if not GROQ_API_KEY:
        return await _google_llm_call(prompt)

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 2048,
    }

    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers=headers, json=payload,
                )
                if resp.status_code == 429:
                    wait = (2 ** attempt) * 5 + 2
                    print(f"⚠️  Groq rate limited — waiting {wait}s")
                    await asyncio.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"].strip()
        except httpx.TimeoutException:
            print(f"⚠️  Groq timeout (attempt {attempt+1})")
            await asyncio.sleep(3)
        except Exception as e:
            print(f"⚠️  Groq error: {e}")
            if attempt == max_retries - 1:
                try:
                    return await _google_llm_call(prompt)
                except Exception:
                    pass
            await asyncio.sleep(2)

    raise Exception("LLM all retries exhausted")


async def _google_llm_call(prompt: str) -> str:
    if not GOOGLE_API_KEY:
        raise Exception("No LLM API keys available")

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 2048},
    }
    for model in ["gemini-1.5-flash", "gemini-1.0-pro"]:
        try:
            url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
                   f"{model}:generateContent?key={GOOGLE_API_KEY}")
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json=payload,
                                         headers={"Content-Type": "application/json"})
                if resp.status_code == 429:
                    await asyncio.sleep(10)
                    continue
                resp.raise_for_status()
                return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        except Exception as e:
            print(f"⚠️  Google {model} failed: {e}")
    raise Exception("All LLM backends failed")


# ─────────────────────────────────────────────────────────────────────────────
# MAKCORPS — hotel API
# ─────────────────────────────────────────────────────────────────────────────

_makcorps_jwt: Optional[str] = None
_makcorps_jwt_expiry: float = 0.0

async def _get_makcorps_jwt() -> Optional[str]:
    global _makcorps_jwt, _makcorps_jwt_expiry

    if _makcorps_jwt and time.time() < _makcorps_jwt_expiry - 60:
        return _makcorps_jwt

    if MAKCORPS_API_KEY:
        _makcorps_jwt = MAKCORPS_API_KEY
        _makcorps_jwt_expiry = time.time() + 86400
        print("  ✅ Makcorps: using direct API key")
        return _makcorps_jwt

    if not MAKCORPS_USERNAME or not MAKCORPS_PASSWORD:
        return None

    for body in [
        {"username": MAKCORPS_USERNAME, "password": MAKCORPS_PASSWORD},
        {"email":    MAKCORPS_USERNAME, "password": MAKCORPS_PASSWORD},
    ]:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    "https://api.makcorps.com/auth",
                    json=body, headers={"Content-Type": "application/json"},
                )
                print(f"  Makcorps auth → HTTP {resp.status_code}")
                if resp.status_code in (200, 201):
                    data = resp.json()
                    token = (data.get("access_token") or data.get("token") or
                             data.get("jwt") or data.get("access"))
                    if token:
                        if str(token).lower().startswith(("bearer ", "jwt ")):
                            token = token.split(" ", 1)[1]
                        _makcorps_jwt = token
                        _makcorps_jwt_expiry = time.time() + 3600
                        return _makcorps_jwt
                elif resp.status_code == 401:
                    return None
        except Exception as e:
            print(f"  ⚠️  Makcorps auth: {e}")

    print("  ❌ Makcorps auth exhausted")
    return None


def _parse_makcorps_response(raw: list) -> List[HotelOption]:
    results: List[HotelOption] = []
    for item in raw:
        if not isinstance(item, list) or len(item) < 2:
            continue
        hotel_block = item[0]
        if isinstance(hotel_block, list):
            hotel_block = hotel_block[0] if hotel_block else {}
        if not isinstance(hotel_block, dict):
            continue
        hotel_name = hotel_block.get("hotelName") or hotel_block.get("name")
        hotel_id   = str(hotel_block.get("hotelId", ""))
        if not hotel_name:
            continue
        vendor_list = item[1] if isinstance(item[1], list) else []
        vendors: List[Dict] = []
        best_price: Optional[float] = None
        best_vendor: str = "Unknown"
        for vd in vendor_list:
            if not isinstance(vd, dict):
                continue
            for idx in range(1, 6):
                p_raw = vd.get(f"price{idx}")
                t_raw = vd.get(f"tax{idx}")
                v_raw = vd.get(f"vendor{idx}")
                if p_raw is None or v_raw is None:
                    continue
                try:
                    price_num = float(p_raw)
                    tax_num   = float(t_raw) if t_raw else 0.0
                    total     = price_num + tax_num
                    vendors.append({"vendor": v_raw, "price": price_num,
                                    "tax": tax_num, "total": total})
                    if best_price is None or price_num < best_price:
                        best_price  = price_num
                        best_vendor = v_raw
                except (ValueError, TypeError):
                    continue
        if best_price is None:
            continue
        if   best_price < 50:  category = "2-star"
        elif best_price < 100: category = "3-star"
        elif best_price < 200: category = "4-star"
        else:                  category = "5-star"
        vendor_str = " | ".join(
            f"{v['vendor']}: ${v['total']:.0f}"
            for v in sorted(vendors, key=lambda x: x["total"])[:4]
        )
        results.append(HotelOption(
            name=hotel_name, category=category,
            price_per_night=f"${best_price:.0f} USD (from {best_vendor})",
            source="Makcorps (live)", rating=None,
            amenities=vendor_str or None, hotel_id=hotel_id,
            vendors=sorted(vendors, key=lambda x: x["total"]),
        ))
    results.sort(key=lambda h: _to_float(h.price_per_night))
    print(f"  ✅ Parsed {len(results)} hotels from Makcorps")
    return results


async def _makcorps_hotel_search(city: str) -> List[HotelOption]:
    jwt = await _get_makcorps_jwt()
    if not jwt:
        return []
    city_slug = city.lower().strip().replace(" ", "-")
    aliases = {
        "new-york-city": "new-york", "nyc": "new-york", "calcutta": "kolkata",
        "bengaluru": "bangalore", "new-delhi": "delhi", "kl": "kuala-lumpur",
    }
    city_slug = aliases.get(city_slug, city_slug)
    url = f"https://api.makcorps.com/free/{city_slug}"
    print(f"  → Makcorps: {url}")
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(url, headers={"Authorization": f"JWT {jwt}"})
            print(f"  Makcorps hotels → HTTP {resp.status_code}")
            if resp.status_code == 401:
                global _makcorps_jwt, _makcorps_jwt_expiry
                _makcorps_jwt = None
                _makcorps_jwt_expiry = 0.0
                return []
            if resp.status_code != 200:
                return []
            raw = resp.json()
            if not isinstance(raw, list):
                return []
            return _parse_makcorps_response(raw)
    except Exception as e:
        print(f"  ❌ Makcorps error: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# ── FIXED SERPAPI PARSER ──────────────────────────────────────────────────────
# All 10 fixes applied here
# ─────────────────────────────────────────────────────────────────────────────

def _normalise_time(raw: str) -> str:
    if not raw:
        return raw
    raw = raw.strip()
    if "T" in raw:
        return raw
    try:
        return datetime.strptime(raw, "%Y-%m-%d %H:%M").strftime("%Y-%m-%dT%H:%M:00")
    except ValueError:
        return raw


def _parse_serpapi_itinerary(itinerary: dict, travel_class: str,
                              dep_date: str, route_key: str) -> Optional[FlightOption]:
    """
    Parse one SerpAPI itinerary with full validation.
    Returns None on ANY data quality issue — never returns garbage.
    """
    flights_legs = itinerary.get("flights", [])

    # ── FIX #5: MISSING FIELD GUARD ──────────────────────────────────────────
    if not flights_legs:
        print("  🚫 SerpAPI: no legs in itinerary")
        return None

    price_raw = itinerary.get("price")
    if price_raw is None:
        print("  🚫 SerpAPI: missing price field")
        return None

    try:
        price_num = int(price_raw)
    except (TypeError, ValueError):
        print(f"  🚫 SerpAPI: unparseable price '{price_raw}'")
        return None

    if price_num <= 0:
        print(f"  🚫 SerpAPI: zero/negative price {price_num}")
        return None

    # ── FIX #3: PRICE OUTLIER FILTER ─────────────────────────────────────────
    if not _price_is_realistic(price_num, route_key, travel_class):
        lo, hi = ROUTE_PRICE_RANGE.get(route_key, (50, 5000))
        print(f"  🚫 SerpAPI: price ${price_num} outside realistic range "
              f"${lo}–${hi} for {route_key} [{travel_class}]")
        return None

    total_duration_min = int(itinerary.get("total_duration", 0))
    if total_duration_min <= 0:
        print("  🚫 SerpAPI: zero duration")
        return None

    # ── FIX #1: DURATION SANITY GATE ─────────────────────────────────────────
    max_dur = ROUTE_MAX_DURATION_MINUTES.get(route_key, 1200)
    if total_duration_min > max_dur:
        print(f"  🚫 SerpAPI: duration {total_duration_min}min > max {max_dur}min "
              f"for route {route_key} — REJECTED")
        return None

    if total_duration_min < 30:
        print(f"  🚫 SerpAPI: duration {total_duration_min}min too short — REJECTED")
        return None

    duration_str = _minutes_to_str(total_duration_min)
    first_leg = flights_legs[0]

    dep_airport = first_leg.get("departure_airport", {})
    if not dep_airport:
        print("  🚫 SerpAPI: missing departure_airport")
        return None

    dep_time_raw = dep_airport.get("time", "")
    if not dep_time_raw:
        print("  🚫 SerpAPI: missing departure time")
        return None

    dep_iso = _normalise_time(dep_time_raw)
    if not dep_iso:
        print(f"  🚫 SerpAPI: couldn't parse departure time '{dep_time_raw}'")
        return None

    # CRITICAL: arrival = dep + duration. Never trust API arrival time.
    try:
        arr_iso = _arrival_from_dep_and_duration(dep_iso, total_duration_min)
    except Exception as e:
        print(f"  🚫 SerpAPI: arrival computation failed: {e}")
        return None

    airline_name = first_leg.get("airline", "")
    if not airline_name:
        print("  🚫 SerpAPI: missing airline name")
        return None

    # ── FIX #6: STOPS = len(legs) - 1, not the stops field ───────────────────
    stops = len(flights_legs) - 1

    flight_number = (first_leg.get("flight_number") or "").replace(" ", "")
    airplane      = first_leg.get("airplane")
    legroom       = first_leg.get("legroom")
    airline_logo  = first_leg.get("airline_logo") or itinerary.get("airline_logo")

    # Block domestic-only carriers on international routes
    if airline_name in DOMESTIC_ONLY:
        print(f"  🚫 SerpAPI: {airline_name} blocked (domestic-only) on {route_key}")
        return None

    # Validate transit hub for connecting flights
    via_note = None
    if stops >= 1 and len(flights_legs) >= 2:
        via_airport = flights_legs[0].get("arrival_airport", {})
        via_iata = via_airport.get("id", "")
        via_name = via_airport.get("name", "")
        if not _is_valid_transit(via_iata, via_name):
            print(f"  🚫 SerpAPI: {airline_name} via {via_name} ({via_iata}) — invalid hub")
            return None
        via_note = f"via {via_name}" if via_name else (f"via {via_iata}" if via_iata else None)

    carbon_kg = _carbon_estimate_kg(total_duration_min, travel_class)
    ce = itinerary.get("carbon_emissions", {})
    if ce and "this_flight" in ce:
        carbon_kg = int(ce["this_flight"] / 1000)

    print(f"  ✅ SerpAPI accepted: {airline_name} {flight_number} | "
          f"${price_num} | {duration_str} | {stops} stop(s)")

    return FlightOption(
        airline=airline_name,
        flight_number=flight_number,
        price=f"${price_num:,} USD",
        departure_time=dep_iso,
        arrival_time=arr_iso,
        duration=duration_str,
        duration_minutes=total_duration_min,
        stops=stops,
        live_status="live",
        cabin_class=travel_class.title(),
        airline_logo=airline_logo,
        airplane=airplane,
        legroom=legroom,
        carbon_kg=carbon_kg,
        terminal=via_note,
        data_quality="live",
    )


def _dedup_flights(flights: List[FlightOption]) -> List[FlightOption]:
    """3-layer deduplication — keeps cheapest on collision."""
    by_fn: Dict[str, FlightOption] = {}
    no_fn: List[FlightOption] = []

    for f in flights:
        fk = _fn_key(f.flight_number or "")
        if fk:
            if fk not in by_fn:
                by_fn[fk] = f
            else:
                existing = by_fn[fk]
                ex_price = _to_float(existing.price)
                f_price  = _to_float(f.price)
                if f_price < ex_price:
                    by_fn[fk] = f
                elif f_price == ex_price and f.duration_minutes < existing.duration_minutes:
                    by_fn[fk] = f
        else:
            no_fn.append(f)

    by_alt: Dict[Tuple, FlightOption] = {}
    for f in no_fn:
        key = (f.airline, _dep_bucket(f.departure_time))
        if key not in by_alt:
            by_alt[key] = f
        elif _to_float(f.price) < _to_float(by_alt[key].price):
            by_alt[key] = f

    candidates = list(by_fn.values()) + list(by_alt.values())
    candidates.sort(key=lambda f: _score_flight(f))
    airline_count: Dict[str, int] = {}
    final: List[FlightOption] = []
    for f in candidates:
        if airline_count.get(f.airline, 0) < 2:
            final.append(f)
            airline_count[f.airline] = airline_count.get(f.airline, 0) + 1

    print(f"  ✂️  Dedup: {len(flights)} → {len(final)} flights")
    return final


async def _serpapi_flights(
    origin_iata: str, dest_iata: str, dep_date: str,
    adults: int = 1, travel_class: str = "ECONOMY",
    return_date: Optional[str] = None,
    route_key: str = "longhaul",
) -> List[FlightOption]:
    if not SERPAPI_KEY:
        return []

    tc = TRAVEL_CLASS_MAP.get((travel_class or "ECONOMY").upper(), "1")
    flight_type = "2" if not return_date else "1"
    params: Dict[str, Any] = {
        "engine": "google_flights", "api_key": SERPAPI_KEY,
        "departure_id": origin_iata, "arrival_id": dest_iata,
        "outbound_date": dep_date, "travel_class": tc,
        "adults": str(adults), "currency": "USD", "hl": "en", "gl": "us",
        "type": flight_type,
    }
    if return_date and flight_type == "1":
        params["return_date"] = return_date

    print(f"  → SerpAPI: {origin_iata}→{dest_iata} on {dep_date} [{travel_class}]")
    try:
        async with httpx.AsyncClient(timeout=35.0) as client:
            resp = await client.get("https://serpapi.com/search", params=params)
            if resp.status_code in (401, 429):
                print(f"  ❌ SerpAPI HTTP {resp.status_code}")
                return []
            if resp.status_code != 200:
                print(f"  ❌ SerpAPI HTTP {resp.status_code}")
                return []
            data = resp.json()
            if "error" in data:
                print(f"  ❌ SerpAPI error: {data['error']}")
                return []
            all_raw = data.get("best_flights", []) + data.get("other_flights", [])
            if not all_raw:
                print("  ❌ SerpAPI: no itineraries in response")
                return []

            results: List[FlightOption] = []
            rejected = 0
            for itinerary in all_raw[:20]:   # process more to compensate for filtering
                try:
                    result = _parse_serpapi_itinerary(
                        itinerary, travel_class, dep_date, route_key
                    )
                    if result:
                        results.append(result)
                    else:
                        rejected += 1
                except Exception as e:
                    print(f"  ⚠️  SerpAPI parse error: {e}")
                    rejected += 1

            print(f"  📊 SerpAPI: {len(results)} accepted, {rejected} rejected")
            if not results:
                return []

            results = _dedup_flights(results)
            print(f"  ✅ SerpAPI final: {len(results)} clean flights")
            return results

    except httpx.TimeoutException:
        print("  ❌ SerpAPI timeout")
        return []
    except Exception as e:
        print(f"  ❌ SerpAPI error: {e}")
        return []


async def search_flights(
    origin: str, destination: str,
    dep_date: str, ret_date: Optional[str] = None,
    adults: int = 1, travel_class: str = "ECONOMY",
    price_priority: str = "balanced",
) -> List[FlightOption]:
    origin_iata = city_to_iata(origin)
    dest_iata   = city_to_iata(destination)
    tc = (travel_class or "ECONOMY").upper()
    oc = origin.lower().strip()
    dc = destination.lower().strip()
    route_key = _classify_route(oc, dc)

    print(f"\n🛫 Flights: {origin}({origin_iata}) → {destination}({dest_iata})"
          f" | {dep_date} | {tc} | route={route_key} | priority={price_priority}")

    live_results: List[FlightOption] = []

    if not DEMO_MODE and SERPAPI_KEY:
        try:
            live_results = await _serpapi_flights(
                origin_iata, dest_iata, dep_date,
                adults=adults, travel_class=tc,
                return_date=ret_date,
                route_key=route_key,
            )
        except Exception as e:
            print(f"  ❌ SerpAPI pipeline failed: {e}")

    # ── FIX #10: FALLBACK GUARANTEE ──────────────────────────────────────────
    if len(live_results) >= 3:
        # Sort by user's price priority
        live_results.sort(key=lambda f: _score_flight(f, price_priority))
        return live_results[:6]
    
    if not DEMO_MODE and len(live_results) < 3:
        try:
            from browser_agent import scrape_google_flights
            browser_results = await scrape_google_flights(
                origin_iata, dest_iata, dep_date,
                travel_class=tc, adults=adults, route_key=route_key,
            )
            # Run through your existing filters
            validated = [
                f for f in browser_results
                if f.duration_minutes <= ROUTE_MAX_DURATION_MINUTES.get(route_key, 1200)
                and _price_is_realistic(_to_float(f.price), route_key, tc)
            ]
            live_results = _dedup_flights(live_results + validated)
            print(f"  Browser agent added {len(validated)} valid flights")
        except Exception as e:
            print(f"  ⚠️  Browser agent skipped: {e}")
    if len(live_results) >= 3:
       live_results.sort(key=lambda f: _score_flight(f, price_priority))
       return live_results[:6]
    # Not enough live results — supplement with mock
    mock = _mock_flights(origin, destination, dep_date, tc, adults)

    if live_results:
        print(f"  ↪ Only {len(live_results)} live — merging with mock for minimum 3")
        live_airlines = {f.airline for f in live_results}
        extra_mock = [m for m in mock if m.airline not in live_airlines]
        combined = live_results + extra_mock
        combined = _dedup_flights(combined)
        combined.sort(key=lambda f: _score_flight(f, price_priority))
        return combined[:6]
    else:
        print("  ↪ SerpAPI returned nothing clean — using mock")
        mock.sort(key=lambda f: _score_flight(f, price_priority))
        return mock


# ─────────────────────────────────────────────────────────────────────────────
# CURATED HOTELS
# ─────────────────────────────────────────────────────────────────────────────

DEST_HOTELS: Dict[str, List[Tuple]] = {
    "doha": [
        ("Souq Waqif Boutique Hotels",    "3-star",  90,  4.3, "Souq Waqif, Old Town"),
        ("Marriott Marquis City Center",  "5-star",  195, 4.6, "West Bay, City Centre"),
        ("W Doha Hotel & Residences",     "5-star",  265, 4.7, "West Bay, Diplomatic District"),
        ("Mandarin Oriental Doha",        "5-star",  340, 4.8, "Msheireb, Downtown"),
        ("The St. Regis Doha",            "5-star",  410, 4.9, "West Bay, Corniche"),
    ],
    "qatar": [
        ("Souq Waqif Boutique Hotels",    "3-star",  90,  4.3, "Souq Waqif, Old Town"),
        ("Marriott Marquis City Center",  "5-star",  195, 4.6, "West Bay, City Centre"),
        ("The St. Regis Doha",            "5-star",  410, 4.9, "West Bay, Corniche"),
    ],
    "dubai": [
        ("Citymax Hotel Bur Dubai",       "3-star",  55,  3.9, "Bur Dubai, Metro access"),
        ("Ramada by Wyndham Dubai",       "3-star",  80,  4.0, "Deira, Airport 15min"),
        ("Sofitel Dubai Downtown",        "4-star",  175, 4.5, "Downtown, Burj Khalifa views"),
        ("Atlantis The Palm",             "5-star",  400, 4.7, "Palm Jumeirah, Private Beach"),
        ("Burj Al Arab Jumeirah",         "5-star",  850, 4.9, "Jumeirah Beach, Iconic"),
    ],
    "abu dhabi": [
        ("Citymax Hotel Al Bahia",        "3-star",  65,  3.9, "Al Bahia, City access"),
        ("Radisson Blu Abu Dhabi",        "4-star",  125, 4.3, "Corniche Road, Sea views"),
        ("Yas Island Rotana",             "4-star",  150, 4.4, "Yas Island, Near F1 circuit"),
        ("Emirates Palace Mandarin",      "5-star",  620, 4.9, "Corniche, Private Beach"),
    ],
    "new york": [
        ("Pod 39 Hotel",                  "2-star",  115, 4.0, "Murray Hill, Midtown East"),
        ("Kimpton Hotel Theta",           "4-star",  270, 4.4, "Midtown West, Near Times Square"),
        ("The Knickerbocker",             "4-star",  310, 4.5, "Times Square, 42nd Street"),
        ("Four Seasons New York",         "5-star",  720, 4.8, "Midtown East, 57th Street"),
        ("The Plaza Hotel",               "5-star",  860, 4.9, "Central Park South, Grand Army Plaza"),
    ],
    "mumbai": [
        ("Hotel Suba Palace",             "3-star",  50,  3.8, "Colaba, Gateway of India 5min"),
        ("The Fern Residency",            "3-star",  70,  4.0, "Andheri, Airport 10min"),
        ("ITC Grand Central",             "5-star",  190, 4.6, "Parel, Central Mumbai"),
        ("The Taj Mahal Palace",          "5-star",  360, 4.9, "Colaba, Harbour front"),
    ],
    "delhi": [
        ("Hotel Palace Heights",          "3-star",  48,  3.9, "Connaught Place, Central"),
        ("The Lalit New Delhi",           "5-star",  150, 4.5, "Barakhamba Road, Connaught Place"),
        ("The Imperial New Delhi",        "5-star",  270, 4.8, "Janpath, Colonial heritage"),
        ("The Leela Palace",              "5-star",  335, 4.9, "Chanakyapuri, Diplomatic enclave"),
    ],
    "bangalore": [
        ("Hotel Pai Viceroy",             "3-star",  42,  3.8, "Majestic, City Centre"),
        ("Lemon Tree Premier",            "4-star",  85,  4.2, "Ulsoor, Central Bangalore"),
        ("ITC Gardenia",                  "5-star",  180, 4.7, "Residency Road, Business hub"),
        ("The Oberoi Bengaluru",          "5-star",  265, 4.8, "MG Road, Cubbon Park"),
    ],
    "bengaluru": [
        ("Hotel Pai Viceroy",             "3-star",  42,  3.8, "Majestic, City Centre"),
        ("Lemon Tree Premier",            "4-star",  85,  4.2, "Ulsoor, Central Bangalore"),
        ("ITC Gardenia",                  "5-star",  180, 4.7, "Residency Road, Business hub"),
        ("The Oberoi Bengaluru",          "5-star",  265, 4.8, "MG Road, Cubbon Park"),
    ],
    "kolkata": [
        ("Hotel Diplomat",                "3-star",  38,  3.7, "Park Street, Central"),
        ("Swissotel Kolkata",             "5-star",  125, 4.4, "New Town, Rajarhat"),
        ("ITC Royal Bengal",              "5-star",  190, 4.7, "JBS Haldane Ave, City Centre"),
        ("The Oberoi Grand",              "5-star",  265, 4.8, "Chowringhee, Heritage location"),
    ],
    "bangkok": [
        ("Lub d Bangkok Silom",           "2-star",  25,  4.2, "Silom, BTS access"),
        ("ibis Bangkok Sukhumvit",        "3-star",  50,  4.0, "Sukhumvit 4, Nana BTS"),
        ("Novotel Bangkok Ploenchit",     "4-star",  105, 4.4, "Ploenchit, Skywalk access"),
        ("Mandarin Oriental Bangkok",     "5-star",  460, 4.9, "Riverside, Chao Phraya"),
    ],
    "singapore": [
        ("ibis Singapore on Bencoolen",   "3-star",  115, 4.1, "Bencoolen, City Hall area"),
        ("Orchard Hotel Singapore",       "4-star",  190, 4.3, "Orchard Road, Shopping belt"),
        ("The Fullerton Hotel",           "5-star",  400, 4.8, "Marina Bay, Riverside"),
        ("Marina Bay Sands",              "5-star",  530, 4.7, "Marina Bay, Infinity pool"),
    ],
    "london": [
        ("Generator London",              "2-star",  65,  4.0, "King's Cross, Zone 1"),
        ("Hilton London Bankside",        "4-star",  240, 4.4, "Southbank, Tate Modern 5min"),
        ("Claridge's",                    "5-star",  670, 4.8, "Mayfair, Art Deco landmark"),
        ("The Savoy",                     "5-star",  620, 4.8, "Strand, Thames views"),
    ],
    "paris": [
        ("ibis Paris Gare du Nord",       "3-star",  105, 4.0, "10th arrondissement, Train hub"),
        ("Mercure Paris Opera",           "4-star",  190, 4.3, "9th arrondissement, Opera Quarter"),
        ("Le Bristol Paris",              "5-star",  760, 4.9, "8th arrondissement, Rue du Faubourg"),
        ("Le Meurice",                    "5-star",  720, 4.9, "1st arrondissement, Tuileries views"),
    ],
    "madrid": [
        ("Generator Madrid",              "2-star",  45,  4.1, "Chueca, Central Madrid"),
        ("Hotel Vincci Soho",             "4-star",  135, 4.4, "Lavapiés / Huertas"),
        ("NH Collection Gran Vía",        "4-star",  155, 4.5, "Gran Vía, City Centre"),
        ("Hotel Palace Madrid",           "5-star",  440, 4.8, "Congreso, Belle Époque"),
        ("Mandarin Oriental Ritz Madrid", "5-star",  590, 4.9, "Retiro, Prado Museum views"),
    ],
    "barcelona": [
        ("Generator Barcelona",           "2-star",  65,  4.1, "Gràcia, Bohemian area"),
        ("Hotel Arts Barcelona",          "5-star",  360, 4.7, "Barceloneta, Beach & Marina"),
        ("W Barcelona",                   "5-star",  400, 4.8, "Barceloneta, Sail building"),
        ("Mandarin Oriental Barcelona",   "5-star",  480, 4.9, "Passeig de Gràcia"),
    ],
    "tokyo": [
        ("APA Hotel Shinjuku",            "3-star",  85,  4.0, "Shinjuku, Entertainment hub"),
        ("Shinjuku Washington Hotel",     "4-star",  150, 4.3, "Shinjuku, West exit"),
        ("Hotel New Otani Tokyo",         "4-star",  210, 4.5, "Akasaka, Garden views"),
        ("Park Hyatt Tokyo",              "5-star",  470, 4.8, "Shinjuku, Lost in Translation hotel"),
    ],
    "bali": [
        ("Kuta Station Hotel",            "3-star",  42,  4.1, "Kuta Beach, 2min walk"),
        ("Nusa Dua Beach Hotel",          "4-star",  125, 4.4, "Nusa Dua, Private beach"),
        ("COMO Uma Canggu",               "5-star",  335, 4.7, "Canggu, Rice field views"),
        ("Four Seasons Jimbaran Bay",     "5-star",  580, 4.9, "Jimbaran, Clifftop villas"),
    ],
    "phuket": [
        ("The Bloc Hotel Phuket",         "3-star",  48,  4.2, "Patong Beach, 5min walk"),
        ("Novotel Phuket Surin Beach",    "4-star",  105, 4.5, "Surin Beach, Quieter area"),
        ("Anantara Layan Phuket",         "5-star",  385, 4.8, "Layan Beach, Secluded bay"),
        ("Amanpuri",                      "5-star",  670, 5.0, "Pansea Beach, Legendary resort"),
    ],
    "miami": [
        ("Freehand Miami",                "3-star",  85,  4.2, "Wynwood / Midtown, Trendy"),
        ("Kimpton EPIC Hotel",            "4-star",  265, 4.5, "Brickell, Biscayne Bay views"),
        ("1 Hotel South Beach",           "5-star",  430, 4.7, "South Beach, Eco-luxury"),
        ("Faena Hotel Miami Beach",       "5-star",  620, 4.9, "Mid-Beach, Iconic red curtain"),
    ],
    "los angeles": [
        ("Freehand Los Angeles",          "3-star",  95,  4.1, "Koreatown, Central LA"),
        ("Loews Hollywood Hotel",         "4-star",  210, 4.4, "Hollywood, Walk of Fame"),
        ("Chateau Marmont",               "5-star",  480, 4.7, "West Hollywood, Legendary"),
        ("The Beverly Hills Hotel",       "5-star",  620, 4.8, "Beverly Hills, Iconic Pink Palace"),
    ],
    "goa": [
        ("The Baga Marina Beach Resort",  "3-star",  52,  4.0, "Baga Beach, North Goa"),
        ("Taj Holiday Village Resort",    "5-star",  210, 4.7, "Candolim, North Goa"),
        ("Alila Diwa Goa",                "5-star",  265, 4.7, "Majorda, South Goa"),
        ("W Goa",                         "5-star",  295, 4.8, "Vagator, Cliffside North"),
    ],
    "amsterdam": [
        ("Generator Amsterdam",           "2-star",  75,  4.1, "Oosterpark, East Amsterdam"),
        ("Hotel V Nesplein",              "4-star",  180, 4.4, "Jordaan, Canal district"),
        ("Hotel De L'Europe",             "5-star",  460, 4.7, "Amstel, City Centre"),
        ("Conservatorium Hotel",          "5-star",  530, 4.8, "Museum Quarter, Van Baerlestraat"),
    ],
    "rome": [
        ("The Yellow Hostel",             "2-star",  55,  4.2, "Termini, Central Rome"),
        ("Hotel Artemide",                "4-star",  170, 4.5, "Via Nazionale, Esquilino"),
        ("Hotel de Russie",               "5-star",  555, 4.8, "Flaminio, Spanish Steps area"),
        ("Hassler Roma",                  "5-star",  620, 4.9, "Top of Spanish Steps, Iconic"),
    ],
    "hong kong": [
        ("Urban Pack Hostel",             "2-star",  48,  4.0, "Mong Kok, Kowloon"),
        ("Hotel ICON",                    "4-star",  190, 4.5, "Tsim Sha Tsui, Harbour views"),
        ("The Peninsula Hong Kong",       "5-star",  580, 4.9, "Tsim Sha Tsui, Legendary"),
        ("Four Seasons Hong Kong",        "5-star",  670, 4.8, "Central, Harbour & Peak views"),
    ],
    "seoul": [
        ("Beewon Guesthouse",             "2-star",  55,  4.2, "Insadong, Traditional area"),
        ("Novotel Ambassador Seoul",      "4-star",  155, 4.4, "Gangnam, Business district"),
        ("The Shilla Seoul",              "5-star",  365, 4.8, "Jangchung, Hill garden"),
        ("Lotte Hotel Seoul",             "5-star",  400, 4.7, "Myeongdong, Central"),
    ],
    "sydney": [
        ("Wake Up! Sydney",               "2-star",  65,  4.1, "Central Station, Backpacker hub"),
        ("Novotel Sydney Darling Harbour", "4-star", 200, 4.4, "Darling Harbour, Waterfront"),
        ("Four Seasons Sydney",           "5-star",  500, 4.8, "The Rocks, Harbour Bridge views"),
        ("Park Hyatt Sydney",             "5-star",  625, 4.9, "The Rocks, Opera House views"),
    ],
    "toronto": [
        ("HI Toronto Hostel",             "2-star",  52,  3.9, "Downtown, Near CN Tower"),
        ("Sheraton Centre Toronto",       "4-star",  190, 4.3, "City Hall area, Downtown Core"),
        ("The Ritz-Carlton Toronto",      "5-star",  460, 4.8, "Financial District, Wellington"),
        ("Four Seasons Toronto",          "5-star",  530, 4.9, "Yorkville, Upscale quarter"),
    ],
    "kuala lumpur": [
        ("BackHome KL",                   "2-star",  22,  4.2, "Chinatown, Pasar Seni LRT"),
        ("Hotel Stripes Kuala Lumpur",    "4-star",  105, 4.5, "Bukit Bintang, Shopping belt"),
        ("Mandarin Oriental KL",          "5-star",  265, 4.8, "KLCC, Twin Towers views"),
        ("The Ritz-Carlton KL",           "5-star",  345, 4.9, "Bukit Bintang, City Centre"),
    ],
    "istanbul": [
        ("World House Hostel",            "2-star",  32,  4.3, "Beyoğlu, Taksim area"),
        ("Swissotel The Bosphorus",       "5-star",  210, 4.7, "Beşiktaş, Bosphorus views"),
        ("Four Seasons Sultanahmet",      "5-star",  460, 4.9, "Sultanahmet, Hagia Sophia 2min"),
        ("Ciragan Palace Kempinski",      "5-star",  580, 4.9, "Beşiktaş, Ottoman Palace"),
    ],
    "zurich": [
        ("ibis Zurich Adliswil",          "3-star",  101, 3.9, "Adliswil, S-Bahn 15min to centre"),
        ("Hotel Krone Unterstrass",       "3-star",  135, 4.1, "Unterstrass, 15min to Old Town"),
        ("25hours Hotel Zürich West",     "4-star",  213, 4.5, "Zürich West, Hipster district"),
        ("Park Hyatt Zurich",             "5-star",  458, 4.8, "Beethoven Strasse, City Centre"),
        ("The Dolder Grand",              "5-star",  648, 4.9, "Adlisberg, Forest hillside & spa"),
    ],
    "vienna": [
        ("Wombat's City Hostel",          "2-star",  42,  4.2, "Naschmarkt, 6th district"),
        ("Hotel Schani Wien",             "3-star",  115, 4.3, "Hauptbahnhof, City access"),
        ("Radisson Blu Style Hotel",      "4-star",  190, 4.5, "Josefstadt, Inner City"),
        ("Hotel Sacher Wien",             "5-star",  500, 4.9, "1st district, Opera adjacent"),
    ],
    "munich": [
        ("Wombat's City Hostel Munich",   "2-star",  48,  4.2, "Theresienwiese, Oktoberfest area"),
        ("Hotel Olympic München",         "3-star",  105, 4.1, "Schwabing, University area"),
        ("Bayerischer Hof",               "5-star",  400, 4.7, "Promenadeplatz, City Centre"),
        ("Mandarin Oriental Munich",      "5-star",  430, 4.8, "Maximilianstrasse, Luxury mile"),
    ],
    "berlin": [
        ("Generator Berlin Mitte",        "2-star",  52,  4.1, "Mitte, Museum Island area"),
        ("Hotel Indigo Berlin",           "4-star",  155, 4.4, "Alexanderplatz, East Berlin"),
        ("Soho House Berlin",             "5-star",  365, 4.7, "Mitte, Torstraße members club"),
        ("Regent Berlin",                 "5-star",  400, 4.8, "Gendarmenmarkt, Opera views"),
    ],
    "prague": [
        ("Czech Inn",                     "2-star",  28,  4.2, "Vinohrady, Residential area"),
        ("Hotel Maximilian",              "4-star",  125, 4.5, "Old Town, Republic Square"),
        ("Hotel Paris Prague",            "5-star",  365, 4.7, "Old Town, Art Nouveau"),
        ("Four Seasons Prague",           "5-star",  430, 4.9, "Staré Město, Vltava River views"),
    ],
    "frankfurt": [
        ("Five Elements Hostel",          "2-star",  42,  4.0, "Sachsenhausen, Apple wine area"),
        ("NH Frankfurt Messe",            "3-star",  95,  4.1, "Westend, Trade Fair access"),
        ("Steigenberger Frankfurter Hof", "5-star",  335, 4.7, "Kaiserplatz, City Centre"),
        ("Villa Kennedy",                 "5-star",  385, 4.8, "Sachsenhausen, Garden villa"),
    ],
    "lisbon": [
        ("Home Lisbon Hostel",            "2-star",  38,  4.4, "Baixa, Downtown Lisbon"),
        ("Hotel Avenida Palace",          "4-star",  170, 4.6, "Rossio, Belle Époque"),
        ("Bairro Alto Hotel",             "5-star",  400, 4.8, "Bairro Alto, Chiado"),
        ("Four Seasons Ritz Lisbon",      "5-star",  480, 4.9, "Marquês de Pombal, Panoramic"),
    ],
    "athens": [
        ("Athens Backpackers",            "2-star",  32,  4.3, "Makrygianni, Acropolis 5min"),
        ("Hotel Grande Bretagne",         "5-star",  365, 4.8, "Syntagma Square, Parliament views"),
        ("King George Athens",            "5-star",  305, 4.7, "Syntagma Square, Rooftop pool"),
    ],
    "cairo": [
        ("Ismailia House Hostel",         "2-star",  22,  3.9, "Downtown, Tahrir Square area"),
        ("Novotel Cairo Airport",         "4-star",  95,  4.1, "Airport, Transit convenience"),
        ("Sofitel Cairo Nile El Gezirah", "5-star",  195, 4.7, "Zamalek, Nile Island views"),
        ("Four Seasons Cairo at Nile",    "5-star",  320, 4.8, "Giza, Pyramids & Nile views"),
    ],
    "maldives": [
        ("Centara Grand Island Resort",   "4-star",  280, 4.6, "South Ari Atoll, Overwater"),
        ("Conrad Maldives Rangali",       "5-star",  800, 4.9, "South Ari Atoll, Iconic"),
        ("Gili Lankanfushi",              "5-star",  1100, 5.0, "North Male Atoll, No news, no shoes"),
    ],
    "male": [
        ("Centara Grand Island Resort",   "4-star",  280, 4.6, "South Ari Atoll, Overwater"),
        ("Conrad Maldives Rangali",       "5-star",  800, 4.9, "South Ari Atoll, Iconic"),
        ("Gili Lankanfushi",              "5-star",  1100, 5.0, "North Male Atoll, No news, no shoes"),
    ],
}


def _hotels_for_curated(city: str) -> List[HotelOption]:
    key = city.lower().strip()
    alias_map = {
        "calcutta": "kolkata", "nyc": "new york", "bengaluru": "bangalore",
        "new delhi": "delhi", "kl": "kuala lumpur", "new york city": "new york",
        "denpasar": "bali",
    }
    key = alias_map.get(key, key)
    templates = DEST_HOTELS.get(key)
    if not templates:
        print(f"  ⚠️  No curated hotels for '{key}' — using generic fallback")
        base_price = 80
        templates = [
            (f"{city.title()} Central Hostel",  "2-star",  max(base_price - 30, 20), 3.8, f"{city.title()} City Centre"),
            (f"Best Western {city.title()}",    "3-star",  base_price,               4.0, f"{city.title()} Downtown"),
            (f"Grand Hotel {city.title()}",     "4-star",  base_price + 60,          4.3, f"{city.title()} Central District"),
            (f"Premier {city.title()}",         "5-star",  base_price + 220,         4.6, f"{city.title()} Premium District"),
        ]
    return [
        HotelOption(
            name=name, category=cat,
            price_per_night=f"${price:,} USD",
            source="Curated estimate",
            rating=rating,
            area=area,
        )
        for name, cat, price, rating, area in templates
    ]


async def search_hotels(city: str, check_in: str, check_out: str,
                         adults: int = 1) -> List[HotelOption]:
    print(f"\n🏨 Hotels: {city} | {check_in}→{check_out}")
    if not DEMO_MODE and MAKCORPS_USERNAME:
        try:
            results = await _makcorps_hotel_search(city)
            if results:
                return results
            print("  ↪ Makcorps empty — using curated")
        except Exception as e:
            print(f"  ❌ Makcorps failed: {e}")
    curated = _hotels_for_curated(city)
    print(f"  ✅ Curated: {len(curated)} hotels")
    return curated


# ─────────────────────────────────────────────────────────────────────────────
# ACTIVITIES
# ─────────────────────────────────────────────────────────────────────────────

DEST_ACTIVITIES: Dict[str, List[Tuple]] = {
    "new york": [
        ("Statue of Liberty & Ellis Island", "Ferry to America's most iconic monument — book in advance to climb to the crown", "$25 USD", "3 hours"),
        ("Empire State Building", "Views from the 86th-floor open-air observation deck", "$44 USD", "1–2 hours"),
        ("Metropolitan Museum of Art", "One of the world's greatest art collections, spanning 5,000 years", "$30 USD", "3–4 hours"),
        ("Brooklyn Bridge Walk", "Walk across the iconic bridge and explore the DUMBO neighbourhood", "Free", "1–2 hours"),
        ("Broadway Show", "World-class live theatre in the Theater District", "$80–200 USD", "2.5 hours"),
        ("High Line Elevated Park", "New York's famous park built on a disused elevated railway", "Free", "1–2 hours"),
        ("9/11 Memorial & Museum", "Powerful tribute at the footprint of the Twin Towers", "$33 USD", "2–3 hours"),
    ],
    "dubai": [
        ("Burj Khalifa 'At The Top'", "Observation deck of the world's tallest building (828m)", "$40 USD", "1–2 hours"),
        ("Desert Safari with BBQ Dinner", "Dune bashing, camel rides, belly dancing & Bedouin feast", "$65 USD", "6 hours"),
        ("Dubai Frame", "Walk across a glass bridge 150 metres in the air", "$14 USD", "1 hour"),
        ("Dubai Creek Dhow Cruise", "Traditional wooden dhow dinner past the glittering gold souks", "$45 USD", "2 hours"),
        ("Gold Souk & Spice Souk", "Haggle for gold jewellery, spices and perfumes in old Dubai", "Free", "2 hours"),
        ("Palm Jumeirah & Atlantis Aquaventure", "The iconic palm island and famous waterpark", "$70 USD", "Half day"),
    ],
    "doha": [
        ("Museum of Islamic Art", "I.M. Pei's masterpiece on the corniche — world-class collection", "Free", "2–3 hours"),
        ("Souq Waqif", "Qatar's most vibrant traditional market — spices, falcons, shisha", "Free", "2–3 hours"),
        ("The Pearl-Qatar Island", "Luxury artificial island with designer shops and marina", "Free", "2–3 hours"),
        ("Desert Safari & Inland Sea", "4WD dunes, camel rides, sandboarding & UNESCO Khor Al Adaid", "$80 USD", "Full day"),
        ("Katara Cultural Village", "Open-air cultural hub with amphitheatre, mosque and beach", "Free", "2 hours"),
        ("National Museum of Qatar", "Frank Gehry's stunning desert-rose building", "$14 USD", "2 hours"),
    ],
    "madrid": [
        ("Prado Museum", "One of Europe's finest art museums — Goya, Velázquez, El Greco", "$18 USD", "3–4 hours"),
        ("Royal Palace of Madrid", "Europe's largest royal palace by floor area", "$14 USD", "2–3 hours"),
        ("Retiro Park", "Madrid's beloved 350-acre park — rowboats on the lake", "Free", "2–3 hours"),
        ("Tapas & Wine Evening Tour", "Bar-hop through La Latina sampling jamón, pintxos and Rioja", "$60 USD", "3 hours"),
        ("Flamenco Show at Tablao Cardamomo", "Authentic flamenco performance in an intimate tablao", "$45 USD", "1.5 hours"),
        ("Thyssen-Bornemisza Museum", "Impressive collection tracing Western art from the 13th century", "$16 USD", "2–3 hours"),
    ],
    "barcelona": [
        ("Sagrada Família", "Gaudí's extraordinary unfinished basilica — book well ahead", "$30 USD", "2 hours"),
        ("Park Güell", "Mosaic terraces and colourful architecture overlooking the city", "$14 USD", "1.5 hours"),
        ("Las Ramblas & Boqueria Market", "Barcelona's iconic boulevard and vibrant food market", "Free", "2 hours"),
        ("Gothic Quarter Walking Tour", "Medieval labyrinth of narrow streets and hidden squares", "$20 USD", "2 hours"),
        ("Barceloneta Beach", "Barcelona's most popular city beach on the Mediterranean", "Free", "Half day"),
    ],
    "mumbai": [
        ("Gateway of India", "Mumbai's iconic triumphal arch overlooking the Arabian Sea", "Free", "1 hour"),
        ("Elephanta Caves", "UNESCO cave temples on a harbour island — 1hr ferry", "$10 USD", "3–4 hours"),
        ("Dharavi Walking Tour", "Eye-opening guided walk through one of Asia's largest communities", "$20 USD", "2–3 hours"),
        ("Marine Drive Promenade", "The legendary 3km seafront — the 'Queen's Necklace' at night", "Free", "1–2 hours"),
        ("Bollywood Studio Tour", "Behind-the-scenes look at Film City Goregaon", "$30 USD", "3 hours"),
    ],
    "kolkata": [
        ("Victoria Memorial", "Stunning white marble monument — British India's grandest building", "$3 USD", "2 hours"),
        ("Howrah Bridge", "The world's busiest cantilever bridge — iconic photo spot at dawn", "Free", "1 hour"),
        ("Indian Museum", "India's oldest and largest museum, founded in 1814", "$2 USD", "2–3 hours"),
        ("Dakshineswar Kali Temple", "Famous riverside temple associated with Sri Ramakrishna", "Free", "1–2 hours"),
        ("Park Street Food Walk", "Kolkata's legendary food scene — kathi rolls, biryani, rosogolla", "$15 USD", "2 hours"),
    ],
    "bangalore": [
        ("Lalbagh Botanical Garden", "Sprawling 240-acre garden with a 19th-century glasshouse", "$1 USD", "2 hours"),
        ("Cubbon Park", "18th-century park — perfect for a morning walk through the city", "Free", "1–2 hours"),
        ("Mysore Day Trip", "Palace, silk market and Chamundi Hill temple", "$30 USD", "Full day"),
        ("Vidhana Soudha", "Imposing neo-Dravidian legislative building — beautiful at night", "Free", "30 mins"),
        ("Craft Beer Trail", "Bangalore's thriving craft beer scene — Toit, Arbor, Windmills", "$20 USD", "Evening"),
    ],
    "bengaluru": [
        ("Lalbagh Botanical Garden", "Sprawling 240-acre garden with a 19th-century glasshouse", "$1 USD", "2 hours"),
        ("Cubbon Park", "18th-century park — perfect for a morning walk", "Free", "1–2 hours"),
        ("Mysore Day Trip", "Palace, silk market and Chamundi Hill temple", "$30 USD", "Full day"),
        ("Craft Beer Trail", "Bangalore's thriving craft beer scene — Toit, Arbor, Windmills", "$20 USD", "Evening"),
    ],
    "goa": [
        ("Baga & Calangute Beach", "North Goa's most popular beaches — beach shacks, water sports", "Free", "Half day"),
        ("Old Goa Churches", "UNESCO-listed Basilica of Bom Jesus and Se Cathedral", "Free", "2–3 hours"),
        ("Dudhsagar Waterfalls Jeep Safari", "Dramatic 4-tier waterfall in the Western Ghats", "$35 USD", "Full day"),
        ("Anjuna Flea Market", "Famous Wednesday market for hippie goods and local crafts", "Free", "2 hours"),
        ("Spice Plantation Tour", "Guided walk through a working spice farm with Goan lunch", "$25 USD", "3 hours"),
    ],
    "bangkok": [
        ("Grand Palace & Wat Phra Kaew", "Thailand's most revered royal temple complex — dress modestly", "$15 USD", "2–3 hours"),
        ("Floating Market Tour", "Traditional vendors selling food from wooden boats on canals", "$30 USD", "Half day"),
        ("Tuk-Tuk Street Food Night Tour", "Zip through neon-lit Chinatown sampling local dishes", "$45 USD", "3 hours"),
        ("Chao Phraya River Cruise", "Scenic evening cruise past temples and the skyline", "$25 USD", "1.5 hours"),
        ("Wat Pho & Traditional Thai Massage", "Temple of the Reclining Buddha + 1-hour massage", "$20 USD", "2 hours"),
    ],
    "singapore": [
        ("Gardens by the Bay", "Futuristic Supertrees, Cloud Forest and Flower Dome", "$28 USD", "3 hours"),
        ("Sentosa Island Day", "Universal Studios, beaches and Wings of Time show at night", "$80 USD", "Full day"),
        ("Singapore Night Safari", "The world's first nocturnal wildlife park", "$49 USD", "3 hours"),
        ("Hawker Centre Food Tour", "Maxwell, Lau Pa Sat and Tiong Bahru with a local guide", "$40 USD", "3 hours"),
        ("Marina Bay Sands SkyPark", "Rooftop infinity pool and iconic views over Marina Bay", "$26 USD", "1–2 hours"),
    ],
    "london": [
        ("British Museum", "8 million objects spanning 2 million years — Rosetta Stone, mummies", "Free", "3–4 hours"),
        ("Tower of London & Crown Jewels", "Historic fortress, Beefeater tours and the Crown Jewels", "$35 USD", "3 hours"),
        ("Harry Potter Warner Bros. Studio Tour", "Walk through actual sets from all 8 films — book ahead", "$60 USD", "3–4 hours"),
        ("Thames River Cruise", "Scenic cruise through the heart of London past major landmarks", "$20 USD", "1.5 hours"),
        ("Borough Market & Southbank Walk", "London's finest food market followed by a Thames walk", "Free", "2–3 hours"),
    ],
    "paris": [
        ("Eiffel Tower Summit", "Ascend to the very top of Paris's beloved iron lady", "$35 USD", "2 hours"),
        ("Louvre Museum", "Home to the Mona Lisa, Venus de Milo and 35,000 works of art", "$22 USD", "3–4 hours"),
        ("Seine River Cruise", "1-hour cruise past Notre-Dame, Eiffel Tower and monuments", "$20 USD", "1 hour"),
        ("Versailles Day Trip", "The Sun King's opulent palace and Hall of Mirrors — book ahead", "$45 USD", "Full day"),
        ("Montmartre & Sacré-Cœur", "Bohemian hilltop village, artist studios and Paris views", "Free", "2–3 hours"),
        ("Musée d'Orsay", "Impressionist masterpieces by Monet, Renoir and Van Gogh", "$18 USD", "2–3 hours"),
    ],
    "tokyo": [
        ("teamLab Planets", "Immersive walk-through digital art installation — book ahead", "$35 USD", "1.5 hours"),
        ("Senso-ji Temple", "Tokyo's oldest temple in historic Asakusa — stunning at dawn", "Free", "1.5 hours"),
        ("Shibuya Crossing & Harajuku", "Cross the world's busiest pedestrian scramble", "Free", "2–3 hours"),
        ("Mt Fuji Day Trip via Hakone", "Views of Fuji, ropeway over Owakudani, hot spring onsen", "$60 USD", "Full day"),
        ("Tsukiji Outer Market Breakfast", "Fresh sushi and seafood at the famous market at 6am", "$20 USD", "2 hours"),
    ],
    "bali": [
        ("Tanah Lot Temple at Sunset", "Iconic sea temple on a rocky outcrop — stunning sunsets", "$5 USD", "2 hours"),
        ("Ubud Monkey Forest & Tegalalang Rice Terraces", "Sacred monkey forest + iconic rice paddies", "$15 USD", "Half day"),
        ("Mount Batur Sunrise Trek", "4am hike to an active volcano summit for magical sunrise", "$45 USD", "6 hours"),
        ("Nusa Penida Island Day Trip", "Snorkel with manta rays and visit Kelingking Beach", "$55 USD", "Full day"),
        ("Balinese Cooking Class in Ubud", "Learn 5 traditional dishes with a local family", "$35 USD", "4 hours"),
        ("Uluwatu Temple & Kecak Fire Dance", "Clifftop temple + traditional fire dance at sunset", "$12 USD", "3 hours"),
    ],
    "istanbul": [
        ("Hagia Sophia", "Breathtaking 6th-century cathedral-turned-mosque", "Free", "1.5 hours"),
        ("Blue Mosque (Sultan Ahmed Mosque)", "Six-minareted mosque famous for its Iznik tilework", "Free", "1 hour"),
        ("Grand Bazaar", "One of the world's oldest covered markets — 4,000 shops", "Free", "2–3 hours"),
        ("Bosphorus Sunset Cruise", "Cruise between Europe and Asia at sunset", "$25 USD", "2 hours"),
        ("Topkapi Palace & Harem", "Ottoman palace with priceless relics and Harem quarters", "$20 USD", "3 hours"),
    ],
    "zurich": [
        ("Old Town (Altstadt) Walking Tour", "Medieval cobblestone lanes, guildhalls, and the twin-towered Grossmünster", "Free", "2–3 hours"),
        ("Lake Zurich Boat Cruise", "Scenic cruise with views of the Alps and lakeshore villas", "$25 USD", "1.5 hours"),
        ("Swiss National Museum", "Switzerland's largest cultural history museum in a neo-Gothic building", "$15 USD", "2 hours"),
        ("Uetliberg Mountain Hike", "Zurich's city mountain — 360° panoramic views over city and Alps", "Free", "3 hours"),
        ("Kunsthaus Zürich", "One of Switzerland's premier art collections — Monet, Picasso, Giacometti", "$20 USD", "2 hours"),
        ("Day Trip to Lucerne & Mt Pilatus", "Chapel Bridge, Lion Monument + cable car to Mt Pilatus", "$65 USD", "Full day"),
    ],
    "miami": [
        ("South Beach & Art Deco Historic District", "Iconic neon-lit beach strip and 1930s pastel architecture", "Free", "2–3 hours"),
        ("Everglades Airboat Tour", "Airboat ride through America's most unique ecosystem — spot alligators", "$50 USD", "3 hours"),
        ("Wynwood Walls", "World-famous outdoor street art museum", "$10 USD", "1–2 hours"),
        ("Key West Day Trip", "Drive the legendary Overseas Highway to the southernmost USA point", "$30 USD", "Full day"),
    ],
    "amsterdam": [
        ("Anne Frank House", "The hiding place of Anne Frank — book weeks in advance", "$18 USD", "1.5 hours"),
        ("Rijksmuseum", "Dutch Golden Age masterpieces: Rembrandt, Vermeer and Night Watch", "$25 USD", "2–3 hours"),
        ("Canal Boat Tour", "Classic Amsterdam experience — 1 hour through the UNESCO canals", "$18 USD", "1 hour"),
        ("Van Gogh Museum", "The world's largest Van Gogh collection — 200+ paintings", "$22 USD", "2 hours"),
        ("Vondelpark & Jordaan Walk", "Peaceful park followed by boutique shopping in the Jordaan", "Free", "2–3 hours"),
    ],
    "rome": [
        ("Colosseum, Roman Forum & Palatine Hill", "Ancient Rome's greatest monuments — book ahead", "$20 USD", "3 hours"),
        ("Vatican Museums & Sistine Chapel", "Michelangelo's ceiling and the Papal collections", "$30 USD", "3–4 hours"),
        ("Trevi Fountain & Pantheon Walk", "Toss a coin and explore the ancient Pantheon", "Free", "2 hours"),
        ("Borghese Gallery", "Bernini sculptures and Raphael paintings in a palace garden", "$20 USD", "2 hours"),
        ("Trastevere Food Walk", "Explore Rome's most charming neighbourhood with local bites", "$35 USD", "3 hours"),
    ],
    "hong kong": [
        ("The Peak & Victoria Harbour", "Tram to the Peak for spectacular harbour panorama", "$10 USD", "2 hours"),
        ("Star Ferry & Kowloon Walk", "Iconic 5-minute ferry across Victoria Harbour", "$0.5 USD", "2 hours"),
        ("Lantau Island & Big Buddha", "Cable car to Ngong Ping and the Giant Tian Tan Buddha", "$30 USD", "Full day"),
        ("Michelin Street Food Tour", "Char siu, dim sum and roast goose in Wan Chai and Sham Shui Po", "$40 USD", "3 hours"),
    ],
    "seoul": [
        ("Gyeongbokgung Palace", "Korea's grandest Joseon-era palace — changing of the guard", "$3 USD", "2 hours"),
        ("Bukchon Hanok Village", "Traditional Korean village of preserved hanok houses", "Free", "1.5 hours"),
        ("N Seoul Tower & Namsan", "Iconic tower with 360° city views, especially at night", "$12 USD", "2 hours"),
        ("Myeongdong Street Food & Shopping", "Korea's most famous shopping street — Korean BBQ, tteokbokki", "Free", "3 hours"),
        ("Korean Cooking Class", "Learn to make bibimbap, kimchi and japchae", "$45 USD", "3 hours"),
    ],
    "sydney": [
        ("Sydney Opera House Tour", "Behind-the-scenes tour of the world's most famous performing arts venue", "$43 USD", "1 hour"),
        ("Sydney Harbour Bridge Climb", "Walk to the top of the bridge for panoramic harbour views", "$174 USD", "3.5 hours"),
        ("Bondi to Coogee Coastal Walk", "Scenic 6km clifftop walk past iconic beaches", "Free", "2–3 hours"),
        ("The Rocks & Circular Quay", "Sydney's historic birthplace — museums, galleries and pubs", "Free", "2 hours"),
        ("Blue Mountains Day Trip", "Three Sisters, Scenic World railway and Jamison Valley", "$35 USD", "Full day"),
    ],
    "cairo": [
        ("Giza Pyramids & Sphinx", "The only surviving Ancient Wonder — hire a licensed guide", "$15 USD", "3–4 hours"),
        ("Egyptian Museum", "Over 120,000 artefacts including Tutankhamun's gold mask", "$10 USD", "3 hours"),
        ("Nile Felucca Sunset Cruise", "Traditional wooden sailboat ride at sunset", "$20 USD", "1.5 hours"),
        ("Khan el-Khalili Bazaar", "Cairo's medieval bazaar — copper, spices and sheesha", "Free", "2–3 hours"),
    ],
    "nairobi": [
        ("Nairobi National Park Safari", "Wild lion, rhino and giraffe with the city skyline behind", "$45 USD", "3–4 hours"),
        ("Giraffe Centre", "Hand-feed endangered Rothschild giraffes", "$12 USD", "1 hour"),
        ("Maasai Market", "Vibrant open-air craft market with Maasai jewellery", "Free", "1–2 hours"),
        ("Karen Blixen Museum", "Out of Africa author's farmhouse preserved as a museum", "$5 USD", "1.5 hours"),
    ],
}


def _activities_for(city: str) -> List[ActivityOption]:
    key = city.lower().strip()
    alias_map = {
        "calcutta": "kolkata", "bengaluru": "bangalore",
        "new delhi": "delhi", "kl": "kuala lumpur",
        "new york city": "new york", "nyc": "new york",
        "denpasar": "bali",
    }
    key = alias_map.get(key, key)
    templates = DEST_ACTIVITIES.get(key, [])
    if not templates:
        print(f"  ⚠️  No curated activities for '{key}'")
    return [
        ActivityOption(name=n, description=d, price=p, location=city, duration=dur)
        for n, d, p, dur in templates
    ]


async def search_activities(city: str) -> List[ActivityOption]:
    print(f"\n🎯 Activities: {city}")
    curated = _activities_for(city)
    if curated:
        print(f"  ✅ {len(curated)} curated activities")
        return curated
    print(f"  ↪ No curated activities — asking LLM")
    return await _llm_activities(city)


async def _llm_activities(city: str) -> List[ActivityOption]:
    prompt = f"""List the top 6 tourist activities in {city}.
For each: name, brief description (1 sentence), approximate price in USD, and duration.
Output ONLY valid JSON array, no markdown:
[{{"name":"...","description":"...","price":"$X USD","duration":"X hours"}}]"""
    try:
        content = await _llm_call(
            prompt,
            system="You are a travel expert. Output ONLY valid JSON arrays, no markdown."
        )
        content = re.sub(r'^```(?:json)?\s*', '', content)
        content = re.sub(r'\s*```$', '', content).strip()
        match = re.search(r'\[.*\]', content, re.DOTALL)
        if match:
            data = json.loads(match.group())
            return [ActivityOption(
                name=item.get("name", "Local Experience"),
                description=item.get("description", "Popular local attraction"),
                price=item.get("price", "Price varies"),
                location=city,
                duration=item.get("duration", "—"),
            ) for item in data[:8]]
    except Exception as e:
        print(f"  ❌ LLM activities failed: {e}")
    return [
        ActivityOption(name="City Walking Tour",
                       description=f"Explore the highlights of {city} with a local guide",
                       price="$20 USD", location=city, duration="3 hours"),
        ActivityOption(name="Local Food Tour",
                       description=f"Sample the best street food and restaurants in {city}",
                       price="$35 USD", location=city, duration="3 hours"),
        ActivityOption(name="Museum Visit",
                       description=f"Discover {city}'s history and culture at the main museum",
                       price="$15 USD", location=city, duration="2 hours"),
    ]


# ─────────────────────────────────────────────────────────────────────────────
# COST COMPUTATION — single source of truth
# ─────────────────────────────────────────────────────────────────────────────

def _compute_costs(
    plan: TravelPlan,
    flights: List[FlightOption],
    hotels: List[HotelOption],
    activities: List[ActivityOption],
    nights: int,
) -> Dict[str, Any]:
    sorted_by_price = sorted(flights, key=lambda f: _to_float(f.price))
    cheapest_flight = sorted_by_price[0] if sorted_by_price else None
    cf_price = _to_float(cheapest_flight.price) if cheapest_flight else 0.0

    # ── FIX #2: best-value uses the user's stated priority ────────────────────
    scored_flights = sorted(flights, key=lambda f: _score_flight(f, plan.price_priority))
    best_value_flight = scored_flights[0] if scored_flights else cheapest_flight

    sorted_hotels = sorted(hotels, key=lambda h: _to_float(h.price_per_night))
    cheapest_hotel = sorted_hotels[0] if sorted_hotels else None
    ch_per_night = _to_float(cheapest_hotel.price_per_night) if cheapest_hotel else 0.0
    hotel_total  = round(ch_per_night * nights, 2)

    act_costs = []
    for a in activities:
        price_val = _to_float(a.price)
        if price_val > 0:
            act_costs.append(price_val)
    act_estimate = round(sum(min(p, 200.0) for p in act_costs[:4]) * plan.adults, 2)
    act_estimate = min(act_estimate, 400.0 * plan.adults)

    total = round(cf_price * plan.adults + hotel_total + act_estimate, 2)

    return {
        "cheapest_flight_obj":   cheapest_flight,
        "best_value_flight_obj": best_value_flight,
        "cheapest_hotel_obj":    cheapest_hotel,
        "flight_price":          cf_price,
        "hotel_per_night":       ch_per_night,
        "hotel_total":           hotel_total,
        "activities_estimate":   act_estimate,
        "total_estimate":        total,
        "nights":                nights,
        "adults":                plan.adults,
    }


def _build_budget_summary(costs: Dict, plan: TravelPlan) -> Optional[Dict]:
    if costs["flight_price"] == 0 and costs["hotel_per_night"] == 0:
        return None
    nights = costs["nights"]
    total  = costs["total_estimate"]
    adults = costs["adults"]
    result = {
        "cheapest_flight":     f"${costs['flight_price']:,.0f}",
        "hotel_per_night":     f"${costs['hotel_per_night']:,.0f}",
        "hotel_total":         f"${costs['hotel_total']:,.0f} ({nights} night{'s' if nights != 1 else ''})",
        "activities_estimate": f"${costs['activities_estimate']:,.0f}",
        "total_estimate":      f"${total:,.0f}",
        "adults":              adults,
        "budget":              f"${plan.total_budget:,.0f}" if plan.total_budget else None,
        "fits":                (total <= plan.total_budget) if plan.total_budget else None,
    }
    return result


# ─────────────────────────────────────────────────────────────────────────────
# NARRATIVE — always references the correctly-scored best flight
# ─────────────────────────────────────────────────────────────────────────────

async def _build_travel_narrative(
    plan: TravelPlan,
    flights: List[FlightOption],
    hotels: List[HotelOption],
    activities: List[ActivityOption],
    costs: Dict,
) -> str:
    nights   = costs["nights"]
    total    = costs["total_estimate"]
    bvf      = costs["best_value_flight_obj"]
    cf       = costs["cheapest_flight_obj"]
    h0       = costs["cheapest_hotel_obj"]
    top_acts = [a.name for a in activities[:4]]

    # ── FIX #7: recommendation justification aligned with price_priority ──────
    if bvf and cf:
        price_diff = _to_float(bvf.price) - _to_float(cf.price)
        quality = AIRLINE_QUALITY.get(bvf.airline, 5)
        bvf_fn_key = _fn_key(bvf.flight_number or "")
        cf_fn_key  = _fn_key(cf.flight_number or "")

        if plan.price_priority == "cheapest":
            flight_why = "It is the most affordable option on this route."
        elif bvf_fn_key == cf_fn_key:
            flight_why = "It is both the most affordable and best-value option available."
        elif quality >= 8 and price_diff > 0:
            flight_why = (
                f"It costs ${price_diff:.0f} more than the cheapest option "
                f"but delivers significantly better service as a top-rated airline."
            )
        elif price_diff <= 0:
            flight_why = "It offers better airline quality at the same or lower price — a clear best pick."
        else:
            flight_why = "It delivers the best overall balance of price, duration, and comfort."
    else:
        flight_why = "It is the best-value option on this route."

    bvf_ctx = (
        f"RECOMMENDED FLIGHT: {bvf.airline} {bvf.flight_number or ''} | "
        f"Price: {bvf.price} | Duration: {bvf.duration} | "
        f"{'Non-stop' if bvf.stops == 0 else str(bvf.stops) + ' stop via ' + (bvf.terminal or 'hub')} | "
        f"Departs: {_hhmm(bvf.departure_time)} → Arrives: {_hhmm(bvf.arrival_time)}. "
        f"Why recommend: {flight_why}"
    ) if bvf else "No flights found."

    h0_ctx = (
        f"BEST VALUE HOTEL: {h0.name} | {h0.category}"
        f"{' | ' + h0.area if h0.area else ''} | {h0.price_per_night}/night"
    ) if h0 else "No hotels found."

    budget_ctx = (
        f"BUDGET: User budget ${plan.total_budget:,.0f} USD | "
        f"{'✅ Fits within budget' if total <= plan.total_budget else '⚠️ Over budget by $' + f'{total - plan.total_budget:,.0f}'}"
        if plan.total_budget else ""
    )

    prompt = f"""You are a world-class travel advisor. Write a warm, expert travel recommendation.

TRIP DETAILS:
Origin: {plan.origin or '?'} → Destination: {plan.destination}
Travel dates: {plan.departure_date} to {plan.return_date} ({nights} nights)
Travellers: {plan.adults} adult(s) | Class: {plan.travel_class or 'Economy'}
User priority: {plan.price_priority}
{budget_ctx}

VERIFIED DATA — use these exact values, copy numbers verbatim:
{bvf_ctx}
{h0_ctx}
Top activities: {', '.join(top_acts) if top_acts else 'various local attractions'}

EXACT COST BREAKDOWN — these exact numbers MUST appear in your response, do not change them:
• Cheapest flight (per person): ${costs['flight_price']:,.0f} USD
• Hotel stay ({nights} nights × ${costs['hotel_per_night']:,.0f}/night): ${costs['hotel_total']:,.0f} USD
• Activities (estimate): ${costs['activities_estimate']:,.0f} USD
• ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• TOTAL ESTIMATE: ${total:,.0f} USD ← copy this EXACTLY

Write ONE fluent paragraph (120–160 words) covering all of the following:
1. The recommended flight (airline, flight number, price, duration, why it's recommended)
2. The best-value hotel (name, area, price/night)
3. The EXACT total estimate: ${total:,.0f} USD
4. 2–3 specific {plan.destination} highlights from the activities list
5. One practical tip for visiting {plan.destination} in {(plan.departure_date or '')[:7]}

RULES: flowing conversational prose, no bullet points, no headers, no markdown,
friendly and confident tone. Use the exact numbers provided above — do NOT invent alternatives."""

    try:
        narrative = await _llm_call(
            prompt,
            system=(
                "You are a friendly expert travel advisor. "
                "Always use the EXACT cost figures provided. No markdown. No bullet points."
            )
        )
        return narrative
    except Exception as e:
        print(f"  ⚠️  LLM narrative failed: {e}")
        if bvf and h0:
            stops_label = "non-stop" if bvf.stops == 0 else f"{bvf.stops}-stop"
            return (
                f"For your {nights}-night trip from {plan.origin or 'your city'} to {plan.destination}, "
                f"we recommend {bvf.airline} {bvf.flight_number or ''} "
                f"({bvf.price}, {bvf.duration}, {stops_label}) "
                f"paired with {h0.name} ({h0.area or h0.category}) "
                f"at {h0.price_per_night}/night. "
                f"The estimated total for this trip is ${total:,.0f} USD. "
                f"Top highlights include {', '.join(top_acts[:2]) if top_acts else 'the local attractions'}."
            )
        return f"Estimated trip total: ${total:,.0f} USD for {nights} nights."


# ─────────────────────────────────────────────────────────────────────────────
# ── FIX #4 + #2: REQUEST PARSING with intent + date detection ────────────────
# ─────────────────────────────────────────────────────────────────────────────

def _detect_price_priority(message: str) -> str:
    """
    Detect user's price intent from their message text.
    "cheapest", "budget", "cheap", "lowest", "most affordable" → "cheapest"
    "best", "premium", "luxury", "comfortable", "business" → "best"
    Default → "balanced"
    """
    msg = message.lower()
    cheapest_signals = [
        "cheapest", "cheap", "budget", "lowest price", "most affordable",
        "least expensive", "best deal", "lowest fare", "minimum price"
    ]
    best_signals = [
        "best airline", "premium", "luxury", "most comfortable", "business class",
        "first class", "top airline", "best quality"
    ]
    for sig in cheapest_signals:
        if sig in msg:
            print(f"  💰 Price priority detected: CHEAPEST (signal: '{sig}')")
            return "cheapest"
    for sig in best_signals:
        if sig in msg:
            print(f"  💰 Price priority detected: BEST (signal: '{sig}')")
            return "best"
    return "balanced"


async def parse_travel_request(user_message: str) -> TravelPlan:
    today = datetime.now()

    # Pre-process: try to resolve natural language dates before LLM
    # so LLM gets explicit date hints
    natural_date_hints = ""
    for phrase, result in [
        ("next weekend", _parse_natural_date("next weekend", today)),
        ("this weekend", _parse_natural_date("this weekend", today)),
        ("next friday",  _parse_natural_date("next friday",  today)),
        ("next saturday", _parse_natural_date("next saturday", today)),
        ("this saturday", _parse_natural_date("this saturday", today)),
        ("tomorrow",     _parse_natural_date("tomorrow",     today)),
    ]:
        if phrase in user_message.lower() and result:
            natural_date_hints += f"\nNote: '{phrase}' resolves to {result}"

    prompt = f"""Extract travel details from this message. Output ONLY valid JSON, no markdown.

Message: "{user_message}"
Today's date: {today.strftime('%Y-%m-%d')} ({today.strftime('%A')})
{natural_date_hints}

Return JSON:
{{
  "origin": "city name or null",
  "destination": "city name",
  "departure_date": "YYYY-MM-DD",
  "return_date": "YYYY-MM-DD or null",
  "duration_days": integer or null,
  "adults": integer (default 1),
  "travel_class": "ECONOMY" or "PREMIUM_ECONOMY" or "BUSINESS" or "FIRST",
  "total_budget": float or null,
  "user_intent": "full_plan" or "flights_only" or "hotels_only" or "activities_only"
}}

Rules:
- If departure_date not specified, use 2 weeks from today
- If return_date not specified but duration given, calculate it
- If "plan", "trip", "visit", "travel", "explore", "with hotels", "with places" → user_intent = "full_plan"
- destination is required; use the most likely city mentioned
- travel_class defaults to "ECONOMY" if not specified
- Use natural date hints above if provided"""

    content = await _llm_call(
        prompt,
        system="You are a JSON extractor. Output ONLY valid JSON, no markdown."
    )
    content = re.sub(r'^```(?:json)?\s*', '', content)
    content = re.sub(r'\s*```$', '', content).strip()
    match = re.search(r'\{.*\}', content, re.DOTALL)
    if match:
        content = match.group()

    plan = TravelPlan.model_validate_json(content)

    if not plan.travel_class:
        plan.travel_class = "ECONOMY"
    plan.travel_class = plan.travel_class.upper()

    # ── Detect price priority from original message ───────────────────────────
    plan.price_priority = _detect_price_priority(user_message)

    # Sanity check dates
    min_dep = today + timedelta(days=1)
    if plan.departure_date:
        try:
            dep_dt = datetime.strptime(plan.departure_date, "%Y-%m-%d")
            if dep_dt < min_dep:
                # Check if natural language date applies
                resolved = None
                for phrase in ["next weekend", "this weekend", "next friday",
                               "next saturday", "this saturday", "tomorrow"]:
                    if phrase in user_message.lower():
                        resolved = _parse_natural_date(phrase, today)
                        break
                plan.departure_date = resolved or (today + timedelta(days=14)).strftime("%Y-%m-%d")
        except ValueError:
            plan.departure_date = (today + timedelta(days=14)).strftime("%Y-%m-%d")
    else:
        plan.departure_date = (today + timedelta(days=14)).strftime("%Y-%m-%d")

    if not plan.return_date:
        dep = datetime.strptime(plan.departure_date, "%Y-%m-%d")
        plan.return_date = (dep + timedelta(days=plan.duration_days or 5)).strftime("%Y-%m-%d")

    print(f"✅ Parsed: {plan.user_intent} | {plan.origin}→{plan.destination} | "
          f"{plan.departure_date}→{plan.return_date} | adults={plan.adults} | "
          f"class={plan.travel_class} | priority={plan.price_priority}")
    return plan


# ─────────────────────────────────────────────────────────────────────────────
# MAIN AGENT
# ─────────────────────────────────────────────────────────────────────────────

def _compute_flight_note(flights: List[FlightOption]) -> str:
    if not flights:
        return "estimated"
    statuses = {f.data_quality for f in flights}
    if "live" in statuses:
        live_count = sum(1 for f in flights if f.data_quality == "live")
        return f"live ({live_count} live, {len(flights)-live_count} estimated)"
    return "estimated"


class TravelAgent:
    async def ainvoke(self, state: dict, config: dict = None) -> dict:
        try:
            from telegram_notifier import notify_itinerary as _notify
        except ImportError:
            _notify = None

        messages      = state.get("messages", [])
        customer_info = state.get("customer_info", {})

        user_msg = ""
        for m in reversed(messages):
            if isinstance(m, HumanMessage):
                user_msg = m.content
                break

        if not user_msg:
            return {
                **state,
                "messages": messages + [AIMessage(
                    content="Hi! I'm your AI travel assistant ✈️ Ask me about flights, hotels, or full trip planning!"
                )],
                "structured_data": None,
            }

        print(f"\n{'='*60}\n📩 User: {user_msg[:120]}\n{'='*60}")

        try:
            plan = await parse_travel_request(user_msg)
        except Exception as e:
            print(f"❌ Parse failed: {e}")
            return {
                **state,
                "messages": messages + [AIMessage(
                    content="I had trouble understanding your request. Try: "
                            "'Flights from Mumbai to Dubai on June 15 for 2 adults'"
                )],
                "structured_data": None,
            }

        if not plan.total_budget and customer_info.get("budget"):
            try:
                plan.total_budget = float(
                    str(customer_info["budget"]).replace("$", "").replace("USD", "").strip()
                )
            except Exception:
                pass

        tasks: Dict[str, Any] = {}

        if plan.user_intent in ["full_plan", "flights_only"] and plan.origin:
            tasks["flights"] = search_flights(
                plan.origin, plan.destination,
                plan.departure_date, plan.return_date,
                plan.adults, plan.travel_class or "ECONOMY",
                price_priority=plan.price_priority,
            )

        if plan.user_intent in ["full_plan", "hotels_only"]:
            tasks["hotels"] = search_hotels(
                plan.destination, plan.departure_date,
                plan.return_date, plan.adults,
            )

        if plan.user_intent in ["full_plan", "activities_only"]:
            tasks["activities"] = search_activities(plan.destination)

        if not tasks:
            msg = f"I found your destination: **{plan.destination}**."
            if not plan.origin:
                msg += " Please tell me your **departure city** so I can search for flights! 🛫"
            return {
                **state,
                "messages": messages + [AIMessage(content=msg)],
                "structured_data": None,
            }

        print(f"\n🔍 Running {len(tasks)} search(es) in parallel...")
        t_start = time.time()
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        print(f"⏱️  Done in {time.time() - t_start:.1f}s")

        flights:    List[FlightOption]   = []
        hotels:     List[HotelOption]    = []
        activities: List[ActivityOption] = []

        for key, result in zip(tasks.keys(), results):
            if isinstance(result, Exception):
                print(f"❌ {key} error: {result}")
            elif key == "flights":    flights    = result
            elif key == "hotels":     hotels     = result
            elif key == "activities": activities = result

        nights = 5
        try:
            if plan.departure_date and plan.return_date:
                nights = max(
                    (datetime.strptime(plan.return_date,    "%Y-%m-%d") -
                     datetime.strptime(plan.departure_date, "%Y-%m-%d")).days,
                    1
                )
        except Exception:
            pass

        costs = _compute_costs(plan, flights, hotels, activities, nights)
        budget_summary = _build_budget_summary(costs, plan)
        narrative = await _build_travel_narrative(plan, flights, hotels, activities, costs)

        if _notify and (flights or hotels):
            try:
                await _notify(plan, flights, hotels, activities)
            except Exception as tg_err:
                print(f"⚠️  Telegram notify failed: {tg_err}")

        flight_note  = _compute_flight_note(flights)
        hotel_source = (
            "live" if hotels and any("Makcorps" in h.source for h in hotels)
            else "curated"
        )

        bvf_fn = (costs["best_value_flight_obj"].flight_number
                  if costs.get("best_value_flight_obj") else None)

        structured_data = {
            "trip": {
                "origin":         plan.origin,
                "destination":    plan.destination,
                "departure_date": plan.departure_date,
                "return_date":    plan.return_date,
                "adults":         plan.adults,
                "travel_class":   plan.travel_class or "ECONOMY",
                "intent":         plan.user_intent,
                "nights":         nights,
                "price_priority": plan.price_priority,
            },
            "flights": [
                {
                    "airline":            f.airline,
                    "flight_number":      f.flight_number or "—",
                    "price":              f.price,
                    "price_numeric":      _to_float(f.price),
                    "departure":          _hhmm(f.departure_time),
                    "arrival":            _hhmm(f.arrival_time),
                    "departure_date":     f.departure_time[:10],
                    "arrival_date":       f.arrival_time[:10],
                    "arrival_day_offset": _day_offset(f.departure_time, f.arrival_time),
                    "duration":           f.duration or "—",
                    "duration_minutes":   f.duration_minutes,
                    "stops":              f.stops,
                    "stops_label": (
                        "Non-stop" if f.stops == 0
                        else f"{f.stops} Stop{'s' if f.stops > 1 else ''}"
                             + (f" {f.terminal}" if f.terminal else "")
                    ),
                    "cabin_class":        f.cabin_class or "Economy",
                    "live_status":        f.live_status or "estimated",
                    "data_quality":       f.data_quality,   # ── FIX #8 ──
                    "terminal":           f.terminal,
                    "airline_logo":       f.airline_logo,
                    "airplane":           f.airplane,
                    "legroom":            f.legroom,
                    "carbon_kg":          f.carbon_kg,
                    "value_score":        round(_score_flight(f, plan.price_priority), 1),
                    "is_best_value":      (
                        _fn_key(f.flight_number or "") == _fn_key(bvf_fn or "")
                        if bvf_fn else False
                    ),
                }
                for f in flights
            ],
            "hotels": [
                {
                    "name":            h.name,
                    "category":        h.category,
                    "price_per_night": h.price_per_night,
                    "price_numeric":   _to_float(h.price_per_night),
                    "rating":          h.rating,
                    "source":          h.source,
                    "vendors":         h.vendors or [],
                    "amenities":       h.amenities,
                    "area":            h.area or "",
                }
                for h in hotels
            ],
            "activities": [
                {
                    "name":          a.name,
                    "description":   a.description,
                    "price":         a.price,
                    "price_numeric": _to_float(a.price),
                    "duration":      a.duration or "—",
                    "is_free":       a.price.lower().startswith("free"),
                }
                for a in activities
            ],
            "recommendation":       narrative,
            "flight_note":          flight_note,
            "hotel_source":         hotel_source,
            "budget_summary":       budget_summary,
            "best_value_flight_fn": bvf_fn,
        }

        intro = (
            f"Here are the results for your trip from **{plan.origin or '?'}** "
            f"to **{plan.destination}** on {plan.departure_date} ✈️"
        )
        if not flights:
            intro += "\n\n⚠️ No flights found — try specifying a different origin city."
        if not hotels:
            intro += "\n\n⚠️ No hotels found for this destination."

        print(f"\n✅ Complete | "
              f"flights={len(flights)} hotels={len(hotels)} activities={len(activities)}")
        if costs.get("best_value_flight_obj"):
            bvf = costs["best_value_flight_obj"]
            off = f" +{_day_offset(bvf.departure_time, bvf.arrival_time)}d" if _day_offset(bvf.departure_time, bvf.arrival_time) else ""
            print(f"  🏆 Best value ({plan.price_priority}): {bvf.airline} {bvf.flight_number} | "
                  f"{bvf.price} | {bvf.duration} | score={_score_flight(bvf, plan.price_priority):.0f} | "
                  f"dep={_hhmm(bvf.departure_time)} arr={_hhmm(bvf.arrival_time)}{off}")
        if costs.get("budget_summary"):
            bs = costs["budget_summary"]
            print(f"  💰 Total: {bs['total_estimate']} | Budget: {bs.get('budget','N/A')} | Fits: {bs.get('fits','N/A')}")

        return {
            **state,
            "messages":        messages + [AIMessage(content=intro)],
            "current_step":    "complete",
            "form_to_display": None,
            "structured_data": structured_data,
        }


def build_enhanced_graph(checkpointer=None):
    agent = TravelAgent()
    print("✅ TravelAgent v6 ready")
    print("   Flights:    SerpAPI(duration gate + price outlier filter) → Mock fallback")
    print("   Date:       Natural language resolver (next weekend, this Saturday, etc.)")
    print("   Intent:     cheapest/balanced/best — ranking and narrative aligned")
    print("   Hotels:     Makcorps(live) → Curated(fixed prices, area tags)")
    print("   Activities: Curated → LLM → Generic fallback (never empty)")
    print("   Costs:      Single _compute_costs() — no duplication possible")
    print("   Duration:   dep + timedelta ONLY — arrival never parsed from strings")
    print("   Dedup:      3-layer (fn key → airline+bucket → max 2/airline)")
    print("   Filtering:  DOMESTIC_ONLY + CORRIDOR_AIRLINES + DURATION GATE + PRICE GATE")
    print("   Data label: data_quality per flight: live | mock")
    return agent


# ─────────────────────────────────────────────────────────────────────────────
# TEST HARNESS
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    async def test():
        agent = build_enhanced_graph()
        queries = [
            # The original failing query — should block SriLankan 26h, show clean results
            "Find me the cheapest flight from Mumbai to Dubai for next weekend with hotels",
            # Standard queries
            "Flights from Mumbai to New York May 7 with hotels and places",
            "Plan 5-day Bali trip from Delhi July 10",
            "Plan a 5-day trip from Kolkata to Madrid starting August 5",
            "Flights from London to Tokyo business class September 1",
            "Plan trip from Mumbai to Paris for June 15, budget $3000",
            "Flights from Mumbai to Zurich for June 20th with hotels and places",
            "Plan trip from Delhi to Singapore June 15th 2 adults budget $4000",
        ]
        for q in queries:
            print(f"\n{'='*70}\nQUERY: {q}\n{'='*70}")
            result = await agent.ainvoke({
                "messages": [HumanMessage(content=q)],
                "customer_info": {}, "is_continuation": False, "current_step": "initial",
            })
            sd = result.get("structured_data", {})
            if sd:
                trip = sd.get("trip", {})
                print(f"\nTrip: {trip.get('origin')}→{trip.get('destination')} | "
                      f"{trip.get('departure_date')} | priority={trip.get('price_priority')}")
                print(f"Flights: {len(sd.get('flights', []))} | "
                      f"Hotels: {len(sd.get('hotels', []))} | "
                      f"Activities: {len(sd.get('activities', []))}")
                for f in sd.get("flights", []):
                    bv  = " ⭐ RECOMMENDED" if f.get("is_best_value") else ""
                    off = f" (+{f['arrival_day_offset']}d)" if f.get("arrival_day_offset") else ""
                    dq  = f" [{f.get('data_quality', '?')}]"
                    print(f"  ✈️  {f['airline']} {f['flight_number']} | "
                          f"{f['price']} | {f['duration']} | "
                          f"{f['stops_label']}{off}{dq}{bv}")
                print()
                for h in sd.get("hotels", []):
                    print(f"  🏨 {h['name']} ({h['category']}) | "
                          f"{h['price_per_night']} | {h.get('area', '')}")
                bs = sd.get("budget_summary", {})
                if bs:
                    print(f"\n  💰 Flight: {bs['cheapest_flight']} | "
                          f"Hotel: {bs['hotel_total']} | "
                          f"Activities: {bs['activities_estimate']} | "
                          f"TOTAL: {bs['total_estimate']}")
                print(f"\n  📝 Narrative:\n{sd.get('recommendation', '')}")

    import asyncio
    asyncio.run(test())