"""
ticket_normalizer.py
────────────────────
Drop this file next to server.py.
Call  normalize_parsed_ticket(raw)  on whatever your pdf_parser returns.

It handles every field-name variant seen across IndiGo, Air India, Emirates,
MakeMyTrip, Cleartrip, EaseMyTrip, Yatra, and generic GDS printouts.
"""
import re
from typing import Any, Dict, Optional
CANONICAL_KEYS = [
    "name",
    "pnr",
    "flight_number",
    "origin",           
    "destination",      # IATA  e.g. "LHR"
    "origin_city",      # Human e.g. "Mumbai"
    "destination_city", # Human e.g. "London"
    "departure_date",   # ISO   e.g. "2026-04-25"
    "departure_time",   # HH:MM e.g. "07:15"
    "confidence",
]
_NAME_ALIASES = {
    # passenger name
    "passenger_name", "passenger", "traveller", "traveler",
    "guest_name", "guest", "pax_name", "pax",
    "full_name", "customer_name", "customer",
}
_PNR_ALIASES = {
    "pnr", "pnr_number", "booking_ref", "booking_reference",
    "reservation_code", "record_locator", "confirmation_code",
    "reference_number", "ref_no", "ticket_ref", "itinerary_ref",
    "locator", "gds_pnr",
}
_FLIGHT_ALIASES = {
    "flight_number", "flight_no", "flight", "flt",
    "flight_code", "flt_no", "flt_number",
    "service_number", "service_no", "operating_flight",
}
_ORIGIN_IATA_ALIASES = {
    "origin", "from", "from_airport", "departure_airport",
    "dep_airport", "origin_airport", "origin_iata",
    "source", "source_airport", "boarding_point",
    "origin_code", "dep_code",
}
_ORIGIN_CITY_ALIASES = {
    "origin_city", "from_city", "departure_city",
    "dep_city", "origin_name", "from_location",
    "source_city", "boarding_city",
}
_DEST_IATA_ALIASES = {
    "destination", "to", "to_airport", "arrival_airport",
    "arr_airport", "destination_airport", "destination_iata",
    "dest", "dest_airport", "destination_code", "arr_code",
}
_DEST_CITY_ALIASES = {
    "destination_city", "to_city", "arrival_city",
    "arr_city", "dest_city", "destination_name",
    "to_location",
}
_DATE_ALIASES = {
    "departure_date", "dep_date", "travel_date",
    "journey_date", "date_of_travel", "flight_date",
    "date", "travel_on", "scheduled_date",
}
_TIME_ALIASES = {
    "departure_time", "dep_time", "flight_time",
    "scheduled_time", "std", "departs_at",
    "time", "departure_at",
}
_CONF_ALIASES = {
    "confidence", "confidence_score", "parse_confidence",
    "accuracy", "score",
}
# Ordered list: (canonical_key, set_of_aliases)
_ALIAS_MAP = [
    ("name",             _NAME_ALIASES),
    ("pnr",              _PNR_ALIASES),
    ("flight_number",    _FLIGHT_ALIASES),
    ("origin",           _ORIGIN_IATA_ALIASES),
    ("destination",      _DEST_IATA_ALIASES),
    ("origin_city",      _ORIGIN_CITY_ALIASES),
    ("destination_city", _DEST_CITY_ALIASES),
    ("departure_date",   _DATE_ALIASES),
    ("departure_time",   _TIME_ALIASES),
    ("confidence",       _CONF_ALIASES),
]


