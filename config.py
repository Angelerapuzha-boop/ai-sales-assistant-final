import os

SECRET_KEY           = os.environ.get("SECRET_KEY",           "ai-sales-secret-key-32chars-2024!")
JWT_ALGORITHM        = "HS256"
TOKEN_EXPIRE_HOURS   = 48

GROQ_API_KEY         = os.environ.get("GROQ_API_KEY",         "")
GROQ_MODEL           = os.environ.get("GROQ_MODEL",           "llama-3.3-70b-versatile")

BLAND_API_KEY        = os.environ.get("BLAND_API_KEY",        "")

GMAIL_EMAIL          = os.environ.get("GMAIL_SENDER_EMAIL",   "")
GMAIL_PASSWORD       = os.environ.get("GMAIL_APP_PASSWORD",   "")
GMAIL_NAME           = os.environ.get("GMAIL_SENDER_NAME",    "AI Sales Team")

TWILIO_SID           = os.environ.get("TWILIO_ACCOUNT_SID",   "")
TWILIO_TOKEN         = os.environ.get("TWILIO_AUTH_TOKEN",    "")
TWILIO_FROM          = os.environ.get("TWILIO_FROM_NUMBER",   "")
TWILIO_ADMIN         = os.environ.get("TWILIO_ADMIN_NUMBER",  "")

GOOGLE_CLIENT_ID     = os.environ.get("GOOGLE_CLIENT_ID",     "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI  = os.environ.get("GOOGLE_REDIRECT_URI",  "http://localhost:5000/integrations/google/callback")

DAILY_REPORT_HOUR    = int(os.environ.get("DAILY_REPORT_HOUR_UTC", "18"))
PORT                 = int(os.environ.get("PORT", "5000"))
DEBUG                = os.environ.get("DEBUG", "false").lower() == "true"

# Render uses /tmp for writable storage; local uses ./data/
import tempfile
_default_db = os.path.join(tempfile.gettempdir(), "sales.db")
DB_PATH = os.environ.get("DB_PATH", _default_db)
