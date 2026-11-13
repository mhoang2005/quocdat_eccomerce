from app import create_app
from app.services.bootstrap import ensure_initialized


app = create_app()


if __name__ == "__main__":
    with app.app_context():
        ensure_initialized()
    app.run(host="127.0.0.1", port=5000, debug=True)

