"""twilio_sms.py — Twilio SMS via urllib (no SDK). Handles all 12 notification events."""
import json, logging, base64, threading
import urllib.request, urllib.error
from urllib.parse import quote
from datetime import datetime, timedelta
from config import TWILIO_SID, TWILIO_TOKEN, TWILIO_FROM, TWILIO_ADMIN

logger = logging.getLogger("sales.sms")

TEMPLATES = {
    "company_added":
        "🏢 Company Added\nCompany: {company_name}\nIndustry: {industry}\nScore: {lead_score}/100\nStatus: {status}",
    "hot_lead":
        "🔥 Hot Lead Alert!\nCompany: {company_name}\nScore: {lead_score}/100\nIndustry: {industry}\n⚡ Reach out now!",
    "email_generated":
        "📧 Email Generated\nCompany: {company_name}\nType: {email_type}\nTo: {recipient_email}\nSubject: {subject}",
    "email_sent":
        "✅ Email Sent\nTo: {recipient_email}\nSubject: {subject}\nType: {email_type}",
    "meeting_scheduled":
        "📅 Meeting Scheduled\nTitle: {title}\nCompany: {company_name}\nTime: {scheduled_at}\nDuration: {duration_minutes} min",
    "meeting_completed":
        "✅ Meeting Completed\nTitle: {title}\nCompany: {company_name}\nType: {meeting_type}",
    "call_initiated":
        "📞 Call Initiated\nCompany: {company_name}\nPhone: {phone_number}\nObjective: {objective}",
    "csv_import":
        "📤 Import Completed\nFile: {filename}\n✅ Imported: {processed_rows}\n❌ Failed: {failed_rows}",
    "daily_report":
        "📊 Daily Report — {report_date}\n🏢 Companies: {total_companies} | 🔥 Hot: {hot_leads} | 🟡 Warm: {warm_leads}\n"
        "📧 Emails: {emails_sent} | Open: {email_open_rate}%\n📞 Calls: {total_calls} | 📅 Meetings: {meetings_scheduled}\n"
        "💰 Pipeline: ${revenue_pipeline:,}\nTop: {top_companies}",
    "meeting_reminder_24h":
        "📅 Reminder — 24 Hours\n{title}\nCompany: {company_name}\nTime: {scheduled_at}",
    "meeting_reminder_1h":
        "⏰ Reminder — 1 Hour\n{title}\nCompany: {company_name}\nTime: {scheduled_at}",
    "meeting_reminder_10min":
        "⏰ Reminder — 10 Minutes!\n{title}\nCompany: {company_name}\n🚀 Starting soon!",
}


class _Safe(dict):
    def __missing__(self, key):
        return ""


def _send_raw(to: str, body: str) -> dict:
    if not all([TWILIO_SID, TWILIO_TOKEN, TWILIO_FROM, to]):
        logger.debug("Twilio not configured — skipped")
        return {"status": "not_configured"}
    payload = f"To={quote(to)}&From={quote(TWILIO_FROM)}&Body={quote(body[:1600])}"
    creds = base64.b64encode(f"{TWILIO_SID}:{TWILIO_TOKEN}".encode()).decode()
    url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}/Messages.json"
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=payload.encode(),
                headers={"Authorization": f"Basic {creds}",
                         "Content-Type": "application/x-www-form-urlencoded"})
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read())
                logger.info(f"SMS sent → {to}: {data.get('sid','')}")
                return {"status": "sent", "sid": data.get("sid"), "to": to}
        except urllib.error.HTTPError as e:
            err = e.read().decode()[:200]
            logger.error(f"Twilio HTTP {e.code}: {err}")
            return {"status": "error", "message": f"HTTP {e.code}: {err}"}
        except Exception as e:
            if attempt < 2:
                import time; time.sleep(1)
            else:
                logger.error(f"Twilio failed: {e}")
                return {"status": "error", "message": str(e)}
    return {"status": "error", "message": "Max retries exceeded"}


def send_sms(to: str, body: str) -> dict:
    return _send_raw(to, body)


def _log_sms(event_type: str, body: str, result: dict):
    try:
        from database import run
        run("INSERT INTO sms_logs(to_number,from_number,body,status,event_type) VALUES(?,?,?,?,?)",
            (TWILIO_ADMIN or "admin", TWILIO_FROM, body[:500],
             result.get("status","unknown"), event_type))
    except Exception as e:
        logger.debug(f"SMS log failed: {e}")


def notify(event_type: str, data: dict):
    tmpl = TEMPLATES.get(event_type)
    if not tmpl:
        logger.warning(f"Unknown SMS event: {event_type}")
        return
    try:
        body = tmpl.format_map(_Safe(data))
        result = _send_raw(TWILIO_ADMIN or "", body)
        _log_sms(event_type, body, result)
    except Exception as e:
        logger.error(f"notify [{event_type}]: {e}")


def notify_async(event_type: str, data: dict):
    threading.Thread(target=notify, args=(event_type, data), daemon=True).start()


def send_test(to: str) -> dict:
    body = (f"✅ AI Sales Assistant\nTwilio SMS Connected!\n"
            f"Time: {datetime.utcnow().strftime('%d %b %Y %H:%M')} UTC")
    return _send_raw(to, body)


def schedule_reminders(meeting_id: int, title: str, company_name: str, scheduled_at: str):
    """Background threads for 24h / 1h / 10min reminders."""
    if not scheduled_at:
        return
    try:
        meeting_dt = datetime.strptime(scheduled_at[:19], "%Y-%m-%d %H:%M:%S")
    except Exception:
        return

    def _fire(delta, event_type):
        trigger = meeting_dt - delta
        delay = (trigger - datetime.utcnow()).total_seconds()
        if delay <= 0:
            return
        data = {"title": title, "company_name": company_name,
                "scheduled_at": meeting_dt.strftime("%d %b %Y %H:%M UTC")}
        def _run():
            import time; time.sleep(delay)
            notify(event_type, data)
        threading.Thread(target=_run, daemon=True).start()
        logger.info(f"Reminder '{event_type}' set in {int(delay/60)} min")

    _fire(timedelta(hours=24), "meeting_reminder_24h")
    _fire(timedelta(hours=1),  "meeting_reminder_1h")
    _fire(timedelta(minutes=10),"meeting_reminder_10min")
