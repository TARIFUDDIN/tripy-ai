"""
FastAPI Server - Multi-Agent Travel Booking System
FIX: structured_data is now included in every /chat/status response
     so the frontend can render clean tables without regex parsing.
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
import uvicorn
import uuid
import asyncio
import traceback

from langchain_core.messages import HumanMessage
from langchain_core.messages import AIMessage as AI

from travel_workflow import build_enhanced_graph

# ============================================================================
# APP INIT
# ============================================================================

app = FastAPI(
    title="Travel AI Assistant API",
    description="Async multi-agent system for intelligent travel planning",
    version="2.1.0"
)

agent_graph = build_enhanced_graph()

jobs: Dict[str, Dict[str, Any]] = {}
customer_data: Dict[str, Dict[str, Any]] = {}

# ============================================================================
# CORS
# ============================================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
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


# ============================================================================
# BACKGROUND TASK
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
            "messages":      [HumanMessage(content=message)],
            "is_continuation": is_continuation,
        }

        if thread_id in customer_data:
            state["customer_info"] = customer_data[thread_id]
            state["current_step"]  = "info_collected"
        else:
            state["current_step"] = "initial"

        final_state = await agent_graph.ainvoke(state, config)

        # Extract last AI message
        reply = "I'm processing your request, please try again."
        for m in reversed(final_state.get("messages", [])):
            if isinstance(m, AI):
                reply = str(m.content)
                break

        # ✅ FIX: include structured_data in the response
        response: Dict[str, Any] = {
            "status": "completed",
            "result": {
                "reply":           reply,
                "structured_data": final_state.get("structured_data"),  # ← NEW
            }
        }

        if final_state.get("form_to_display"):
            response["form_to_display"] = final_state["form_to_display"]

        jobs[task_id] = response
        print(f"✓ Task {task_id} completed")

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
    return {"status": "ok", "service": "Travel AI Assistant", "version": "2.1.0"}


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
# EVENTS
# ============================================================================

@app.on_event("startup")
async def startup():
    print("\n🚀 Travel AI Server v2.1 Started\n")


@app.on_event("shutdown")
async def shutdown():
    print("\n🛑 Server Shutdown\n")


# ============================================================================
# LOCAL RUN
# ============================================================================

if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)