"""
AI Service for AI Voice-Controlled Kanban App
Supports both OpenAI (gpt-4o) and Google Gemini (gemini-2.5-flash / gemini-2.0-flash / gemini-1.5-flash),
with an intelligent rule-based fallback when no API key is provided.
"""

import json
import os
import re
from typing import Optional, Dict, Any, Tuple
from dotenv import load_dotenv

load_dotenv()

# System prompt builder
def build_prompt_context(board_state: dict) -> Tuple[str, str]:
    columns = board_state.get("columns", [])
    column_names = [f'{col["title"]} (id="{col["id"]}")' for col in columns]
    
    card_list = []
    for col in columns:
        for card in col.get("cards", []):
            card_list.append(f'"{card["text"]}" (in {col["title"]}, id="{col["id"]}")')
    cards_text = "\n".join(card_list) if card_list else "No cards yet."
    
    return "\n".join(column_names), cards_text


def get_system_prompt(columns_desc: str, cards_desc: str) -> str:
    return f"""You control an interactive Kanban board application.
The board has these columns:
{columns_desc}

Current cards on the board:
{cards_desc}

The user will give you a voice or text command. Return ONLY valid JSON matching one of the schemas below. Do not include markdown formatting or extra text.

Schemas:
1. Add a card:
{{"action": "add", "text": "<card title>", "column": "<column id>", "priority": "low|medium|high"}}

2. Move a card:
{{"action": "move", "card": "<card name>", "to": "<column id>"}}

3. Delete a card:
{{"action": "delete", "card": "<card name>"}}

4. Change priority:
{{"action": "priority", "card": "<card name>", "priority": "low|medium|high"}}

5. Command not understood:
{{"action": "unknown", "message": "<explanation>"}}

Rules:
- For "column" and "to" fields, always use the column ID (e.g. "todo", "progress", "review", "done") — not the display title.
- For card names, use the closest matching text from the current cards list.
- Default priority for new cards is "medium" unless specified ("high", "urgent", "p0" -> high; "low", "minor" -> low).
- If the user says "in progress" or "doing", map to the column with "progress" in its ID.
- If the user says "to do" or "backlog", map to the column with "todo" or "backlog" in its ID.
- If the user says "completed" or "finished", map to "done".
"""


def rule_based_fallback_parser(transcript: str, board_state: dict) -> dict:
    """
    Intelligent regex/heuristic parser used when no API keys are provided or when offline.
    """
    t = transcript.strip().lower()
    cols = board_state.get("columns", [])
    col_ids = [c["id"] for c in cols]
    
    # 1. Add card
    # e.g., "add card Buy milk to todo with high priority"
    # e.g., "add deploy to production to done"
    add_match = re.search(r"(?:add|create)(?:\s+a)?(?:\s+card)?(?:\s+called)?\s+[\"']?(.*?)[\"']?\s+to\s+([a-zA-Z0-9_\-\s]+)", t)
    if add_match:
        text = add_match.group(1).strip()
        col_part = add_match.group(2).strip()
        
        # Priority detection
        priority = "medium"
        if "high" in t or "urgent" in t:
            priority = "high"
        elif "low" in t:
            priority = "low"
            
        # Clean priority words from col_part or text
        col_part = re.sub(r"\s+with\s+(high|medium|low)\s+priority.*", "", col_part).strip()
        text = re.sub(r"\s+with\s+(high|medium|low)\s+priority.*", "", text).strip()
        
        # Resolve target column
        matched_col = None
        for cid in col_ids:
            if cid in col_part or col_part in cid:
                matched_col = cid
                break
        if not matched_col:
            if "progress" in col_part or "doing" in col_part:
                matched_col = next((c["id"] for c in cols if "progress" in c["id"]), "progress")
            elif "done" in col_part or "finish" in col_part or "complete" in col_part:
                matched_col = next((c["id"] for c in cols if "done" in c["id"]), "done")
            elif "review" in col_part:
                matched_col = next((c["id"] for c in cols if "review" in c["id"]), "review")
            else:
                matched_col = col_ids[0] if col_ids else "todo"

        return {"action": "add", "text": text, "column": matched_col, "priority": priority}

    # 2. Move card
    # e.g., "move Fix login bug to done"
    move_match = re.search(r"(?:move|shift|transfer)\s+[\"']?(.*?)[\"']?\s+to\s+([a-zA-Z0-9_\-\s]+)", t)
    if move_match:
        card = move_match.group(1).strip()
        col_part = move_match.group(2).strip()
        matched_col = None
        for cid in col_ids:
            if cid in col_part or col_part in cid:
                matched_col = cid
                break
        if not matched_col:
            if "progress" in col_part or "doing" in col_part:
                matched_col = next((c["id"] for c in cols if "progress" in c["id"]), "progress")
            elif "done" in col_part:
                matched_col = next((c["id"] for c in cols if "done" in c["id"]), "done")
            elif "review" in col_part:
                matched_col = next((c["id"] for c in cols if "review" in c["id"]), "review")
            elif "todo" in col_part:
                matched_col = next((c["id"] for c in cols if "todo" in c["id"]), "todo")
            else:
                matched_col = col_ids[-1] if col_ids else "done"

        return {"action": "move", "card": card, "to": matched_col}

    # 3. Delete card
    # e.g., "delete card Fix login bug"
    delete_match = re.search(r"(?:delete|remove)\s+(?:the\s+)?(?:card\s+)?[\"']?(.*?)[\"']?$", t)
    if delete_match:
        card = delete_match.group(1).strip()
        return {"action": "delete", "card": card}

    # 4. Change priority
    # e.g., "change priority of Fix login bug to high" or "set Fix login bug priority to high"
    prio_match = re.search(r"(?:change|set)\s+(?:priority\s+of\s+)?[\"']?(.*?)[\"']?\s+(?:priority\s+)?to\s+(high|medium|low)", t)
    if prio_match:
        card = prio_match.group(1).replace("priority of", "").strip()
        prio = prio_match.group(2).strip()
        return {"action": "priority", "card": card, "priority": prio}

    return {"action": "unknown", "message": f'Could not interpret command: "{transcript}"'}


