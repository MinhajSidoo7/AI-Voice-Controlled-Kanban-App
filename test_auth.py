"""
test_auth.py - Comprehensive Unit & Integration Tests for Kanban Authentication
Tests password hashing, JWT lifecycle, SQLite user & board storage,
and FastAPI auth endpoints.
"""

import os
import unittest
import tempfile
import sqlite3
import uuid
from datetime import timedelta

# Set temporary database path for testing before importing auth
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

from fastapi.testclient import TestClient
from api.index import app


class TestKanbanAuth(unittest.TestCase):

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
        # Clean users and user_boards tables before each test
        conn = sqlite3.connect(self.db_path)
        with conn:
            conn.execute("DELETE FROM user_boards")
            conn.execute("DELETE FROM users")
        conn.close()

    def test_password_hashing_and_verification(self):
        password = "supersecretpassword123"
        pwd_hash, salt = hash_password(password)

        self.assertIsNotNone(pwd_hash)
        self.assertIsNotNone(salt)
        self.assertNotEqual(password, pwd_hash)

        # Verify correct password
        self.assertTrue(verify_password(password, pwd_hash, salt))

        # Verify incorrect password
        self.assertFalse(verify_password("wrongpassword", pwd_hash, salt))

        # Verify different salt produces different hash
        pwd_hash2, salt2 = hash_password(password)
        self.assertNotEqual(salt, salt2)
        self.assertNotEqual(pwd_hash, pwd_hash2)

    def test_jwt_token_creation_and_decoding(self):
        user_id = "user_12345"
        username = "alice"

        token = create_access_token(user_id, username)
        self.assertIsInstance(token, str)

        payload = decode_access_token(token)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["sub"], user_id)
        self.assertEqual(payload["username"], username)

        # Tampered token
        tampered = token[:-4] + "abcd"
        self.assertIsNone(decode_access_token(tampered))

        # Expired token
        expired_token = create_access_token(user_id, username, expires_delta=timedelta(seconds=-10))
        self.assertIsNone(decode_access_token(expired_token))

    def test_user_registration_and_authentication(self):
        # Register user
        u_bob = f"bob_{uuid.uuid4().hex[:6]}"
        user, err = create_user(u_bob, "password123", db_path=self.db_path)
        self.assertIsNone(err)
        self.assertIsNotNone(user)
        self.assertEqual(user["username"], u_bob)

        # Duplicate username should fail
        dup, err2 = create_user(u_bob, "anotherpass", db_path=self.db_path)
        self.assertIsNone(dup)
        self.assertIn("already exists", err2)

        # Username case insensitivity
        dup_case, err3 = create_user(u_bob.upper(), "anotherpass", db_path=self.db_path)
        self.assertIsNone(dup_case)
        self.assertIn("already exists", err3)

        # Short username/password validation
        _, err_short_u = create_user("ab", "pass123", db_path=self.db_path)
        self.assertIn("at least 3 characters", err_short_u)
        _, err_short_p = create_user("validuser", "12", db_path=self.db_path)
        self.assertIn("at least 4 characters", err_short_p)

        # Authenticate valid
        auth_success = authenticate_user(u_bob, "password123", db_path=self.db_path)
        self.assertIsNotNone(auth_success)
        self.assertEqual(auth_success["username"], u_bob)

        # Authenticate invalid password
        auth_fail = authenticate_user(u_bob, "wrongpass", db_path=self.db_path)
        self.assertIsNone(auth_fail)

        # Authenticate non-existent user
        auth_none = authenticate_user(f"unknown_{uuid.uuid4().hex[:6]}", "password123", db_path=self.db_path)
        self.assertIsNone(auth_none)

    def test_user_board_persistence(self):
        u_charlie = f"charlie_{uuid.uuid4().hex[:6]}"
        user, _ = create_user(u_charlie, "mypassword", db_path=self.db_path)
        user_id = user["id"]

        test_board = {
            "title": "Charlie's Board",
            "columns": [
                {"id": "c1", "title": "To Do", "color": "#6366f1", "cards": [{"id": "1", "text": "Task A"}]}
            ]
        }

        # Save board
        saved = save_user_board(user_id, test_board, db_path=self.db_path)
        self.assertTrue(saved)

        # Retrieve board
        loaded = get_user_board(user_id, db_path=self.db_path)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["title"], "Charlie's Board")
        self.assertEqual(len(loaded["columns"][0]["cards"]), 1)

        # Update board
        test_board["columns"][0]["cards"].append({"id": "2", "text": "Task B"})
        save_user_board(user_id, test_board, db_path=self.db_path)

        updated = get_user_board(user_id, db_path=self.db_path)
        self.assertEqual(len(updated["columns"][0]["cards"]), 2)

    def test_api_register_and_login_endpoints(self):
        # Register via API
        u_diana = f"diana_{uuid.uuid4().hex[:6]}"
        reg_payload = {"username": u_diana, "password": "dianapassword"}
        res = self.client.post("/api/auth/register", json=reg_payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("access_token", data)
        self.assertEqual(data["user"]["username"], u_diana)

        token = data["access_token"]

        # /auth/me with valid Bearer token
        me_res = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(me_res.status_code, 200)
        self.assertEqual(me_res.json()["user"]["username"], u_diana)

        # /auth/me without token should be 401
        me_fail = self.client.get("/api/auth/me")
        self.assertEqual(me_fail.status_code, 401)

        # Login via API
        login_res = self.client.post("/api/auth/login", json={"username": u_diana, "password": "dianapassword"})
        self.assertEqual(login_res.status_code, 200)
        login_data = login_res.json()
        self.assertIn("access_token", login_data)

        # Login with bad password
        login_bad = self.client.post("/api/auth/login", json={"username": u_diana, "password": "badpassword"})
        self.assertEqual(login_bad.status_code, 401)

    def test_api_user_board_sync(self):
        u_evan = f"evan_{uuid.uuid4().hex[:6]}"
        reg = self.client.post("/api/auth/register", json={"username": u_evan, "password": "evanpassword"}).json()
        token = reg["access_token"]
        auth_header = {"Authorization": f"Bearer {token}"}

        # Initial board
        get_b = self.client.get("/api/user/board", headers=auth_header)
        self.assertEqual(get_b.status_code, 200)
        self.assertIn("board_state", get_b.json())

        # Update board
        custom_board = {
            "title": "Evan's Roadmap",
            "columns": [{"id": "done", "title": "Done", "color": "#10b981", "cards": []}]
        }
        save_res = self.client.post("/api/user/board", json={"board_state": custom_board}, headers=auth_header)
        self.assertEqual(save_res.status_code, 200)

        # Verify board persisted
        verify_b = self.client.get("/api/user/board", headers=auth_header)
        self.assertEqual(verify_b.json()["board_state"]["title"], "Evan's Roadmap")

    def test_api_command_with_user_auto_save(self):
        u_fiona = f"fiona_{uuid.uuid4().hex[:6]}"
        reg = self.client.post("/api/auth/register", json={"username": u_fiona, "password": "fionapassword"}).json()
        token = reg["access_token"]
        auth_header = {"Authorization": f"Bearer {token}"}

        initial_board = {
            "columns": [
                {
                    "id": "todo",
                    "title": "To Do",
                    "color": "#6366f1",
                    "cards": [{"id": "1", "text": "Draft release notes", "priority": "medium"}]
                },
                {
                    "id": "done",
                    "title": "Done",
                    "color": "#10b981",
                    "cards": []
                }
            ]
        }

        # Send command with Bearer token
        cmd_payload = {
            "transcript": "move Draft release notes to done",
            "board_state": initial_board,
            "provider": "local"
        }
        cmd_res = self.client.post("/api/command", json=cmd_payload, headers=auth_header)
        self.assertEqual(cmd_res.status_code, 200)
        cmd_data = cmd_res.json()
        self.assertIn(f"User: {u_fiona}", cmd_data["status"])

        # Check that user board in database was auto-saved with moved card
        saved_b = self.client.get("/api/user/board", headers=auth_header).json()["board_state"]
        done_cards = saved_b["columns"][1]["cards"]
        self.assertEqual(len(done_cards), 1)
        self.assertEqual(done_cards[0]["text"], "Draft release notes")


if __name__ == "__main__":
    unittest.main()
