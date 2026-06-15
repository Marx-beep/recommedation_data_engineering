from __future__ import annotations

import re
import os
from pathlib import Path

import fitz
import pytesseract
from docx import Document
from PIL import Image


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".rtf", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}


def _configure_tesseract() -> str:
    executable = Path(os.getenv("TESSERACT_CMD", r"C:\Program Files\Tesseract-OCR\tesseract.exe"))
    if executable.exists():
        pytesseract.pytesseract.tesseract_cmd = str(executable)
    tessdata = Path(os.getenv("TESSDATA_DIR", Path(os.getenv("LOCALAPPDATA", "")) / "Tesseract-OCR" / "tessdata"))
    if tessdata.exists():
        os.environ["TESSDATA_PREFIX"] = str(tessdata)
    return ""


def _ocr_image(image: Image.Image) -> str:
    config = _configure_tesseract()
    try:
        return pytesseract.image_to_string(image, lang="chi_sim+eng", config=config)
    except pytesseract.TesseractNotFoundError as exc:
        raise ValueError("OCR 需要本机安装 Tesseract") from exc
    except pytesseract.TesseractError:
        return pytesseract.image_to_string(image, lang="eng", config=config)


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        with fitz.open(path) as document:
            text = "\n".join(page.get_text("text") for page in document)
            if len(text.strip()) < 80:
                ocr_pages = []
                for page in document:
                    pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                    image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
                    ocr_pages.append(_ocr_image(image))
                text = "\n".join(ocr_pages)
    elif suffix == ".docx":
        document = Document(path)
        text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    elif suffix in {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}:
        try:
            with Image.open(path) as image:
                text = _ocr_image(image)
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
