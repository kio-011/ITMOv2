from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, File, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.db import get_db_session
from app.dependencies import get_today
from app.models import User
from app.schemas.imports import ConfirmRequest, ConfirmResponse, ImportRead
from app.services import imports as service

router = APIRouter(prefix="/api/imports/statement", tags=["imports"])

ALLOWED_SUFFIXES = (".csv", ".txt", ".tsv")


def _now() -> datetime:
    """A dependency so tests can pin the clock the same way they pin the date."""
    return datetime.now(UTC)


@router.post("", response_model=ImportRead, status_code=status.HTTP_201_CREATED)
async def upload_statement(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    today: date = Depends(get_today),
    now: datetime = Depends(_now),
) -> dict:
    filename = file.filename or "statement.csv"
    if not filename.lower().endswith(ALLOWED_SUFFIXES):
        raise service.api_error(
            "statement.unsupported_media_type",
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            allowed=list(ALLOWED_SUFFIXES),
        )
    record = await service.create_import(
        session, user, filename, await file.read(), now, today
    )
    return service.to_read(record)


@router.get("/{import_id}", response_model=ImportRead)
async def read_statement_import(
    import_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    now: datetime = Depends(_now),
) -> dict:
    return service.to_read(await service.load_import(session, user, import_id, now))


@router.post(
    "/{import_id}/confirm",
    response_model=ConfirmResponse,
    status_code=status.HTTP_201_CREATED,
)
async def confirm_statement_import(
    import_id: str,
    body: ConfirmRequest,
    response: Response,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    today: date = Depends(get_today),
    now: datetime = Depends(_now),
) -> ConfirmResponse:
    result, replayed = await service.confirm_import(
        session, user, import_id, body, now, today
    )
    if replayed:
        response.status_code = status.HTTP_200_OK
    return result


@router.delete("/{import_id}", status_code=status.HTTP_204_NO_CONTENT)
async def discard_statement_import(
    import_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    now: datetime = Depends(_now),
) -> Response:
    await service.discard_import(session, user, import_id, now)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
