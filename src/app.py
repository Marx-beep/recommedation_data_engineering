from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.config import ROOT, settings
from src.data_loader import load_candidates
from src.ingestion.batch_service import get_job, list_jobs, public_job, resume_incomplete_jobs, save_uploads
from src.models import RecommendationRequest, RecommendationResponse
from src.service import recommend


@asynccontextmanager
async def lifespan(_: FastAPI):
    resume_incomplete_jobs()
    yield


app = FastAPI(title="MaterialMatch HR", version="1.1.0", lifespan=lifespan)
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


@app.post("/api/import-jobs", status_code=202)
async def create_import_job(
    files: list[UploadFile] = File(...),
    use_llm: bool = Form(True),
) -> dict:
    try:
        return await save_uploads(files, use_llm)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/import-jobs")
async def import_jobs(limit: int = 10) -> list[dict]:
    return [public_job(job) for job in list_jobs(min(max(limit, 1), 50))]


@app.get("/api/import-jobs/{job_id}")
async def import_job(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="导入任务不存在")
    return public_job(job)


@app.post("/api/recommend", response_model=RecommendationResponse)
async def recommendation(request: RecommendationRequest) -> RecommendationResponse:
    try:
        return await recommend(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"推荐流程执行失败：{exc}") from exc
