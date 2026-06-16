"""services.py — Gmail SMTP, Bland AI, Google Calendar, Lead Scoring."""
import json, logging, smtplib, base64
import urllib.request, urllib.error
from urllib.parse import quote
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from config import (GMAIL_EMAIL, GMAIL_PASSWORD, GMAIL_NAME,
                    BLAND_API_KEY, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI)

logger = logging.getLogger("sales.services")


# ─── Gmail SMTP ────────────────────────────────────────────────────────────────

def send_email(to_email: str, to_name: str, subject: str, body: str) -> dict:
    if not (GMAIL_EMAIL and GMAIL_PASSWORD):
        return {"status": "not_configured", "message": "Set GMAIL_SENDER_EMAIL + GMAIL_APP_PASSWORD in .env"}
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{GMAIL_NAME} <{GMAIL_EMAIL}>"
        msg["To"] = f"{to_name} <{to_email}>" if to_name else to_email
        msg.attach(MIMEText(body, "plain"))
        html = ("<html><body style='font-family:Arial,sans-serif;font-size:14px;"
                "color:#1e293b;max-width:600px;margin:auto;padding:20px'>")
        for para in body.strip().split("\n\n"):
            html += f"<p>{para.replace(chr(10),'<br>')}</p>"
        html += "</body></html>"
        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP("smtp.gmail.com", 587) as s:
            s.starttls()
            s.login(GMAIL_EMAIL, GMAIL_PASSWORD)
            s.sendmail(GMAIL_EMAIL, to_email, msg.as_string())
        logger.info(f"Email sent → {to_email}")
        return {"status": "sent"}
    except smtplib.SMTPAuthenticationError:
        msg2 = "Gmail auth failed — use App Password from myaccount.google.com/apppasswords"
        logger.error(msg2)
        return {"status": "error", "message": msg2}
    except Exception as e:
        logger.error(f"Gmail error: {e}")
        return {"status": "error", "message": str(e)}


def test_gmail() -> tuple:
    if not (GMAIL_EMAIL and GMAIL_PASSWORD):
        return False, "Not configured — set GMAIL_SENDER_EMAIL + GMAIL_APP_PASSWORD"
    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as s:
            s.starttls()
            s.login(GMAIL_EMAIL, GMAIL_PASSWORD)
        return True, f"✅ Connected as {GMAIL_EMAIL}"
    except smtplib.SMTPAuthenticationError:
        return False, "Auth failed — check Gmail App Password"
    except Exception as e:
        return False, str(e)


# ─── Lead Scoring ──────────────────────────────────────────────────────────────

INDUSTRY_SCORES = {
    "technology":15,"software":15,"saas":15,"fintech":12,"design":10,
    "database":12,"healthcare":12,"manufacturing":10,"financial":12,
    "e-commerce":11,"cloud":14,"ai":15,"cybersecurity":13,"logistics":9,
}

