"""
kanban_actions.py - Pure Python Kanban State & Action Dispatcher
Shared between Gradio UI (kanban_voice.py) and Serverless REST API (api/index.py).
"""

import copy
import re
import uuid
from typing import Tuple, Optional, Dict, Any, List

# ─── Preset Boards ────────────────────────────────────────────────

PRESET_BOARDS: Dict[str, Dict[str, Any]] = {
    "🚀 Product Launch": {
        "columns": [
            {
                "id": "backlog",
                "title": "📦 Backlog",
                "color": "#6366f1",
                "collapsed": False,
                "cards": [
                    {"id": "p1", "text": "Market research & competitor pricing", "priority": "high", "tags": ["research"]},
                    {"id": "p2", "text": "User persona definition & interviews", "priority": "medium", "tags": ["product"]},
                    {"id": "p3", "text": "Brand assets and design system", "priority": "low", "tags": ["design"]},
                ],
            },
            {
                "id": "progress",
                "title": "🔨 In Progress",
                "color": "#f59e0b",
                "collapsed": False,
                "cards": [
                    {"id": "p4", "text": "Build responsive SaaS landing page", "priority": "high", "tags": ["dev", "frontend"]},
                    {"id": "p5", "text": "Draft launch announcement newsletter", "priority": "medium", "tags": ["marketing"]},
                ],
            },
            {
                "id": "review",
                "title": "👀 Review",
                "color": "#8b5cf6",
                "collapsed": False,
                "cards": [
                    {"id": "p6", "text": "Record 2-minute product demo video", "priority": "high", "tags": ["video"]},
                ],
            },
            {
                "id": "done",
                "title": "✅ Done",
                "color": "#10b981",
                "collapsed": False,
                "cards": [
                    {"id": "p7", "text": "Configure automated CI/CD pipelines", "priority": "medium", "tags": ["devops"]},
                    {"id": "p8", "text": "Set up privacy policy and terms", "priority": "low", "tags": ["legal"]},
                ],
            },
        ],
    },
    "🎓 Study Plan": {
        "columns": [
            {
                "id": "topics",
                "title": "📚 Topics",
                "color": "#6366f1",
                "collapsed": False,
                "cards": [
                    {"id": "s1", "text": "Transformer architecture & self-attention", "priority": "high", "tags": ["nlp", "deep-learning"]},
                    {"id": "s2", "text": "Vector databases & HNSW indexing", "priority": "high", "tags": ["rag", "database"]},
                    {"id": "s3", "text": "Diffusion models theoretical formulation", "priority": "medium", "tags": ["genai"]},
                ],
            },
            {
                "id": "studying",
                "title": "📖 Studying",
                "color": "#f59e0b",
                "collapsed": False,
                "cards": [
                    {"id": "s4", "text": "Agent tool calling and MCP protocol", "priority": "high", "tags": ["agents"]},
                ],
            },
            {
                "id": "practice",
                "title": "🧪 Practice",
                "color": "#8b5cf6",
                "collapsed": False,
                "cards": [
                    {"id": "s5", "text": "Implement mini GPT from scratch", "priority": "high", "tags": ["coding"]},
                ],
            },
            {
                "id": "mastered",
                "title": "🏆 Mastered",
                "color": "#10b981",
                "collapsed": False,
                "cards": [
                    {"id": "s6", "text": "Python asynchronous concurrency (asyncio)", "priority": "medium", "tags": ["python"]},
                    {"id": "s7", "text": "REST API development with FastAPI", "priority": "low", "tags": ["backend"]},
                ],
            },
        ],
    },
    "🐛 Bug Tracker": {
        "columns": [
            {
                "id": "reported",
                "title": "🐛 Reported",
                "color": "#ef4444",
                "collapsed": False,
                "cards": [
                    {"id": "b1", "text": "Safari audio permission grant crash", "priority": "high", "tags": ["safari", "p0"]},
                    {"id": "b2", "text": "API rate limit exponential backoff error", "priority": "high", "tags": ["api", "p1"]},
                    {"id": "b3", "text": "Dark mode contrast on disabled buttons", "priority": "low", "tags": ["ui"]},
                ],
            },
            {
                "id": "investigating",
                "title": "🔬 Investigating",
                "color": "#f59e0b",
                "collapsed": False,
                "cards": [
                    {"id": "b4", "text": "Memory leak on continuous speech recognition", "priority": "high", "tags": ["perf"]},
                ],
            },
            {
                "id": "fixing",
                "title": "🔧 Fixing",
                "color": "#6366f1",
                "collapsed": False,
                "cards": [
                    {"id": "b5", "text": "JSON schema validation error handler", "priority": "medium", "tags": ["backend"]},
                ],
            },
            {
                "id": "done",
                "title": "✅ Resolved",
                "color": "#10b981",
                "collapsed": False,
                "cards": [
                    {"id": "b6", "text": "Double execute click debounce", "priority": "medium", "tags": ["js"]},
                ],
            },
        ],
    },
    "🏠 Empty Board": {
        "columns": [
            {"id": "todo", "title": "📋 To Do", "color": "#6366f1", "collapsed": False, "cards": []},
            {"id": "progress", "title": "🔨 In Progress", "color": "#f59e0b", "collapsed": False, "cards": []},
            {"id": "review", "title": "👀 Review", "color": "#8b5cf6", "collapsed": False, "cards": []},
            {"id": "done", "title": "✅ Done", "color": "#10b981", "collapsed": False, "cards": []},
        ],
    },
}

