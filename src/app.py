from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.config import ROOT, settings
from src.data_loader import load_candidates
from src.models import RecommendationRequest, RecommendationResponse
from src.service import recommend


app = FastAPI(title="MaterialMatch HR", version="1.0.0")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/health")
async def health() -> dict:
    return {
        "status": "ok",
        "candidate_count": len(load_candidates()),
        "llm_configured": bool(settings.api_key),
        "model": settings.model,
    }


@app.get("/api/candidates")
async def candidates() -> list[dict]:
    return [candidate.model_dump() for candidate in load_candidates()]


@app.post("/api/recommend", response_model=RecommendationResponse)
async def recommendation(request: RecommendationRequest) -> RecommendationResponse:
    try:
        return await recommend(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"推荐流程执行失败：{exc}") from exc

