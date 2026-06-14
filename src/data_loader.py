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
    return [Candidate.model_validate(record) for record in records]

