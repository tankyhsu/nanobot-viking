"""FastAPI routes for OpenViking knowledge base.

Usage:
    from viking_service import VikingService
    from viking_routes import create_viking_router

    viking = VikingService(data_dir="/path/to/data")
    viking.start_worker()

    app.include_router(create_viking_router(viking))
"""

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from viking_service import VikingService

logger = logging.getLogger("viking_routes")


class VikingSearchRequest(BaseModel):
    query: str
    limit: int = 5


class VikingAddRequest(BaseModel):
    path: str


def create_viking_router(viking: VikingService) -> APIRouter:
    """Create a FastAPI router with all Viking knowledge base endpoints."""
    router = APIRouter(prefix="/api/viking", tags=["viking"])

    @router.get("/status")
    async def viking_status():
        if not viking or not viking.ready:
            return {"status": "disabled", "message": "OpenViking not initialized"}
        return {"status": "ok", "ready": True}

    @router.post("/search")
    async def viking_search(req: VikingSearchRequest):
        if not viking or not viking.ready:
            raise HTTPException(503, "OpenViking not initialized")
        result = await viking.search(req.query, req.limit)
        return {"result": result}

    @router.post("/find")
    async def viking_find(req: VikingSearchRequest):
        if not viking or not viking.ready:
            raise HTTPException(503, "OpenViking not initialized")
        result = await viking.find(req.query, req.limit)
        return {"result": result}

    @router.post("/add")
    async def viking_add(req: VikingAddRequest):
        if not viking or not viking.ready:
            raise HTTPException(503, "OpenViking not initialized")
        result = await viking.add_resource(req.path)
        return {"result": result}

    @router.get("/ls")
    async def viking_ls(uri: str = "viking://resources/"):
        if not viking or not viking.ready:
            raise HTTPException(503, "OpenViking not initialized")
        result = await viking.ls(uri)
        return {"result": result}

    @router.get("/sessions")
    async def viking_sessions():
        if not viking or not viking.ready:
            raise HTTPException(503, "OpenViking not initialized")
        result = await viking.list_sessions()
        return {"result": result}

    return router


async def augment_with_context(viking: VikingService, message: str, limit: int = 3) -> str:
    """Prepend relevant Viking context to a user message (RAG augmentation).

    Call this before passing the message to your LLM. If Viking is unavailable
    or no relevant context is found, returns the original message unchanged.
    """
    if not viking or not viking.ready:
        return message
    try:
        context = await viking.retrieve_context(message, limit)
        if context:
            return (
                "[The following context was retrieved from the knowledge base for reference]\n"
                f"{context}\n"
                "[End of context]\n\n"
                f"{message}"
            )
    except Exception as e:
        logger.error(f"Memory augmentation failed: {e}")
    return message
