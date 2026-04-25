"""Standalone smoke tests for the storage/auth/API layer.

Run with:
    uv run python scripts/smoke_tests.py

These tests intentionally avoid Turso, Gemini, and scraping. They force a
temporary local SQLite database and exercise one layer at a time.
"""

from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _configure_test_env() -> tempfile.TemporaryDirectory[str]:
    temp_dir = tempfile.TemporaryDirectory()
    os.environ["TURSO_DATABASE_URL"] = ""
    os.environ["TURSO_AUTH_TOKEN"] = ""
    os.environ["JWT_SECRET_KEY"] = "test-secret-key-with-enough-length-for-hs256"
    os.environ["LOCAL_DATABASE_PATH"] = os.path.join(temp_dir.name, "shopsmart-test.db")
    return temp_dir


def _check(name: str, fn: Callable[[], None]) -> None:
    print(f"[RUN] {name}")
    fn()
    print(f"[OK]  {name}")


def test_auth_helpers() -> None:
    from backend.auth import create_token, hash_password, verify_password

    hashed = hash_password("password123")
    assert hashed != "password123"
    assert verify_password("password123", hashed)
    assert not verify_password("wrong-password", hashed)
    assert create_token("user-1", "user@example.com")


def test_database_helpers() -> None:
    from backend.database import (
        create_user,
        delete_list,
        get_all_comparisons,
        get_all_lists,
        get_comparison,
        get_comparisons_for_list,
        get_list,
        init_db,
        save_comparison,
        save_list,
    )

    init_db()
    user = create_user("db@example.com", "hashed-password")
    saved_list = save_list(
        user["id"],
        "Laptops",
        [
            {"url": "https://www.amazon.com/dp/B000000001", "platform": "Amazon", "selected": True},
            {"url": "https://www.amazon.com/dp/B000000002", "platform": "Amazon", "selected": False},
        ],
    )

    lists = get_all_lists(user["id"])
    assert len(lists) == 1
    assert lists[0]["product_count"] == 2

    loaded = get_list(user["id"], saved_list["id"])
    assert loaded is not None
    assert len(loaded["products"]) == 2
    assert loaded["products"][0]["selected"] is True

    comparison_id = save_comparison(
        user["id"],
        saved_list["id"],
        {
            "summary": "Summary",
            "recommendation": "Recommendation",
            "markdown": "# Report",
            "questionnaire": {"questions": [{"id": "q1", "text": "Budget?", "options": ["Low", "High"]}]},
            "products": [{"title": "Laptop A", "platform": "Amazon"}],
        },
    )

    assert get_comparisons_for_list(user["id"], saved_list["id"])[0]["id"] == comparison_id
    assert get_all_comparisons(user["id"])[0]["id"] == comparison_id

    loaded_comparison = get_comparison(user["id"], comparison_id)
    assert loaded_comparison is not None
    assert loaded_comparison["questionnaire"]["questions"][0]["id"] == "q1"
    assert loaded_comparison["products"][0]["title"] == "Laptop A"

    assert delete_list(user["id"], saved_list["id"])
    assert get_list(user["id"], saved_list["id"]) is None
    # Comparison remains accessible even if its parent list was deleted.
    assert get_comparison(user["id"], comparison_id) is not None


def test_api_routes() -> None:
    from fastapi.testclient import TestClient

    from backend.api import app

    with TestClient(app) as client:
        signup = client.post(
            "/auth/signup",
            json={"email": "api@example.com", "password": "password123"},
        )
        assert signup.status_code == 200, signup.text
        token = signup.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        me = client.get("/auth/me", headers=headers)
        assert me.status_code == 200
        assert me.json()["email"] == "api@example.com"

        unauthorized_lists = client.get("/lists")
        assert unauthorized_lists.status_code == 401

        saved = client.post(
            "/lists",
            headers=headers,
            json={
                "name": "Headphones",
                "products": [
                    {"url": "https://www.amazon.com/dp/B000000003", "platform": "Amazon"},
                    {"url": "https://www.amazon.com/dp/B000000004", "platform": "Amazon"},
                ],
            },
        )
        assert saved.status_code == 200, saved.text
        list_id = saved.json()["id"]

        lists = client.get("/lists", headers=headers)
        assert lists.status_code == 200
        assert lists.json()[0]["product_count"] == 2

        loaded = client.get(f"/lists/{list_id}", headers=headers)
        assert loaded.status_code == 200
        assert len(loaded.json()["products"]) == 2

        # This validates the compare input gate without running scraping/LLM.
        too_many = client.post(
            f"/lists/{list_id}/compare",
            headers=headers,
            json={"urls": [f"https://www.amazon.com/dp/B00000000{i}" for i in range(6)]},
        )
        assert too_many.status_code == 400

        comparisons = client.get("/comparisons", headers=headers)
        assert comparisons.status_code == 200
        assert comparisons.json() == []


def main() -> None:
    temp_dir = _configure_test_env()
    try:
        _check("auth helpers", test_auth_helpers)
        _check("database helpers", test_database_helpers)
        _check("api routes", test_api_routes)
        print("\nAll smoke tests passed.")
    finally:
        temp_dir.cleanup()


if __name__ == "__main__":
    main()
