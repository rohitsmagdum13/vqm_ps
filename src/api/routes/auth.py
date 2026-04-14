"""Authentication endpoints for VQMS.

POST /auth/login  — Authenticate with username/email + password, get JWT
POST /auth/logout — Blacklist the current token (invalidate session)
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from models.auth import LoginRequest, LoginResponse
from services.auth import AuthenticationError, authenticate_user, blacklist_token
from utils.decorators import log_api_call
from utils.helpers import IdGenerator

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["auth"])


@router.post("/auth/login")
@log_api_call
async def login(request_body: LoginRequest) -> LoginResponse:
    """Authenticate a user and return a JWT token."""
    correlation_id = IdGenerator.generate_correlation_id()

    try:
        response = await authenticate_user(
            username_or_email=request_body.username_or_email,
            password=request_body.password,
            correlation_id=correlation_id,
        )
    except AuthenticationError as exc:
        logger.warning(
            "Login rejected",
            username_or_email=request_body.username_or_email,
            reason=str(exc),
            correlation_id=correlation_id,
        )
        return JSONResponse(
            status_code=401,
            content={"detail": str(exc)},
        )

    return response


@router.post("/auth/logout")
@log_api_call
async def logout(request: Request) -> dict:
    """Log out by blacklisting the current JWT token."""
    correlation_id = IdGenerator.generate_correlation_id()

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse(
            status_code=401,
            content={"detail": "No token provided"},
        )

    token = auth_header[7:]

    try:
        await blacklist_token(token, correlation_id=correlation_id)
    except AuthenticationError as exc:
        logger.warning(
            "Logout failed",
            reason=str(exc),
            correlation_id=correlation_id,
        )
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )

    return {"message": "Logged out successfully"}
