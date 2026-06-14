from __future__ import annotations

import re
from pathlib import Path

import fitz
import pytesseract
from docx import Document
from PIL import Image


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".rtf", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        with fitz.open(path) as document:
            text = "\n".join(page.get_text("text") for page in document)
    elif suffix == ".docx":
        document = Document(path)
        text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    elif suffix in {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}:
        try:
            with Image.open(path) as image:
                text = pytesseract.image_to_string(image, lang="chi_sim+eng")
        except pytesseract.TesseractNotFoundError as exc:
            raise ValueError("图片 OCR 需要本机安装 Tesseract") from exc
    elif suffix in {".txt", ".md", ".rtf"}:
        text = path.read_text(encoding="utf-8", errors="ignore")
    else:
        raise ValueError(f"不支持的文件类型：{suffix or '未知'}")
    text = clean_and_anonymize(text)
    if len(text) < 20:
        raise ValueError("未提取到足够的简历文本")
    return text


def clean_and_anonymize(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[\t ]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", "[手机号已脱敏]", text)
    text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "[邮箱已脱敏]", text)
    text = re.sub(r"(?<!\d)\d{17}[\dXx](?!\d)", "[身份证号已脱敏]", text)
    return text.strip()
