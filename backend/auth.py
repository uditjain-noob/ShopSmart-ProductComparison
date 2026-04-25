"""Authentication utilities for ShopSmart API."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from dotenv import load_dotenv
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext

from .database import get_user_by_id

load_dotenv()

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_bearer = HTTPBearer(auto_error=False)
_ALGORITHM = "HS256"
_TOKEN_DAYS = 30


def hash_password(plain_password: str) -> str:
    return _pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return _pwd_context.verify(plain_password, hashed_password)


def _secret_key() -> str:
    secret = os.getenv("JWT_SECRET_KEY")
    if not secret:
        raise RuntimeError("JWT_SECRET_KEY is required")
    return secret


def create_token(user_id: str, email: str) -> str:
    expires_at = datetime.now(UTC) + timedelta(days=_TOKEN_DAYS)
    payload = {
        "sub": user_id,
        "email": email,
        "exp": expires_at,
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, _secret_key(), algorithm=_ALGORITHM)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict[str, Any]:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        payload = jwt.decode(credentials.credentials, _secret_key(), algorithms=[_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="Session expired") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User no longer exists")
    return user