_cached_gemini_key: Optional[str] = None
_secret_manager_used = False


def get_gemini_api_key() -> Tuple[Optional[str], bool]:
    """
    Retrieve Gemini API key from:
    1. In-memory cache
    2. Environment variable GEMINI_API_KEY
    3. Google Cloud Secret Manager (project 'fir-p1-8dbb8' or GCP_PROJECT_ID, secret 'gemini-api-key')
    Returns: (key_string, from_secret_manager_flag)
    """
    global _cached_gemini_key, _secret_manager_used
    if _cached_gemini_key:
        return _cached_gemini_key, _secret_manager_used

    # Check env var first (supports both GEMINI_API_KEY and GOOGLE_API_KEY)
    key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
    if key:
        _cached_gemini_key = key
        _secret_manager_used = False
        return key, False

    # Try Google Cloud Secret Manager
    try:
        from google.cloud import secretmanager
        project_id = os.getenv("GCP_PROJECT_ID", "fir-p1-8dbb8")
        secret_name = os.getenv("GEMINI_SECRET_NAME", "gemini-api-key")
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
        response = client.access_secret_version(request={"name": name})
        secret_val = response.payload.data.decode("UTF-8").strip()
        if secret_val:
            _cached_gemini_key = secret_val
            _secret_manager_used = True
            return secret_val, True
    except Exception:
        pass

    return None, False


def parse_voice_command(transcript: str, board_state: dict, preferred_provider: Optional[str] = None) -> Tuple[dict, str]:
    """
    Parse a spoken voice transcript into a structured action dictionary.
    Returns: (action_dict, provider_used)
    """
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    gemini_key, from_sm = get_gemini_api_key()
    
    # Determine provider
    provider = (preferred_provider or os.getenv("DEFAULT_AI_PROVIDER", "auto")).lower()
    
    # 1. Try Google Gemini first if key available or if preferred
    if (provider in ("gemini", "auto") and gemini_key) or (provider == "gemini"):
        try:
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=gemini_key)
            cols_desc, cards_desc = build_prompt_context(board_state)
            sys_prompt = get_system_prompt(cols_desc, cards_desc)
            
            # Support robust model fallback across Gemini API generations
            models_to_try = [
                os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest"),
                "gemini-flash-latest",
                "gemini-pro-latest",
            ]
            response = None
            last_err = None
            model_used = None

            for m in models_to_try:
                try:
                    response = client.models.generate_content(
                        model=m,
                        contents=f"{sys_prompt}\n\nUser command: {transcript}",
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            temperature=0.1
                        )
                    )
                    model_used = m
                    break
                except Exception as ex:
                    last_err = ex
                    continue

            if response is None:
                raise last_err

            raw = response.text.strip()
            source_tag = " [Google Secret Manager]" if from_sm else ""
            return json.loads(raw), f"Google Gemini ({model_used}){source_tag}"
        except Exception as e:
            if not openai_key:
                return rule_based_fallback_parser(transcript, board_state), f"Fallback (Gemini error: {e})"

    # 2. Try OpenAI if configured
    if (provider in ("openai", "auto") and openai_key) or (provider == "openai"):
        try:
            from openai import OpenAI
            client = OpenAI(api_key=openai_key)
            cols_desc, cards_desc = build_prompt_context(board_state)
            sys_prompt = get_system_prompt(cols_desc, cards_desc)
            
            response = client.chat.completions.create(
                model="gpt-4o",
                max_tokens=256,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": transcript},
                ],
            )
            raw = response.choices[0].message.content.strip()
            return json.loads(raw), "OpenAI (gpt-4o)"
        except Exception as e:
            return rule_based_fallback_parser(transcript, board_state), f"Fallback (OpenAI error: {e})"

    # 3. Rule-based offline heuristic fallback
    return rule_based_fallback_parser(transcript, board_state), "Local Rule Engine (No API key set)"

