"""
Tests for admin access control.

Verifies that:
- Non-admin users get 403 on admin routes
- Admin users succeed on admin routes
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models import User
from app.api.auth import get_password_hash


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def admin_user(db: Session) -> User:
    """Create an admin user."""
    user = User(
        email="admin@test.com",
        hashed_password=get_password_hash("testpassword123"),
        is_admin=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def regular_user(db: Session) -> User:
    """Create a regular (non-admin) user."""
    user = User(
        email="user@test.com",
        hashed_password=get_password_hash("testpassword123"),
        is_admin=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_auth_token(client: TestClient, email: str, password: str) -> str:
    """Helper to get auth token."""
    response = client.post(
        "/api/auth/token",
        data={"username": email, "password": password},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def test_admin_can_access_training_status(client: TestClient, admin_user: User):
    """Admin user can access training status endpoint."""
    token = get_auth_token(client, admin_user.email, "testpassword123")
    response = client.get(
        "/api/admin/training/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200


def test_non_admin_cannot_access_training_status(client: TestClient, regular_user: User):
    """Non-admin user gets 403 on training status endpoint."""
    token = get_auth_token(client, regular_user.email, "testpassword123")
    response = client.get(
        "/api/admin/training/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert "Admin access required" in response.json()["detail"]


def test_admin_can_access_diagnostics(client: TestClient, admin_user: User):
    """Admin user can access diagnostics endpoint."""
    token = get_auth_token(client, admin_user.email, "testpassword123")
    response = client.get(
        "/api/admin/diagnostics/zero-forecasts",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200


def test_non_admin_cannot_access_diagnostics(client: TestClient, regular_user: User):
    """Non-admin user gets 403 on diagnostics endpoint."""
    token = get_auth_token(client, regular_user.email, "testpassword123")
    response = client.get(
        "/api/admin/diagnostics/zero-forecasts",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert "Admin access required" in response.json()["detail"]
