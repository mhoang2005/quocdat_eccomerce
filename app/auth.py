from __future__ import annotations

from urllib.parse import urljoin, urlparse

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db


bp = Blueprint("auth", __name__, url_prefix="/auth")


def _safe_next(target: str | None) -> bool:
    if not target:
        return False
    host = urlparse(request.host_url)
    candidate = urlparse(urljoin(request.host_url, target))
    return candidate.scheme in {"http", "https"} and host.netloc == candidate.netloc


def role_home(role: str) -> str:
    return {
        "customer": url_for("customer.orders"),
        "employee": url_for("employee.dashboard"),
        "admin": url_for("admin.dashboard"),
    }.get(role, url_for("catalog.home"))


@bp.route("/login", methods=("GET", "POST"))
def login():
    if g.user:
        return redirect(role_home(g.user["role"]))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        error = None
        if user is None or not check_password_hash(user["password_hash"], password):
            error = "Incorrect email or password."
        elif not user["is_active"]:
            error = "This account is locked."
        if error:
            flash(error, "error")
        else:
            session.clear()
            session["user_id"] = user["id"]
            target = request.form.get("next")
            return redirect(target if _safe_next(target) else role_home(user["role"]))
    return render_template("auth/login.html", next=request.args.get("next", ""))


@bp.route("/register", methods=("GET", "POST"))
def register():
    if g.user:
        return redirect(role_home(g.user["role"]))
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        city = request.form.get("city", "").strip()
        address = request.form.get("address", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        error = None
        if len(full_name) < 2:
            error = "Please enter a valid full name."
        elif "@" not in email:
            error = "Please enter a valid email address."
        elif len(password) < 8:
            error = "Password must contain at least 8 characters."
        elif password != confirm:
            error = "Password confirmation does not match."
        if error:
            flash(error, "error")
        else:
            database = get_db()
            try:
                cursor = database.execute(
                    """
                    INSERT INTO users(
                        email, password_hash, role, full_name, phone, city, address
                    ) VALUES (?, ?, 'customer', ?, ?, ?, ?)
                    """,
                    (email, generate_password_hash(password), full_name, phone, city, address),
                )
                database.execute("INSERT INTO carts(customer_id) VALUES (?)", (cursor.lastrowid,))
                database.commit()
            except Exception as exc:
                database.rollback()
                if "UNIQUE" in str(exc).upper():
                    flash("This email address is already in use.", "error")
                else:
                    raise
            else:
                flash("Registration successful. You can now sign in.", "success")
                return redirect(url_for("auth.login"))
    return render_template("auth/register.html")


@bp.post("/logout")
def logout():
    session.clear()
    flash("You have signed out.", "info")
    return redirect(url_for("catalog.home"))


def load_logged_in_user() -> None:
    user_id = session.get("user_id")
    if user_id is None:
        g.user = None
    else:
        g.user = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if g.user is None or not g.user["is_active"]:
            session.clear()
            g.user = None


def cart_count() -> int:
    if not g.user or g.user["role"] != "customer":
        return 0
    row = get_db().execute(
        """
        SELECT COALESCE(SUM(ci.quantity), 0) AS count
        FROM carts c LEFT JOIN cart_items ci ON ci.cart_id = c.id
        WHERE c.customer_id = ?
        """,
        (g.user["id"],),
    ).fetchone()
    return row["count"]


def init_app(app) -> None:
    app.before_request(load_logged_in_user)
    app.context_processor(lambda: {"cart_count": cart_count()})

