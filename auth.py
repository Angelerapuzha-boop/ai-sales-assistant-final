"""auth.py — password hashing, JWT creation and verification."""
import hashlib, jwt, logging
from datetime import datetime, timedelta
from functools import wraps
from flask import request, jsonify, g
from config import SECRET_KEY, JWT_ALGORITHM, TOKEN_EXPIRE_HOURS
from database import q1, run, now

logger = logging.getLogger("sales.auth")


def hash_pw(password: str) -> str:
    return hashlib.sha256((password + SECRET_KEY).encode()).hexdigest()


def verify_pw(password: str, hashed: str) -> bool:
    return hash_pw(password) == hashed


def make_token(user_id: int, email: str, role: str) -> str:
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "exp": datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])


def login_required(f):
    """Decorator: validates Bearer token, sets g.user."""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
        if not token:
            return jsonify({"error": "Missing token"}), 401
        try:
            payload = decode_token(token)
            g.user = {
                "id":    int(payload["sub"]),
                "email": payload["email"],
                "role":  payload["role"],
            }
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token expired — please log in again"}), 401
        except Exception:
            return jsonify({"error": "Invalid token"}), 401
        return f(*args, **kwargs)
    return decorated
