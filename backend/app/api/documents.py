import asyncio
import io
from pathlib import PurePath
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from app.api.deps import DatabaseSession, get_current_user
from app.api.deps_rag import EmbedderDep, Store
from app.core.config import settings
from app.models.entities import Document, User
from app.rag.chunking import STRATEGIES
from app.rag.pipeline import EmptyDocumentError, IndexingError, ingest_document
from app.schemas.documents import CrawlRequest, DocumentResponse
from app.services.crawl import CrawlError, fetch_page_text

MAX_UPLOAD_BYTES = 10_000_000
MARKDOWN_SUFFIXES = {".md", ".markdown", ".txt"}

router = APIRouter(prefix="/documents", tags=["documents"])
CurrentUser = Annotated[User, Depends(get_current_user)]


def _resolve_strategy(strategy: str | None) -> str:
    resolved = strategy or settings.chunk_strategy
    if resolved not in STRATEGIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"strategy must be one of {sorted(STRATEGIES)}",
        )
    return resolved


def _extract_pdf_text(data: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(data))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    except PyPdfError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not read PDF",
        ) from None


def _to_response(document: Document, strategy: str, chunk_count: int) -> DocumentResponse:
    return DocumentResponse(
        id=document.id,
        filename=document.filename,
        source_type=document.source_type,
        source_uri=document.source_uri,
        status=document.status,
        strategy=strategy,
        chunk_count=chunk_count,
    )


async def _ingest_or_422(*args, **kwargs):
    try:
        return await ingest_document(*args, **kwargs)
    except EmptyDocumentError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from None
    except IndexingError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
        ) from None


@router.post("/upload", response_model=DocumentResponse)
async def upload_document(
    user: CurrentUser,
    session: DatabaseSession,
    store: Store,
    embedder: EmbedderDep,
    file: Annotated[UploadFile, File()],
    strategy: Annotated[str | None, Query()] = None,
) -> DocumentResponse:
    resolved = _resolve_strategy(strategy)
    filename = PurePath(file.filename or "upload").name
    suffix = PurePath(filename).suffix.lower()
    if suffix != ".pdf" and suffix not in MARKDOWN_SUFFIXES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only PDF and Markdown files are supported",
        )
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File is too large",
        )
    if suffix == ".pdf":
        text = await asyncio.to_thread(_extract_pdf_text, data)
    else:
        text = data.decode("utf-8", errors="replace")

    document, records = await _ingest_or_422(
        session,
        store,
        embedder,
        owner_user_id=user.id,
        filename=filename,
        source_type="pdf" if suffix == ".pdf" else "markdown",
        source_uri=None,
        text=text,
        strategy=resolved,
    )
    return _to_response(document, resolved, len(records))


@router.post("/crawl", response_model=DocumentResponse)
async def crawl_document(
    payload: CrawlRequest,
    user: CurrentUser,
    session: DatabaseSession,
    store: Store,
    embedder: EmbedderDep,
    strategy: Annotated[str | None, Query()] = None,
) -> DocumentResponse:
    resolved = _resolve_strategy(strategy)
    try:
        title, text = await fetch_page_text(payload.url)
    except CrawlError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from None

    document, records = await _ingest_or_422(
        session,
        store,
        embedder,
        owner_user_id=user.id,
        filename=title[:255],
        source_type="web",
        source_uri=payload.url,
        text=text,
        strategy=resolved,
    )
    return _to_response(document, resolved, len(records))
