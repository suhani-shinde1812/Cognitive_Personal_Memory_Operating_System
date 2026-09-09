# LOCATION: backend/test/test_auth.py
import pytest
from fastapi.testclient import TestClient
from main import app

import time

client = TestClient(app)


def test_register_and_login_flow():
    email = f"auth_test_user_{int(time.time())}@cognisphere.ai"
    password = "StrongPassword123!"

    # 1. Register new user
    res = client.post("/auth/register", json={"email": email, "password": password})
    assert res.status_code in [201, 409]
    if res.status_code == 201:
        data = res.json()
        assert data["status"] == "ok"
        assert data["user"]["email"] == email
        assert "token" in data
        assert "access_token" in res.cookies

    # 2. Duplicate registration fails with 409 Conflict
    dup_res = client.post("/auth/register", json={"email": email, "password": password})
    assert dup_res.status_code == 409
    assert "already exists" in dup_res.json()["detail"].lower()

    # 3. Weak password fails with 400
    weak_res = client.post("/auth/register", json={"email": "weak@cognisphere.ai", "password": "123"})
    assert weak_res.status_code == 400
    assert "at least 8 characters" in weak_res.json()["detail"]

    # 4. Invalid email format fails with 400
    inv_res = client.post("/auth/register", json={"email": "not-an-email", "password": password})
    assert inv_res.status_code == 400

    # 5. Login with correct password
    login_res = client.post("/auth/login", json={"email": email, "password": password})
    assert login_res.status_code == 200
    login_data = login_res.json()
    assert login_data["user"]["email"] == email
    token = login_data["token"]
    assert token

    # 6. Login with incorrect password fails with 401
    bad_login = client.post("/auth/login", json={"email": email, "password": "WrongPassword999!"})
    assert bad_login.status_code == 401
    assert "invalid email or password" in bad_login.json()["detail"].lower()

    # 7. GET /auth/me with Bearer token
    me_res = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_res.status_code == 200
    assert me_res.json()["email"] == email

    # 8. GET /auth/me with Cookie
    cookie_res = client.get("/auth/me", cookies={"access_token": token})
    assert cookie_res.status_code == 200
    assert cookie_res.json()["email"] == email

    # 9. GET /auth/me without authentication fails with 401
    unauth_res = client.get("/auth/me")
    assert unauth_res.status_code == 401

    # 10. POST /auth/change-password
    new_password = "NewSuperPassword456!"
    ch_res = client.post(
        "/auth/change-password",
        json={"current_password": password, "new_password": new_password},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert ch_res.status_code == 200

    # Old password no longer works
    old_login = client.post("/auth/login", json={"email": email, "password": password})
    assert old_login.status_code == 401

    # New password works
    new_login = client.post("/auth/login", json={"email": email, "password": new_password})
    assert new_login.status_code == 200

    # 11. POST /auth/logout
    logout_res = client.post("/auth/logout")
    assert logout_res.status_code == 200

    # 12. POST /auth/reset-password
    reset_pass = "ResetPassword987!"
    reset_res = client.post("/auth/reset-password", json={"email": email, "password": reset_pass})
    assert reset_res.status_code == 200
    assert reset_res.json()["status"] == "ok"
    # Login with newly reset password
    assert client.post("/auth/login", json={"email": email, "password": reset_pass}).status_code == 200


def test_legacy_unhashed_account_activation():
    from database.database import SessionLocal
    from app.models.user import User

    legacy_email = f"legacy_{int(time.time())}@cognisphere.ai"
    db = SessionLocal()
    # Insert user with empty password_hash mimicking unhashed or legacy row
    u = User(email=legacy_email, password_hash="")
    db.add(u)
    db.commit()
    db.close()

    # Registering should auto-activate instead of 409
    reg = client.post("/auth/register", json={"email": legacy_email, "password": "NewValidPassword123!"})
    assert reg.status_code == 201
    assert "token" in reg.json()

    # Subsequent login works
    login = client.post("/auth/login", json={"email": legacy_email, "password": "NewValidPassword123!"})
    assert login.status_code == 200

