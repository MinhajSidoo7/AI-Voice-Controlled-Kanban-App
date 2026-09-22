"""
auth.py - Authentication and User Board State Management
Provides secure salted PBKDF2 password hashing, JWT token lifecycle,
and dual-backend storage (Supabase PostgreSQL in production, with local SQLite fallback).
"""

import os
import sqlite3
import secrets
import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple, Dict, Any
import jwt
from dotenv import load_dotenv

load_dotenv()

# ─── Configuration & Security Settings ──────────────────────────────
JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "kanban-secret-key-change-in-production-ai-voice")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_DAYS = int(os.environ.get("JWT_EXPIRE_DAYS", "7"))
HASH_ITERATIONS = 100_000

# Supabase Credentials
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

# SQLite Fallback Path (uses /tmp on Vercel if Supabase is not configured)
if os.environ.get("VERCEL"):
    DEFAULT_DB_PATH = "/tmp/kanban_users.db"
else:
    DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kanban_users.db")

# ─── Supabase Client Initialization ──────────────────────────────────
_supabase_client = None


def normalize_supabase_url(url: Optional[str]) -> Optional[str]:
    """Normalize Supabase URL by stripping /rest/v1 suffix and trailing slashes."""
    if not url:
        return None
    cleaned = url.strip()
    if "/rest/v1" in cleaned:
        cleaned = cleaned.split("/rest/v1")[0]
    return cleaned.rstrip("/")


def get_supabase_client():
    """Returns initialized Supabase client if credentials exist, else None."""
    global _supabase_client
    url = normalize_supabase_url(os.environ.get("SUPABASE_URL") or SUPABASE_URL)
    key = os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or SUPABASE_KEY
    if not url or not key:
        return None
    if _supabase_client is None:
        try:
            from supabase import create_client
            _supabase_client = create_client(url, key)
        except Exception as err:
            print(f"⚠️ Could not initialize Supabase client: {err}. Falling back to SQLite.")
            return None
    return _supabase_client


# ─── SQLite Local Fallback Helpers ────────────────────────────────────

def get_db_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = db_path or os.environ.get("DB_PATH") or DEFAULT_DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Optional[str] = None) -> None:
    """Initialize SQLite database tables for users and user boards."""
    conn = get_db_connection(db_path)
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_boards (
                user_id TEXT PRIMARY KEY,
                board_data TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
    conn.close()


# Ensure SQLite tables exist upon import (for offline/test mode)
init_db()


# ─── Cryptographic Password Hashing & Verification ───────────────────

def hash_password(password: str, salt: Optional[str] = None) -> Tuple[str, str]:
    """Hash password using PBKDF2-HMAC-SHA256 with cryptographically random salt."""
    if salt is None:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        HASH_ITERATIONS
    )
    return dk.hex(), salt


def verify_password(password: str, stored_hash: str, salt: str) -> bool:
    """Verify password against stored salt and PBKDF2 hash using constant-time comparison."""
    calculated_hash, _ = hash_password(password, salt)
    return secrets.compare_digest(calculated_hash, stored_hash)


# ─── JWT Token Lifecycle ─────────────────────────────────────────────

def create_access_token(user_id: str, username: str, expires_delta: Optional[timedelta] = None) -> str:
    """Generate a signed JWT access token."""
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(days=JWT_EXPIRE_DAYS)

    payload = {
        "sub": user_id,
        "username": username,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp())
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode and validate a JWT access token. Returns payload dict or None."""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except (jwt.PyJWTError, Exception):
        return None


# ─── Dual-Storage User Operations (Supabase / SQLite) ────────────────

def create_user(
    username: str,
    password: str,
    initial_board: Optional[Dict[str, Any]] = None,
    db_path: Optional[str] = None
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Register a new user and initialize an optional default board.
    Uses Supabase if configured, otherwise falls back to SQLite.
    Returns (user_dict, None) on success, or (None, error_message) on failure.
    """
    clean_username = username.strip()
    if not clean_username or len(clean_username) < 3:
        return None, "Username must be at least 3 characters long."
    if len(clean_username) > 50:
        return None, "Username cannot exceed 50 characters."
    if not password or len(password) < 4:
        return None, "Password must be at least 4 characters long."
    if len(password) > 128:
        return None, "Password cannot exceed 128 characters."

    pwd_hash, salt = hash_password(password)
    user_id = str(secrets.token_hex(12))
    created_at = datetime.now(timezone.utc).isoformat()

    # 1. Try Supabase
    supabase = get_supabase_client()
    if supabase and not db_path:
        try:
            # Check duplicate username
            existing = supabase.table("users").select("id").ilike("username", clean_username).execute()
            if existing.data:
                return None, "Username already exists. Please choose another username."

            user_row = {
                "id": user_id,
                "username": clean_username,
                "password_hash": pwd_hash,
                "salt": salt,
                "created_at": created_at
            }
            supabase.table("users").insert(user_row).execute()

            if initial_board:
                board_row = {
                    "user_id": user_id,
                    "board_data": initial_board,
                    "updated_at": created_at
                }
                supabase.table("user_boards").insert(board_row).execute()

            return {"id": user_id, "username": clean_username, "created_at": created_at}, None
        except Exception as e:
            err_msg = str(e).lower()
            if "duplicate key" in err_msg or "unique" in err_msg:
                return None, "Username already exists. Please choose another username."
            print(f"⚠️ Supabase error creating user: {e}. Falling back to SQLite.")

    # 2. SQLite Fallback
    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.execute(
                "INSERT INTO users (id, username, password_hash, salt, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, clean_username, pwd_hash, salt, created_at)
            )
            if initial_board:
                conn.execute(
                    "INSERT INTO user_boards (user_id, board_data, updated_at) VALUES (?, ?, ?)",
                    (user_id, json.dumps(initial_board), created_at)
                )
        return {"id": user_id, "username": clean_username, "created_at": created_at}, None
    except sqlite3.IntegrityError:
        return None, "Username already exists. Please choose another username."
    finally:
        conn.close()


