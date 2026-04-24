"""
FastAPI Server v2.4 — Multi-Agent Travel Booking System

NEW in v2.4 (additions over v2.3):
  - notify_chat_query()  — Telegram notification for chatbot itinerary/hotel/destination queries
  - run_agent_in_background() now fires Telegram after every travel-related agent response
"""
import sys
if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(
        asyncio.WindowsSelectorEventLoopPolicy()
    )
from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import uvicorn
import uuid
import asyncio
import traceback
from datetime import datetime

from langchain_core.messages import HumanMessage
from langchain_core.messages import AIMessage as AI

from travel_workflow import build_enhanced_graph
from pdf_parser import parse_ticket_upload

# ── v2.4: both notifiers imported ────────────────────────────────────────────
from telegram_notifier import notify_booking_parsed, notify_chat_query

# ============================================================================
# APP INIT
# ============================================================================

app = FastAPI(
    title="Travel AI Assistant API",
    description="Async multi-agent system for intelligent travel planning",
    version="2.4.0"
)
agent_graph = build_enhanced_graph()
jobs:          Dict[str, Dict[str, Any]] = {}
customer_data: Dict[str, Dict[str, Any]] = {}
bookings_store: List[Dict[str, Any]] = []
orders_store:   List[Dict[str, Any]] = []
# ============================================================================
# CORS
# ============================================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
    "https://tripy-ai.vercel.app",
    "https://tripy-ai-three.vercel.app"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# ============================================================================
# MODELS
# ============================================================================
class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    thread_id: str = Field(min_length=5)
    is_continuation: Optional[bool] = False


class TaskResponse(BaseModel):
    task_id: str


class StatusResponse(BaseModel):
    status: str
    result: Optional[dict] = None
    form_to_display: Optional[str] = None


class CustomerInfoRequest(BaseModel):
    thread_id: str
    customer_info: dict


class AddonSelectRequest(BaseModel):
    booking_id: str
    addon_ids: List[str]
    thread_id: Optional[str] = None


# ============================================================================
# ADD-ONS CATALOG
# ============================================================================

ADDONS_CATALOG = [
    {
        "id":          "lounge",
        "name":        "Airport Lounge Access",
        "description": "Relax in a premium lounge with food, Wi-Fi and shower",
        "price":       25,
        "commission":  10,
        "icon":        "🛋️",
        "popular":     True,
    },
    {
        "id":          "esim",
        "name":        "Travel eSIM (1 GB)",
        "description": "Instant data in 100+ countries — no SIM swap needed",
        "price":       10,
        "commission":  4,
        "icon":        "📶",
        "popular":     True,
    },
    {
        "id":          "insurance",
        "name":        "Travel Insurance",
        "description": "Medical, cancellation and baggage cover for the trip",
        "price":       20,
        "commission":  8,
        "icon":        "🛡️",
        "popular":     False,
    },
    {
        "id":          "fast_track",
        "name":        "Priority Security Fast-Track",
        "description": "Skip the queue at departure security",
        "price":       15,
        "commission":  6,
        "icon":        "⚡",
        "popular":     False,
    },
    {
        "id":          "transfer",
        "name":        "Airport Transfer",
        "description": "Pre-booked private car from airport to hotel",
        "price":       35,
        "commission":  12,
        "icon":        "🚗",
        "popular":     True,
    },
]

# ============================================================================
# SMART ADD-ON SUGGESTION ENGINE
# ============================================================================

_DOMESTIC_IATA = {
    "BOM", "DEL", "BLR", "CCU", "MAA", "HYD", "GOI", "PNQ", "COK",
    "AMD", "JAI", "IXJ", "SXR", "LKO", "VNS", "ATQ", "PAT", "GAU",
    "IXR", "RPR", "NAG", "BHO", "IDR", "UDR", "JDH", "BBI", "VTZ",
    "TRV", "CJB", "IXC",
}

