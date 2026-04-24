"""
pdf_parser.py — Flight Ticket PDF + Image Parser v6
Handles: Yatra, Air India, IndiGo, Emirates, Qatar, SpiceJet, MakeMyTrip, Cleartrip
Image support: JPG, JPEG, PNG, WEBP, BMP via Google Cloud Vision API (free tier: 1000/month)

Key fixes vs v5:
  - FIX #6: PNR pattern now matches "Booking reference no (PNR): JBT5M (AI)" —
             parenthesised suffix like "(AI)" is consumed so it never bleeds into value.
  - FIX #7: Name "MR DHANANJAY PAWAR" no longer appends "AI" from trailing ticket-number
             line.  The ALL-CAPS slash pattern now strips everything after the value
             including any trailing "(AI)" or standalone two-letter suffix.
  - FIX #8: Origin / Destination: "NA" is now explicitly in SKIP_IATA so the table
             header row "NA – NA" is skipped; also IATA pair scan now skips rows where
             both codes are identical or where either is in SKIP_IATA.
  - FIX #9: Departure date: Added "Issued date" / "Issue date" / "Issued on" as a
             suppressed prefix so those dates are never returned as the travel date.
             Travel-date patterns are tried first; issue-date is stripped from the
             candidate text before fallback date extraction runs.
  - FIX #10: "Booking reference no (PNR)" label (Air India style) added to PNR
             label patterns so JBT5M is captured correctly.
"""
import re
import os
import io
import base64
import requests
from typing import Optional, Dict, Any, Tuple, List
from datetime import datetime

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── pdfplumber (PDF parsing) ──────────────────────────────────────────────────
try:
    import pdfplumber
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False
    print("⚠️  pdfplumber not installed — run: pip install pdfplumber")

# ── Pillow (image preprocessing) ─────────────────────────────────────────────
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("⚠️  Pillow not installed — run: pip install Pillow")
# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────
GOOGLE_VISION_API_KEY = os.getenv("GOOGLE_VISION_API_KEY", "")
SUPPORTED_IMAGE_TYPES = {
    '.jpg':  'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png':  'image/png',
    '.webp': 'image/webp',
    '.gif':  'image/gif',
    '.bmp':  'image/bmp',
}
# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────
IATA_TO_CITY: Dict[str, str] = {
    "BOM": "Mumbai",        "DEL": "Delhi",         "BLR": "Bangalore",
    "CCU": "Kolkata",       "MAA": "Chennai",        "HYD": "Hyderabad",
    "GOI": "Goa",           "PNQ": "Pune",           "COK": "Kochi",
    "AMD": "Ahmedabad",     "JAI": "Jaipur",         "IXJ": "Jammu",
    "SXR": "Srinagar",      "LKO": "Lucknow",        "VNS": "Varanasi",
    "ATQ": "Amritsar",      "PAT": "Patna",          "GAU": "Guwahati",
    "IXR": "Ranchi",        "RPR": "Raipur",         "NAG": "Nagpur",
    "BHO": "Bhopal",        "IDR": "Indore",         "UDR": "Udaipur",
    "JDH": "Jodhpur",       "BBI": "Bhubaneswar",
    "VTZ": "Visakhapatnam",
    "TRV": "Trivandrum",    "CJB": "Coimbatore",     "IXC": "Chandigarh",
    "DXB": "Dubai",         "AUH": "Abu Dhabi",      "DOH": "Doha",
    "RUH": "Riyadh",        "MCT": "Muscat",         "KWI": "Kuwait",
    "SIN": "Singapore",     "BKK": "Bangkok",        "KUL": "Kuala Lumpur",
    "DPS": "Bali",          "HKT": "Phuket",         "CGK": "Jakarta",
    "MNL": "Manila",        "SGN": "Ho Chi Minh",    "HAN": "Hanoi",
    "NRT": "Tokyo",         "KIX": "Osaka",          "ICN": "Seoul",
    "PEK": "Beijing",       "PVG": "Shanghai",       "HKG": "Hong Kong",
    "TPE": "Taipei",
    "LHR": "London",        "CDG": "Paris",          "FRA": "Frankfurt",
    "AMS": "Amsterdam",     "FCO": "Rome",           "MAD": "Madrid",
    "BCN": "Barcelona",     "ZRH": "Zurich",         "VIE": "Vienna",
    "IST": "Istanbul",      "ATH": "Athens",         "MUC": "Munich",
    "BER": "Berlin",        "PRG": "Prague",         "WAW": "Warsaw",
    "LIS": "Lisbon",        "DUB": "Dublin",
    "JFK": "New York",      "LAX": "Los Angeles",    "ORD": "Chicago",
    "MIA": "Miami",         "SFO": "San Francisco",  "BOS": "Boston",
    "ATL": "Atlanta",       "DFW": "Dallas",         "SEA": "Seattle",
    "YYZ": "Toronto",       "YVR": "Vancouver",
    "SYD": "Sydney",        "MEL": "Melbourne",      "BNE": "Brisbane",
    "JNB": "Johannesburg",  "CPT": "Cape Town",      "NBO": "Nairobi",
    "CAI": "Cairo",
}

AIRLINE_CODES: Dict[str, str] = {
    "AI": "Air India",       "6E": "IndiGo",          "SG": "SpiceJet",
    "UK": "Vistara",         "QP": "Akasa Air",       "G8": "Go First",
    "I5": "AirAsia India",   "EK": "Emirates",        "QR": "Qatar Airways",
    "EY": "Etihad",          "FZ": "Flydubai",        "G9": "Air Arabia",
    "WY": "Oman Air",        "SQ": "Singapore Airlines", "TG": "Thai Airways",
    "AK": "AirAsia",         "MH": "Malaysia Airlines",  "VN": "Vietnam Airlines",
    "CX": "Cathay Pacific",  "JL": "Japan Airlines",  "NH": "ANA",
    "KE": "Korean Air",      "BA": "British Airways", "LH": "Lufthansa",
    "AF": "Air France",      "KL": "KLM",             "TK": "Turkish Airlines",
    "VS": "Virgin Atlantic", "LX": "SWISS",           "IB": "Iberia",
    "DL": "Delta",           "UA": "United Airlines", "AA": "American Airlines",
    "QF": "Qantas",          "ET": "Ethiopian Airlines", "MS": "EgyptAir",
}

# Known OTA reference number patterns to SKIP (not real PNRs)
OTA_REF_PATTERN = re.compile(r'^\d{8,}$|^NF\d{6,}$', re.IGNORECASE)

