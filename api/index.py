"""
api/index.py - FastAPI Serverless Backend for Vercel
Serves API endpoints for AI voice command parsing, Kanban state mutations,
and JWT user authentication with board state persistence.
"""

from typing import Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Security, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

import sys
import os

# Ensure root workspace directory is in sys.path so modules like ai_service, kanban_actions & auth resolve
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_service import parse_voice_command
from kanban_actions import action_dispatcher, PRESET_BOARDS
from auth import (
    create_user,
    authenticate_user,
    create_access_token,
    decode_access_token,
    get_user_by_id,
    get_user_board,
    save_user_board,
)

app = FastAPI(title="AI Voice-Controlled Kanban API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBearer(auto_error=False)


def get_current_user_optional(credentials: Optional[HTTPAuthorizationCredentials] = Security(security)) -> Optional[Dict[str, Any]]:
    """Return authenticated user dict if valid Bearer token provided, else None."""
    if not credentials or not credentials.credentials:
        return None
    payload = decode_access_token(credentials.credentials)
    if not payload or "sub" not in payload:
        return None
    return get_user_by_id(payload["sub"])


def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Security(security)) -> Dict[str, Any]:
    """Require valid Bearer token or raise 401 Unauthorized."""
    user = get_current_user_optional(credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required or token expired.")
    return user


# ─── Pydantic Models ─────────────────────────────────────────────────────────

class CommandRequest(BaseModel):
    transcript: str
    board_state: Dict[str, Any]
    provider: Optional[str] = "auto"


class CommandResponse(BaseModel):
    board_state: Dict[str, Any]
    action: Dict[str, Any]
    status: str
    engine: str


class RegisterRequest(BaseModel):
    username: str
    password: str
    initial_board: Optional[Dict[str, Any]] = None


class LoginRequest(BaseModel):
    username: str
    password: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: Dict[str, Any]


class BoardSyncRequest(BaseModel):
    board_state: Dict[str, Any]


# ─── General Endpoints ───────────────────────────────────────────────────────

@app.get("/")
@app.get("/api")
@app.get("/api/health")
@app.get("/health")
def health():
    return {"status": "ok", "service": "ai-voice-kanban-api"}


@app.get("/api/presets")
@app.get("/presets")
def get_presets():
    return PRESET_BOARDS


# ─── Authentication Endpoints ────────────────────────────────────────────────

@app.post("/api/auth/register", response_model=AuthResponse)
@app.post("/auth/register", response_model=AuthResponse)
def register(req: RegisterRequest):
    default_board = req.initial_board or PRESET_BOARDS.get("🚀 Product Launch")
    user, error = create_user(req.username, req.password, initial_board=default_board)
    if error:
        raise HTTPException(status_code=400, detail=error)

    token = create_access_token(user["id"], user["username"])
    return AuthResponse(access_token=token, user=user)


@app.post("/api/auth/login", response_model=AuthResponse)
@app.post("/auth/login", response_model=AuthResponse)
def login(req: LoginRequest):
    user = authenticate_user(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    token = create_access_token(user["id"], user["username"])
    return AuthResponse(access_token=token, user=user)


@app.get("/api/auth/me")
@app.get("/auth/me")
def me(user: Dict[str, Any] = Depends(get_current_user)):
    return {"user": user}


# ─── User Board Persistence Endpoints ────────────────────────────────────────

@app.get("/api/user/board")
@app.get("/user/board")
def get_board(user: Dict[str, Any] = Depends(get_current_user)):
    saved = get_user_board(user["id"])
    if not saved:
        saved = PRESET_BOARDS.get("🚀 Product Launch")
    return {"board_state": saved}


@app.post("/api/user/board")
@app.post("/user/board")
def save_board(req: BoardSyncRequest, user: Dict[str, Any] = Depends(get_current_user)):
    success = save_user_board(user["id"], req.board_state)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to persist board state.")
    return {"status": "saved", "user_id": user["id"]}


# ─── Voice & Action Command Endpoint ─────────────────────────────────────────

@app.post("/api/command", response_model=CommandResponse)
@app.post("/command", response_model=CommandResponse)
def handle_command(req: CommandRequest, user: Optional[Dict[str, Any]] = Depends(get_current_user_optional)):
    if not req.transcript or not req.transcript.strip():
        raise HTTPException(status_code=400, detail="Transcript cannot be empty.")

    pref = "auto"
    p = (req.provider or "").lower()
    if "openai" in p:
        pref = "openai"
    elif "gemini" in p:
        pref = "gemini"
    elif "local" in p:
        pref = "local"

    action, engine_name = parse_voice_command(req.transcript, req.board_state, preferred_provider=pref)
    new_state, status_msg = action_dispatcher(action, req.board_state)

    # Auto-save board if user is authenticated
    if user:
        save_user_board(user["id"], new_state)

    user_indicator = f" (User: {user['username']})" if user else ""
    audit_status = f'🎙️ Heard: "{req.transcript}"\n🤖 Processed via: {engine_name}{user_indicator}\n{status_msg}'

    return CommandResponse(
        board_state=new_state,
        action=action,
        status=audit_status,
        engine=engine_name,
    )
