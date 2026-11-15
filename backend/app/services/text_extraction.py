"""Turn an uploaded CV file (PDF, DOCX, TXT) into plain text."""

import io
from pathlib import PurePath

import docx
from pypdf import PdfReader
from pypdf.errors import PdfReadError

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
TXT = "text/plain"

_EXTENSIONS = {".pdf": PDF, ".docx": DOCX, ".txt": TXT, ".md": TXT}


class UnsupportedFileTypeError(ValueError):
    pass


class EmptyDocumentError(ValueError):
    pass


class CorruptDocumentError(ValueError):
    pass


def detect_kind(filename: str, content_type: str | None) -> str:
    """Pick the parser from the extension first (browsers send unreliable MIME types)."""
    ext = PurePath(filename).suffix.lower()
    if ext in _EXTENSIONS:
        return _EXTENSIONS[ext]
    if content_type in {PDF, DOCX, TXT}:
        return content_type
    raise UnsupportedFileTypeError(f"unsupported file type: {filename!r} ({content_type})")


def _pdf_text(data: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except PdfReadError as exc:
        raise CorruptDocumentError(f"could not read PDF: {exc}") from exc


def _docx_text(data: bytes) -> str:
    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:  # python-docx raises several unrelated types
        raise CorruptDocumentError(f"could not read DOCX: {exc}") from exc
    lines = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            lines.append(" | ".join(cell.text for cell in row.cells))
    return "\n".join(lines)


def _plain_text(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def extract_text(filename: str, content_type: str | None, data: bytes) -> str:
    kind = detect_kind(filename, content_type)
    if kind == PDF:
        text = _pdf_text(data)
    elif kind == DOCX:
        text = _docx_text(data)
    else:
        text = _plain_text(data)

    # Normalise whitespace per line, drop runs of blank lines.
    lines = [" ".join(line.split()) for line in text.splitlines()]
    cleaned = "\n".join(line for i, line in enumerate(lines) if line or (i and lines[i - 1]))
    cleaned = cleaned.strip()
    if not cleaned:
        raise EmptyDocumentError(
            "no text found in the document (scanned PDFs without a text layer are not supported)"
        )
    return cleaned