# ── IATA ↔ City lookup (common Indian + international airports) ──────────────
_IATA_TO_CITY: Dict[str, str] = {
    # India
    "BOM": "Mumbai",      "DEL": "Delhi",       "BLR": "Bengaluru",
    "CCU": "Kolkata",     "MAA": "Chennai",      "HYD": "Hyderabad",
    "GOI": "Goa",         "PNQ": "Pune",         "COK": "Kochi",
    "AMD": "Ahmedabad",   "JAI": "Jaipur",       "IXJ": "Jammu",
    "SXR": "Srinagar",    "LKO": "Lucknow",      "VNS": "Varanasi",
    "ATQ": "Amritsar",    "PAT": "Patna",        "GAU": "Guwahati",
    "IXR": "Ranchi",      "RPR": "Raipur",       "NAG": "Nagpur",
    "BHO": "Bhopal",      "IDR": "Indore",       "UDR": "Udaipur",
    "JDH": "Jodhpur",     "BBI": "Bhubaneswar",  "VTZ": "Visakhapatnam",
    "TRV": "Thiruvananthapuram", "CJB": "Coimbatore", "IXC": "Chandigarh",
    # Gulf
    "DXB": "Dubai",       "AUH": "Abu Dhabi",   "DOH": "Doha",
    "RUH": "Riyadh",      "MCT": "Muscat",       "KWI": "Kuwait City",
    # Popular international
    "LHR": "London",      "CDG": "Paris",        "JFK": "New York",
    "SIN": "Singapore",   "BKK": "Bangkok",      "KUL": "Kuala Lumpur",
    "HKG": "Hong Kong",   "NRT": "Tokyo",        "SYD": "Sydney",
    "MEL": "Melbourne",   "YYZ": "Toronto",      "ORD": "Chicago",
    "LAX": "Los Angeles", "DFW": "Dallas",       "MIA": "Miami",
    "FRA": "Frankfurt",   "AMS": "Amsterdam",    "MUC": "Munich",
    "IST": "Istanbul",    "ZRH": "Zurich",       "FCO": "Rome",
    "BCN": "Barcelona",   "MAD": "Madrid",       "LIS": "Lisbon",
    "CPT": "Cape Town",   "NBO": "Nairobi",      "JNB": "Johannesburg",
}

_CITY_TO_IATA: Dict[str, str] = {v.lower(): k for k, v in _IATA_TO_CITY.items()}


# ── Date normalizer ──────────────────────────────────────────────────────────
_MONTH_MAP = {
    "jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,
    "jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12,
    "january":1,"february":2,"march":3,"april":4,"june":6,
    "july":7,"august":8,"september":9,"october":10,"november":11,"december":12,
}

def _normalize_date(raw: Any) -> Optional[str]:
    """Convert any date representation to YYYY-MM-DD, or return None."""
    if not raw:
        return None
    s = str(raw).strip()

    # Already ISO
    if re.match(r'^\d{4}-\d{2}-\d{2}$', s):
        return s

    # DD/MM/YYYY or DD-MM-YYYY
    m = re.match(r'^(\d{1,2})[\/\-\.](\d{1,2})[\/\-\.](\d{4})$', s)
    if m:
        d, mo, y = m.groups()
        return f"{y}-{int(mo):02d}-{int(d):02d}"

    # MM/DD/YYYY (US)
    m = re.match(r'^(\d{1,2})[\/\-\.](\d{1,2})[\/\-\.](\d{4})$', s)
    # (handled above — we default to DD/MM/YYYY for aviation context)

    # YYYY/MM/DD
    m = re.match(r'^(\d{4})[\/\-\.](\d{2})[\/\-\.](\d{2})$', s)
    if m:
        y, mo, d = m.groups()
        return f"{y}-{int(mo):02d}-{int(d):02d}"

    # "24 Oct 2019" / "Oct 24, 2019" / "24-Oct-2019"
    m = re.match(r'^(\d{1,2})[\s\-]+([A-Za-z]{3,9})[\s\-,]+(\d{4})$', s)
    if m:
        d, mon, y = m.groups()
        mo = _MONTH_MAP.get(mon.lower())
        if mo:
            return f"{y}-{mo:02d}-{int(d):02d}"

    m = re.match(r'^([A-Za-z]{3,9})[\s\-]+(\d{1,2})[\s,]+(\d{4})$', s)
    if m:
        mon, d, y = m.groups()
        mo = _MONTH_MAP.get(mon.lower())
        if mo:
            return f"{y}-{mo:02d}-{int(d):02d}"

    return s  # return as-is if we can't parse


