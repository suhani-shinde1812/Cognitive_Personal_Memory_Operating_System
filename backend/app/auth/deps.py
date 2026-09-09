# LOCATION: backend/app/auth/deps.py
"""
deps.py
=======
FastAPI authentication dependencies for protecting endpoints and extracting current user.
"""

from __future__ import annotations
from typing import Optional
from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session
from database.database import get_db
from app.models.user import User
from app.models.sync_device import SyncDevice
from app.auth.security import decode_access_token

COOKIE_NAME = "access_token"
COOKIE_MAX_AGE = 7 * 24 * 3600  # 7 days in seconds


def set_auth_cookie(response: Response, token: str) -> None:
    """Sets a secure HTTP-only cookie with cross-site SameSite=None support."""
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="none",
        secure=True,
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    """Clears the authentication cookie."""
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        samesite="none",
        secure=True,
    )


def extract_token_from_request(request: Request) -> Optional[str]:
    """Extracts JWT token from cookie or Authorization header."""
    # 1. Preferred: HTTP-only cookie
    token = request.cookies.get(COOKIE_NAME)
    if token:
        return token

    # 2. Fallback: Authorization: Bearer <token>
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header[7:].strip()

    return None


def _resolve_user_from_token(token: str, db: Session) -> Optional[User]:
    """Helper to resolve a User from either a JWT access token or a paired SyncDevice auth_token."""
    # 1. Attempt JWT access token decode
    payload = decode_access_token(token)
    if payload and "sub" in payload:
        sub_val = payload["sub"]
        try:
            user_id = int(sub_val)
            user = db.query(User).filter(User.id == user_id).first()
            if user:
                return user
        except (ValueError, TypeError):
            pass

        # Fallback if user id is stored as string/varchar in PostgreSQL
        try:
            user = db.query(User).filter(User.id == str(sub_val)).first()
            if user:
                return user
        except Exception:
            pass

    # 2. Check if this is a paired Desktop Agent device token (e.g. cs_...)
    device = db.query(SyncDevice).filter(SyncDevice.auth_token == token).first()
    if device and device.user_id:
        try:
            user = db.query(User).filter(User.id == device.user_id).first()
            if user:
                return user
        except Exception:
            pass
        try:
            user = db.query(User).filter(User.id == str(device.user_id)).first()
            if user:
                return user
        except Exception:
            pass

    return None


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """
    Dependency that enforces authentication.
    Accepts JWT access tokens or paired desktop agent auth tokens.
    Raises HTTP 401 if token is missing, invalid, or user does not exist.
    """
    token = extract_token_from_request(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please log in.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = _resolve_user_from_token(token, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def get_optional_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> Optional[User]:
    """
    Dependency that returns the authenticated User if valid token is provided,
    or None if unauthenticated (without raising an exception).
    """
    token = extract_token_from_request(request)
    if not token:
        return None

    return _resolve_user_from_token(token, db)
