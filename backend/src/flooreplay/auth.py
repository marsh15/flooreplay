"""Individual accounts and revocable, hashed, eight-hour bearer sessions."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import Depends, Request
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, select
from sqlalchemy.orm import Mapped, mapped_column

from .db import session_scope
from .models import Base
from .service import ServiceError

hasher = PasswordHasher()
# Make unknown-account verification take the same expensive path.
_dummy_hash = hasher.hash(secrets.token_urlsafe(24))


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    username: Mapped[str] = mapped_column(String(120), unique=True)
    display_name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(16))
    password_hash: Mapped[str] = mapped_column(String(256))
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class AccessLimit(Base):
    __tablename__ = "access_limits"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
    reset_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def user_view(user: Account) -> dict[str, str]:
    return {"id": user.id, "username": user.username, "display_name": user.display_name, "role": user.role}


def enforce_access_limit(identity: str, limit: int, seconds: int) -> None:
    """Persist rate limits across API instances, including failed logins."""
    from sqlalchemy.dialects.postgresql import insert

    key = hashlib.sha256(identity.encode()).hexdigest()
    now = datetime.now(UTC)
    with session_scope() as session:
        session.execute(insert(AccessLimit).values(key=key, count=0, reset_at=now + timedelta(seconds=seconds)).on_conflict_do_nothing())
        row = session.execute(select(AccessLimit).where(AccessLimit.key == key).with_for_update()).scalar_one()
        if row.reset_at <= now:
            row.count = 0
            row.reset_at = now + timedelta(seconds=seconds)
        if row.count >= limit:
            raise ServiceError("RATE_LIMITED", "Please wait before trying again", 429)
        row.count += 1


def sign_in(username: str, password: str, client: str) -> dict[str, Any]:
    enforce_access_limit("login:" + client, 10, 900)
    with session_scope() as session:
        user = session.execute(select(Account).where(Account.username == username.strip().lower())).scalar_one_or_none()
        try:
            hasher.verify(user.password_hash if user else _dummy_hash, password)
        except VerificationError:
            raise ServiceError("INVALID_CREDENTIALS", "Username or password is incorrect", 401) from None
        if user is None or user.disabled:
            raise ServiceError("INVALID_CREDENTIALS", "Username or password is incorrect", 401)
        token = secrets.token_urlsafe(48)
        expiry = datetime.now(UTC) + timedelta(hours=8)
        session.add(AuthSession(token_hash=hashlib.sha256(token.encode()).hexdigest(), account_id=user.id, expires_at=expiry))
        return {"token": token, "user": user_view(user), "expires_at": expiry.isoformat()}


def current_user(request: Request) -> Account | None:
    authorization = request.headers.get("Authorization", "")
    if not authorization:
        return None
    if not authorization.startswith("Bearer ") or len(authorization) > 300:
        raise ServiceError("SESSION_INVALID", "Sign in again", 401)
    token_hash = hashlib.sha256(authorization[7:].encode()).hexdigest()
    with session_scope() as session:
        auth = session.get(AuthSession, token_hash)
        if auth is None or auth.revoked or auth.expires_at <= datetime.now(UTC):
            raise ServiceError("SESSION_EXPIRED", "Sign in again", 401)
        user = session.get(Account, auth.account_id)
        if user is None or user.disabled:
            raise ServiceError("ACCOUNT_DISABLED", "Account access is disabled", 401)
        return user


def require_reviewer(user: Annotated[Account | None, Depends(current_user)]) -> Account:
    if user is None:
        raise ServiceError("SIGN_IN_REQUIRED", "Sign in as an invited reviewer", 401)
    return user


def require_owner(user: Annotated[Account, Depends(require_reviewer)]) -> Account:
    if user.role != "owner":
        raise ServiceError("OWNER_REQUIRED", "This operation requires the owner", 403)
    return user


def sign_out(request: Request) -> None:
    token = request.headers.get("Authorization", "")[7:]
    with session_scope() as session:
        auth = session.get(AuthSession, hashlib.sha256(token.encode()).hexdigest())
        if auth:
            auth.revoked = True


def create_account(username: str, password: str, role: str, display_name: str | None = None) -> dict[str, str]:
    username = username.strip().lower()
    if role not in {"owner", "reviewer"} or not 3 <= len(username) <= 120 or len(password) < 12:
        raise ValueError("Use an owner/reviewer role, a username of 3–120 characters and a password of at least 12 characters")
    with session_scope() as session:
        if session.scalar(select(Account.id).where(Account.username == username)):
            raise ValueError("Account already exists")
        user = Account(username=username, password_hash=hasher.hash(password), role=role, display_name=display_name or username)
        session.add(user)
        session.flush()
        return user_view(user)


def disable_account(username: str) -> None:
    with session_scope() as session:
        user = session.scalar(select(Account).where(Account.username == username.strip().lower()))
        if user is None:
            raise ValueError("Unknown account")
        user.disabled = True
