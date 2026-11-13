from __future__ import annotations

import hmac
import secrets
from functools import wraps

from flask import abort, g, redirect, request, session, url_for


SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


def csrf_token() -> str:
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def validate_csrf() -> None:
    if request.method in SAFE_METHODS:
        return
    expected = session.get("_csrf_token", "")
    received = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
    if not expected or not received or not hmac.compare_digest(expected, received):
        abort(400, "CSRF token is missing or invalid")


def login_required(view):
    @wraps(view)
    def wrapped(**kwargs):
        if g.user is None:
            return redirect(url_for("auth.login", next=request.full_path))
        return view(**kwargs)

    return wrapped


def role_required(*roles: str):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(**kwargs):
            if not g.user["is_active"] or g.user["role"] not in roles:
                abort(403)
            return view(**kwargs)

        return wrapped

    return decorator


def init_app(app) -> None:
    app.before_request(validate_csrf)
    app.jinja_env.globals["csrf_token"] = csrf_token