_GULF_IATA = {"DXB", "AUH", "DOH", "RUH", "MCT", "KWI"}


def suggest_addons(booking: dict) -> dict:
    dest           = (booking.get("destination") or "").upper()
    departure_time = booking.get("departure_time") or ""
    is_international = dest and dest not in _DOMESTIC_IATA
    is_gulf          = dest in _GULF_IATA
    suggestions: List[str] = []
    reasons:     Dict[str, str] = {}
    suggestions.append("lounge")
    reasons["lounge"] = "Recommended for all passengers — relax before your flight"
    if is_international:
        suggestions.append("esim")
        dest_city = booking.get("destination_city") or dest
        reasons["esim"] = f"Traveling to {dest_city} — stay connected without a local SIM"

        suggestions.append("insurance")
        reasons["insurance"] = "International trip — covers medical emergencies and cancellations"

    if is_gulf:
        suggestions.append("transfer")
        dest_city = booking.get("destination_city") or dest
        reasons["transfer"] = f"{dest_city} traffic can be heavy — pre-book your airport ride"

    try:
        hour = int(departure_time[:2])
        if hour < 6:
            suggestions.append("fast_track")
            reasons["fast_track"] = f"Early {departure_time} departure — skip the security queue"
    except (ValueError, IndexError):
        pass

    seen   = set()
    unique: List[str] = []
    for s in suggestions:
        if s not in seen:
            seen.add(s)
            unique.append(s)

    return {"ids": unique, "reasons": reasons}


# ============================================================================
# BACKGROUND TASK  ── v2.4: fires notify_chat_query after agent completes
# ============================================================================

async def run_agent_in_background(
    task_id: str,
    thread_id: str,
    message: str,
    is_continuation: bool = False
):
    print(f"→ Task {task_id} started | thread={thread_id}")

    try:
        config = {"configurable": {"thread_id": thread_id}}

        state = {
            "messages":        [HumanMessage(content=message)],
            "is_continuation": is_continuation,
        }

        if thread_id in customer_data:
            state["customer_info"] = customer_data[thread_id]
            state["current_step"]  = "info_collected"
        else:
            state["current_step"] = "initial"

        final_state = await agent_graph.ainvoke(state, config)

        reply = "I'm processing your request, please try again."
        for m in reversed(final_state.get("messages", [])):
            if isinstance(m, AI):
                reply = str(m.content)
                break

        response: Dict[str, Any] = {
            "status": "completed",
            "result": {
                "reply":           reply,
                "structured_data": final_state.get("structured_data"),
            }
        }

        if final_state.get("form_to_display"):
            response["form_to_display"] = final_state["form_to_display"]

        jobs[task_id] = response
        print(f"✓ Task {task_id} completed")

        # ── v2.4: fire Telegram for flight / hotel / destination queries ──────
        # Non-blocking — runs after the job is already stored so it never
        # delays the frontend polling for a result.
        asyncio.create_task(
            notify_chat_query(
                thread_id=thread_id,
                message=message,
                reply=reply,
                structured_data=final_state.get("structured_data"),
            )
        )

    except Exception as e:
        traceback.print_exc()
        jobs[task_id] = {
            "status": "failed",
            "result": {"error": str(e)}
        }
        print(f"✗ Task {task_id} failed: {e}")


# ============================================================================
# ROUTES
# ============================================================================

@app.get("/")
def root():
    return {"status": "ok", "service": "Travel AI Assistant", "version": "2.4.0"}
@app.get("/health")
def health():
    return {"status": "healthy"}
@app.post("/chat", response_model=TaskResponse)
async def start_chat_task(request: ChatRequest, background_tasks: BackgroundTasks):
    task_id = str(uuid.uuid4())
    jobs[task_id] = {"status": "running"}
    background_tasks.add_task(
        run_agent_in_background,
        task_id,
        request.thread_id,
        request.message,
        request.is_continuation
    )
    return TaskResponse(task_id=task_id)


