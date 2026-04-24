"""
pdf_parser.py — Flight Ticket PDF + Image Parser v3
Handles: Yatra, Air India, IndiGo, Emirates, Qatar, SpiceJet, MakeMyTrip, Cleartrip
Image support: JPG, JPEG, PNG, WEBP, BMP via Google Cloud Vision API (free tier: 1000/month)

Key fixes vs v2:
  - Added Google Cloud Vision OCR for image tickets (JPG/PNG/WEBP)
  - Universal upload handler auto-detects PDF vs image
  - Image preprocessing (resize + compress) before Vision API call
  - Zero heavy installs — only Pillow + requests needed for images
  - .env support via GOOGLE_VISION_API_KEY environment variable
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
    "BOM": "Mumbai",       "DEL": "Delhi",        "BLR": "Bangalore",
    "CCU": "Kolkata",      "MAA": "Chennai",       "HYD": "Hyderabad",
    "GOI": "Goa",          "PNQ": "Pune",          "COK": "Kochi",
    "AMD": "Ahmedabad",    "JAI": "Jaipur",        "IXJ": "Jammu",
    "SXR": "Srinagar",     "LKO": "Lucknow",       "VNS": "Varanasi",
    "ATQ": "Amritsar",     "PAT": "Patna",         "GAU": "Guwahati",
    "IXR": "Ranchi",       "RPR": "Raipur",        "NAG": "Nagpur",
    "BHO": "Bhopal",       "IDR": "Indore",        "UDR": "Udaipur",
    "JDH": "Jodhpur",      "BBI": "Bhubaneswar",   "VTZ": "Visakhapatnam",
    "TRV": "Trivandrum",   "CJB": "Coimbatore",    "IXC": "Chandigarh",
    "DXB": "Dubai",        "AUH": "Abu Dhabi",     "DOH": "Doha",
    "RUH": "Riyadh",       "MCT": "Muscat",        "KWI": "Kuwait",
    "SIN": "Singapore",    "BKK": "Bangkok",       "KUL": "Kuala Lumpur",
    "DPS": "Bali",         "HKT": "Phuket",        "CGK": "Jakarta",
    "MNL": "Manila",       "SGN": "Ho Chi Minh",   "HAN": "Hanoi",
    "NRT": "Tokyo",        "KIX": "Osaka",         "ICN": "Seoul",
    "PEK": "Beijing",      "PVG": "Shanghai",      "HKG": "Hong Kong",
    "TPE": "Taipei",
    "LHR": "London",       "CDG": "Paris",         "FRA": "Frankfurt",
    "AMS": "Amsterdam",    "FCO": "Rome",          "MAD": "Madrid",
    "BCN": "Barcelona",    "ZRH": "Zurich",        "VIE": "Vienna",
    "IST": "Istanbul",     "ATH": "Athens",        "MUC": "Munich",
    "BER": "Berlin",       "PRG": "Prague",        "WAW": "Warsaw",
    "LIS": "Lisbon",       "DUB": "Dublin",
    "JFK": "New York",     "LAX": "Los Angeles",   "ORD": "Chicago",
    "MIA": "Miami",        "SFO": "San Francisco", "BOS": "Boston",
    "ATL": "Atlanta",      "DFW": "Dallas",        "SEA": "Seattle",
    "YYZ": "Toronto",      "YVR": "Vancouver",
    "SYD": "Sydney",       "MEL": "Melbourne",     "BNE": "Brisbane",
    "JNB": "Johannesburg", "CPT": "Cape Town",     "NBO": "Nairobi",
    "CAI": "Cairo",
}

AIRLINE_CODES: Dict[str, str] = {
    "AI": "Air India",      "6E": "IndiGo",         "SG": "SpiceJet",
    "UK": "Vistara",        "QP": "Akasa Air",      "G8": "Go First",
    "I5": "AirAsia India",  "EK": "Emirates",       "QR": "Qatar Airways",
    "EY": "Etihad",         "FZ": "Flydubai",       "G9": "Air Arabia",
    "WY": "Oman Air",       "SQ": "Singapore Airlines", "TG": "Thai Airways",
    "AK": "AirAsia",        "MH": "Malaysia Airlines",  "VN": "Vietnam Airlines",
    "CX": "Cathay Pacific", "JL": "Japan Airlines", "NH": "ANA",
    "KE": "Korean Air",     "BA": "British Airways","LH": "Lufthansa",
    "AF": "Air France",     "KL": "KLM",            "TK": "Turkish Airlines",
    "VS": "Virgin Atlantic","LX": "SWISS",          "IB": "Iberia",
    "DL": "Delta",          "UA": "United Airlines","AA": "American Airlines",
    "QF": "Qantas",         "ET": "Ethiopian Airlines", "MS": "EgyptAir",
}

# Known OTA reference number patterns to SKIP (not real PNRs)
OTA_REF_PATTERN = re.compile(r'^\d{8,}$')

# English stopwords often misidentified as IATA codes
SKIP_IATA = {
    "THE", "ARE", "FOR", "AND", "BUT", "NOT", "YOU", "ALL", "CAN",
    "HER", "WAS", "ONE", "OUR", "OUT", "WHO", "ITS", "HAS", "HAD",
    "HIM", "HIS", "HOW", "MAN", "NEW", "NOW", "OLD", "SEE", "TWO",
    "WAY", "BOY", "DID", "GET", "MAY", "SAY", "USE", "WAR", "ETA",
    "ETD", "STD", "STA", "REF", "PNR", "OTA", "PDF", "UTC", "GMT",
    "INR", "USD", "EUR", "GBP", "TAX", "VAT", "GST", "TDS", "NET",
    "NAT", "NON", "PRE", "PRO", "PER", "SUB", "SUM", "TAB", "TOP",
    "AIR", "FLY", "JET", "SKY", "VIA", "WEB", "YES", "AGE", "AGO",
}


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

def _extract_pnr(text: str, ota: str) -> Optional[str]:
    pnr_label_patterns = [
        r'PNR\s*\n\s*([A-Z0-9]{5,8})\b',
        r'PNR\s*[:\-\|]?\s*([A-Z][A-Z0-9]{4,7})\b',
        r'PNR\s*/\s*Booking\s*Ref[:\s]+([A-Z][A-Z0-9]{4,7})\b',
    ]
    for p in pnr_label_patterns:
        m = re.search(p, text, re.IGNORECASE | re.MULTILINE)
        if m:
            val = m.group(1).strip().upper()
            if not OTA_REF_PATTERN.match(val) and val not in SKIP_IATA:
                return val

    booking_ref_patterns = [
        r'(?:Booking\s*(?:Ref(?:erence)?|Code)|Record\s*Locator|Confirmation\s*(?:Code|No\.?))\s*[:\-]?\s*([A-Z][A-Z0-9]{4,7})\b',
        r'Reference\s*(?:No\.?|Number)?\s*[:\-]?\s*([A-Z][A-Z0-9]{4,7})\b',
    ]
    for p in booking_ref_patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            val = m.group(1).strip().upper()
            if not OTA_REF_PATTERN.match(val) and val not in SKIP_IATA:
                return val

    candidates = re.findall(r'\b([A-Z][A-Z0-9]{5})\b', text)
    for c in candidates:
        if OTA_REF_PATTERN.match(c):
            continue
        if c in SKIP_IATA:
            continue
        if re.search(r'\d', c):
            return c

    return None


def _extract_name(text: str, ota: str) -> Optional[str]:
    name = None

    title_pattern = re.compile(
        r'\b(Mr\.?|Mrs\.?|Ms\.?|Miss\.?|Dr\.?|Shri|Smt)\s+'
        r'([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){1,3})',
        re.IGNORECASE
    )
    m = title_pattern.search(text)
    if m:
        name = f"{m.group(1).rstrip('.')}. {m.group(2).strip()}"
        name = re.sub(r'\s+', ' ', name).strip()

    if not name:
        pax_patterns = [
            r'Passenger(?:\s*Name)?\s*[:\-]\s*([A-Z][A-Za-z\s/\.]{3,40})',
            r'PAX(?:\s*Name)?\s*[:\-]\s*([A-Z][A-Za-z\s/\.]{3,40})',
            r'Travelling\s*as\s*[:\-]\s*([A-Z][A-Za-z\s/\.]{3,40})',
        ]
        for p in pax_patterns:
            m = re.search(p, text, re.IGNORECASE | re.MULTILINE)
            if m:
                name = m.group(1).strip()
                break

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
                    firstname = re.sub(r'\s*(MR|MRS|MS|MISS).*$', '', parts[1], flags=re.IGNORECASE).strip().title()
                    name = f"{firstname} {surname}"
                else:
                    name = m.group(1).title()
                break

    if not name:
        m = re.search(r'Dear\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)', text)
        if m:
            name = m.group(1).strip()

    if name:
        name = re.sub(
            r'\s*[\(\[].*$|'
            r'\s+(Adult|Child|Infant|Mr|Mrs|Ms)\b.*$',
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
        'air india':            'Air India',
        'air india express':    'Air India Express',
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
        r'\b([A-Z]{1,2})\s*[-–]\s*(\d{2,4}[A-Z]?)\b',
        r'(?:Flight|Flt|Flight\s*No\.?|Flight\s*Number)\s*[:\-]?\s*([A-Z]{1,2}[\s\-]?\d{2,4}[A-Z]?)',
        r'\b([A-Z]{1,2})\s(\d{3,4}[A-Z]?)\b',
        r'\b([A-Z]{1,2})(\d{3,4}[A-Z]?)\b',
    ]

    for p in flight_patterns:
        m = re.search(p, text, re.IGNORECASE | re.MULTILINE)
        if m:
            if m.lastindex == 2:
                code = m.group(1).upper()
                num  = m.group(2).upper()
                flight_number = f"{code}{num}"
                if not airline_name and code in AIRLINE_CODES:
                    airline_name = AIRLINE_CODES[code]
            else:
                raw = re.sub(r'[\s\-]', '', m.group(1)).upper()
                flight_number = raw
                code = raw[:2]
                if not airline_name and code in AIRLINE_CODES:
                    airline_name = AIRLINE_CODES[code]
            break

    return airline_name, flight_number


def _extract_route(text: str) -> Tuple[Optional[str], Optional[str]]:
    origin = destination = None

    iata_pair_patterns = [
        r'\b([A-Z]{3})\s*[-–—→/]\s*([A-Z]{3})\b',
        r'From\s*[:\-]?\s*([A-Z]{3})\s+To\s*[:\-]?\s*([A-Z]{3})',
        r'Departure\s*[:\-]?\s*([A-Z]{3}).{0,50}Arrival\s*[:\-]?\s*([A-Z]{3})',
    ]
    for p in iata_pair_patterns:
        for m in re.finditer(p, text, re.IGNORECASE | re.MULTILINE):
            o = m.group(1).upper()
            d = m.group(2).upper()
            if o in SKIP_IATA or d in SKIP_IATA:
                continue
            if o == d:
                continue
            if o in IATA_TO_CITY or d in IATA_TO_CITY:
                origin, destination = o, d
                return origin, destination
            if re.match(r'^[A-Z]{3}$', o) and re.match(r'^[A-Z]{3}$', d):
                origin, destination = o, d
                return origin, destination

    city_pair_patterns = [
        r'([A-Z][a-zA-Z\s]+?)\s*(?:→|to|TO)\s*([A-Z][a-zA-Z\s]+?)(?:\n|$|\s{2,})',
        r'(?:From|Departing)\s*[:\-]?\s*([A-Z][a-zA-Z\s]+?)\s+(?:To|Arriving)\s*[:\-]?\s*([A-Z][a-zA-Z\s]+?)(?:\n|$)',
    ]
    city_to_iata = {v.lower(): k for k, v in IATA_TO_CITY.items()}
    for p in city_pair_patterns:
        m = re.search(p, text, re.MULTILINE)
        if m:
            o_city = m.group(1).strip().lower()
            d_city = m.group(2).strip().lower()
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


def _extract_date(text: str) -> Optional[str]:
    date_patterns = [
        r'(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[,\s]+(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{4})',
        r'(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[,\s]+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+(\d{1,2}[,\s]+\d{4})',
        r'\b(\d{1,2}[-\s](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*[-\s]\d{2,4})\b',
        r'\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{1,2}[,\s]+\d{4})\b',
        r'(?:Departure|Travel|Journey|Dep)\s*Date[:\s]+(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})',
        r'\b(\d{4}-\d{2}-\d{2})\b',
        r'\b(\d{1,2}/\d{1,2}/\d{4})\b',
    ]

    for p in date_patterns:
        m = re.search(p, text, re.IGNORECASE | re.MULTILINE)
        if m:
            raw = m.group(1).strip()
            normalized = _normalize_date(raw)
            if normalized:
                return normalized

    m = re.search(
        r'(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[,\.]?\s+'
        r'(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{4})',
        text, re.IGNORECASE
    )
    if m:
        return _normalize_date(m.group(1))

    m = re.search(r'\b(\d{1,2}[-/]\d{1,2}[-/]\d{4})\b', text)
    if m:
        return _normalize_date(m.group(1))

    return None


def _normalize_date(raw: str) -> Optional[str]:
    if not raw:
        return None
    raw = re.sub(r'\s+', ' ', raw.strip())

    fmt_list = [
        "%d %b %Y",   "%d-%b-%Y",  "%d/%b/%Y",
        "%d %B %Y",   "%d-%B-%Y",
        "%B %d, %Y",  "%b %d, %Y", "%b %d %Y",
        "%d-%m-%Y",   "%d/%m/%Y",  "%m/%d/%Y",
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
                        if any(h in row_upper for h in ['NAME', 'PNR', 'AIRLINE', 'DEPARTURE', 'ARRIVAL']):
                            headers = row_upper
                            continue
                        if headers and row_clean:
                            for col_idx, header in enumerate(headers):
                                if col_idx >= len(row_clean):
                                    break
                                val = row_clean[col_idx].strip()
                                if not val or val.upper() in ('NA', 'N/A', '-', ''):
                                    continue

                                if 'NAME' in header and 'name' not in result:
                                    result['name_raw'] = val
                                elif 'PNR' in header and 'pnr' not in result:
                                    if not OTA_REF_PATTERN.match(val):
                                        result['pnr'] = val.upper()
                                elif 'AIRLINE' in header and 'airline' not in result:
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
    Vision API works best under 4MB — this keeps it light.
    """
    if not PIL_AVAILABLE:
        # Return as-is if Pillow not installed
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
         (or add to .env file if using python-dotenv)

    Free tier: 1000 images/month — plenty for a travel agent tool.
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
        # Step 1: Preprocess image (resize + compress)
        processed_bytes = _preprocess_image(file_bytes)
        b64_image = base64.b64encode(processed_bytes).decode('utf-8')

        # Step 2: Call Google Vision API
        # DOCUMENT_TEXT_DETECTION is better than TEXT_DETECTION for structured docs
        payload = {
            "requests": [{
                "image": {
                    "content": b64_image
                },
                "features": [
                    {
                        "type": "DOCUMENT_TEXT_DETECTION",
                        "maxResults": 1
                    }
                ]
            }]
        }

        url = f"https://vision.googleapis.com/v1/images:annotate?key={api_key}"

        response = requests.post(url, json=payload, timeout=20)
        response.raise_for_status()

        data = response.json()

        # Step 3: Extract text from response
        responses = data.get('responses', [{}])
        if not responses:
            return {"error": "Empty response from Google Vision API"}

        first = responses[0]

        # Check for API-level error
        if 'error' in first:
            err = first['error']
            return {"error": f"Google Vision API error {err.get('code')}: {err.get('message')}"}

        annotation = first.get('fullTextAnnotation', {})
        raw_text = annotation.get('text', '').strip()

        if not raw_text:
            return {"error": "Google Vision found no text in the image. Try a clearer photo."}

        # Step 4: Feed OCR text into the same parser
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

    # Step 1: Extract all text
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

    # Step 2: Table extraction for structured OTA PDFs
    table_hints = _extract_from_tables(io.BytesIO(pdf_bytes))

    # Step 3: Parse
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

    Usage in your route:
        result = await parse_ticket_upload(file)

    Supported formats:
        PDF  → pdfplumber text extraction + table hints
        JPG/JPEG/PNG/WEBP/BMP → Google Cloud Vision OCR

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

    # Get extension
    if '.' in filename:
        ext = '.' + filename.rsplit('.', 1)[-1]
    else:
        ext = ''

    if ext == '.pdf':
        return parse_ticket_pdf(content)

    elif ext in SUPPORTED_IMAGE_TYPES:
        return parse_ticket_image_google(content)

    else:
        supported = ', '.join(['.pdf'] + list(SUPPORTED_IMAGE_TYPES.keys()))
        return {
            "error": f"Unsupported file type '{ext}'. Supported formats: {supported}"
        }


