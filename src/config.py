from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read_local_key() -> str:
    key_file = ROOT / "api"
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()
    return ""


@dataclass(frozen=True)
class Settings:
    api_key: str = os.getenv("DEEPSEEK_API_KEY", "") or _read_local_key()
    base_url: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    use_llm: bool = os.getenv("USE_LLM", "true").lower() not in {"0", "false", "no"}
    import_workers: int = int(os.getenv("IMPORT_WORKERS", "3"))
    max_batch_files: int = int(os.getenv("MAX_BATCH_FILES", "10000"))
    max_file_mb: int = int(os.getenv("MAX_FILE_MB", "50"))
    max_batch_gb: int = int(os.getenv("MAX_BATCH_GB", "5"))


settings = Settings()
