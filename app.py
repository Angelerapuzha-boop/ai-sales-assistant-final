"""
AI Sales Assistant — Flask 3.1
Render deploy: gunicorn app:app
Local: python app.py
"""
import logging
import os
from flask import Flask, render_template, jsonify

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("sales")

app = Flask(__name__, template_folder="templates")
app.secret_key = os.environ.get("SECRET_KEY", "ai-sales-secret-key-32chars-2024!")

from routes_api import api as api_bp
app.register_blueprint(api_bp)

@app.route("/")
@app.route("/<path:_>")
def index(_=None):
    return render_template("index.html")

@app.get("/health")
def health():
    from database import q
    try:
        cos = len(q("SELECT id FROM companies"))
        db_ok = True
    except Exception:
        cos, db_ok = 0, False
    return jsonify({
        "status": "healthy" if db_ok else "degraded",
        "database": db_ok,
        "companies": cos,
        "groq":   bool(os.environ.get("GROQ_API_KEY")),
        "twilio": bool(os.environ.get("TWILIO_ACCOUNT_SID")),
        "bland":  bool(os.environ.get("BLAND_API_KEY")),
        "gmail":  bool(os.environ.get("GMAIL_SENDER_EMAIL")),
    })

@app.errorhandler(404)
def not_found(e):
    return render_template("index.html")

@app.errorhandler(405)
def method_not_allowed(e):
    return jsonify({"ok": False, "error": "Method not allowed"}), 405

@app.errorhandler(500)
def server_error(e):
    logger.error(f"500: {e}")
    return jsonify({"ok": False, "error": "Internal server error"}), 500

_started = False

@app.before_request
def _startup():
    global _started
    if not _started:
        _started = True
        from database import init_db
        init_db()
        from scheduler import start
        start()
        logger.info("✅ App ready")

if __name__ == "__main__":
    from database import init_db
    from scheduler import start
    init_db()
    start()
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"🚀 http://localhost:{port}  login: admin@salesai.com / Admin@123456")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
