"""
PrivacyGateAI - FastAPI REST Server
Drop-in replacement for direct AI API calls.
Change one URL in your app → instant privacy protection.

Usage:
    uvicorn api.server:app --reload --port 8000

Endpoints:
    POST /v1/process     - Full pipeline (sanitize + AI + restore)
    POST /v1/sanitize    - Sanitize only (no AI call)
    POST /v1/restore     - Restore only (from a saved entity map)
    GET  /v1/health      - Health check
    GET  /v1/audit/{id}  - Retrieve audit log for a session
"""

import uuid
import json
import logging
from datetime import datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core.engine import PrivacyEngine, DetectedEntity
from core.gateway import AIGateway

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="PrivacyGateAI",
    description="Privacy middleware for AI models — sanitize, route, restore.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory audit log (swap for Redis/Postgres in production)
audit_log: dict[str, Any] = {}

engine = PrivacyEngine()


# ── Request / Response Models ──────────────────────────────────────────────

class ProcessRequest(BaseModel):
    prompt: str
    system_prompt: str | None = None
    provider: str = "anthropic"          # "anthropic" | "openai"
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 1024
    session_id: str | None = None


class SanitizeRequest(BaseModel):
    text: str
    session_id: str | None = None


class RestoreRequest(BaseModel):
    text: str
    entity_map: dict[str, dict]          # placeholder → {original, entity_type, confidence}


class ProcessResponse(BaseModel):
    session_id: str
    response: str                         # Final restored response for the user
    entity_count: int
    entity_types: list[str]
    model_used: str
    provider: str


class SanitizeResponse(BaseModel):
    session_id: str
    sanitized_text: str
    entity_count: int
    entity_types: list[str]
    entity_map: dict[str, dict]           # Return map so client can restore later


# ── Routes ─────────────────────────────────────────────────────────────────

@app.get("/v1/health")
async def health():
    return {"status": "ok", "service": "PrivacyGateAI", "version": "0.1.0"}


@app.post("/v1/process", response_model=ProcessResponse)
async def process(req: ProcessRequest, x_api_key: str = Header(...)):
    """
    Full pipeline endpoint.
    Replaces your direct call to OpenAI/Anthropic.
    x-api-key header: your AI provider's API key (we never store it)
    """
    session_id = req.session_id or str(uuid.uuid4())

    try:
        gateway = AIGateway(
            provider=req.provider,
            model=req.model,
            api_key=x_api_key,
        )

        result = await gateway.process(
            prompt=req.prompt,
            system_prompt=req.system_prompt,
            session_id=session_id,
            max_tokens=req.max_tokens,
        )

        # Write audit log entry
        audit_log[session_id] = {
            "session_id": session_id,
            "timestamp": datetime.utcnow().isoformat(),
            "provider": req.provider,
            "model": req.model,
            "entity_count": result.entity_count,
            "entity_types": result.entity_types,
            "entities_detected": [
                {
                    "placeholder": k,
                    "type": v.entity_type,
                    "confidence": round(v.confidence, 3),
                    # Original values are NOT stored in audit log
                }
                for k, v in gateway.engine.sanitize(req.prompt).entity_map.items()
            ],
        }

        return ProcessResponse(
            session_id=session_id,
            response=result.restored_response,
            entity_count=result.entity_count,
            entity_types=result.entity_types,
            model_used=result.model_used,
            provider=result.provider,
        )

    except Exception as e:
        logger.error(f"Process error [{session_id}]: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/v1/sanitize", response_model=SanitizeResponse)
async def sanitize_only(req: SanitizeRequest):
    """
    Sanitize text without calling an AI model.
    Useful for pre-processing before storing or sending elsewhere.
    """
    session_id = req.session_id or str(uuid.uuid4())

    result = engine.sanitize(req.text, session_id)

    entity_map_serializable = {
        k: {
            "original": v.original,
            "entity_type": v.entity_type,
            "confidence": v.confidence,
        }
        for k, v in result.entity_map.items()
    }

    return SanitizeResponse(
        session_id=session_id,
        sanitized_text=result.sanitized_text,
        entity_count=result.entity_count,
        entity_types=result.entity_types,
        entity_map=entity_map_serializable,
    )


@app.post("/v1/restore")
async def restore_only(req: RestoreRequest):
    """
    Restore a previously sanitized text using a saved entity map.
    """
    entity_map = {
        k: DetectedEntity(
            original=v["original"],
            placeholder=k,
            entity_type=v["entity_type"],
            confidence=v.get("confidence", 1.0),
        )
        for k, v in req.entity_map.items()
    }

    restored = engine.restore(req.text, entity_map)
    return {"restored_text": restored}


@app.get("/v1/audit/{session_id}")
async def get_audit(session_id: str):
    """
    Retrieve the audit log for a session.
    Shows what was detected — never the original values.
    """
    entry = audit_log.get(session_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Session not found")
    return entry


@app.get("/v1/audit")
async def list_audits(limit: int = 50):
    """List recent audit entries (most recent first)."""
    entries = list(audit_log.values())
    entries.sort(key=lambda x: x["timestamp"], reverse=True)
    return {"total": len(entries), "entries": entries[:limit]}
