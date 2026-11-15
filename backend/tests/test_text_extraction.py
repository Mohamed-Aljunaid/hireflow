import pytest

from app.services.text_extraction import (
    DOCX,
    PDF,
    TXT,
    CorruptDocumentError,
    EmptyDocumentError,
    UnsupportedFileTypeError,
    detect_kind,
    extract_text,
)
from tests.docs import make_docx, make_pdf


@pytest.mark.parametrize(
    ("filename", "content_type", "expected"),
    [
        ("cv.pdf", "application/octet-stream", PDF),
        ("CV.PDF", None, PDF),
        ("cv.docx", None, DOCX),
        ("cv.txt", None, TXT),
        ("cv.md", None, TXT),
        ("upload", PDF, PDF),
    ],
)
def test_detect_kind(filename: str, content_type: str | None, expected: str) -> None:
    assert detect_kind(filename, content_type) == expected


@pytest.mark.parametrize(("filename", "content_type"), [("cv.png", "image/png"), ("cv", None)])
def test_detect_kind_rejects_unsupported(filename: str, content_type: str | None) -> None:
    with pytest.raises(UnsupportedFileTypeError):
        detect_kind(filename, content_type)


def test_extract_txt_normalises_whitespace() -> None:
    data = b"Jordan   Rivera\r\n\r\n\r\n\r\n  Senior   Engineer \n"
    assert extract_text("cv.txt", None, data) == "Jordan Rivera\n\nSenior Engineer"


def test_extract_txt_handles_bom_and_latin1() -> None:
    utf8_bom = b"\xef\xbb\xbf"
    assert extract_text("cv.txt", None, utf8_bom + "José".encode()) == "José"
    assert extract_text("cv.txt", None, "José".encode("latin-1")) == "José"


def test_extract_pdf() -> None:
    data = make_pdf(["Jordan Rivera", "Senior Backend Engineer (Acme)"])
    text = extract_text("cv.pdf", PDF, data)
    assert "Jordan Rivera" in text
    assert "Senior Backend Engineer (Acme)" in text


def test_extract_docx_includes_tables() -> None:
    data = make_docx(["Jordan Rivera", "Skills"], table=[["Python", "FastAPI"]])
    text = extract_text("cv.docx", DOCX, data)
    assert text.splitlines()[0] == "Jordan Rivera"
    assert "Python | FastAPI" in text


def test_empty_document_raises() -> None:
    with pytest.raises(EmptyDocumentError):
        extract_text("cv.txt", None, b"   \n\n ")
    with pytest.raises(EmptyDocumentError):
        extract_text("cv.pdf", None, make_pdf([]))


@pytest.mark.parametrize("filename", ["cv.pdf", "cv.docx"])
def test_corrupt_document_raises(filename: str) -> None:
    with pytest.raises(CorruptDocumentError):
        extract_text(filename, None, b"definitely not a real file")
