"""
Unit tests for AI Voice-Controlled Kanban App
Tests intent parsing, fuzzy matching, and action dispatching.
"""

import unittest
from ai_service import rule_based_fallback_parser, build_prompt_context
from kanban_actions import _find_card, action_dispatcher, PRESET_BOARDS


class TestKanbanApp(unittest.TestCase):

    def setUp(self):
        self.board = {
            "columns": [
                {
                    "id": "todo",
                    "title": "📋 To Do",
                    "color": "#6366f1",
                    "cards": [
                        {"id": "1", "text": "Research gr.HTML component", "priority": "high", "tags": ["ui"]},
                        {"id": "2", "text": "Fix login authentication bug", "priority": "medium", "tags": ["auth"]},
                    ],
                },
                {
                    "id": "progress",
                    "title": "🔨 In Progress",
                    "color": "#f59e0b",
                    "cards": [
                        {"id": "3", "text": "Build Kanban prototype", "priority": "high", "tags": ["dev"]},
                    ],
                },
                {
                    "id": "done",
                    "title": "✅ Done",
                    "color": "#10b981",
                    "cards": [],
                },
            ]
        }

    def test_fuzzy_matching_exact(self):
        card, col = _find_card(self.board["columns"], "Build Kanban prototype")
        self.assertIsNotNone(card)
        self.assertEqual(card["id"], "3")
        self.assertEqual(col["id"], "progress")

    def test_fuzzy_matching_partial(self):
        # User says "login bug"
        card, col = _find_card(self.board["columns"], "login bug")
        self.assertIsNotNone(card)
        self.assertEqual(card["id"], "2")
        self.assertEqual(col["id"], "todo")

    def test_fuzzy_matching_research(self):
        # User says "the research component thing"
        card, col = _find_card(self.board["columns"], "research component")
        self.assertIsNotNone(card)
        self.assertEqual(card["id"], "1")

    def test_action_add(self):
        action = {
            "action": "add",
            "text": "Write API documentation",
            "column": "todo",
            "priority": "low"
        }
        new_state, msg = action_dispatcher(action, self.board)
        todo_cards = new_state["columns"][0]["cards"]
        self.assertEqual(len(todo_cards), 3)
        self.assertEqual(todo_cards[-1]["text"], "Write API documentation")
        self.assertEqual(todo_cards[-1]["priority"], "low")
        self.assertIn("Added", msg)

    def test_action_move(self):
        action = {
            "action": "move",
            "card": "login bug",
            "to": "done"
        }
        new_state, msg = action_dispatcher(action, self.board)
        todo_cards = new_state["columns"][0]["cards"]
        done_cards = new_state["columns"][2]["cards"]
        self.assertEqual(len(todo_cards), 1)
        self.assertEqual(len(done_cards), 1)
        self.assertEqual(done_cards[0]["text"], "Fix login authentication bug")
        self.assertIn("Moved", msg)

    def test_action_delete(self):
        action = {
            "action": "delete",
            "card": "research"
        }
        new_state, msg = action_dispatcher(action, self.board)
        todo_cards = new_state["columns"][0]["cards"]
        self.assertEqual(len(todo_cards), 1)
        self.assertEqual(todo_cards[0]["id"], "2")
        self.assertIn("Deleted", msg)

    def test_action_priority(self):
        action = {
            "action": "priority",
            "card": "prototype",
            "priority": "low"
        }
        new_state, msg = action_dispatcher(action, self.board)
        prog_card = new_state["columns"][1]["cards"][0]
        self.assertEqual(prog_card["priority"], "low")
        self.assertIn("Changed priority", msg)

    def test_rule_based_fallback_parser(self):
        # Add command
        res = rule_based_fallback_parser("add a card called Ship Feature to progress with high priority", self.board)
        self.assertEqual(res["action"], "add")
        self.assertEqual(res["priority"], "high")
        self.assertEqual(res["column"], "progress")

        # Move command
        res = rule_based_fallback_parser("move login bug to done", self.board)
        self.assertEqual(res["action"], "move")
        self.assertEqual(res["to"], "done")

        # Delete command
        res = rule_based_fallback_parser("delete card Build Kanban prototype", self.board)
        self.assertEqual(res["action"], "delete")
        self.assertIn("kanban prototype", res["card"].lower())

        # Priority command
        res = rule_based_fallback_parser("set login bug priority to high", self.board)
        self.assertEqual(res["action"], "priority")
        self.assertEqual(res["priority"], "high")

    def test_prompt_builder(self):
        cols, cards = build_prompt_context(self.board)
        self.assertIn("To Do", cols)
        self.assertIn("Fix login authentication bug", cards)


if __name__ == "__main__":
    unittest.main()
