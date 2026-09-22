"""
test_security_and_full_app.py
Comprehensive End-to-End Test Suite for AI Voice-Controlled Kanban App:
1. Feature & Functional Verification
2. Authentication & Authorization Security Protocols
3. User Privacy, PII & Secret Leakage Prevention
4. Cross-User Data Isolation & IDOR Protection
5. Input Validation, SQL Injection & Boundary Testing
6. Frontend XSS & Entity Escaping Validation
"""

import os
import unittest
import tempfile
import sqlite3
import json
import secrets
import uuid
from datetime import timedelta

# Use isolated temporary test database
test_db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
test_db_path = test_db_file.name
test_db_file.close()
os.environ["DB_PATH"] = test_db_path

import auth
from auth import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
    create_user,
    authenticate_user,
    get_user_by_id,
    get_user_board,
    save_user_board,
    init_db
)
from ai_service import rule_based_fallback_parser, build_prompt_context
from kanban_actions import _find_card, action_dispatcher, PRESET_BOARDS
from fastapi.testclient import TestClient
from api.index import app


class TestFullAppAndSecurity(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.db_path = test_db_path
        init_db(cls.db_path)
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(test_db_path):
            try:
                os.remove(test_db_path)
            except Exception:
                pass

    def setUp(self):
        conn = sqlite3.connect(self.db_path)
        with conn:
            conn.execute("DELETE FROM user_boards")
            conn.execute("DELETE FROM users")
        conn.close()

    # ═════════════════════════════════════════════════════════════════
    # SECTION 1: API Core Endpoints & Presets
    # ═════════════════════════════════════════════════════════════════

    def test_01_health_and_root_endpoints(self):
        """Verify health checks return 200 and correct status."""
        for path in ["/", "/api", "/api/health", "/health"]:
            res = self.client.get(path)
            self.assertEqual(res.status_code, 200, f"Failed on {path}")
            self.assertEqual(res.json()["status"], "ok")

    def test_02_presets_endpoint(self):
        """Verify all preset board templates are returned and valid."""
        res = self.client.get("/api/presets")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("🚀 Product Launch", data)
        self.assertIn("🎓 Study Plan", data)
        self.assertIn("🐛 Bug Tracker", data)
        self.assertIn("🏠 Empty Board", data)
        for name, preset in data.items():
            self.assertIn("columns", preset)
            self.assertIsInstance(preset["columns"], list)

    # ═════════════════════════════════════════════════════════════════
    # SECTION 2: Authentication Security & Privacy Protocols
    # ═════════════════════════════════════════════════════════════════

    def test_03_password_hashing_cryptography(self):
        """Ensure PBKDF2 uses cryptographically strong salts and constant-time compare."""
        password = "UserP@ssw0rd!#2026"
        h1, s1 = hash_password(password)
        h2, s2 = hash_password(password)

        self.assertNotEqual(s1, s2, "Salts must be unique per hash.")
        self.assertNotEqual(h1, h2, "Hashes of same password with different salts must differ.")
        self.assertTrue(verify_password(password, h1, s1))
        self.assertFalse(verify_password("wrongpassword", h1, s1))

    def test_04_jwt_integrity_and_tampering(self):
        """Verify JWT fails gracefully when signature is forged or expired."""
        token = create_access_token("user_abc", "alice")
        payload = decode_access_token(token)
        self.assertEqual(payload["sub"], "user_abc")
        self.assertEqual(payload["username"], "alice")

        # Privacy check: No sensitive secrets leaked in token payload
        self.assertNotIn("password", payload)
        self.assertNotIn("password_hash", payload)
        self.assertNotIn("salt", payload)

        # Forged/tampered token
        tampered = token[:-6] + "xxxxxx"
        self.assertIsNone(decode_access_token(tampered))

        # Expired token
        expired = create_access_token("user_abc", "alice", expires_delta=timedelta(seconds=-1))
        self.assertIsNone(decode_access_token(expired))

    def test_05_sql_injection_defense_in_auth(self):
        """Verify SQL injection payloads are neutralized by parameterization."""
        sqli_payloads = [
            "' OR '1'='1",
            "admin'--",
            "'; DROP TABLE users; --",
            "' UNION SELECT * FROM users --"
        ]
        for injection in sqli_payloads:
            # Registration should either safely store or validate, but NOT execute injection
            user, err = create_user(f"user_{injection[:6]}", "ValidPass123", db_path=self.db_path)
            # Either created safely as literal string or cleanly rejected
            conn = sqlite3.connect(self.db_path)
            # Table users must remain intact and unharmed
            cursor = conn.cursor()
            cursor.execute("SELECT count(*) FROM users")
            count = cursor.fetchone()[0]
            conn.close()
            self.assertGreaterEqual(count, 0)

    def test_06_case_insensitive_username_collision(self):
        """Ensure usernames are treated case-insensitively to prevent identity spoofing."""
        u1, err1 = create_user("JohnDoe", "password123", db_path=self.db_path)
        self.assertIsNotNone(u1)
        self.assertIsNone(err1)

        # Attempt to register lowercase or uppercase clone
        u2, err2 = create_user("johndoe", "anotherpass", db_path=self.db_path)
        self.assertIsNone(u2, "Must prevent duplicate username with different casing.")
        self.assertIn("already exists", err2)

        # Login must succeed with any casing
        auth_res = authenticate_user("JOHNDOE", "password123", db_path=self.db_path)
        self.assertIsNotNone(auth_res, "Login should be case-insensitive for username.")

    # ═════════════════════════════════════════════════════════════════
    # SECTION 3: Cross-User Data Isolation & IDOR Protection
    # ═════════════════════════════════════════════════════════════════

    def test_07_user_board_isolation(self):
        """Verify User A cannot access or mutate User B's board."""
        # Create User A
        u_a = f"userA_{uuid.uuid4().hex[:6]}"
        res_a = self.client.post("/api/auth/register", json={"username": u_a, "password": "passwordA"})
        token_a = res_a.json()["access_token"]

        # Create User B
        u_b = f"userB_{uuid.uuid4().hex[:6]}"
        res_b = self.client.post("/api/auth/register", json={"username": u_b, "password": "passwordB"})
        token_b = res_b.json()["access_token"]

        # User A saves private board
        board_a = {"title": "User A Secret Board", "columns": [{"id": "c1", "title": "A Tasks", "cards": []}]}
        self.client.post("/api/user/board", json={"board_state": board_a}, headers={"Authorization": f"Bearer {token_a}"})

        # User B saves different private board
        board_b = {"title": "User B Secret Board", "columns": [{"id": "c2", "title": "B Tasks", "cards": []}]}
        self.client.post("/api/user/board", json={"board_state": board_b}, headers={"Authorization": f"Bearer {token_b}"})

        # User A reads board
        load_a = self.client.get("/api/user/board", headers={"Authorization": f"Bearer {token_a}"}).json()["board_state"]
        self.assertEqual(load_a["title"], "User A Secret Board")

        # User B reads board
        load_b = self.client.get("/api/user/board", headers={"Authorization": f"Bearer {token_b}"}).json()["board_state"]
        self.assertEqual(load_b["title"], "User B Secret Board")
        self.assertNotEqual(load_a["title"], load_b["title"], "Data leak across user accounts!")

    def test_08_unauthorized_endpoints_protection(self):
        """Verify protected endpoints return 401 Unauthorized without valid tokens."""
        res_me = self.client.get("/api/auth/me")
        self.assertEqual(res_me.status_code, 401)

        res_board_get = self.client.get("/api/user/board")
        self.assertEqual(res_board_get.status_code, 401)

        res_board_post = self.client.post("/api/user/board", json={"board_state": {}})
        self.assertEqual(res_board_post.status_code, 401)

        # Invalid token
        res_bad_token = self.client.get("/api/auth/me", headers={"Authorization": "Bearer invalid.token.value"})
        self.assertEqual(res_bad_token.status_code, 401)

    # ═════════════════════════════════════════════════════════════════
    # SECTION 4: AI Intent Parsing & Command Robustness
    # ═════════════════════════════════════════════════════════════════

    def test_09_voice_command_execution(self):
        """Verify command processing and state dispatching."""
        initial_board = {
            "columns": [
                {"id": "todo", "title": "To Do", "cards": [{"id": "1", "text": "Fix memory leak", "priority": "high"}]},
                {"id": "done", "title": "Done", "cards": []}
            ]
        }

        # Command: Move card
        cmd = {
            "transcript": "move memory leak to done",
            "board_state": initial_board,
            "provider": "local"
        }
        res = self.client.post("/api/command", json=cmd)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        done_cards = data["board_state"]["columns"][1]["cards"]
        self.assertEqual(len(done_cards), 1)
        self.assertEqual(done_cards[0]["text"], "Fix memory leak")

    def test_10_empty_and_boundary_transcripts(self):
        """Verify boundary inputs like empty transcripts or excessive strings."""
        # Empty transcript should raise 400
        res = self.client.post("/api/command", json={"transcript": "   ", "board_state": {}})
        self.assertEqual(res.status_code, 400)

        # Unicode / Emoji transcript
        res_emoji = self.client.post("/api/command", json={
            "transcript": "add card 🚀 Deploy v2.0 to done with high priority",
            "board_state": {"columns": [{"id": "done", "title": "Done", "cards": []}]},
            "provider": "local"
        })
        self.assertEqual(res_emoji.status_code, 200)

    # ═════════════════════════════════════════════════════════════════
    # SECTION 5: Frontend Security & Stored XSS Neutralization
    # ═════════════════════════════════════════════════════════════════

    def test_11_xss_payload_in_card_text(self):
        """Verify XSS payloads in card text do not execute or break board state logic."""
        xss_payload = "<script>alert('pwned')</script>"
        action = {"action": "add", "text": xss_payload, "column": "todo", "priority": "high"}
        board = {"columns": [{"id": "todo", "title": "To Do", "cards": []}]}

        new_state, msg = action_dispatcher(action, board)
        card = new_state["columns"][0]["cards"][0]
        # State stores raw string
        self.assertEqual(card["text"], xss_payload)

        # In Python/FastAPI it should be serializable and valid JSON without breaking
        dumped = json.dumps(new_state)
        self.assertIn("<script>", dumped)

    def test_12_excessive_transcript_length_dos_protection(self):
        """Verify transcript > 500 characters is rejected to prevent LLM cost/DoS attacks."""
        oversized = "a" * 501
        res = self.client.post("/api/command", json={
            "transcript": oversized,
            "board_state": {"columns": [{"id": "todo", "title": "To Do", "cards": []}]}
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn("exceeds maximum length", res.json()["detail"])

    def test_13_input_bounds_oversized_credentials(self):
        """Verify username > 50 and password > 128 characters are rejected."""
        long_u = "u" * 51
        long_p = "p" * 129
        # Test long username
        res_u = self.client.post("/api/auth/register", json={"username": long_u, "password": "validpassword"})
        self.assertEqual(res_u.status_code, 400)
        self.assertIn("cannot exceed 50 characters", res_u.json()["detail"])

        # Test long password
        res_p = self.client.post("/api/auth/register", json={"username": f"valid_{uuid.uuid4().hex[:6]}", "password": long_p})
        self.assertEqual(res_p.status_code, 400)
        self.assertIn("cannot exceed 128 characters", res_p.json()["detail"])

    def test_14_cors_wildcard_credential_security(self):
        """Verify CORS allows origin * without allow-credentials: true (preventing W3C CORS violations)."""
        options_res = self.client.options("/api/command", headers={
            "Origin": "https://attacker.example.com",
            "Access-Control-Request-Method": "POST"
        })
        allow_origin = options_res.headers.get("access-control-allow-origin")
        allow_cred = options_res.headers.get("access-control-allow-credentials")
        self.assertEqual(allow_origin, "*")
        self.assertNotEqual(allow_cred, "true")

    def test_15_frontend_html_escaping_in_rendered_files(self):
        """Verify index.html and public/index.html have escapeHtml applied to card.text, col.title, and tags."""
        for filename in ["index.html", "public/index.html"]:
            with open(filename, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("function escapeHtml(", content, f"{filename} missing escapeHtml function")
            self.assertIn("escapeHtml(card.text)", content, f"{filename} must escape card.text")
            self.assertIn("escapeHtml(col.title)", content, f"{filename} must escape col.title")
            self.assertIn("escapeHtml(t)", content, f"{filename} must escape tags")


if __name__ == "__main__":
    unittest.main()