# ─── Fuzzy Entity Matching & Action Dispatcher ─────────────────────

def _find_card(cols: list, fuzzy_name: str) -> Tuple[Optional[dict], Optional[dict]]:
    """
    Find a card by fuzzy text matching across all columns.
    Uses exact match > word overlap > substring scoring.
    Returns: (card_dict, column_dict) or (None, None)
    """
    fuzzy = fuzzy_name.lower().strip()
    if not fuzzy:
        return None, None

    best_card = None
    best_col = None
    best_score = 0

    for col in cols:
        for card in col.get("cards", []):
            card_text = card.get("text", "").lower().strip()
            
            # Exact match
            if card_text == fuzzy:
                return card, col
                
            # Substring matches
            if fuzzy in card_text or card_text in fuzzy:
                score = 100 + len(fuzzy)
                if score > best_score:
                    best_score = score
                    best_card = card
                    best_col = col

            # Token intersection score
            fuzzy_tokens = set(re.findall(r"\w+", fuzzy))
            card_tokens = set(re.findall(r"\w+", card_text))
            overlap = len(fuzzy_tokens & card_tokens)
            if overlap > 0 and overlap > best_score:
                best_score = overlap
                best_card = card
                best_col = col

    return best_card, best_col


def action_dispatcher(action: dict, board_state: dict) -> Tuple[dict, str]:
    """
    Execute structured LLM action on board state.
    Returns: (new_state, status_message)
    """
    state = copy.deepcopy(board_state)
    cols = state.get("columns", [])
    act = action.get("action")

    # 1. ADD
    if act == "add":
        target_col_id = action.get("column", "")
        # Fuzzy match column ID or title
        target_col = next((c for c in cols if c["id"].lower() == target_col_id.lower()), None)
        if not target_col:
            target_col = next((c for c in cols if target_col_id.lower() in c["title"].lower()), None)
        if not target_col and cols:
            target_col = cols[0]

        if not target_col:
            return state, f"⚠️ Column '{target_col_id}' not found."

        new_card = {
            "id": str(uuid.uuid4())[:8],
            "text": action.get("text", "New Task"),
            "priority": action.get("priority", "medium").lower(),
            "tags": action.get("tags", []),
        }
        target_col.setdefault("cards", []).append(new_card)
        return state, f'✅ Added "{new_card["text"]}" to {target_col["title"]} with {new_card["priority"]} priority.'

    # 2. MOVE
    elif act == "move":
        card, src_col = _find_card(cols, action.get("card", ""))
        if not card:
            return state, f'⚠️ Could not find card matching "{action.get("card")}".'

        dest_col_id = action.get("to", "")
        dest_col = next((c for c in cols if c["id"].lower() == dest_col_id.lower()), None)
        if not dest_col:
            dest_col = next((c for c in cols if dest_col_id.lower() in c["title"].lower()), None)
        if not dest_col:
            return state, f"⚠️ Could not find destination column '{dest_col_id}'."

        src_col["cards"].remove(card)
        dest_col.setdefault("cards", []).append(card)
        return state, f'📦 Moved "{card["text"]}" from {src_col["title"]} → {dest_col["title"]}.'

    # 3. DELETE
    elif act == "delete":
        card, src_col = _find_card(cols, action.get("card", ""))
        if not card:
            return state, f'⚠️ Could not find card matching "{action.get("card")}".'
        src_col["cards"].remove(card)
        return state, f'🗑️ Deleted "{card["text"]}" from {src_col["title"]}.'

    # 4. PRIORITY
    elif act == "priority":
        card, _ = _find_card(cols, action.get("card", ""))
        if not card:
            return state, f'⚠️ Could not find card matching "{action.get("card")}".'
        old_prio = card.get("priority", "medium")
        new_prio = action.get("priority", "medium").lower()
        card["priority"] = new_prio
        return state, f'⚡ Changed priority of "{card["text"]}" from {old_prio} → {new_prio}.'

    # 5. UNKNOWN
    elif act == "unknown":
        return state, f'❓ Command not understood: {action.get("message", "Please try rephrasing.")}'

    return state, f"⚠️ Unknown action '{act}'."
