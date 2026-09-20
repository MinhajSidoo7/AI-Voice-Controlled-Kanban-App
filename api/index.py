"""
api/index.py - FastAPI Serverless Backend for Vercel
Serves API endpoints for AI voice command parsing and Kanban state mutations.
"""

from typing import Optional, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import sys
import os
# Ensure root workspace directory is in sys.path so modules like ai_service & kanban_actions resolve
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_service import parse_voice_command
from kanban_actions import action_dispatcher, PRESET_BOARDS

app = FastAPI(title="AI Voice-Controlled Kanban API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CommandRequest(BaseModel):
    transcript: str
    board_state: Dict[str, Any]
    provider: Optional[str] = "auto"


class CommandResponse(BaseModel):
    board_state: Dict[str, Any]
    action: Dict[str, Any]
    status: str
    engine: str


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


@app.post("/api/command", response_model=CommandResponse)
@app.post("/command", response_model=CommandResponse)
def handle_command(req: CommandRequest):
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

    audit_status = f'🎙️ Heard: "{req.transcript}"\n🤖 Processed via: {engine_name}\n{status_msg}'

    return CommandResponse(
        board_state=new_state,
        action=action,
        status=audit_status,
        engine=engine_name,
    )
