"""
Kanban Board with Shared State & Live Synchronization
- Persists board state to `board_state.json`
- Real-time UI refresh via Gradio Timer
- Headless REST / WebSocket endpoints for Python clients, scripts, and AI agents
"""

import json
from pathlib import Path
import gradio as gr

STATE_FILE = Path(__file__).parent / "board_state.json"

DEFAULT_BOARD = {
    "title": "🚀 Live Synchronized Kanban Board",
    "columns": [
        {"id": "todo", "title": "📋 To Do", "color": "#6366f1", "cards": []},
        {"id": "progress", "title": "🔨 In Progress", "color": "#f59e0b", "cards": []},
        {"id": "review", "title": "👀 Review", "color": "#8b5cf6", "cards": []},
        {"id": "done", "title": "✅ Done", "color": "#10b981", "cards": []},
    ]
}


def load_board():
    """Load board state from shared JSON file with fallback to default."""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return save_board(DEFAULT_BOARD.copy())


def save_board(board_data: dict):
    """Save board state atomically to shared JSON file."""
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(board_data, f, indent=2)
    return board_data


def render_board_html(board: dict) -> str:
    """Render the board state into responsive HTML."""
    title = board.get("title", "Live Kanban Board")
    columns = board.get("columns", [])
    
    priority_colors = {
        "high": "#ef4444",
        "medium": "#f59e0b",
        "low": "#10b981"
    }
    
    columns_html = ""
    total_cards = 0
    done_cards = 0

    for col in columns:
        cards = col.get("cards", [])
        total_cards += len(cards)
        if col.get("id") == "done":
            done_cards += len(cards)

        cards_html = ""
        for card in cards:
            priority = card.get("priority", "medium").lower()
            p_color = priority_colors.get(priority, "#f59e0b")
            tags = card.get("tags", [])
            tags_html = " ".join([
                f'<span style="background: rgba(255,255,255,0.08); color: #94a3b8; padding: 2px 6px; border-radius: 4px; font-size: 11px;">{t}</span>'
                for t in tags
            ])
            
            cards_html += f"""
            <div style="background: #0f172a; padding: 12px; border-radius: 8px; margin-bottom: 10px; border-left: 4px solid {p_color}; box-shadow: 0 2px 6px rgba(0,0,0,0.3);">
                <div style="font-size: 14px; color: #f1f5f9; font-weight: 500; margin-bottom: 6px;">{card.get("text", "")}</div>
                <div style="display: flex; gap: 4px; flex-wrap: wrap;">{tags_html}</div>
            </div>
            """

        empty_placeholder = '<div style="color: #64748b; text-align: center; padding: 24px 10px; font-size: 13px; font-style: italic;">No tasks</div>'
        
        columns_html += f"""
        <div style="background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 14px; min-width: 260px; flex: 1; display: flex; flex-direction: column;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; padding-bottom: 8px; border-bottom: 2px solid {col.get('color', '#6366f1')};">
                <span style="font-weight: 600; font-size: 14px; color: #f8fafc;">{col.get("title", "Column")}</span>
                <span style="background: {col.get('color', '#6366f1')}22; color: {col.get('color', '#6366f1')}; font-size: 12px; font-weight: 700; padding: 2px 8px; border-radius: 12px;">{len(cards)}</span>
            </div>
            <div style="flex: 1; min-height: 80px;">
                {cards_html if cards_html else empty_placeholder}
            </div>
        </div>
        """

    pct = round((done_cards / total_cards) * 100) if total_cards > 0 else 0

    return f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #e2e8f0; padding: 16px; background: #0b0f19; border-radius: 14px; border: 1px solid #1e293b;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 8px;">
            <h2 style="margin: 0; font-size: 22px; color: #f8fafc; font-weight: 700;">{title}</h2>
            <div style="display: flex; gap: 8px; font-size: 13px;">
                <span style="background: rgba(255,255,255,0.06); padding: 5px 12px; border-radius: 12px; color: #94a3b8;">📊 {total_cards} Total</span>
                <span style="background: rgba(16,185,129,0.1); padding: 5px 12px; border-radius: 12px; color: #10b981; font-weight: 600;">✅ {done_cards} Done ({pct}%)</span>
            </div>
        </div>

        <div style="height: 4px; background: rgba(255,255,255,0.08); border-radius: 4px; margin-bottom: 18px; overflow: hidden;">
            <div style="height: 100%; width: {pct}%; background: linear-gradient(90deg, #6366f1, #10b981); transition: width 0.3s ease;"></div>
        </div>

        <div style="display: flex; gap: 14px; overflow-x: auto; padding-bottom: 8px;">
            {columns_html}
        </div>

        <div style="margin-top: 14px; font-size: 12px; color: #64748b; text-align: right;">
            ⚡ Auto-sync active (refreshing every 2s) · Shared across all clients & agents
        </div>
    </div>
    """


# ─── Gradio Endpoints for External Python Client / Agents ──────────

def api_get_board():
    """Endpoint: Get raw board dictionary."""
    return load_board()


def api_set_board(board_data: dict):
    """Endpoint: Replace entire board state."""
    save_board(board_data)
    return {"status": "ok", "message": "Board updated successfully"}


def api_clear_board():
    """Endpoint: Clear all cards from the board."""
    board = load_board()
    for col in board.get("columns", []):
        col["cards"] = []
    save_board(board)
    return {"status": "ok", "message": "Board cleared"}


def api_set_title(new_title: str):
    """Endpoint: Update the board title."""
    board = load_board()
    board["title"] = new_title
    save_board(board)
    return {"status": "ok", "title": new_title}


def api_add_card(column_id: str, text: str, priority: str = "medium", tags: list = None):
    """Endpoint: Add a card to a specific column."""
    import uuid
    board = load_board()
    col = next((c for c in board.get("columns", []) if c["id"] == column_id), None)
    if not col:
        return {"status": "error", "message": f"Column '{column_id}' not found"}

    new_card = {
        "id": str(uuid.uuid4())[:8],
        "text": text,
        "priority": priority,
        "tags": tags or [],
    }
    col.setdefault("cards", []).append(new_card)
    save_board(board)
    return {"status": "ok", "card": new_card}


def api_move_card(card_text: str, to_column_id: str):
    """Endpoint: Move a card to target column by matching text."""
    board = load_board()
    cols = board.get("columns", [])
    
    # Locate card
    found_card = None
    found_col = None
    for c in cols:
        for card in c.get("cards", []):
            if card_text.lower() in card.get("text", "").lower():
                found_card = card
                found_col = c
                break
        if found_card:
            break

    if not found_card:
        return {"status": "error", "message": f"Card matching '{card_text}' not found"}

    dest_col = next((c for c in cols if c["id"] == to_column_id), None)
    if not dest_col:
        return {"status": "error", "message": f"Destination column '{to_column_id}' not found"}

    found_col["cards"].remove(found_card)
    dest_col.setdefault("cards", []).append(found_card)
    save_board(board)
    return {"status": "ok", "message": f"Moved '{found_card['text']}' to {to_column_id}"}


def api_delete_card(card_text: str):
    """Endpoint: Delete a card by matching text."""
    board = load_board()
    cols = board.get("columns", [])
    for c in cols:
        for card in c.get("cards", []):
            if card_text.lower() in card.get("text", "").lower():
                c["cards"].remove(card)
                save_board(board)
                return {"status": "ok", "message": f"Deleted '{card['text']}'"}
    return {"status": "error", "message": f"Card matching '{card_text}' not found"}


# ─── Refresh Loop & App UI ─────────────────────────────────────────

def get_current_html():
    """Called on initial load and timer tick."""
    return render_board_html(load_board())


def get_current_status():
    board = load_board()
    total = sum(len(c.get("cards", [])) for c in board.get("columns", []))
    return f"Live Sync Active · {total} tasks on board"


def create_sync_app():
    with gr.Blocks(title="Kanban Board - Live Sync") as demo:
        gr.Markdown(
            """
            # 🔄 Kanban Board — Live Shared State
            This board automatically polls `board_state.json` every 2 seconds.
            External Python scripts and AI agents can manipulate the board in real time via the Gradio API!
            """
        )

        board_html = gr.HTML(value=get_current_html)
        status_bar = gr.Textbox(value=get_current_status, interactive=False, label="Sync Status")

        # Auto-refresh timer every 2 seconds
        timer = gr.Timer(2.0)
        timer.tick(fn=get_current_html, outputs=board_html)
        timer.tick(fn=get_current_status, outputs=status_bar)

        # Hidden API inputs and endpoints for Python clients and external agents
        with gr.Group(visible=False):
            in_board_data = gr.JSON()
            in_col_id = gr.Textbox()
            in_card_text = gr.Textbox()
            in_priority = gr.Textbox(value="medium")
            in_tags = gr.JSON(value=[])
            in_dest_col = gr.Textbox()
            in_title = gr.Textbox()
            out_result = gr.JSON()

            set_board_btn = gr.Button("API Set Board")
            set_board_btn.click(fn=api_set_board, inputs=[in_board_data], outputs=out_result, api_name="set_board")

            add_card_btn = gr.Button("API Add Card")
            add_card_btn.click(fn=api_add_card, inputs=[in_col_id, in_card_text, in_priority, in_tags], outputs=out_result, api_name="add_card")

            move_card_btn = gr.Button("API Move Card")
            move_card_btn.click(fn=api_move_card, inputs=[in_card_text, in_dest_col], outputs=out_result, api_name="move_card")

            del_card_btn = gr.Button("API Delete Card")
            del_card_btn.click(fn=api_delete_card, inputs=[in_card_text], outputs=out_result, api_name="delete_card")

            clear_btn = gr.Button("API Clear Board")
            clear_btn.click(fn=api_clear_board, inputs=None, outputs=out_result, api_name="clear_board")

            title_btn = gr.Button("API Set Title")
            title_btn.click(fn=api_set_title, inputs=[in_title], outputs=out_result, api_name="set_title")

            get_board_btn = gr.Button("API Get Board")
            get_board_btn.click(fn=api_get_board, inputs=None, outputs=out_result, api_name="get_board")

    return demo


if __name__ == "__main__":
    app = create_sync_app()
    app.launch(server_port=7860)
