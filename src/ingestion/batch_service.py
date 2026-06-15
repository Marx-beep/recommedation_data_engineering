from __future__ import annotations

import asyncio
import json
import shutil
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

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
CHUNK_SIZE = 8 * 1024 * 1024


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _job_path(job_id: str) -> Path:
    return JOB_DIR / f"{job_id}.job.json"


def _manifest_path(job_id: str) -> Path:
    return JOB_DIR / f"{job_id}.files.json"


def _session_path(upload_id: str) -> Path:
    return RAW_DIR / upload_id / "upload.session.json"


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
        size_limit_mb = settings.max_archive_mb if target.suffix.lower() == ".zip" else settings.max_file_mb
        upload_error = ""
        try:
            with target.open("wb") as destination:
                while chunk := await upload.read(1024 * 1024):
                    size += len(chunk)
                    batch_size += len(chunk)
                    if size > size_limit_mb * 1024 * 1024:
                        upload_error = f"{safe_name} 超过 {size_limit_mb}MB 限制"
                        break
                    if batch_size > settings.max_batch_gb * 1024 * 1024 * 1024:
                        upload_error = f"单批上传总大小超过 {settings.max_batch_gb}GB 限制"
                        break
                    destination.write(chunk)
        finally:
            await upload.close()
        if upload_error:
            target.unlink(missing_ok=True)
            shutil.rmtree(job_raw_dir, ignore_errors=True)
            raise ValueError(upload_error)
        saved.append(str(target))

    try:
        expanded, skipped = await asyncio.to_thread(_expand_archives, saved, job_raw_dir)
    except Exception:
        shutil.rmtree(job_raw_dir, ignore_errors=True)
        raise
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
        "skipped": skipped,
    }
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    _manifest_path(job_id).write_text(json.dumps(expanded, ensure_ascii=False), encoding="utf-8")
    _write_job(job)
    task = asyncio.create_task(process_job(job_id))
    TASKS.add(task)
    task.add_done_callback(TASKS.discard)
    return public_job(job)


async def save_streamed_upload(file_name: str, chunks, use_llm: bool) -> dict:
    safe_name = Path(unquote(file_name or "resumes.zip")).name
    job_id = uuid.uuid4().hex[:12]
    job_raw_dir = RAW_DIR / job_id
    job_raw_dir.mkdir(parents=True, exist_ok=True)
    target = job_raw_dir / f"00001-{safe_name}"
    size_limit_mb = settings.max_archive_mb if target.suffix.lower() == ".zip" else settings.max_file_mb
    size = 0
    try:
        with target.open("wb") as destination:
            async for chunk in chunks:
                size += len(chunk)
                if size > size_limit_mb * 1024 * 1024:
                    raise ValueError(f"{safe_name} 超过 {size_limit_mb}MB 限制")
                destination.write(chunk)
        return await _create_job_from_saved(job_id, job_raw_dir, [str(target)], use_llm)
    except Exception:
        shutil.rmtree(job_raw_dir, ignore_errors=True)
        raise


def create_upload_session(file_name: str, file_size: int, use_llm: bool) -> dict:
    safe_name = Path(unquote(file_name or "resumes.zip")).name
    limit_mb = settings.max_archive_mb if Path(safe_name).suffix.lower() == ".zip" else settings.max_file_mb
    if file_size > limit_mb * 1024 * 1024:
        raise ValueError(f"{safe_name} 超过 {limit_mb}MB 限制")
    upload_id = uuid.uuid4().hex[:12]
    upload_dir = RAW_DIR / upload_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    session = {
        "upload_id": upload_id,
        "file_name": safe_name,
        "file_size": file_size,
        "received": 0,
        "next_chunk": 0,
        "use_llm": use_llm,
    }
    _session_path(upload_id).write_text(json.dumps(session, ensure_ascii=False), encoding="utf-8")
    return {**session, "chunk_size": CHUNK_SIZE}