# Words that must never be treated as PNR values
PNR_SKIP_WORDS = {
    "NUMBER", "BOOKING", "REFERENCE", "CONFIRM", "DETAILS", "TICKET",
    "FLIGHT", "ITINERARY", "PASSENGER", "TRAVELLER", "RECEIPT", "ETICKET",
    "INVOICE", "SUMMARY", "STATUS", "CONTACT", "SUPPORT", "CANCELLATION",
}

# English stopwords / non-IATA codes
# FIX #8: Added "NA" explicitly so table header "NA" cells are always skipped
SKIP_IATA = {
    "THE", "ARE", "FOR", "AND", "BUT", "NOT", "YOU", "ALL", "CAN",
    "HER", "WAS", "ONE", "OUR", "OUT", "WHO", "ITS", "HAS", "HAD",
    "HIM", "HIS", "HOW", "MAN", "NEW", "NOW", "OLD", "SEE", "TWO",
    "WAY", "BOY", "DID", "GET", "MAY", "SAY", "USE", "WAR", "ETA",
    "ETD", "STD", "STA", "REF", "PNR", "OTA", "PDF", "UTC", "GMT",
    "INR", "USD", "EUR", "GBP", "TAX", "VAT", "GST", "TDS", "NET",
    "NAT", "NON", "PRE", "PRO", "PER", "SUB", "SUM", "TAB", "TOP",
    "AIR", "FLY", "JET", "SKY", "VIA", "WEB", "YES", "AGE", "AGO",
    "MMT", "NRI", "DOM", "SAT", "FRI", "MON", "TUE", "WED", "THU",
    "SUN", "ADT", "CHD", "INF", "PAX", "DEP", "ARR", "DUR",
    "NON", "STOP", "HRS",
    # FIX #8: "NA" is a table filler, never a real IATA code
    "NA", "N/A",
}

# Brand/company names that must never be matched as city or destination
BRAND_SKIP = {
    "makemytrip", "yatra", "cleartrip", "ixigo", "goibibo",
    "indigo", "spicejet", "vistara", "airindia", "akasa",
    "emirates", "etihad", "flydubai",
}
# ── FIX #11: Labeled-city helpers for interleaved-column boarding passes ──────
_FROM_TO_STOP = r'(?:To|From|Flight|Date|Boarding|PNR|Name|Flt|Seat|Seq|Gate|Class|Departure|Arrival|Sequence)'

# REPLACE the entire _labeled_city function with this:

def _labeled_city(text: str, label: str, city_to_iata_map: dict) -> Optional[str]:
    """
    Extract city name after a 'From :' or 'To :' label.
    Handles pdfplumber interleaved-column output and single-space separation.
    """
    # Strategy 1: end-of-line — highest priority
    p_eol = rf'(?:^|\s){label}\s*[:\-]\s*([A-Z][a-zA-Z]+(?:[ \t]+[A-Za-z]+)*)[ \t]*(?:\n|$)'
    for m in re.finditer(p_eol, text, re.IGNORECASE | re.MULTILINE):
        city = m.group(1).strip()
        if city.lower() in city_to_iata_map:
            return city

    # Strategy 2: inline before another label keyword (relaxed spacing: 1+ spaces)
    # FIX: Changed \s+ to allow single space before stop word (was requiring \s{2,})
    _stop_rx = rf'(?:{_FROM_TO_STOP})'
    p_inline = rf'\b{label}\s*[:\-]\s*([A-Z][a-zA-Z]+(?:[ \t]+[A-Za-z]+)*?)[ \t]+(?={_stop_rx}\s*[:\-# ])'
    for m in re.finditer(p_inline, text, re.IGNORECASE | re.MULTILINE):
        city = m.group(1).strip()
        if city.lower() in city_to_iata_map:
            return city

    # Strategy 3: greedy grab to end of line then trim trailing junk
    p_greedy = rf'\b{label}\s*[:\-]\s*([A-Z][a-zA-Z ]+?)(?:\s{{2,}}|\t|(?=\s+{_stop_rx})|\n|$)'
    for m in re.finditer(p_greedy, text, re.IGNORECASE | re.MULTILINE):
        city = m.group(1).strip()
        if city.lower() in city_to_iata_map:
            return city

    return None

def _city_str_to_iata(city: str, city_to_iata_map: dict) -> Optional[str]:
    if not city:
        return None
    c = city.lower().strip()
    if c in city_to_iata_map:
        return city_to_iata_map[c]
    for k, v in city_to_iata_map.items():
        if k in c or c in k:
            return v
    return None
# FIX #1: Field-label words that must terminate a passenger name match
NAME_STOP_WORDS = (
    "From", "To", "Date", "Flight", "PNR", "Seat", "Gate",
    "Board", "Depart", "Arriv", "Class", "Seq", "Time", "No",
    "Booking", "Ticket", "E-Ticket", "Status", "Ref",
)

# FIX #9: Patterns for dates that are ISSUE/BOOKING dates, not travel dates.
# We strip lines matching these before falling back to generic date extraction.
ISSUE_DATE_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r'(?:Issued?|Issue)\s*(?:date|on|:)\s*[\w,\s]+\d{4}',
        r'Booking\s*Date\s*[-:\s]+[\w,\s]+\d{4}',
        r'Purchase\s*Date\s*[-:\s]+[\w,\s]+\d{4}',
        r'Date\s*of\s*Issue\s*[-:\s]+[\w,\s]+\d{4}',
    ]
]


# ─────────────────────────────────────────────────────────────────────────────
# TEXT CLEANING
# ─────────────────────────────────────────────────────────────────────────────

