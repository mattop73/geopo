from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from services.llm_service import stream_llm, list_ollama_models
from config import get_settings

router = APIRouter(prefix="/api/llm", tags=["llm"])
settings = get_settings()

GEOPO_SYSTEM = (
    "You are a geopolitical analyst assistant. You have access to real-time commodity prices, "
    "news headlines, and prediction market data. Provide concise, data-driven analysis. "
    "When referencing data, be specific about figures. Keep responses under 400 words unless asked for more."
)


class AnalyzeRequest(BaseModel):
    prompt: str
    model: str = ""
    system: str = ""


@router.post("/analyze")
async def analyze(req: AnalyzeRequest):
    model = req.model or settings.default_llm_model
    system = req.system or GEOPO_SYSTEM

    async def generate():
        async for chunk in stream_llm(req.prompt, model, system):
            yield chunk

    return StreamingResponse(generate(), media_type="text/plain")


@router.get("/models")
async def get_models():
    ollama_models = await list_ollama_models()
    available = []
    if settings.anthropic_api_key:
        available += [
            {"id": "claude-opus-4-7", "label": "Claude Opus 4.7", "provider": "anthropic"},
            {"id": "claude-sonnet-4-6", "label": "Claude Sonnet 4.6", "provider": "anthropic"},
            {"id": "claude-haiku-4-5-20251001", "label": "Claude Haiku 4.5", "provider": "anthropic"},
        ]
    if settings.openai_api_key:
        available += [
            {"id": "gpt-4o", "label": "GPT-4o", "provider": "openai"},
            {"id": "gpt-4o-mini", "label": "GPT-4o Mini", "provider": "openai"},
        ]
    for m in ollama_models:
        available.append({"id": f"ollama:{m}", "label": f"Ollama: {m}", "provider": "ollama"})
    if not available:
        available.append({"id": settings.default_llm_model, "label": settings.default_llm_model, "provider": "ollama"})
    return available


@router.get("/default-model")
async def default_model():
    return {"model": settings.default_llm_model}
