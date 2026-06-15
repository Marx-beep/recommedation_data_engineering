from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.config import ROOT, settings
from src.data_loader import load_candidates
from src.ingestion.batch_service import (
    get_job,
    append_upload_chunk,
    create_upload_session,
    finalize_upload_session,
    list_jobs,
    public_job,
    resume_incomplete_jobs,
    retry_job,
    save_streamed_upload,
    save_uploads,
)
from src.models import RecommendationRequest, RecommendationResponse, UploadSessionRequest
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
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"批量导入失败：{exc}") from exc


@app.get("/api/import-jobs")
async def import_jobs(limit: int = 10) -> list[dict]:
    return [public_job(job) for job in list_jobs(min(max(limit, 1), 50))]


@app.get("/api/import-jobs/{job_id}")
async def import_job(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="导入任务不存在")
    return public_job(job)


@app.post("/api/import-jobs/{job_id}/retry", status_code=202)
async def retry_import_job(job_id: str) -> dict:
    try:
        return retry_job(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/import-jobs/stream", status_code=202)
async def create_streamed_import_job(
    request: Request,
    x_file_name: str = Header(...),
    x_use_llm: bool = Header(True),
) -> dict:
    try:
        return await save_streamed_upload(x_file_name, request.stream(), x_use_llm)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"大文件流式导入失败：{exc}") from exc


@app.post("/api/upload-sessions", status_code=201)
async def new_upload_session(payload: UploadSessionRequest) -> dict:
    try:
        return create_upload_session(payload.file_name, payload.file_size, payload.use_llm)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/upload-sessions/{upload_id}/chunks/{chunk_index}")
async def upload_chunk(upload_id: str, chunk_index: int, request: Request) -> dict:
    try:
        return await append_upload_chunk(upload_id, chunk_index, request.stream())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/upload-sessions/{upload_id}/complete", status_code=202)
async def complete_upload(upload_id: str) -> dict:
    try:
        return await finalize_upload_session(upload_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"完成上传失败：{exc}") from exc


@app.post("/api/recommend", response_model=RecommendationResponse)
async def recommendation(request: RecommendationRequest) -> RecommendationResponse:
    try:
        return await recommend(request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"推荐流程执行失败：{exc}") from exc