def authenticate_user(
    username: str,
    password: str,
    db_path: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Validate username and password. Returns user dict or None."""
    clean_username = username.strip()

    # 1. Try Supabase
    supabase = get_supabase_client()
    if supabase and not db_path:
        try:
            res = supabase.table("users").select("*").ilike("username", clean_username).limit(1).execute()
            if res.data:
                row = res.data[0]
                if verify_password(password, row["password_hash"], row["salt"]):
                    return {
                        "id": row["id"],
                        "username": row["username"],
                        "created_at": row.get("created_at")
                    }
            return None
        except Exception as e:
            print(f"⚠️ Supabase authentication error: {e}. Falling back to SQLite.")

    # 2. SQLite Fallback
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, username, password_hash, salt, created_at FROM users WHERE username = ?",
            (clean_username,)
        )
        row = cursor.fetchone()
        if not row:
            return None

        if verify_password(password, row["password_hash"], row["salt"]):
            return {
                "id": row["id"],
                "username": row["username"],
                "created_at": row["created_at"]
            }
        return None
    finally:
        conn.close()


def get_user_by_id(user_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieve user record by user ID."""
    # 1. Try Supabase
    supabase = get_supabase_client()
    if supabase and not db_path:
        try:
            res = supabase.table("users").select("id, username, created_at").eq("id", user_id).limit(1).execute()
            if res.data:
                return res.data[0]
            return None
        except Exception as e:
            print(f"⚠️ Supabase error getting user: {e}. Falling back to SQLite.")

    # 2. SQLite Fallback
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, created_at FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        if row:
            return {"id": row["id"], "username": row["username"], "created_at": row["created_at"]}
        return None
    finally:
        conn.close()


def get_user_board(user_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieve saved board for user."""
    # 1. Try Supabase
    supabase = get_supabase_client()
    if supabase and not db_path:
        try:
            res = supabase.table("user_boards").select("board_data").eq("user_id", user_id).limit(1).execute()
            if res.data:
                board = res.data[0]["board_data"]
                if isinstance(board, str):
                    return json.loads(board)
                return board
            return None
        except Exception as e:
            print(f"⚠️ Supabase error getting board: {e}. Falling back to SQLite.")

    # 2. SQLite Fallback
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT board_data FROM user_boards WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if row and row["board_data"]:
            return json.loads(row["board_data"])
        return None
    finally:
        conn.close()


def save_user_board(user_id: str, board_data: Dict[str, Any], db_path: Optional[str] = None) -> bool:
    """Save or update user's board state."""
    now = datetime.now(timezone.utc).isoformat()

    # 1. Try Supabase
    supabase = get_supabase_client()
    if supabase and not db_path:
        try:
            row = {
                "user_id": user_id,
                "board_data": board_data,
                "updated_at": now
            }
            supabase.table("user_boards").upsert(row).execute()
            return True
        except Exception as e:
            print(f"⚠️ Supabase error saving board: {e}. Falling back to SQLite.")

    # 2. SQLite Fallback
    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.execute("""
                INSERT INTO user_boards (user_id, board_data, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    board_data = excluded.board_data,
                    updated_at = excluded.updated_at
            """, (user_id, json.dumps(board_data), now))
        return True
    except Exception:
        return False
    finally:
        conn.close()
