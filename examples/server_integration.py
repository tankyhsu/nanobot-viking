"""Example: integrating nanobot-viking into a FastAPI nanobot-api server.

This shows the minimal code needed to add Viking knowledge base support
to an existing nanobot API server.
"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI

# Import from nanobot-viking
from viking_service import VikingService
from viking_routes import create_viking_router, augment_with_context

logger = logging.getLogger("server")

viking: VikingService = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global viking

    # ... your existing nanobot init code ...

    # Initialize Viking (optional — gracefully degrades if unavailable)
    try:
        viking = VikingService()  # uses ~/.openviking/data by default
        viking.start_worker()
        logger.info("Viking knowledge base initialized")
    except Exception as e:
        logger.warning(f"Viking init failed (knowledge base disabled): {e}")
        viking = None

    yield

    # Cleanup
    if viking:
        viking.close()


app = FastAPI(lifespan=lifespan)

# Mount Viking API routes (all under /api/viking/*)
# Only responds when Viking is ready; returns 503 otherwise
app.include_router(create_viking_router(viking))


# --- Using RAG augmentation in your chat endpoint ---

@app.post("/api/chat")
async def chat(message: str):
    # Augment user message with knowledge base context before sending to LLM
    augmented = await augment_with_context(viking, message)

    # Pass augmented message to your nanobot agent
    # response = await agent.process(content=augmented, ...)

    return {"response": "..."}


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "viking_ready": viking is not None and viking.ready,
    }