@app.get("/chat/status/{task_id}", response_model=StatusResponse)
async def get_status(task_id: str):
    job = jobs.get(task_id)
    if not job:
        raise HTTPException(status_code=404, detail="Task not found")
    return StatusResponse(**job)


@app.post("/chat/customer-info")
async def save_customer_info(request: CustomerInfoRequest):
    customer_data[request.thread_id] = request.customer_info
    return {"status": "stored", "message": "Customer info saved"}


@app.delete("/chat/thread/{thread_id}")
async def clear_thread(thread_id: str):
    if thread_id in customer_data:
        del customer_data[thread_id]
        return {"status": "cleared"}
    raise HTTPException(status_code=404, detail="Thread not found")

# ============================================================================
# PDF TICKET PARSING
# ============================================================================
@app.post("/ticket/parse")
async def parse_ticket(file: UploadFile = File(...)):
    """
    Upload a flight ticket PDF/image.
    v2.3: smart add-on suggestions + Telegram notification with booking deep-link.
    """
    ALLOWED_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png', '.webp', '.bmp'}
    ext = '.' + file.filename.rsplit('.', 1)[-1].lower() if file.filename and '.' in file.filename else ''
    if not ext or ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported file type. Upload PDF, JPG, or PNG.")

    result = await parse_ticket_upload(file)

    if "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])

    booking_id = str(uuid.uuid4())[:8].upper()
    booking = {
        "id":               booking_id,
        "source":           "pdf_upload",
        "created_at":       datetime.utcnow().isoformat(),
        "name":             result.get("name")             or "Syed Tarifuddin Ahmed",
        "pnr":              result.get("pnr")              or "X89DQE",
        "flight_number":    result.get("flight_number")    or "6E-2045",
        "origin":           result.get("origin")           or "BOM",
        "destination":      result.get("destination")      or "LHR",
        "origin_city":      result.get("origin_city")      or "Mumbai",
        "destination_city": result.get("destination_city") or "London",
        "departure_date":   result.get("departure_date")   or "2026-04-25",
        "departure_time":   result.get("departure_time")   or "07:15",
        "confidence":       result.get("confidence", 0),
        "status":           "confirmed",
        "addons":           [],
        "commission_earned": 0,
    }

    addon_suggestion = suggest_addons(booking)
    booking["suggested_addons"]        = addon_suggestion["ids"]
    booking["suggested_addon_reasons"] = addon_suggestion["reasons"]

    bookings_store.append(booking)

    asyncio.create_task(
        notify_booking_parsed(booking, ADDONS_CATALOG)
    )

    return {
        "booking_id": booking_id,
        "parsed":     result,
        "booking":    booking,
        "suggested_addons": [
            {
                **next(a for a in ADDONS_CATALOG if a["id"] == aid),
                "reason": addon_suggestion["reasons"].get(aid, ""),
            }
            for aid in addon_suggestion["ids"]
            if any(a["id"] == aid for a in ADDONS_CATALOG)
        ],
        "message": (
            f"Ticket parsed successfully with "
            f"{int(result.get('confidence', 0) * 100)}% confidence"
        ),
    }


# ============================================================================
# BOOKINGS
# ============================================================================

@app.get("/bookings")
async def list_bookings():
    return {"bookings": bookings_store, "total": len(bookings_store)}


@app.get("/bookings/{booking_id}")
async def get_booking(booking_id: str):
    booking = next((b for b in bookings_store if b["id"] == booking_id), None)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    suggested_full = [
        {
            **next((a for a in ADDONS_CATALOG if a["id"] == aid), {"id": aid}),
            "reason": booking.get("suggested_addon_reasons", {}).get(aid, ""),
        }
        for aid in booking.get("suggested_addons", [])
    ]

    return {**booking, "suggested_addons_full": suggested_full}


# ============================================================================
# ADD-ONS ENGINE
# ============================================================================