# ─────────────────────────────────────────────────────────────────────────────
# CLI TEST HARNESS
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    # ── Test with a real file if path provided ────────────────────────────────
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
        ext = '.' + file_path.rsplit('.', 1)[-1].lower() if '.' in file_path else ''

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

    # ── Built-in text-based tests ─────────────────────────────────────────────
    tests = [
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
        },
        {
            "label": "IndiGo / MakeMyTrip",
            "text": """
makemytrip
BOOKING CONFIRMED
Booking ID: NF2204567890123
PNR: ABCD12
Dear Priya Mehta,
IndiGo 6E-2541
Mumbai (BOM) → Delhi (DEL)
Date: 25 Dec 2024
""",
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
        },
    ]

    all_pass = True
    print("\n" + "="*60)
    print("  Running built-in test suite")
    print("="*60)

    for t in tests:
        result = parse_ticket_text(t["text"])
        ok = result["confidence"] >= 0.6
        status = "✅ PASS" if ok else "❌ FAIL"
        if not ok:
            all_pass = False
        print(f"\n{status}  [{t['label']}]  conf={result['confidence']}")
        for k in ['name', 'pnr', 'flight_number', 'airline', 'origin', 'destination', 'departure_date']:
            print(f"  {k:16}: {result.get(k) or '—'}")

    print(f"\n{'All tests passed ✅' if all_pass else 'Some tests failed ❌'}")
    print("\nUsage: python pdf_parser.py path/to/ticket.pdf")
    print("       python pdf_parser.py path/to/ticket.jpg")
    print("       python pdf_parser.py path/to/ticket.png")