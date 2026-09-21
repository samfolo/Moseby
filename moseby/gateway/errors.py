"""Map expected service failures to HTTP responses."""

from fastapi import Request
from fastapi.responses import JSONResponse

from moseby.db.pagination import InvalidCursor

READ_RESPONSES = {
    400: {"description": "The cursor is invalid or belongs to another search."},
    403: {"description": "The caller lacks the required read access."},
    503: {"description": "The gateway has not been configured."},
}


async def permission_denied(request: Request, error: PermissionError) -> JSONResponse:
    return JSONResponse(
        status_code=403, content={"detail": "The required permission is missing."}
    )


async def invalid_cursor(request: Request, error: InvalidCursor) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={
            "detail": "Use a cursor from the same search or omit it to start again."
        },
    )
