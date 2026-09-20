"""
Python Client for Kanban Board Live Synchronization
Run this script in a separate terminal while `kanban_board_with_live_sync.py` is running
to watch the board update dynamically in the browser!
"""

import sys
import time
from gradio_client import Client

SERVER_URL = "http://127.0.0.1:7860"

def main():
    print("=" * 60)
    print("🤖 Automated Python Client for Kanban Board Live Sync")
    print(f"Connecting to: {SERVER_URL} ...")
    print("=" * 60)

    try:
        client = Client(SERVER_URL)
        print(" Connected successfully to Kanban Board API!\n")
    except Exception as e:
        print(f"❌ Failed to connect to {SERVER_URL}: {e}")
        print("💡 Ensure `python kanban_board_with_live_sync.py` is running in another terminal first!")
        sys.exit(1)

    # 1. Reset / Clear the board
    print("1. Clearing the board...")
    res = client.predict(api_name="/clear_board")
    print(f"   Result: {res}")
    time.sleep(1.5)

    # 2. Set new Sprint Title
    print("\n2. Setting board title to '⚡ Sprint 42 - Autonomous Agents Demo'...")
    res = client.predict("⚡ Sprint 42 - Autonomous Agents Demo", api_name="/set_title")
    print(f"   Result: {res}")
    time.sleep(1.5)

    # 3. Add initial tasks to To Do
    print("\n3. Adding tasks to 'To Do' column...")
    todo_tasks = [
        ("todo", "Build Web Speech recognition bridge", "high", ["voice", "frontend"]),
        ("todo", "Integrate Google Gemini & OpenAI intent parser", "high", ["ai", "nlp"]),
        ("todo", "Add unit tests for action dispatcher", "medium", ["testing"]),
        ("todo", "Write comprehensive documentation", "low", ["docs"]),
    ]

    for col_id, text, priority, tags in todo_tasks:
        res = client.predict(col_id, text, priority, tags, api_name="/add_card")
        print(f"   ➕ Added: '{text}' ({priority} priority)")
        time.sleep(0.7)

    # 4. Move a task to In Progress
    print("\n4. Moving 'Build Web Speech recognition bridge' to 'In Progress'...")
    time.sleep(1.5)
    res = client.predict("Build Web Speech", "progress", api_name="/move_card")
    print(f"   Result: {res}")

    # 5. Move a task to Done
    print("\n5. Moving 'Integrate Google Gemini & OpenAI intent parser' to 'Done'...")
    time.sleep(1.5)
    res = client.predict("Integrate Google Gemini", "done", api_name="/move_card")
    print(f"   Result: {res}")

    # 6. Add review task
    print("\n6. Adding 'Peer Code Review' to 'Review' column...")
    time.sleep(1.5)
    res = client.predict("review", "Peer Code Review & E2E Verification", "high", ["qa", "review"], api_name="/add_card")
    print(f"   Result: {res}")

    print("\n" + "=" * 60)
    print("✅ All automation actions dispatched!")
    print("👀 Look at your browser at http://127.0.0.1:7860 to see the live synced board.")
    print("=" * 60)


if __name__ == "__main__":
    main()
