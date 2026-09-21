"""
auth.py - Authentication and User Board State Management
Provides secure salted PBKDF2 password hashing, JWT token lifecycle,
and user board persistence with SQLite.
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

# Determine database path (use /tmp on Vercel serverless environment)
if os.environ.get("VERCEL"):
    DEFAULT_DB_PATH = "/tmp/kanban_users.db"
else:
    DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kanban_users.db")

JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "kanban-secret-key-change-in-production-ai-voice")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_DAYS = int(os.environ.get("JWT_EXPIRE_DAYS", "7"))
HASH_ITERATIONS = 100_000


def get_db_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = db_path or os.environ.get("DB_PATH") or DEFAULT_DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Optional[str] = None) -> None:
    """Initialize database tables for users and user boards."""
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


# Ensure DB tables exist upon module import
init_db()


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


def create_user(
    username: str,
    password: str,
    initial_board: Optional[Dict[str, Any]] = None,
    db_path: Optional[str] = None
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Register a new user and initialize an optional default board.
    Returns (user_dict, None) on success, or (None, error_message) on failure.
    """
    clean_username = username.strip()
    if not clean_username or len(clean_username) < 3:
        return None, "Username must be at least 3 characters long."
    if not password or len(password) < 4:
        return None, "Password must be at least 4 characters long."

    pwd_hash, salt = hash_password(password)
    user_id = str(secrets.token_hex(12))
    created_at = datetime.now(timezone.utc).isoformat()

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
    """Retrieve saved board for user. Returns dict or None."""
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
    conn = get_db_connection(db_path)
    now = datetime.now(timezone.utc).isoformat()
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