def _clean(text: str) -> str:
    text = re.sub(r'\r\n|\r', '\n', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _lines(text: str) -> List[str]:
    return [l.strip() for l in text.splitlines() if l.strip()]


# ─────────────────────────────────────────────────────────────────────────────
# OTA DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def _detect_ota(text: str) -> str:
    """Returns: 'yatra' | 'makemytrip' | 'cleartrip' | 'ixigo' | 'airline' | 'unknown'"""
    tl = text.lower()
    if 'yatra' in tl or 'yatra ref' in tl:
        return 'yatra'
    if 'makemytrip' in tl or 'mmt' in tl:
        return 'makemytrip'
    if 'cleartrip' in tl:
        return 'cleartrip'
    if 'ixigo' in tl:
        return 'ixigo'
    for airline in ['air india', 'indigo', 'spicejet', 'vistara', 'emirates',
                    'qatar airways', 'etihad', 'singapore airlines']:
        if airline in tl:
            return 'airline'
    return 'unknown'
# ─────────────────────────────────────────────────────────────────────────────
# FIELD EXTRACTORS
# ─────────────────────────────────────────────────────────────────────────────
def _is_valid_pnr(val: str) -> bool:
    """
    Strict PNR validation.
    - Must be 5-8 chars, start with a letter
    - Must not be a known label word
    - Must not match OTA booking ID pattern
    - Must contain at least one letter (not all digits)
    """
    val = val.strip().upper()
    if not val:
        return False
    if OTA_REF_PATTERN.match(val):
        return False
    if val in SKIP_IATA:
        return False
    if val in PNR_SKIP_WORDS:
        return False
    if not re.match(r'^[A-Z]', val):
        return False
    if not re.search(r'[A-Z]', val):
        return False
    if len(val) < 5 or len(val) > 8:
        return False
    return True


def _extract_pnr(text: str, ota: str) -> Optional[str]:
    # "Airline PNR" column label — strongest signal (MakeMyTrip table format)
    airline_pnr_pattern = re.compile(
        r'Airline\s*PNR\s*[:\-\|]?\s*([A-Z0-9]{5,8})\b',
        re.IGNORECASE
    )
    m = airline_pnr_pattern.search(text)
    if m:
        val = m.group(1).strip().upper()
        if _is_valid_pnr(val):
            return val

    # Standard PNR label patterns
    # FIX #10: Added Air India style "Booking reference no (PNR):" pattern.
    # The (?:\s*\([^)]*\))? suffix consumes optional trailing "(AI)" etc.
    pnr_label_patterns = [
        # Air India: "Booking reference no (PNR): JBT5M (AI)"
        r'Booking\s+reference\s+no\s*\(PNR\)\s*[:\-]?\s*([A-Z][A-Z0-9]{4,7})\b(?:\s*\([^)]{1,10}\))?',
        r'PNR\s*\n\s*([A-Z0-9]{5,8})\b',
        r'\bPNR\s*[:\-\|]\s*([A-Z][A-Z0-9]{4,7})\b',
        r'PNR\s*/\s*Booking\s*Ref[:\s]+([A-Z][A-Z0-9]{4,7})\b',
    ]
    for p in pnr_label_patterns:
        m = re.search(p, text, re.IGNORECASE | re.MULTILINE)
        if m:
            val = m.group(1).strip().upper()
            if _is_valid_pnr(val):
                return val

    # Booking reference patterns
    booking_ref_patterns = [
        r'(?:Booking\s*(?:Ref(?:erence)?|Code)|Record\s*Locator|Confirmation\s*(?:Code|No\.?))\s*[:\-]?\s*([A-Z][A-Z0-9]{4,7})\b',
        r'Reference\s*(?:No\.?|Number)?\s*[:\-]?\s*([A-Z][A-Z0-9]{4,7})\b',
    ]
    for p in booking_ref_patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            val = m.group(1).strip().upper()
            if _is_valid_pnr(val):
                return val

    # Last resort: scan for 6-char alphanumeric tokens with mixed letters+digits
    candidates = re.findall(r'\b([A-Z][A-Z0-9]{5})\b', text)
    for c in candidates:
        if _is_valid_pnr(c) and re.search(r'\d', c) and re.search(r'[A-Z]', c):
            return c

    return None


def _extract_name(text: str, ota: str) -> Optional[str]:
    name = None

    # Build lookahead that stops at field-label words
    _stop = '|'.join(NAME_STOP_WORDS)
    _stop_lookahead = rf'(?=\s*\n|\s{{2,}}|\s+(?:{_stop})\b|[:\|]|$)'

    # ── Priority 1: Title-based (Mr/Mrs/Ms/Dr etc.) ──────────────────────────
    title_pattern = re.compile(
        rf'\b(Mr\.?|Mrs\.?|Ms\.?|Miss\.?|Dr\.?|Shri|Smt)\s+'
        rf'([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){{1,3}}?)'
        rf'{_stop_lookahead}',
        re.IGNORECASE
    )
    m = title_pattern.search(text)
    if m:
        name = f"{m.group(1).rstrip('.')}. {m.group(2).strip()}"
        name = re.sub(r'\s+', ' ', name).strip()

    # ── Priority 2: Explicit "Name :" label (IndiGo boarding pass style) ─────
    if not name:
        name_label_pattern = re.compile(
            r'(?:^|\n)\s*Name\s*[:\-]\s*([A-Z][A-Za-z\s\.]{3,40})',
            re.IGNORECASE | re.MULTILINE
        )
        m = name_label_pattern.search(text)
        if m:
            candidate = m.group(1).strip()
            candidate = re.sub(
                r'\s+(?:' + _stop + r')\b.*$', '', candidate, flags=re.IGNORECASE
            ).strip()
            if len(candidate) > 4:
                name = candidate

    # ── Priority 3: Explicit passenger label ─────────────────────────────────
    if not name:
        pax_patterns = [
            r'Passenger(?:\s*Name)?\s*[:\-]\s*([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){1,3})',
            r'PAX(?:\s*Name)?\s*[:\-]\s*([A-Z][A-Za-z\s/\.]{3,40})',
            r'Travelling\s*as\s*[:\-]\s*([A-Z][A-Za-z\s/\.]{3,40})',
        ]
        for p in pax_patterns:
            m = re.search(p, text, re.IGNORECASE | re.MULTILINE)
            if m:
                name = m.group(1).strip()
                break

    # ── Priority 4: ALL-CAPS surname/firstname format (airline direct tickets) ─
    # FIX #7: Strip trailing two-letter airline suffixes like "(AI)" or bare "AI"
    # that can appear on the same line as the passenger name on Air India tickets.
    if not name:
        caps_patterns = [
            r'NAME\s*[:\-]?\s*([A-Z]{2,20}/[A-Z]{2,20}(?:\s+MR|MRS|MS)?)',
            r'\b([A-Z]{2,20})\s*/\s*([A-Z]{2,20})\s*(?:MR|MRS|MS|MISS)?\b',
        ]
        for p in caps_patterns:
            m = re.search(p, text, re.MULTILINE)
            if m:
                if '/' in m.group(0):
                    parts = m.group(0).split('/')
                    surname = parts[0].strip().title()
                    firstname = re.sub(
                        r'\s*(MR|MRS|MS|MISS).*$', '', parts[1], flags=re.IGNORECASE
                    ).strip().title()
                    name = f"{firstname} {surname}"
                else:
                    name = m.group(1).title()
                break

    # ── Priority 5: "Dear FirstName LastName" greeting ───────────────────────
    if not name:
        m = re.search(r'Dear\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)', text)
        if m:
            name = m.group(1).strip()

    # ── Priority 6: MakeMyTrip table format ──────────────────────────────────
    if not name:
        mmt_name_patterns = [
            r'(?:Passenger Name|Name)\s*\n\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\s*\n',
            r'([A-Z][a-z]+\s+[A-Z][a-z]+)\s+(?:Adult|Child|Infant)\s+[A-Z0-9]{5,8}',
        ]
        for p in mmt_name_patterns:
            m = re.search(p, text, re.MULTILINE)
            if m:
                candidate = m.group(1).strip()
                if candidate.lower() not in BRAND_SKIP and len(candidate) > 4:
                    name = candidate
                    break

    # ── Final cleanup ─────────────────────────────────────────────────────────
    if name:
        # Remove trailing label words and anything after them
        name = re.sub(
            rf'\s+(?:{_stop})\b.*$',
            '', name, flags=re.IGNORECASE
        ).strip()
        name = re.sub(
            r'\s*[\(\[].*$|'
            r'\s+(Adult|Child|Infant|Mr|Mrs|Ms)\b.*$',
            '', name, flags=re.IGNORECASE
        ).strip()
        # FIX #7: Remove trailing standalone airline IATA codes like " AI", " EK" etc.
        # that may appear after a name on the same text line (e.g. "DHANANJAY PAWAR AI")
        name = re.sub(
            r'\s+(?:' + '|'.join(AIRLINE_CODES.keys()) + r')\s*$',
            '', name, flags=re.IGNORECASE
        ).strip()
        name = re.sub(r'\s+', ' ', name)
        parts = name.split()
        name = ' '.join(parts[:4]) if len(parts) > 4 else name
        name = name.title()
        if len(name) < 5 or ' ' not in name:
            name = None

    return name


def _extract_airline_and_flight(text: str) -> Tuple[Optional[str], Optional[str]]:
    airline_name = None
    flight_number = None

    airline_name_map = {
        'vistara':              'Vistara',
        'indigo':               'IndiGo',
        'air india express':    'Air India Express',
        'air india':            'Air India',
        'spicejet':             'SpiceJet',
        'go first':             'Go First',
        'goair':                'GoAir',
        'akasa':                'Akasa Air',
        'airasia india':        'AirAsia India',
        'emirates':             'Emirates',
        'qatar airways':        'Qatar Airways',
        'etihad':               'Etihad Airways',
        'singapore airlines':   'Singapore Airlines',
        'thai airways':         'Thai Airways',
        'malaysia airlines':    'Malaysia Airlines',
        'british airways':      'British Airways',
        'lufthansa':            'Lufthansa',
        'air france':           'Air France',
        'klm':                  'KLM',
        'turkish airlines':     'Turkish Airlines',
        'united airlines':      'United Airlines',
        'american airlines':    'American Airlines',
        'delta':                'Delta',
        'flydubai':             'flydubai',
        'air arabia':           'Air Arabia',
        'oman air':             'Oman Air',
    }
    text_lower = text.lower()
    for key, display in airline_name_map.items():
        if key in text_lower:
            airline_name = display
            break

    flight_patterns = [
        (r'(?:Flt#?|Flight\s*No\.?)\s*[:\-]?\s*([A-Z0-9]{1,2})\s*[-–]?\s*(\d{2,4}[A-Z]?)\b', 2),
        (r'\b([A-Z0-9]{1,2})\s*[-–]\s*(\d{2,4}[A-Z]?)\b', 2),
        (r'\b(6E|AI|SG|UK|QP|G8|I5|EK|QR|EY|FZ|G9|WY|SQ|TG|AK|MH|VN|CX|JL|NH|KE|BA|LH|AF|KL|TK|VS|LX|IB|DL|UA|AA|QF|ET|MS)\s+(\d{3,4}[A-Z]?)\b', 2),
        (r'\b([A-Z]{2})\s+(\d{3,4}[A-Z]?)\b', 2),
    ]

    for p, ngroups in flight_patterns:
        for m in re.finditer(p, text, re.IGNORECASE | re.MULTILINE):
            code = m.group(1).upper().replace(' ', '').replace('-', '')
            num  = m.group(2).upper()
            if code in AIRLINE_CODES or re.match(r'^[A-Z]{2}$', code) or re.match(r'^[A-Z]\d$', code):
                flight_number = f"{code}{num}"
                if not airline_name and code in AIRLINE_CODES:
                    airline_name = AIRLINE_CODES[code]
                break
        if flight_number:
            break

    return airline_name, flight_number


def _extract_route(text: str) -> Tuple[Optional[str], Optional[str]]:
    origin = destination = None
    city_to_iata = {
        re.sub(r'\s+', ' ', v.lower().strip()): k
        for k, v in IATA_TO_CITY.items()
    }

    # ── Pass 0: FIX #11 — extract From/To as independent labeled fields ───────
    # Handles pdfplumber interleaving columns (boarding pass table layout)
    o_city_str = _labeled_city(text, "From", city_to_iata)
    d_city_str = _labeled_city(text, "To",   city_to_iata)
    if o_city_str:
        origin      = _city_str_to_iata(o_city_str, city_to_iata)
    if d_city_str:
        destination = _city_str_to_iata(d_city_str, city_to_iata)
    if origin and destination:
        return origin, destination
    # ── Pass 0.5: Full-line "From : CityName    To : CityName" on same line ──
    # Handles pdfplumber output where both labels land on one line with spaces
    same_line_pat = re.compile(
        r'From\s*[:\-]\s*([A-Z][a-zA-Z]+(?:[ \t]+[A-Za-z]+)*)'
        r'[ \t]+'
        r'To\s*[:\-]\s*([A-Z][a-zA-Z]+(?:[ \t]+[A-Za-z]+)*)',
        re.IGNORECASE
    )
    for m in same_line_pat.finditer(text):
        o_city = re.sub(r'\s+', ' ', m.group(1).strip().lower())
        d_city = re.sub(r'\s+', ' ', m.group(2).strip().lower())
        _o = city_to_iata.get(o_city)
        _d = city_to_iata.get(d_city)
        # Partial match fallback
        if not _o:
            for k, v in city_to_iata.items():
                if k in o_city or o_city in k:
                    _o = v; break
        if not _d:
            for k, v in city_to_iata.items():
                if k in d_city or d_city in k:
                    _d = v; break
        if _o and _d and _o != _d:
            return _o, _d
    # ─────────────────────────────────────────────────────────────────────────
    iata_pair_patterns = [
        r'\b([A-Z]{3})\s*[-–—→/]\s*([A-Z]{3})\b',
        r'From\s*[:\-]?\s*([A-Z]{3})\s+To\s*[:\-]?\s*([A-Z]{3})',
        r'Departure\s*[:\-]?\s*([A-Z]{3}).{0,50}Arrival\s*[:\-]?\s*([A-Z]{3})',
    ]
    for p in iata_pair_patterns:
        for m in re.finditer(p, text, re.IGNORECASE | re.MULTILINE):
            o = m.group(1).upper()
            d = m.group(2).upper()
            # FIX #8: skip if either code is in SKIP_IATA (covers "NA", "DEP", etc.)
            if o in SKIP_IATA or d in SKIP_IATA:
                continue
            if o == d:
                continue
            if o in IATA_TO_CITY or d in IATA_TO_CITY:
                origin, destination = o, d
                return origin, destination

    # ── Pass 2: IATA codes in parentheses e.g. "Mumbai (BOM)" ─────────────────
    iata_in_parens = re.findall(r'\(([A-Z]{3})\)', text)
    valid_iata = [c for c in iata_in_parens if c in IATA_TO_CITY and c not in SKIP_IATA]
    if len(valid_iata) >= 2:
        return valid_iata[0], valid_iata[1]

    # ── Pass 3: City name → IATA lookup ──────────────────────────────────────
    city_pair_patterns = [
        # FIX: allow single-space termination (pdfplumber inline column output)
        r'From\s*[:\-]?\s*([A-Z][a-zA-Z]+(?:\s[A-Za-z]+)*?)\s+To\s*[:\-]?\s*([A-Z][a-zA-Z]+(?:\s[A-Za-z]+)*)(?:\s{2,}|\t|\n|$)',
        # Fallback: single-space before To is OK if followed by colon/dash
        r'From\s*[:\-]\s*([A-Z][a-zA-Z]+(?:[ \t][A-Za-z]+)*?)[ \t]+To\s*[:\-]\s*([A-Z][a-zA-Z]+(?:[ \t][A-Za-z]+)*)',
        r'(?:From|Departing)\s*[:\-]?\s*([A-Z][a-zA-Z\s]+?)\s+(?:To|Arriving)\s*[:\-]?\s*([A-Z][a-zA-Z\s]+?)(?:\n|$)',
        r'([A-Z][a-zA-Z\s]+?)\s*(?:→|to|TO)\s*([A-Z][a-zA-Z\s]+?)(?:\n|$|\s{2,})',
    ]

    city_to_iata = {
        re.sub(r'\s+', ' ', v.lower().strip()): k
        for k, v in IATA_TO_CITY.items()
    }

    for p in city_pair_patterns:
        m = re.search(p, text, re.MULTILINE | re.IGNORECASE)
        if m:
            o_city = re.sub(r'\s+', ' ', m.group(1).strip().lower())
            d_city = re.sub(r'\s+', ' ', m.group(2).strip().lower())

            if o_city in BRAND_SKIP or d_city in BRAND_SKIP:
                continue

            for city, iata in city_to_iata.items():
                if city in o_city and not origin:
                    origin = iata
                if city in d_city and not destination:
                    destination = iata

            if origin and destination and origin != destination:
                return origin, destination

            if not origin:
                origin = m.group(1).strip()
            if not destination:
                destination = m.group(2).strip()
            if origin and destination:
                return origin, destination

    return origin, destination


def _strip_issue_dates(text: str) -> str:
    """
    FIX #9: Remove lines that contain issue/booking dates so the generic
    date extractor cannot accidentally return the ticket-issue date
    instead of the actual travel/departure date.
    """
    lines = text.splitlines()
    cleaned = []
    for line in lines:
        suppress = any(p.search(line) for p in ISSUE_DATE_PATTERNS)
        if not suppress:
            cleaned.append(line)
    return '\n'.join(cleaned)


def _extract_date(text: str) -> Optional[str]:
    # FIX #9: Try explicit departure/travel date labels first (highest priority).
    travel_date_patterns = [
        r'(?:Departure|Travel|Journey|Dep(?:arture)?)\s*Date[:\s]+(\d{1,2}[-/\s](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*[-/\s]\d{2,4})',
        r'(?:Departure|Travel|Journey|Dep(?:arture)?)\s*Date[:\s]+(\d{1,2}[-/]\d{1,2}[-/]\d{4})',
        # Air India table row: "Sat, 1 Jun 2019" in a DATE column
        r'\bDATE\b[^\n]*\n[^\n]*?\b(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{4})\b',
    ]
    for p in travel_date_patterns:
        m = re.search(p, text, re.IGNORECASE | re.MULTILINE)
        if m:
            raw = m.group(1).strip()
            normalized = _normalize_date(raw)
            if normalized:
                return normalized

    # Strip issue/booking date lines before running generic patterns
    # so we don't accidentally return the issue date.
    text_for_dates = _strip_issue_dates(text)

    date_patterns = [
        r'(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[,\s]+(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{4})',
        r'(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[,\s]+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+(\d{1,2}[,\s]+\d{4})',
        r'\b(\d{1,2}[-\s](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*[-\s]\d{2,4})\b',
        r'\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{1,2}[,\s]+\d{4})\b',
        r'\b(\d{4}-\d{2}-\d{2})\b',
        r'\b(\d{1,2}/\d{1,2}/\d{4})\b',
        # IndiGo boarding pass "Date : 24 Oct 19"
        r'Date\s*[:\-]?\s*(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{2,4})',
        r'\b(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{2})\b',
    ]

    for p in date_patterns:
        m = re.search(p, text_for_dates, re.IGNORECASE | re.MULTILINE)
        if m:
            raw = m.group(1).strip()
            normalized = _normalize_date(raw)
            if normalized:
                return normalized

    m = re.search(
        r'(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[,\.]?\s+'
        r'(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{4})',
        text_for_dates, re.IGNORECASE
    )
    if m:
        return _normalize_date(m.group(1))

    m = re.search(r'\b(\d{1,2}[-/]\d{1,2}[-/]\d{4})\b', text_for_dates)
    if m:
        return _normalize_date(m.group(1))

    return None


def _normalize_date(raw: str) -> Optional[str]:
    if not raw:
        return None
    raw = re.sub(r'\s+', ' ', raw.strip())

    fmt_list = [
        "%d %b %Y",   "%d-%b-%Y",   "%d/%b/%Y",
        "%d %B %Y",   "%d-%B-%Y",
        "%B %d, %Y",  "%b %d, %Y",  "%b %d %Y",
        "%d-%m-%Y",   "%d/%m/%Y",   "%m/%d/%Y",
        "%Y-%m-%d",
        "%d %b %y",   "%d-%b-%y",
    ]
    for fmt in fmt_list:
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass

    def _cap_month(s: str) -> str:
        months = ['jan','feb','mar','apr','may','jun',
                  'jul','aug','sep','oct','nov','dec']
        for mo in months:
            s = re.sub(mo, mo.capitalize(), s, flags=re.IGNORECASE)
        return s

    raw2 = _cap_month(raw)
    for fmt in ["%d %b %Y", "%d-%b-%Y", "%d %b %y"]:
        try:
            return datetime.strptime(raw2, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass

    return raw


# ─────────────────────────────────────────────────────────────────────────────
# STRUCTURED TABLE EXTRACTION (for Yatra / MMT style PDFs)
# ─────────────────────────────────────────────────────────────────────────────

def _extract_from_tables(pdf_path_or_bytes) -> Dict[str, Any]:
    result: Dict[str, Any] = {}

    try:
        if isinstance(pdf_path_or_bytes, bytes):
            src = io.BytesIO(pdf_path_or_bytes)
        else:
            src = pdf_path_or_bytes

        with pdfplumber.open(src) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    if not table:
                        continue
                    headers = None
                    for row in table:
                        row_clean = [
                            str(cell).strip() if cell else ''
                            for cell in row
                        ]
                        row_upper = [c.upper() for c in row_clean]
                        if any(h in row_upper for h in ['NAME', 'PNR', 'AIRLINE PNR', 'AIRLINE', 'DEPARTURE', 'ARRIVAL']):
                            headers = row_upper
                            continue
                        if headers and row_clean:
                            for col_idx, header in enumerate(headers):
                                if col_idx >= len(row_clean):
                                    break
                                val = row_clean[col_idx].strip()
                                if not val or val.upper() in ('NA', 'N/A', '-', ''):
                                    continue

                                if ('PASSENGER' in header or 'NAME' in header) and 'name_raw' not in result:
                                    result['name_raw'] = val
                                elif ('AIRLINE PNR' in header or header == 'PNR') and 'pnr' not in result:
                                    if not OTA_REF_PATTERN.match(val) and _is_valid_pnr(val):
                                        result['pnr'] = val.upper()
                                elif 'AIRLINE' in header and 'AIRLINE PNR' not in header and 'airline' not in result:
                                    result['airline'] = val
                                elif 'DESTINATION' in header and 'dest_raw' not in result:
                                    m = re.search(r'([A-Z]{3})\s*[-–]\s*([A-Z]{3})', val.upper())
                                    if m:
                                        result['origin']      = m.group(1)
                                        result['destination'] = m.group(2)

    except Exception as e:
        print(f"  ⚠️  Table extraction failed: {e}")

    return result


# ─────────────────────────────────────────────────────────────────────────────
# CORE TEXT PARSER
# ─────────────────────────────────────────────────────────────────────────────

def parse_ticket_text(raw_text: str, table_hints: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Parse ticket text (and optionally table hints) into structured fields.
    Works for both PDF-extracted text and OCR-extracted text from images.
    """
    text = _clean(raw_text)
    ota  = _detect_ota(text)
    hints = table_hints or {}

    pnr = hints.get('pnr') or _extract_pnr(text, ota)

    airline_from_table = hints.get('airline')
    airline_name, flight_number = _extract_airline_and_flight(text)
    if airline_from_table and not airline_name:
        airline_name = airline_from_table

    name_raw = hints.get('name_raw')
    if name_raw:
        cleaned = _clean(name_raw)
        name = _extract_name(cleaned + "\n" + text, ota)
    else:
        name = _extract_name(text, ota)

    origin      = hints.get('origin')
    destination = hints.get('destination')
    if not origin or not destination:
        origin, destination = _extract_route(text)

    origin_city      = IATA_TO_CITY.get(origin, origin)           if origin      else None
    destination_city = IATA_TO_CITY.get(destination, destination) if destination else None

    departure_date = _extract_date(text)

    fields = {
        'name':           name,
        'pnr':            pnr,
        'flight_number':  flight_number,
        'origin':         origin,
        'destination':    destination,
        'departure_date': departure_date,
    }
    found = sum(1 for v in fields.values() if v)
    confidence = round(found / len(fields), 2)

    return {
        **fields,
        'airline':          airline_name,
        'origin_city':      origin_city,
        'destination_city': destination_city,
        'ota':              ota,
        'confidence':       confidence,
        'fields_found':     found,
        'raw_preview':      text[:400].strip(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# IMAGE PARSER — Google Cloud Vision OCR
# ─────────────────────────────────────────────────────────────────────────────

def _preprocess_image(file_bytes: bytes) -> bytes:
    """
    Resize large images to max 2000px and convert to JPEG.
    Vision API works best under 4MB.
    """
    if not PIL_AVAILABLE:
        return file_bytes

    img = Image.open(io.BytesIO(file_bytes)).convert('RGB')

    max_dim = 2000
    w, h = img.size
    if max(w, h) > max_dim:
        scale = max_dim / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=90)
    return buf.getvalue()


def parse_ticket_image_google(file_bytes: bytes) -> Dict[str, Any]:
    """
    Parse a ticket image (JPG/PNG/WEBP) using Google Cloud Vision OCR.

    Setup:
      1. Enable Cloud Vision API at console.cloud.google.com
      2. Create an API key under APIs & Services → Credentials
      3. Set env variable: GOOGLE_VISION_API_KEY=your_key_here
    """
    api_key = GOOGLE_VISION_API_KEY
    if not api_key:
        return {
            "error": (
                "Google Vision API key not set. "
                "Add GOOGLE_VISION_API_KEY=your_key to your .env file."
            )
        }

    if not PIL_AVAILABLE:
        print("  ⚠️  Pillow not installed — skipping image preprocessing (pip install Pillow)")

    try:
        processed_bytes = _preprocess_image(file_bytes)
        b64_image = base64.b64encode(processed_bytes).decode('utf-8')

        payload = {
            "requests": [{
                "image": {"content": b64_image},
                "features": [{"type": "DOCUMENT_TEXT_DETECTION", "maxResults": 1}]
            }]
        }

        url = f"https://vision.googleapis.com/v1/images:annotate?key={api_key}"
        response = requests.post(url, json=payload, timeout=20)
        response.raise_for_status()

        data = response.json()
        responses = data.get('responses', [{}])
        if not responses:
            return {"error": "Empty response from Google Vision API"}

        first = responses[0]
        if 'error' in first:
            err = first['error']
            return {"error": f"Google Vision API error {err.get('code')}: {err.get('message')}"}

        annotation = first.get('fullTextAnnotation', {})
        raw_text = annotation.get('text', '').strip()

        if not raw_text:
            return {"error": "Google Vision found no text in the image. Try a clearer photo."}

        result = parse_ticket_text(raw_text)
        result['source']      = 'image_google_vision'
        result['raw_preview'] = raw_text[:400]
        return result

    except requests.exceptions.Timeout:
        return {"error": "Google Vision API timed out (20s). Check your internet connection."}
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response else '?'
        if status == 400:
            return {"error": "Google Vision API: Bad request — image may be corrupted or too small."}
        elif status == 403:
            return {"error": "Google Vision API: Access denied — check your API key and that Vision API is enabled."}
        elif status == 429:
            return {"error": "Google Vision API: Rate limit hit. Wait a moment and retry."}
        return {"error": f"Google Vision API HTTP error {status}: {e}"}
    except requests.exceptions.RequestException as e:
        return {"error": f"Network error calling Google Vision API: {e}"}
    except KeyError as e:
        return {"error": f"Unexpected Google Vision API response format: missing key {e}"}
    except Exception as e:
        return {"error": f"Image parsing failed: {e}"}


# ─────────────────────────────────────────────────────────────────────────────
# PDF FILE PARSER
# ─────────────────────────────────────────────────────────────────────────────

def parse_ticket_pdf(file_path_or_bytes) -> Dict[str, Any]:
    """
    Main PDF entry point. Accepts file path (str) or bytes.
    1. Extract full text via pdfplumber
    2. Attempt structured table extraction
    3. Merge results
    """
    if not PDF_AVAILABLE:
        return {"error": "pdfplumber not installed. Run: pip install pdfplumber"}

    if isinstance(file_path_or_bytes, bytes):
        pdf_bytes = file_path_or_bytes
    else:
        with open(file_path_or_bytes, 'rb') as f:
            pdf_bytes = f.read()

    full_text  = ""
    page_count = 0
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            page_count = len(pdf.pages)
            for page in pdf.pages:
                page_text = page.extract_text(x_tolerance=2, y_tolerance=2)
                if page_text:
                    full_text += page_text + "\n"
    except Exception as e:
        return {"error": f"Could not read PDF: {e}"}

    if not full_text.strip():
        return {"error": "Could not extract text — PDF may be a scanned image. Try uploading as JPG/PNG instead."}

    table_hints = _extract_from_tables(io.BytesIO(pdf_bytes))

    result = parse_ticket_text(full_text, table_hints=table_hints)
    result['source'] = 'pdf'
    result['pages']  = page_count
    return result


# ─────────────────────────────────────────────────────────────────────────────
# UNIVERSAL FASTAPI UPLOAD HANDLER
# ─────────────────────────────────────────────────────────────────────────────

async def parse_ticket_upload(upload_file) -> Dict[str, Any]:
    """
    Universal drop-in for FastAPI route — auto-detects PDF vs image.

    Usage:
        result = await parse_ticket_upload(file)

    Example FastAPI route:
        @app.post("/upload-ticket")
        async def upload_ticket(file: UploadFile = File(...)):
            result = await parse_ticket_upload(file)
            return result
    """
    content = await upload_file.read()
    if not content:
        return {"error": "Empty file uploaded"}

    filename = getattr(upload_file, 'filename', '').lower().strip()
    ext = ('.' + filename.rsplit('.', 1)[-1]) if '.' in filename else ''

    if ext == '.pdf':
        return parse_ticket_pdf(content)
    elif ext in SUPPORTED_IMAGE_TYPES:
        return parse_ticket_image_google(content)
    else:
        supported = ', '.join(['.pdf'] + list(SUPPORTED_IMAGE_TYPES.keys()))
        return {"error": f"Unsupported file type '{ext}'. Supported formats: {supported}"}


# ─────────────────────────────────────────────────────────────────────────────
# CLI TEST HARNESS
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        file_path = sys.argv[1]
        ext = ('.' + file_path.rsplit('.', 1)[-1].lower()) if '.' in file_path else ''
        print(f"\nParsing: {file_path}  (detected type: {ext})")
        if ext == '.pdf':
            result = parse_ticket_pdf(file_path)
        elif ext in SUPPORTED_IMAGE_TYPES:
            with open(file_path, 'rb') as f:
                result = parse_ticket_image_google(f.read())
        else:
            print(f"❌ Unsupported file type: {ext}")
            sys.exit(1)

        print("\n=== RESULT ===")
        for k, v in result.items():
            if k != 'raw_preview':
                print(f"  {k:22}: {v}")
        print(f"\n  Raw preview:\n{result.get('raw_preview', '')}\n")
        sys.exit(0)

    # ── Built-in test suite ───────────────────────────────────────────────────
    tests = [
        {
            "label": "Air India Web E-Ticket (v6 NEW — the failing ticket)",
            "text": """
Web E-Ticket Itinerary Receipt
Issuing Airline: Air India
Issued date: Sun, 26 May 2019
Web Reference: AIBE48200917
Booking reference no (PNR): JBT5M (AI)

PASSENGER/ ITINERARY DETAILS
PASSENGER NAME           FREQUENT FLYER NO.   TICKET NO.(S)   SEAT REQUEST
MR DHANANJAY PAWAR       AI 192309833         098-2119825645  NA

DATE          DEP TIME  FROM          TO             FLIGHT NO  DEP TERMINAL  AIRLINE
Sat, 1 Jun 2019  20:05  Doha (DOH)   Mumbai (BOM)   AI 9002    NA            AIR INDIA EXPRESS

TRAVEL INFORMATION
Flight No./ Operated By  Depart               Arrive
AI 9002                  Doha (DOH)           Mumbai (BOM)
Operated by Air India    Sat, 1 Jun 2019      Sun, 2 Jun 2019, 02:15, Terminal 2
Express, IX 244          20:05
""",
            "expect": {
                "name":           "Mr. Dhananjay Pawar",
                "pnr":            "JBT5M",
                "flight_number":  "AI9002",
                "origin":         "DOH",
                "destination":    "BOM",
                "departure_date": "2019-06-01",
            }
        },
        {
            "label": "IndiGo Boarding Pass (v5 regression — the failing ticket)",
            "text": """
Boarding Pass

IndiGo   Boarding pass (web Check-in)   GoIndiGo.in

Name :  MR PAVAN  REDDY
From :  Visakhapatnam    To :  Hyderabad
Flight No :  6E  776    Date :  24 Oct 19
Boarding Time :  18:35  Departure Time :  19:20
Sequence# :  106        Class :  Q
Gate# :                 Seat# :  18E

SPECIAL SERVICES
Name :   MR PAVAN  REDDY
PNR :    HJNCQT
Flt# :   6E  776
Seat# :  18E
Seq# :   106

From :        Visakhapatnam
To :          Hyderabad
Flight No. :  6E 776
Date :        24 Oct 19
Boarding Time : 18:35
Departure Time: 19:20
Seq# :  106   Class :  Q
Gate# :       Seat# :  18E
""",
            "expect": {
                "name":           "Mr. Pavan Reddy",
                "pnr":            "HJNCQT",
                "flight_number":  "6E776",
                "origin":         "VTZ",
                "destination":    "HYD",
            }
        },
        {
            "label": "MakeMyTrip / IndiGo (table format)",
            "text": """
6/19/2015                    Eticket-Dom-Flight
E-Ticket
MakeMyTrip Booking ID -NF2203354197300
Booking Date -Fri, 19 Jun 2015

Itinerary and Reservation Details

IndiGo
Indigo  6E-198
Departure               Arrival
Mumbai (BOM)            Delhi (DEL)
Terminal 1B             Terminal 1C
Fri, 19 Jun 2015 22:10  Sat, 20 Jun 2015 00:20

Passenger Name  Type    Airline PNR  E-Ticket Number
Aishwarya Singh Adult   TCNNFN       TCNNFN
""",
            "expect": {
                "name":           "Aishwarya Singh",
                "pnr":            "TCNNFN",
                "flight_number":  "6E198",
                "origin":         "BOM",
                "destination":    "DEL",
            }
        },
        {
            "label": "Yatra / Vistara",
            "text": """
FLIGHT E-TICKET YATRA REF NUMBER 1111200071731

PASSENGERS DETAILS
NAME                DESTINATION  MEALS  BAGGAGE      SEAT NO.  TICKET NO.
Mr Shekhar Tomer    DEL - IXJ    NA     15 Kg (Free) NA        2283856537463
(Adult)

New Delhi ► Jammu    Wed, Nov 18 2020
AIRLINE   DEPARTURE              ARRIVAL               DURATION  PNR
Vistara   Wed, Nov 18 2020       Wed, Nov 18 2020      Non Stop  M96DOE
UK - 645  13:25 Hrs              14:35 Hrs
""",
            "expect": {
                "name":           "Mr. Shekhar Tomer",
                "pnr":            "M96DOE",
                "flight_number":  "UK645",
                "origin":         "DEL",
                "destination":    "IXJ",
            }
        },
        {
            "label": "Air India direct",
            "text": """
AIR INDIA E-TICKET ITINERARY & RECEIPT
Booking Reference: XKTP72
Passenger: SHARMA/RAHUL MR
Flight: AI 191
Route: BOM – LHR
Date: 20-Jun-2025  |  Time: 02:30
""",
            "expect": {
                "pnr":            "XKTP72",
                "flight_number":  "AI191",
                "origin":         "BOM",
                "destination":    "LHR",
            }
        },
        {
            "label": "Emirates direct",
            "text": """
EMIRATES E-TICKET RECEIPT
Booking Reference: GHJ45K
Passenger: MR AHMED HASSAN
EK 506
Dubai (DXB) to Mumbai (BOM)
Date: 14 Mar 2025
""",
            "expect": {
                "pnr":            "GHJ45K",
                "flight_number":  "EK506",
                "origin":         "DXB",
                "destination":    "BOM",
            }
        },
    ]

    all_pass = True
    print("\n" + "="*60)
    print("  Running built-in test suite  (v6)")
    print("="*60)

    for t in tests:
        result = parse_ticket_text(t["text"])
        expect = t.get("expect", {})

        field_checks = []
        for field, expected_val in expect.items():
            actual = result.get(field, '')
            if field == 'name':
                actual_core   = re.sub(r'^(Mr|Mrs|Ms|Miss|Dr)\.\s*', '', actual or '', flags=re.IGNORECASE).strip().lower()
                expected_core = re.sub(r'^(Mr|Mrs|Ms|Miss|Dr)\.\s*', '', expected_val, flags=re.IGNORECASE).strip().lower()
                match = actual_core == expected_core
            else:
                match = (actual or '').upper() == expected_val.upper()
            field_checks.append((field, expected_val, actual, match))

        ok = result["confidence"] >= 0.6 and all(m for _, _, _, m in field_checks)
        status = "✅ PASS" if ok else "❌ FAIL"
        if not ok:
            all_pass = False

        print(f"\n{status}  [{t['label']}]  conf={result['confidence']}")
        for k in ['name', 'pnr', 'flight_number', 'airline', 'origin', 'destination', 'departure_date']:
            actual = result.get(k) or '—'
            exp = expect.get(k)
            marker = ''
            if exp:
                if k == 'name':
                    actual_core   = re.sub(r'^(Mr|Mrs|Ms|Miss|Dr)\.\s*', '', str(actual), flags=re.IGNORECASE).strip().lower()
                    expected_core = re.sub(r'^(Mr|Mrs|Ms|Miss|Dr)\.\s*', '', exp, flags=re.IGNORECASE).strip().lower()
                    marker = ' ✓' if actual_core == expected_core else f' ✗ (expected: {exp})'
                else:
                    marker = ' ✓' if (actual or '').upper() == exp.upper() else f' ✗ (expected: {exp})'
            print(f"  {k:16}: {actual}{marker}")

    print(f"\n{'All tests passed ✅' if all_pass else 'Some tests failed ❌'}")
    print("\nUsage: python pdf_parser.py path/to/ticket.pdf")
    print("       python pdf_parser.py path/to/ticket.jpg")
    print("       python pdf_parser.py path/to/ticket.png")