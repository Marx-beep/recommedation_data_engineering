from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import ROOT
from src.ingestion.resume_parser import parse_resume
from src.ingestion.text_extractor import extract_text


TEXT_DIR = ROOT / "data" / "processed_text" / "imported"
STRUCTURED_DIR = ROOT / "data" / "structured_resumes" / "imported"
JOB_DIR = ROOT / "data" / "import_jobs"


async def reparse_one(path: Path, resume_id: str, use_llm: bool, semaphore: asyncio.Semaphore, timeout: int, from_raw: bool) -> bool:
    async with semaphore:
        if from_raw:
            text = await asyncio.to_thread(extract_text, path)
            TEXT_DIR.mkdir(parents=True, exist_ok=True)
            (TEXT_DIR / f"{resume_id}.txt").write_text(text, encoding="utf-8")
        else:
            text = path.read_text(encoding="utf-8", errors="ignore")
        try:
            candidate, llm_used = await asyncio.wait_for(parse_resume(text, resume_id, use_llm), timeout=timeout)
        except TimeoutError:
            candidate, llm_used = await parse_resume(text, resume_id, False)
        STRUCTURED_DIR.mkdir(parents=True, exist_ok=True)
        (STRUCTURED_DIR / f"{resume_id}.json").write_text(
            candidate.model_dump_json(indent=2), encoding="utf-8"
        )
        return llm_used


async def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild imported structured resume JSON from saved extracted text.")
    parser.add_argument("--use-llm", action="store_true", help="Call the configured DeepSeek model while reparsing.")
    parser.add_argument("--workers", type=int, default=3, help="Concurrent parsing workers.")
    parser.add_argument("--timeout", type=int, default=90, help="Per-resume timeout in seconds.")
    parser.add_argument("--limit", type=int, default=0, help="Only reparse the first N text files, for smoke tests.")
    parser.add_argument("--job-id", default="", help="Re-extract text from an import job manifest before parsing.")
    args = parser.parse_args()

    from_raw = bool(args.job_id)
    if from_raw:
        manifest = JOB_DIR / f"{args.job_id}.files.json"
        raw_files = json.loads(manifest.read_text(encoding="utf-8"))
        files = [(Path(path), f"I{args.job_id[:4].upper()}{index + 1:05d}") for index, path in enumerate(raw_files)]
    else:
        files = [(path, path.stem) for path in sorted(TEXT_DIR.glob("*.txt"))] if TEXT_DIR.exists() else []
    if args.limit:
        files = files[: args.limit]
    semaphore = asyncio.Semaphore(max(1, args.workers))
    tasks = [
        asyncio.create_task(reparse_one(path, resume_id, args.use_llm, semaphore, args.timeout, from_raw))
        for path, resume_id in files
    ]
    llm_results = []
    for index, task in enumerate(asyncio.as_completed(tasks), 1):
        llm_results.append(await task)
        if index == len(tasks) or index % 20 == 0:
            print(f"processed={index}/{len(tasks)} llm_used={sum(1 for item in llm_results if item)}", flush=True)
    print(f"reparsed={len(files)} llm_used={sum(1 for item in llm_results if item)}")


if __name__ == "__main__":
    asyncio.run(main())