async def append_upload_chunk(upload_id: str, chunk_index: int, chunks) -> dict:
    session_path = _session_path(upload_id)
    if not session_path.exists():
        raise ValueError("上传会话不存在或已过期")
    session = json.loads(session_path.read_text(encoding="utf-8"))
    if chunk_index != session["next_chunk"]:
        raise ValueError(f"分块顺序错误，期望 {session['next_chunk']}，收到 {chunk_index}")
    target = session_path.parent / f"00001-{session['file_name']}"
    chunk_bytes = 0
    with target.open("ab") as destination:
        async for chunk in chunks:
            chunk_bytes += len(chunk)
            if chunk_bytes > CHUNK_SIZE:
                raise ValueError("单个上传分块超过限制")
            destination.write(chunk)
    session["received"] += chunk_bytes
    if session["received"] > session["file_size"]:
        raise ValueError("已上传数据超过声明的文件大小")
    session["next_chunk"] += 1
    session_path.write_text(json.dumps(session, ensure_ascii=False), encoding="utf-8")
    return {"upload_id": upload_id, "received": session["received"], "file_size": session["file_size"]}


async def finalize_upload_session(upload_id: str) -> dict:
    session_path = _session_path(upload_id)
    if not session_path.exists():
        raise ValueError("上传会话不存在或已过期")
    session = json.loads(session_path.read_text(encoding="utf-8"))
    if session["received"] != session["file_size"]:
        raise ValueError(f"文件尚未上传完成：{session['received']} / {session['file_size']}")
    target = session_path.parent / f"00001-{session['file_name']}"
    session_path.unlink(missing_ok=True)
    return await _create_job_from_saved(upload_id, target.parent, [str(target)], session["use_llm"])


async def _create_job_from_saved(job_id: str, job_raw_dir: Path, saved: list[str], use_llm: bool) -> dict:
    expanded, skipped = await asyncio.to_thread(_expand_archives, saved, job_raw_dir)
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
        "skipped": skipped,
    }
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    _manifest_path(job_id).write_text(json.dumps(expanded, ensure_ascii=False), encoding="utf-8")
    _write_job(job)
    task = asyncio.create_task(process_job(job_id))
    TASKS.add(task)
    task.add_done_callback(TASKS.discard)
    return public_job(job)


def _expand_archives(saved: list[str], job_raw_dir: Path) -> tuple[list[str], list[dict]]:
    result: list[str] = []
    skipped: list[dict] = []
    expanded_size = 0
    for item in saved:
        path = Path(item)
        if path.suffix.lower() == ".zip":
            extract_dir = job_raw_dir / f"{path.stem}-expanded"
            extract_dir.mkdir(exist_ok=True)
            try:
                with zipfile.ZipFile(path) as archive:
                    for info in archive.infolist():
                        if info.is_dir():
                            continue
                        suffix = Path(info.filename).suffix.lower()
                        if suffix not in SUPPORTED_EXTENSIONS:
                            if len(skipped) < 50:
                                message = "旧版 .doc 请转换为 .docx" if suffix == ".doc" else f"不支持的文件类型：{suffix or '未知'}"
                                skipped.append({"file": Path(info.filename).name, "message": message})
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
        else:
            skipped.append({"file": path.name, "message": f"不支持的文件类型：{path.suffix.lower() or '未知'}"})
    return result, skipped


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


def retry_job(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise ValueError("导入任务不存在")
    if job["status"] in {"queued", "processing"}:
        raise ValueError("导入任务仍在运行")
    job.update(
        status="queued",
        updated_at=_now(),
        processed=0,
        succeeded=0,
        failed=0,
        llm_parsed=0,
        errors=[],
    )
    _write_job(job)
    task = asyncio.create_task(process_job(job_id))
    TASKS.add(task)
    task.add_done_callback(TASKS.discard)
    return public_job(job)
