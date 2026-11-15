import logging
import uuid

from fastapi import APIRouter, HTTPException, UploadFile, status
from starlette.concurrency import run_in_threadpool

from app.api.deps import LLMDep, SessionDep, SettingsDep
from app.api.schemas import CVRead
from app.core.llm import LLMError, LLMUnavailableError
from app.services import cv_repository
from app.services.cv_parser import parse_cv
from app.services.text_extraction import (
    CorruptDocumentError,
    EmptyDocumentError,
    UnsupportedFileTypeError,
    detect_kind,
    extract_text,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/cvs", tags=["cvs"])


@router.post("", response_model=CVRead, status_code=status.HTTP_201_CREATED)
async def upload_cv(
    file: UploadFile, session: SessionDep, llm: LLMDep, settings: SettingsDep
) -> CVRead:
    filename = file.filename or "upload"
    try:
        kind = detect_kind(filename, file.content_type)
    except UnsupportedFileTypeError as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc

    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"file exceeds {settings.max_upload_bytes} bytes",
        )

    try:
        text = await run_in_threadpool(extract_text, filename, kind, data)
    except (EmptyDocumentError, CorruptDocumentError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    try:
        parsed = await parse_cv(text, llm)
    except LLMUnavailableError as exc:
        logger.error("LLM unavailable: %s", exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except LLMError as exc:
        logger.warning("cv parsing failed: %s", exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"CV parsing failed: {exc}") from exc

    cv = await cv_repository.create_cv(
        session, filename=filename, content_type=kind, raw_text=text, parsed=parsed
    )
    return CVRead.model_validate(cv)


@router.get("/{cv_id}", response_model=CVRead)
async def read_cv(cv_id: uuid.UUID, session: SessionDep) -> CVRead:
    cv = await cv_repository.get_cv(session, cv_id)
    if cv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "CV not found")
    return CVRead.model_validate(cv)
