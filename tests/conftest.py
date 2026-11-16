from __future__ import annotations

from pathlib import Path

import pytest

from app import create_app
from app.services.bootstrap import initialize_system


@pytest.fixture(scope="session")
def app(tmp_path_factory):
    root = tmp_path_factory.mktemp("quocdat-marketplace-tests")
    instance_dir = root / "instance"
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "SQLSERVER_CONNECTION": "",
            "INSTANCE_DIR": instance_dir,
            "OLTP_DATABASE": instance_dir / "oltp.db",
            "STAGING_DATABASE": instance_dir / "staging.db",
            "DWH_DATABASE": instance_dir / "dwh.db",
            "PRODUCTS_PER_PAGE": 12,
        }
    )
    with app.app_context():
        result = initialize_system(reset=True, product_limit=120)
        assert result["products"] == 120
        assert result["raw"]["source"] == 17_640
        assert result["etl"]["status"] == "SUCCESS"
    yield app


@pytest.fixture()
def client(app):
    return app.test_client()


def login_as(client, app, email: str) -> int:
    from app.db import get_db

    with app.app_context():
        user = get_db().execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        assert user is not None
        user_id = user["id"]
    with client.session_transaction() as session:
        session["user_id"] = user_id
        session["_csrf_token"] = "test-csrf-token"
    return user_id


@pytest.fixture()
def csrf_token():
    return "test-csrf-token"