def score_company(company: dict, contacts: list, signals: list) -> dict:
    rev = company.get("annual_revenue") or 0
    rs = 100 if rev>=100_000_000 else 85 if rev>=10_000_000 else 70 if rev>=1_000_000 else 40 if rev>=100_000 else 15

    emp = company.get("employee_count") or 0
    es = 100 if emp>=1000 else 85 if emp>=500 else 70 if emp>=100 else 50 if emp>=20 else 20

    ind = (company.get("industry") or "").lower()
    is_ = next((v for k,v in INDUSTRY_SCORES.items() if k in ind), 8)

    bss = min(100, sum(s.get("strength",5) for s in signals)*10//max(len(signals),1)) if signals else 0

    SENMAP = {"c_suite":30,"vp":25,"director":20,"manager":15,"individual":5}
    ds = min(100, sum(SENMAP.get(c.get("seniority_level",""),5)+(20 if c.get("is_decision_maker") else 0)
                      for c in contacts)) if contacts else 0

    email_score = 50
    total = max(0, min(100, int(rs*0.25 + es*0.15 + is_*0.20 + bss*0.20 + ds*0.10 + email_score*0.10)))
    return {
        "total_score": total,
        "revenue_score": rs, "employee_score": es, "industry_score": is_,
        "buying_signal_score": bss, "department_signal_score": ds,
        "email_activity_score": email_score,
        "tier": "hot" if total>=70 else "warm" if total>=40 else "cold",
    }


# ─── Bland AI ──────────────────────────────────────────────────────────────────

def bland_call(phone: str, task: str, voice: str = "nat",
               company_name: str = "", contact_name: str = "") -> dict:
    if not BLAND_API_KEY:
        return {"status": "error", "message": "BLAND_API_KEY not set in .env"}
    phone = phone.replace(" ","").replace("-","")
    if not phone.startswith("+"):
        return {"status": "error", "message": "Phone must start with + (e.g. +14155550100)"}
    payload = json.dumps({
        "phone_number": phone, "task": task, "model": "enhanced",
        "voice": voice, "max_duration": 300, "record": True,
        "wait_for_greeting": True, "amd": True,
        "metadata": {"company": company_name, "contact": contact_name},
    }).encode()
    try:
        req = urllib.request.Request("https://api.bland.ai/v1/calls", data=payload,
            headers={"authorization": BLAND_API_KEY, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
            return {"status": "queued", "call_id": data.get("call_id"), "data": data}
    except urllib.error.HTTPError as e:
        err = e.read().decode()[:200]
        return {"status": "error", "message": f"Bland API {e.code}: {err}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def bland_get(call_id: str) -> dict:
    if not BLAND_API_KEY: return {}
    try:
        req = urllib.request.Request(f"https://api.bland.ai/v1/calls/{call_id}",
            headers={"authorization": BLAND_API_KEY})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        logger.error(f"bland_get: {e}")
        return {}


def test_bland() -> tuple:
    if not BLAND_API_KEY: return False, "BLAND_API_KEY not set"
    try:
        req = urllib.request.Request("https://api.bland.ai/v1/calls?limit=1",
            headers={"authorization": BLAND_API_KEY})
        with urllib.request.urlopen(req, timeout=10) as r:
            json.loads(r.read())
        return True, "✅ Bland AI connected"
    except urllib.error.HTTPError as e:
        return False, f"Bland error {e.code}"
    except Exception as e:
        return False, str(e)


# ─── Google Calendar ───────────────────────────────────────────────────────────

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_AUTH_URL  = "https://accounts.google.com/o/oauth2/auth"
_CAL_API   = "https://www.googleapis.com/calendar/v3"
_SCOPES    = "https://www.googleapis.com/auth/calendar"


def google_auth_url(user_id: int = 0) -> str:
    if not GOOGLE_CLIENT_ID: return ""
    return (f"{_AUTH_URL}?client_id={quote(GOOGLE_CLIENT_ID)}"
            f"&redirect_uri={quote(GOOGLE_REDIRECT_URI)}"
            f"&response_type=code&scope={quote(_SCOPES)}"
            f"&access_type=offline&prompt=consent&state={user_id}")


def google_exchange(code: str) -> dict:
    payload = (f"code={quote(code)}&client_id={quote(GOOGLE_CLIENT_ID)}"
               f"&client_secret={quote(GOOGLE_CLIENT_SECRET)}"
               f"&redirect_uri={quote(GOOGLE_REDIRECT_URI)}&grant_type=authorization_code").encode()
    try:
        req = urllib.request.Request(_TOKEN_URL, data=payload,
            headers={"Content-Type":"application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        logger.error(f"google_exchange: {e}")
        return {}


def _access_token(refresh_token: str) -> str:
    payload = (f"client_id={quote(GOOGLE_CLIENT_ID)}&client_secret={quote(GOOGLE_CLIENT_SECRET)}"
               f"&refresh_token={quote(refresh_token)}&grant_type=refresh_token").encode()
    try:
        req = urllib.request.Request(_TOKEN_URL, data=payload,
            headers={"Content-Type":"application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read()).get("access_token","")
    except Exception as e:
        logger.error(f"_access_token: {e}")
        return ""


def create_calendar_event(refresh_token: str, title: str, start_dt: datetime,
                          duration_minutes: int = 30, attendees: list = None,
                          description: str = "") -> dict:
    at = _access_token(refresh_token)
    if not at: return {"error": "Not authorized — connect Google Calendar first"}
    end_dt = start_dt + timedelta(minutes=duration_minutes)
    event = {
        "summary": title, "description": description,
        "start": {"dateTime": start_dt.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "UTC"},
        "end":   {"dateTime": end_dt.strftime("%Y-%m-%dT%H:%M:%S"),   "timeZone": "UTC"},
        "conferenceData": {"createRequest": {
            "requestId": f"sales-{int(start_dt.timestamp())}",
            "conferenceSolutionKey": {"type":"hangoutsMeet"},
        }},
    }
    if attendees:
        event["attendees"] = [{"email": e} for e in attendees if e]
    try:
        body = json.dumps(event).encode()
        req = urllib.request.Request(
            f"{_CAL_API}/calendars/primary/events?conferenceDataVersion=1&sendUpdates=all",
            data=body, headers={"Authorization": f"Bearer {at}", "Content-Type":"application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
            meet_link = ""
            for ep in data.get("conferenceData",{}).get("entryPoints",[]):
                if ep.get("entryPointType") == "video":
                    meet_link = ep.get("uri","")
            return {"google_event_id": data.get("id"),
                    "google_meet_link": meet_link,
                    "html_link": data.get("htmlLink",""),
                    "status": "created"}
    except urllib.error.HTTPError as e:
        err = e.read().decode()[:200]
        return {"error": f"Calendar API {e.code}: {err}"}
    except Exception as e:
        return {"error": str(e)}
