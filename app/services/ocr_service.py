"""OCR for scanned PDFs and photographed documents (contracts, FIRs, notices).

Pipeline per page:
  1. Pages with a real text layer are used as-is (document_service).
  2. Image-only pages are rendered (pypdfium2, no Poppler needed) and read with
     Tesseract. Tesseract's per-word confidence is averaged for the page.
  3. Pages Tesseract can't read well (low confidence or almost no text, typically
     handwriting or poor scans) go to Claude's vision model, which transcribes them.

System dependency: the Tesseract binary (https://github.com/tesseract-ocr/tesseract;
Windows installer: https://github.com/UB-Mannheim/tesseract/wiki). Extra languages need
their traineddata packs, e.g. OCR_LANGUAGES=eng+hin.

Privacy: the vision fallback sends the page image to the Claude API, and an image can't be
PII-masked. Set OCR_VISION_FALLBACK=false to keep scanned documents on the server.
"""

import io
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageOps

from app.core.config import get_settings

logger = logging.getLogger(__name__)

WINDOWS_TESSERACT = Path("C:/Program Files/Tesseract-OCR/tesseract.exe")
MIN_OCR_CHARS = 25  # less than this on a page counts as "nothing read"
VISION_MAX_EDGE = 1568  # Claude downsizes larger images anyway


class OcrUnavailable(RuntimeError):
    pass


@dataclass
class PageText:
    number: int
    text: str
    method: str  # "text" | "ocr" | "vision" | "none"
    confidence: float | None = None


@dataclass
class OcrResult:
    pages: list[PageText] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n\n".join(f"[Page {p.number}]\n{p.text}" for p in self.pages if p.text.strip())

    def summary(self) -> dict:
        methods: dict[str, int] = {}
        for page in self.pages:
            methods[page.method] = methods.get(page.method, 0) + 1
        confidences = [p.confidence for p in self.pages if p.method == "ocr" and p.confidence is not None]
        return {
            "methods": methods,
            "ocr_mean_confidence": round(sum(confidences) / len(confidences), 1) if confidences else None,
        }


# ----------------------------------------------------------------------------- Tesseract


def _tesseract_cmd() -> str | None:
    configured = get_settings().tesseract_cmd
    if configured:
        return configured if Path(configured).is_file() else None
    found = shutil.which("tesseract")
    if found:
        return found
    return str(WINDOWS_TESSERACT) if WINDOWS_TESSERACT.is_file() else None


def tesseract_available() -> bool:
    return _tesseract_cmd() is not None


def _pytesseract():
    import pytesseract

    cmd = _tesseract_cmd()
    if cmd is None:
        raise OcrUnavailable("Tesseract is not installed (or TESSERACT_CMD is wrong); scanned documents can't be read")
    pytesseract.pytesseract.tesseract_cmd = cmd
    return pytesseract


def _prepare(image: Image.Image) -> Image.Image:
    image = ImageOps.exif_transpose(image)
    gray = ImageOps.grayscale(image)
    # Small photos OCR badly; bring the short edge up to ~1500px.
    short_edge = min(gray.size)
    if short_edge < 1500:
        factor = 1500 / short_edge
        gray = gray.resize((int(gray.width * factor), int(gray.height * factor)), Image.LANCZOS)
    return ImageOps.autocontrast(gray)


def ocr_image(image: Image.Image) -> tuple[str, float]:
    """(text, mean word confidence 0-100). Rebuilds lines and paragraphs from Tesseract's layout."""
    pytesseract = _pytesseract()
    data = pytesseract.image_to_data(
        _prepare(image), lang=get_settings().ocr_languages, output_type=pytesseract.Output.DICT
    )
    lines: dict[tuple[int, int, int], list[str]] = {}
    confidences: list[float] = []
    for i, word in enumerate(data["text"]):
        word = (word or "").strip()
        conf = float(data["conf"][i])
        if not word or conf < 0:
            continue
        confidences.append(conf)
        lines.setdefault((data["block_num"][i], data["par_num"][i], data["line_num"][i]), []).append(word)

    paragraphs: list[list[str]] = []
    last_paragraph = None
    for (block, par, _line), words in sorted(lines.items()):
        if (block, par) != last_paragraph:
            paragraphs.append([])
            last_paragraph = (block, par)
        paragraphs[-1].append(" ".join(words))
    text = "\n\n".join("\n".join(p) for p in paragraphs)
    return text, (sum(confidences) / len(confidences) if confidences else 0.0)