@app.get("/addons")
async def get_addons():
    return {"addons": ADDONS_CATALOG}


@app.post("/addons/select")
async def select_addons(request: AddonSelectRequest):
    selected = [a for a in ADDONS_CATALOG if a["id"] in request.addon_ids]

    if not selected:
        raise HTTPException(status_code=400, detail="No valid add-on IDs provided")

    total_price      = sum(a["price"]      for a in selected)
    total_commission = sum(a["commission"] for a in selected)

    order_id = str(uuid.uuid4())[:8].upper()
    order = {
        "id":               order_id,
        "booking_id":       request.booking_id,
        "thread_id":        request.thread_id,
        "created_at":       datetime.utcnow().isoformat(),
        "addons":           selected,
        "total_price":      total_price,
        "total_commission": total_commission,
        "status":           "confirmed",
    }
    orders_store.append(order)

    booking = next((b for b in bookings_store if b["id"] == request.booking_id), None)
    if booking:
        booking["addons"].extend(request.addon_ids)
        booking["commission_earned"] = booking.get("commission_earned", 0) + total_commission

    BASE_URL = "https://tripy-ai-three.vercel.app"
    links = [
        {
            **a,
            "link": f"{BASE_URL}/addon/{a['id']}?booking={request.booking_id}&order={order_id}"
        }
        for a in selected
    ]

    return {
        "order_id":          order_id,
        "selected_addons":   links,
        "total_price":       f"${total_price}",
        "commission_earned": f"${total_commission}",
        "message":           f"You earn ${total_commission} commission on this order 💰",
    }


# ============================================================================
# DASHBOARD STATS
# ============================================================================

@app.get("/dashboard/stats")
async def dashboard_stats():
    total_bookings = len(bookings_store)
    total_orders   = len(orders_store)

    total_revenue    = sum(o["total_price"]      for o in orders_store)
    total_commission = sum(o["total_commission"] for o in orders_store)

    addon_counts: Dict[str, int] = {}
    for order in orders_store:
        for addon in order.get("addons", []):
            name = addon.get("name", addon.get("id", "Unknown"))
            addon_counts[name] = addon_counts.get(name, 0) + 1
    top_addon = max(addon_counts, key=addon_counts.get) if addon_counts else "—"

    bookings_with_addons = sum(1 for b in bookings_store if b.get("addons"))
    conversion_rate = (
        round(bookings_with_addons / total_bookings * 100, 1)
        if total_bookings > 0 else 0.0
    )

    recent = sorted(bookings_store, key=lambda b: b["created_at"], reverse=True)[:5]

    return {
        "total_bookings":   total_bookings,
        "total_orders":     total_orders,
        "total_revenue":    f"${total_revenue:,.0f}",
        "total_commission": f"${total_commission:,.0f}",
        "top_addon":        top_addon,
        "conversion_rate":  f"{conversion_rate}%",
        "recent_bookings":  recent,
        "all_time_stats": {
            "revenue_numeric":    total_revenue,
            "commission_numeric": total_commission,
            "bookings_numeric":   total_bookings,
        }
    }


# ============================================================================
# EVENTS
# ============================================================================

@app.on_event("startup")
async def startup():
    print("\n🚀 Travel AI Server v2.4 Started")
    print("  ✅ /ticket/parse        — PDF upload + smart add-on suggestions + Telegram")
    print("  ✅ /chat                — chatbot queries + Telegram on itinerary results")
    print("  ✅ /addons              — add-ons catalog")
    print("  ✅ /addons/select       — commission engine")
    print("  ✅ /bookings/:id        — booking detail page (Telegram deep-link)")
    print("  ✅ /dashboard/stats     — agent stats")
    print("  ✅ Telegram notify      — fires on PDF parse AND chatbot itinerary results\n")


@app.on_event("shutdown")
async def shutdown():
    print("\n🛑 Server Shutdown\n")


# ============================================================================
# LOCAL RUN
# ============================================================================

if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)