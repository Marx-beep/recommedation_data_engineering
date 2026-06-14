from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from src.config import ROOT
from src.models import Candidate


@lru_cache(maxsize=1)
def load_candidates() -> list[Candidate]:
    path = ROOT / "data" / "structured_resumes" / "sample_candidates.json"
    records = json.loads(path.read_text(encoding="utf-8"))
    imported = ROOT / "data" / "structured_resumes" / "imported"
    for candidate_file in sorted(imported.glob("*.json")) if imported.exists() else []:
        try:
            records.append(json.loads(candidate_file.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return [Candidate.model_validate(record) for record in records]


def refresh_candidates() -> list[Candidate]:
    load_candidates.cache_clear()
    return load_candidates()
