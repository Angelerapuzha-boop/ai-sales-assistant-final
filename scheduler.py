"""scheduler.py — Daily SMS report using stdlib threading + schedule loop."""
import threading, logging, time
from datetime import datetime
from config import DAILY_REPORT_HOUR

logger = logging.getLogger("sales.scheduler")
_running = False
_thread = None


def _daily_report():
    try:
        from database import q
        from twilio_sms import notify_async

        cos   = q("SELECT lead_score, name FROM companies")
        emails= q("SELECT status FROM emails")
        mtgs  = q("SELECT status FROM meetings")
        calls = q("SELECT id FROM calls")

        hot   = sum(1 for c in cos if (c.get("lead_score") or 0) >= 70)
        warm  = sum(1 for c in cos if 40 <= (c.get("lead_score") or 0) < 70)
        sent  = sum(1 for e in emails if e.get("status") != "draft")
        opened= sum(1 for e in emails if e.get("status") in ("opened","replied"))
        sched = sum(1 for m in mtgs if m.get("status") == "scheduled")
        top5  = sorted(cos, key=lambda x: x.get("lead_score",0), reverse=True)[:5]
        top_str = ", ".join([f"{c['name']}({c['lead_score']})" for c in top5])

        notify_async("daily_report", {
            "report_date":        datetime.utcnow().strftime("%d %b %Y"),
            "total_companies":    len(cos),
            "hot_leads":          hot,
            "warm_leads":         warm,
            "emails_sent":        sent,
            "email_open_rate":    round(opened/sent*100, 1) if sent else 0,
            "total_calls":        len(calls),
            "meetings_scheduled": sched,
            "revenue_pipeline":   hot*50000 + warm*15000,
            "top_companies":      top_str,
        })
        logger.info("✅ Daily report SMS sent")
    except Exception as e:
        logger.error(f"Daily report failed: {e}")


def _scheduler_loop():
    logger.info(f"Scheduler running — daily report at {DAILY_REPORT_HOUR}:00 UTC")
    last_sent_day = -1
    while _running:
        now = datetime.utcnow()
        if now.hour == DAILY_REPORT_HOUR and now.day != last_sent_day:
            last_sent_day = now.day
            _daily_report()
        time.sleep(60)


def start():
    global _running, _thread
    if _running:
        return
    _running = True
    _thread = threading.Thread(target=_scheduler_loop, daemon=True, name="DailyReportScheduler")
    _thread.start()
    logger.info("✅ Scheduler started")


def stop():
    global _running
    _running = False


def trigger_now():
    """Force-run the daily report immediately (for testing/manual trigger)."""
    threading.Thread(target=_daily_report, daemon=True).start()
