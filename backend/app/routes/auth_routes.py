# LOCATION: backend/app/routes/auth_routes.py
"""
auth_routes.py
==============
Authentication routes for CogniSphere:
- POST /auth/register
- POST /auth/login
- POST /auth/logout
- GET  /auth/me
- POST /auth/change-password
"""

from __future__ import annotations
import re
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database.database import get_db
from app.models.user import User
from app.models.memory import Memory
from app.models.goal import Goal
from app.auth.security import hash_password, verify_password, create_access_token
from app.auth.deps import get_current_user, set_auth_cookie, clear_auth_cookie

router = APIRouter(prefix="/auth", tags=["auth"])

EMAIL_REGEX = re.compile(r"^[\w\.\+\-]+@[a-zA-Z0-9\-]+\.[a-zA-Z0-9\-\.]+$")


class RegisterRequest(BaseModel):
    email:    str
    password: str


class LoginRequest(BaseModel):
    email:    str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password:     str


def _ensure_users_table_schema(db: Session) -> None:
    """Safely ensures users table has required columns and sequence in PostgreSQL."""
    from sqlalchemy import text
    from database.database import is_sqlite
    if is_sqlite:
        return
    stmts = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash VARCHAR;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at VARCHAR;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at VARCHAR;",
        "CREATE SEQUENCE IF NOT EXISTS users_id_seq;",
    ]
    for s in stmts:
        try:
            db.execute(text(s))
            db.commit()
        except Exception:
            db.rollback()
    try:
        db.execute(text("ALTER TABLE users ALTER COLUMN id TYPE INTEGER USING id::integer;"))
        db.commit()
    except Exception:
        db.rollback()
    try:
        db.execute(text("ALTER TABLE users ALTER COLUMN id SET DEFAULT nextval('users_id_seq');"))
        db.commit()
    except Exception:
        try:
            db.execute(text("ALTER TABLE users ALTER COLUMN id SET DEFAULT nextval('users_id_seq')::text;"))
            db.commit()
        except Exception:
            db.rollback()


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(req: RegisterRequest, response: Response, db: Session = Depends(get_db)):
    """Registers a new user and returns authentication session."""
    email = req.email.strip().lower()
    if not email or not EMAIL_REGEX.match(email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please provide a valid email address.",
        )

    if not req.password or len(req.password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters long.",
        )

    try:
        existing = db.query(User).filter(User.email == email).first()
    except Exception:
        db.rollback()
        _ensure_users_table_schema(db)
        try:
            existing = db.query(User).filter(User.email == email).first()
        except Exception as retry_err:
            db.rollback()
            print(f"[Auth] Database error checking existing user {email}: {retry_err}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database error checking account: {retry_err}",
            )

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email address already exists. Please log in.",
        )

    try:
        user = User(
            email=email,
            password_hash=hash_password(req.password),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    except Exception:
        db.rollback()
        _ensure_users_table_schema(db)
        try:
            user = User(
                email=email,
                password_hash=hash_password(req.password),
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        except Exception as retry_err:
            db.rollback()
            print(f"[Auth] Database error creating user {email}: {retry_err}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database error creating user: {retry_err}",
            )

    # Persist account to persisted_accounts.json so it survives container reboots
    try:
        import json
        import os
        backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        accounts_file = os.path.join(backend_dir, "persisted_accounts.json")
        accounts = []
        if os.path.exists(accounts_file):
            with open(accounts_file, "r", encoding="utf-8") as f:
                accounts = json.load(f)
        if not any((a.get("email") or "").strip().lower() == email for a in accounts):
            accounts.append({
                "email": email,
                "password_hash": user.password_hash,
                "created_at": user.created_at,
            })
            with open(accounts_file, "w", encoding="utf-8") as f:
                json.dump(accounts, f, indent=2)
    except Exception as _e:
        print(f"[Auth] Account JSON persistence notice: {_e}")

    # Safe backward-compatibility migration:
    # If unowned legacy memories or goals exist, claim them for the first user
    try:
        unowned_count = db.query(Memory).filter(Memory.user_id.is_(None)).count()
        if unowned_count > 0:
            db.query(Memory).filter(Memory.user_id.is_(None)).update({"user_id": user.id})
            db.query(Goal).filter(Goal.user_id.is_(None)).update({"user_id": user.id})
            db.commit()
    except Exception as _e:
        db.rollback()
        print(f"[Auth] Legacy memory claim notice: {_e}")

    token = create_access_token({"sub": str(user.id), "email": user.email})
    set_auth_cookie(response, token)

    return {
        "status":  "ok",
        "message": "Account registered successfully.",
        "user":    user.to_dict(),
        "token":   token,
    }


@router.post("/login")
def login(req: LoginRequest, response: Response, db: Session = Depends(get_db)):
    """Logs in an existing user and returns authentication session."""
    email = req.email.strip().lower()
    if not email or not req.password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email and password are required.",
        )

    try:
        user = db.query(User).filter(User.email == email).first()
    except Exception:
        db.rollback()
        _ensure_users_table_schema(db)
        try:
            user = db.query(User).filter(User.email == email).first()
        except Exception as retry_err:
            db.rollback()
            print(f"[Auth] Database error looking up user {email}: {retry_err}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database error during login: {retry_err}",
            )

    valid_pass = False
    if user:
        valid_pass = verify_password(req.password, user.password_hash) or verify_password(req.password.strip(), user.password_hash)

    if not user or not valid_pass:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token({"sub": str(user.id), "email": user.email})
    set_auth_cookie(response, token)

    return {
        "status":  "ok",
        "message": "Logged in successfully.",
        "user":    user.to_dict(),
        "token":   token,
    }


@router.post("/logout")
def logout(response: Response):
    """Logs out current user and clears authentication cookie."""
    clear_auth_cookie(response)
    return {"status": "ok", "message": "Logged out successfully."}


@router.get("/me")
def get_me(current_user: User = Depends(get_current_user)):
    """Returns profile for currently authenticated user."""
    return current_user.to_dict()


@router.post("/change-password")
def change_password(
    req: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Changes password for the currently authenticated user."""
    if not verify_password(req.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password does not match.",
        )

    if not req.new_password or len(req.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be at least 8 characters long.",
        )

    current_user.password_hash = hash_password(req.new_password)
    db.commit()

    return {"status": "ok", "message": "Password changed successfully."}