# ----------------------------------------------------------------------------- rendering


def render_pdf_page(data: bytes, page_index: int, dpi: int | None = None) -> Image.Image:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(data)
    try:
        return pdf[page_index].render(scale=(dpi or get_settings().ocr_dpi) / 72).to_pil()
    finally:
        pdf.close()


def _vision_bytes(image: Image.Image) -> tuple[bytes, str]:
    image = ImageOps.exif_transpose(image).convert("RGB")
    image.thumbnail((VISION_MAX_EDGE, VISION_MAX_EDGE))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=88)
    return buffer.getvalue(), "image/jpeg"


# ----------------------------------------------------------------------------- page pipeline


class _VisionBudget:
    def __init__(self):
        settings = get_settings()
        self.remaining = settings.ocr_vision_max_pages if settings.ocr_vision_fallback else 0

    def take(self) -> bool:
        if self.remaining <= 0:
            return False
        self.remaining -= 1
        return True


def read_page_image(image: Image.Image, number: int, budget: _VisionBudget | None = None) -> PageText:
    """OCR one page image, escalating to Claude vision when OCR can't read it."""
    from app.services import anthropic_service

    settings = get_settings()
    budget = budget or _VisionBudget()
    text, confidence = "", 0.0
    if tesseract_available():
        text, confidence = ocr_image(image)
        if len(text.strip()) >= MIN_OCR_CHARS and confidence >= settings.ocr_min_confidence:
            return PageText(number, text, "ocr", round(confidence, 1))

    if anthropic_service.is_configured() and budget.take():
        try:
            image_bytes, media_type = _vision_bytes(image)
            extraction = anthropic_service.extract_text_from_image(image_bytes, media_type)
            if extraction.text.strip():
                return PageText(number, extraction.text.strip(), "vision", None)
        except Exception:
            logger.warning("Vision extraction failed for page %s", number, exc_info=True)

    if text.strip():  # low-confidence OCR beats nothing
        return PageText(number, text, "ocr", round(confidence, 1))
    return PageText(number, "", "none", None)


def ocr_pdf_pages(data: bytes, page_numbers: list[int]) -> list[PageText]:
    """OCR the given 1-based pages of a PDF."""
    settings = get_settings()
    if not tesseract_available() and not (settings.ocr_vision_fallback and _vision_configured()):
        raise OcrUnavailable("No OCR available: install Tesseract or enable the Claude vision fallback")
    budget = _VisionBudget()
    return [read_page_image(render_pdf_page(data, n - 1), n, budget) for n in page_numbers[: settings.ocr_max_pages]]


def ocr_image_document(data: bytes) -> OcrResult:
    """OCR an uploaded image (PNG/JPEG/TIFF/WebP); multi-page TIFFs give one page per frame."""
    settings = get_settings()
    if not tesseract_available() and not (settings.ocr_vision_fallback and _vision_configured()):
        raise OcrUnavailable("No OCR available: install Tesseract or enable the Claude vision fallback")
    image = Image.open(io.BytesIO(data))
    budget = _VisionBudget()
    pages = []
    for index in range(min(getattr(image, "n_frames", 1), settings.ocr_max_pages)):
        image.seek(index)
        pages.append(read_page_image(image.copy(), index + 1, budget))
    return OcrResult(pages)


def _vision_configured() -> bool:
    from app.services import anthropic_service

    return anthropic_service.is_configured()
