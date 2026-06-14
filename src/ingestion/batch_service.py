from __future__ import annotations

import asyncio
import json
import shutil
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import UploadFile

from src.config import ROOT, settings
from src.data_loader import refresh_candidates
from src.ingestion.resume_parser import parse_resume
from src.ingestion.text_extractor import SUPPORTED_EXTENSIONS, extract_text


RAW_DIR = ROOT / "data" / "raw_resumes" / "uploads"
TEXT_DIR = ROOT / "data" / "processed_text" / "imported"
STRUCTURED_DIR = ROOT / "data" / "structured_resumes" / "imported"
JOB_DIR = ROOT / "data" / "import_jobs"
TASKS: set[asyncio.Task] = set()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _job_path(job_id: str) -> Path:
    return JOB_DIR / f"{job_id}.job.json"


def _manifest_path(job_id: str) -> Path:
    return JOB_DIR / f"{job_id}.files.json"


def _write_job(job: dict) -> None:
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    temporary = _job_path(job["job_id"]).with_suffix(".tmp")
    temporary.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(_job_path(job["job_id"]))


def get_job(job_id: str) -> dict | None:
    path = _job_path(job_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def list_jobs(limit: int = 10) -> list[dict]:
    if not JOB_DIR.exists():
        return []
    jobs = [json.loads(path.read_text(encoding="utf-8")) for path in JOB_DIR.glob("*.job.json")]
    return sorted(jobs, key=lambda item: item["created_at"], reverse=True)[:limit]


async def save_uploads(files: list[UploadFile], use_llm: bool) -> dict:
    if not files:
        raise ValueError("请选择至少一份简历或 ZIP 压缩包")
    if len(files) > settings.max_batch_files:
        raise ValueError(f"单批最多上传 {settings.max_batch_files} 个文件")
    job_id = uuid.uuid4().hex[:12]
    job_raw_dir = RAW_DIR / job_id
    job_raw_dir.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    batch_size = 0
    for upload in files:
        safe_name = Path(upload.filename or f"resume-{len(saved) + 1}.txt").name
        target = job_raw_dir / f"{len(saved) + 1:05d}-{safe_name}"
        size = 0
        with target.open("wb") as destination:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                batch_size += len(chunk)
                if size > settings.max_file_mb * 1024 * 1024:
                    target.unlink(missing_ok=True)
                    raise ValueError(f"{safe_name} 超过单文件 {settings.max_file_mb}MB 限制")
                if batch_size > settings.max_batch_gb * 1024 * 1024 * 1024:
                    target.unlink(missing_ok=True)
                    raise ValueError(f"单批上传总大小超过 {settings.max_batch_gb}GB 限制")
                destination.write(chunk)
        saved.append(str(target))
        await upload.close()

    expanded = await asyncio.to_thread(_expand_archives, saved, job_raw_dir)
    if not expanded:
        raise ValueError("未找到支持的简历文件")
    if len(expanded) > settings.max_batch_files:
        raise ValueError(f"单批最多处理 {settings.max_batch_files} 份简历")
    job = {
        "job_id": job_id,
        "status": "queued",
        "created_at": _now(),
        "updated_at": _now(),
        "total": len(expanded),
        "processed": 0,
        "succeeded": 0,
        "failed": 0,
        "llm_parsed": 0,
        "use_llm": use_llm,
        "errors": [],
    }
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    _manifest_path(job_id).write_text(json.dumps(expanded, ensure_ascii=False), encoding="utf-8")
    _write_job(job)
    task = asyncio.create_task(process_job(job_id))
    TASKS.add(task)
    task.add_done_callback(TASKS.discard)
    return public_job(job)


def _expand_archives(saved: list[str], job_raw_dir: Path) -> list[str]:
    result: list[str] = []
    expanded_size = 0
    for item in saved:
        path = Path(item)
        if path.suffix.lower() == ".zip":
            extract_dir = job_raw_dir / f"{path.stem}-expanded"
            extract_dir.mkdir(exist_ok=True)
            try:
                with zipfile.ZipFile(path) as archive:
                    for info in archive.infolist():
                        if info.is_dir() or Path(info.filename).suffix.lower() not in SUPPORTED_EXTENSIONS:
                            continue
                        if len(result) >= settings.max_batch_files:
                            raise ValueError(f"ZIP 内简历数量超过 {settings.max_batch_files} 份")
                        if info.file_size > settings.max_file_mb * 1024 * 1024:
                            raise ValueError(f"ZIP 内文件 {Path(info.filename).name} 超过大小限制")
                        expanded_size += info.file_size
                        if expanded_size > settings.max_batch_gb * 1024 * 1024 * 1024:
                            raise ValueError(f"ZIP 解压后总大小超过 {settings.max_batch_gb}GB 限制")
                        safe_target = extract_dir / f"{len(result) + 1:05d}-{Path(info.filename).name}"
                        with archive.open(info) as source, safe_target.open("wb") as destination:
                            shutil.copyfileobj(source, destination, length=1024 * 1024)
                        result.append(str(safe_target))
            except zipfile.BadZipFile as exc:
                raise ValueError(f"{path.name} 不是有效的 ZIP 文件") from exc
        elif path.suffix.lower() in SUPPORTED_EXTENSIONS:
            result.append(str(path))
    return result


async def process_job(job_id: str) -> None:
    job = get_job(job_id)
    if not job:
        return
    manifest_path = _manifest_path(job_id)
    if not manifest_path.exists():
        job["status"] = "failed"
        job["errors"] = [{"file": "", "message": "任务文件清单不存在"}]
        _write_job(job)
        return
    files = json.loads(manifest_path.read_text(encoding="utf-8"))
    job["status"] = "processing"
    job["updated_at"] = _now()
    _write_job(job)
    semaphore = asyncio.Semaphore(max(1, settings.import_workers))
    lock = asyncio.Lock()

    async def process_one(index: int, file_name: str) -> None:
        async with semaphore:
            try:
                path = Path(file_name)
                text = await asyncio.to_thread(extract_text, path)
                resume_id = f"I{job_id[:4].upper()}{index + 1:05d}"
                candidate, llm_used = await parse_resume(text, resume_id, job["use_llm"])
                TEXT_DIR.mkdir(parents=True, exist_ok=True)
                STRUCTURED_DIR.mkdir(parents=True, exist_ok=True)
                (TEXT_DIR / f"{resume_id}.txt").write_text(text, encoding="utf-8")
                (STRUCTURED_DIR / f"{resume_id}.json").write_text(
                    candidate.model_dump_json(indent=2), encoding="utf-8"
                )
                async with lock:
                    job["succeeded"] += 1
                    job["llm_parsed"] += int(llm_used)
            except Exception as exc:
                async with lock:
                    job["failed"] += 1
                    if len(job["errors"]) < 50:
                        job["errors"].append({"file": Path(file_name).name, "message": str(exc)[:300]})
            finally:
                async with lock:
                    job["processed"] += 1
                    job["updated_at"] = _now()
                    _write_job(job)

    await asyncio.gather(*(process_one(index, file_name) for index, file_name in enumerate(files)))
    refresh_candidates()
    job["status"] = "completed" if job["succeeded"] else "failed"
    job["updated_at"] = _now()
    _write_job(job)


def public_job(job: dict) -> dict:
    return job


def resume_incomplete_jobs() -> None:
    for job in list_jobs(limit=1000):
        if job["status"] in {"queued", "processing"}:
            job["status"] = "queued"
            _write_job({**get_job(job["job_id"]), "status": "queued", "updated_at": _now()})
            task = asyncio.create_task(process_job(job["job_id"]))
            TASKS.add(task)
            task.add_done_callback(TASKS.discard)