def _normalize_time(raw: Any) -> Optional[str]:
    """Return HH:MM or None."""
    if not raw:
        return None
    s = str(raw).strip()
    m = re.search(r'(\d{1,2})[:\.](\d{2})(?:\s*(AM|PM))?', s, re.IGNORECASE)
    if m:
        h, mi, ampm = m.groups()
        h, mi = int(h), int(mi)
        if ampm:
            if ampm.upper() == 'PM' and h != 12:
                h += 12
            elif ampm.upper() == 'AM' and h == 12:
                h = 0
        return f"{h:02d}:{mi:02d}"
    return s


def _normalize_iata(raw: Any) -> Optional[str]:
    """Return 3-letter IATA code (upper) or None."""
    if not raw:
        return None
    s = str(raw).strip().upper()
    if re.match(r'^[A-Z]{3}$', s):
        return s
    # Try city name → IATA
    iata = _CITY_TO_IATA.get(s.lower())
    return iata or s or None


def _normalize_flight_number(raw: Any) -> Optional[str]:
    """Normalise to e.g. '6E-2045' or 'AI-302'."""
    if not raw:
        return None
    s = str(raw).strip().upper()
    # Already formatted  e.g. "6E-2045" "AI 302"
    m = re.match(r'^([A-Z0-9]{2,3})[\s\-]?(\d{1,5})$', s)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return s


def _normalize_pnr(raw: Any) -> Optional[str]:
    if not raw:
        return None
    s = str(raw).strip().upper()
    # Strip common surrounding noise
    s = re.sub(r'[^A-Z0-9]', '', s)
    return s if s else None


def _normalize_name(raw: Any) -> Optional[str]:
    if not raw:
        return None
    s = str(raw).strip()
    # Remove trailing noise like "From" that some parsers append
    s = re.sub(r'\s+(from|to|via)\s*$', '', s, flags=re.IGNORECASE).strip()
    # Remove titles if they cause double-up
    # (keep title but strip repeated spaces)
    s = re.sub(r'\s{2,}', ' ', s)
    return s if s else None


# ── Main normalizer ──────────────────────────────────────────────────────────

def normalize_parsed_ticket(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Accept any dict from pdf_parser and return a dict with exactly the
    canonical keys that server.py and the React frontend expect.

    Fields not found are returned as None (server.py already has fallbacks).
    """
    # Lower-case all incoming keys for case-insensitive matching
    lowered = {k.lower().strip(): v for k, v in raw.items()}

    out: Dict[str, Any] = {k: None for k in CANONICAL_KEYS}

    for canonical, aliases in _ALIAS_MAP:
        # Check canonical key first, then aliases
        for key in [canonical] + list(aliases):
            val = lowered.get(key)
            if val is not None and str(val).strip() not in ("", "null", "none", "—", "-"):
                out[canonical] = val
                break

    # ── Type-specific normalization ──────────────────────────────────────────
    out["name"]          = _normalize_name(out["name"])
    out["pnr"]           = _normalize_pnr(out["pnr"])
    out["flight_number"] = _normalize_flight_number(out["flight_number"])
    out["departure_date"]= _normalize_date(out["departure_date"])
    out["departure_time"]= _normalize_time(out["departure_time"])

    # IATA codes
    out["origin"]      = _normalize_iata(out["origin"])
    out["destination"] = _normalize_iata(out["destination"])

    # Auto-fill city from IATA if city is missing
    if out["origin"] and not out["origin_city"]:
        out["origin_city"] = _IATA_TO_CITY.get(out["origin"])
    if out["destination"] and not out["destination_city"]:
        out["destination_city"] = _IATA_TO_CITY.get(out["destination"])

    if out["origin_city"] and not out["origin"]:
        out["origin"] = _CITY_TO_IATA.get(out["origin_city"].lower())
    if out["destination_city"] and not out["destination"]:
        out["destination"] = _CITY_TO_IATA.get(out["destination_city"].lower())

    try:
        c = float(out["confidence"] or 0)
        out["confidence"] = min(max(c, 0.0), 1.0)
    except (TypeError, ValueError):
        out["confidence"] = 0.0

    return out