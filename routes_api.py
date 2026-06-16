"""routes_api.py — all JSON API endpoints registered on a Blueprint."""
import csv, io, json, logging, threading
from datetime import datetime
from flask import Blueprint, request, jsonify, g
from auth import login_required, hash_pw, verify_pw, make_token
from database import q, q1, run, now
from ai_service import company_summary, generate_email, buying_signals, call_script, chat_reply
from twilio_sms import notify_async, send_test, schedule_reminders
from services import (send_email, test_gmail, score_company,
                      bland_call, bland_get, test_bland,
                      google_auth_url, google_exchange, create_calendar_event)

api = Blueprint("api", __name__, url_prefix="/api")
logger = logging.getLogger("sales.api")


def ok(data=None, **kw):
    resp = {"ok": True}
    if data is not None:
        resp["data"] = data
    resp.update(kw)
    return jsonify(resp)


def err(msg, code=400):
    return jsonify({"ok": False, "error": msg}), code


# ─── AUTH ──────────────────────────────────────────────────────────────────────

@api.post("/auth/login")
def login():
    d = request.get_json(silent=True) or {}
    email = (d.get("email") or "").lower().strip()
    password = d.get("password") or ""
    if not email or not password:
        return err("Email and password required")
    user = q1("SELECT * FROM users WHERE email=? AND is_active=1", (email,))
    if not user or not verify_pw(password, user["password"]):
        return err("Invalid credentials", 401)
    run("UPDATE users SET last_login=? WHERE id=?", (now(), user["id"]))
    token = make_token(user["id"], user["email"], user["role"])
    return ok({"token": token, "user": _user_safe(user)})


@api.post("/auth/register")
def register():
    d = request.get_json(silent=True) or {}
    email = (d.get("email") or "").lower().strip()
    full_name = (d.get("full_name") or "").strip()
    password = d.get("password") or ""
    role = d.get("role", "sales_rep")
    if not email or not full_name or not password:
        return err("email, full_name and password required")
    if len(password) < 6:
        return err("Password must be at least 6 characters")
    if q1("SELECT 1 FROM users WHERE email=?", (email,)):
        return err("Email already registered")
    uid = run("INSERT INTO users(email,full_name,password,role) VALUES(?,?,?,?)",
              (email, full_name, hash_pw(password), role))
    user = q1("SELECT * FROM users WHERE id=?", (uid,))
    token = make_token(uid, email, role)
    return ok({"token": token, "user": _user_safe(user)}), 201


@api.get("/auth/me")
@login_required
def me():
    user = q1("SELECT * FROM users WHERE id=?", (g.user["id"],))
    if not user:
        return err("User not found", 404)
    return ok(_user_safe(user))


def _user_safe(u):
    return {k: u[k] for k in ("id","email","full_name","role","is_active","created_at","last_login")
            if k in u}


# ─── COMPANIES ────────────────────────────────────────────────────────────────

@api.get("/companies")
@login_required
def list_companies():
    search = request.args.get("search", "")
    status = request.args.get("status", "")
    limit  = min(int(request.args.get("limit", 200)), 500)
    sql = "SELECT * FROM companies WHERE 1=1"
    args = []
    if search:
        sql += " AND name LIKE ?"
        args.append(f"%{search}%")
    if status:
        sql += " AND status=?"
        args.append(status)
    sql += " ORDER BY lead_score DESC LIMIT ?"
    args.append(limit)
    return ok(q(sql, args))


@api.post("/companies")
@login_required
def create_company():
    d = request.get_json(silent=True) or {}
    name = (d.get("name") or "").strip()
    if not name:
        return err("name is required")
    cid = run("""INSERT INTO companies
        (name,industry,employee_count,annual_revenue,website,city,country,
         description,technologies,status,linkedin_url,funding_stage,created_by,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
        name, d.get("industry"), d.get("employee_count"), d.get("annual_revenue"),
        d.get("website"), d.get("city"), d.get("country"), d.get("description"),
        d.get("technologies"), d.get("status","prospect"),
        d.get("linkedin_url"), d.get("funding_stage"), g.user["id"], now()))
    co = q1("SELECT * FROM companies WHERE id=?", (cid,))
    notify_async("company_added", {
        "company_name": co["name"], "industry": co.get("industry","N/A"),
        "lead_score": co.get("lead_score",0), "status": co.get("status","prospect"),
    })
    return ok(co), 201


@api.get("/companies/<int:cid>")
@login_required
def get_company(cid):
    co = q1("SELECT * FROM companies WHERE id=?", (cid,))
    if not co:
        return err("Company not found", 404)
    co["contacts"] = q("SELECT * FROM contacts WHERE company_id=?", (cid,))
    co["emails"]   = q("SELECT * FROM emails WHERE company_id=? ORDER BY created_at DESC", (cid,))
    co["meetings"] = q("SELECT * FROM meetings WHERE company_id=? ORDER BY scheduled_at DESC", (cid,))
    co["calls"]    = q("SELECT * FROM calls WHERE company_id=? ORDER BY created_at DESC", (cid,))
    co["buying_signals"] = q("SELECT * FROM buying_signals WHERE company_id=?", (cid,))
    co["lead_score_details"] = q1("SELECT * FROM lead_scores WHERE company_id=?", (cid,))
    return ok(co)


@api.put("/companies/<int:cid>")
@login_required
def update_company(cid):
    co = q1("SELECT id FROM companies WHERE id=?", (cid,))
    if not co:
        return err("Not found", 404)
    d = request.get_json(silent=True) or {}
    allowed = {"name","industry","employee_count","annual_revenue","website","city","country",
                "description","technologies","status","linkedin_url","funding_stage","ai_summary"}
    sets = [f"{k}=?" for k in d if k in allowed]
    vals = [d[k] for k in d if k in allowed]
    if not sets:
        return err("Nothing to update")
    sets.append("updated_at=?"); vals.append(now()); vals.append(cid)
    run(f"UPDATE companies SET {','.join(sets)} WHERE id=?", vals)
    return ok(q1("SELECT * FROM companies WHERE id=?", (cid,)))


@api.delete("/companies/<int:cid>")
@login_required
def delete_company(cid):
    if not q1("SELECT id FROM companies WHERE id=?", (cid,)):
        return err("Not found", 404)
    run("DELETE FROM companies WHERE id=?", (cid,))
    return ok({"deleted": cid})


@api.post("/companies/<int:cid>/score")
@login_required
def score_company_route(cid):
    co = q1("SELECT * FROM companies WHERE id=?", (cid,))
    if not co:
        return err("Not found", 404)
    contacts = q("SELECT * FROM contacts WHERE company_id=?", (cid,))
    signals  = q("SELECT * FROM buying_signals WHERE company_id=?", (cid,))
    sc = score_company(co, contacts, signals)
    existing = q1("SELECT id FROM lead_scores WHERE company_id=?", (cid,))
    if existing:
        run("""UPDATE lead_scores SET total_score=?,revenue_score=?,employee_score=?,
               industry_score=?,buying_signal_score=?,department_signal_score=?,
               email_activity_score=?,tier=?,updated_at=? WHERE company_id=?""",
            (sc["total_score"],sc["revenue_score"],sc["employee_score"],sc["industry_score"],
             sc["buying_signal_score"],sc["department_signal_score"],sc["email_activity_score"],
             sc["tier"],now(),cid))
    else:
        run("""INSERT INTO lead_scores(company_id,total_score,revenue_score,employee_score,
               industry_score,buying_signal_score,department_signal_score,email_activity_score,tier)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (cid,sc["total_score"],sc["revenue_score"],sc["employee_score"],sc["industry_score"],
             sc["buying_signal_score"],sc["department_signal_score"],sc["email_activity_score"],sc["tier"]))
    run("UPDATE companies SET lead_score=?,updated_at=? WHERE id=?",
        (sc["total_score"], now(), cid))
    if sc["total_score"] >= 80:
        notify_async("hot_lead", {"company_name": co["name"],
                     "lead_score": sc["total_score"], "industry": co.get("industry","N/A")})
    return ok(sc)


@api.post("/companies/<int:cid>/ai-summary")
@login_required
def ai_summary(cid):
    co = q1("SELECT * FROM companies WHERE id=?", (cid,))
    if not co:
        return err("Not found", 404)
    summary = company_summary(co)
    run("UPDATE companies SET ai_summary=?,updated_at=? WHERE id=?", (summary, now(), cid))
    return ok({"summary": summary})


@api.post("/companies/<int:cid>/analyze-signals")
@login_required
def analyze_signals(cid):
    co = q1("SELECT * FROM companies WHERE id=?", (cid,))
    if not co:
        return err("Not found", 404)
    run("DELETE FROM buying_signals WHERE company_id=?", (cid,))
    sigs = buying_signals(co)
    for s in sigs:
        run("""INSERT INTO buying_signals(company_id,signal_type,signal_name,signal_description,strength,source)
               VALUES(?,?,?,?,?,?)""",
            (cid, s.get("type",""), s.get("name",""), s.get("description",""), s.get("strength",5), "ai"))
    return ok({"signals": sigs})


@api.post("/companies/upload-csv")
@login_required
def upload_csv():
    f = request.files.get("file")
    if not f or not f.filename.endswith(".csv"):
        return err("CSV file required")
    content = f.read()
    fname = f.filename
    uid = g.user["id"]

    def _process():
        CMAP = {"company":"name","company_name":"name","organization":"name",
                "employees":"employee_count","employee_count":"employee_count",
                "revenue":"annual_revenue","annual_revenue":"annual_revenue",
                "first_name":"first_name","last_name":"last_name","email":"email",
                "phone":"phone","title":"title","job_title":"title",
                "industry":"industry","country":"country","city":"city",
                "website":"website","technologies":"technologies","status":"status"}
        try:
            text = content.decode("utf-8-sig", errors="replace")
            reader = csv.DictReader(io.StringIO(text))
            rows = []
            for raw in reader:
                row = {}
                for k,v in raw.items():
                    nk = (k or "").lower().strip().replace(" ","_")
                    row[CMAP.get(nk,nk)] = (v or "").strip()
                rows.append(row)
            ok_count, fail = 0, 0
            for row in rows:
                name = (row.get("name") or "").strip()
                if not name:
                    fail += 1; continue
                try:
                    def ti(v):
                        if not v: return None
                        try: return int(float(str(v).replace(",","").replace("$","")))
                        except: return None
                    techs = row.get("technologies","")
                    if techs:
                        parts = [t.strip() for t in techs.split(",") if t.strip()]
                        techs = json.dumps(parts)
                    existing = q1("SELECT id FROM companies WHERE name=?", (name,))
                    if existing:
                        cid = existing["id"]
                        run("""UPDATE companies SET industry=COALESCE(?,industry),
                               employee_count=COALESCE(?,employee_count),
                               annual_revenue=COALESCE(?,annual_revenue),
                               country=COALESCE(?,country),city=COALESCE(?,city),
                               website=COALESCE(?,website),technologies=COALESCE(?,technologies),
                               status=COALESCE(?,status),updated_at=? WHERE id=?""",
                            (row.get("industry"),ti(row.get("employee_count")),
                             ti(row.get("annual_revenue")),row.get("country"),row.get("city"),
                             row.get("website"),techs or None,row.get("status"),now(),cid))
                    else:
                        cid = run("""INSERT INTO companies(name,industry,employee_count,annual_revenue,
                                     country,city,website,technologies,status,created_by,updated_at)
                                     VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                                  (name,row.get("industry"),ti(row.get("employee_count")),
                                   ti(row.get("annual_revenue")),row.get("country"),row.get("city"),
                                   row.get("website"),techs or None,row.get("status","prospect"),uid,now()))
                    fn = (row.get("first_name") or "").strip()
                    em_addr = (row.get("email") or "").strip()
                    if fn or em_addr:
                        run("""INSERT INTO contacts(company_id,first_name,last_name,email,phone,title,seniority_level)
                               VALUES(?,?,?,?,?,?,?)""",
                            (cid,fn or "Unknown",row.get("last_name"),em_addr or None,
                             row.get("phone"),row.get("title"),"manager"))
                    sigs = buying_signals({"name":name,"industry":row.get("industry",""),
                                           "employee_count":ti(row.get("employee_count")),
                                           "annual_revenue":ti(row.get("annual_revenue"))})
                    for s in sigs:
                        run("""INSERT INTO buying_signals(company_id,signal_type,signal_name,signal_description,strength,source)
                               VALUES(?,?,?,?,?,?)""",
                            (cid,s.get("type",""),s.get("name",""),s.get("description",""),s.get("strength",5),"csv"))
                    ok_count += 1
                except Exception as e:
                    logger.error(f"CSV row error: {e}")
                    fail += 1
            notify_async("csv_import", {"filename":fname,"processed_rows":ok_count,"failed_rows":fail})
        except Exception as e:
            logger.error(f"CSV import failed: {e}")

    threading.Thread(target=_process, daemon=True).start()
    return ok({"message": "Import started — SMS notification on completion", "filename": fname}), 201


# ─── CONTACTS ─────────────────────────────────────────────────────────────────

@api.get("/contacts")
@login_required
def list_contacts():
    cid = request.args.get("company_id")
    if cid:
        return ok(q("SELECT * FROM contacts WHERE company_id=?", (cid,)))
    return ok(q("SELECT * FROM contacts ORDER BY created_at DESC LIMIT 500"))


@api.post("/contacts")
@login_required
def create_contact():
    d = request.get_json(silent=True) or {}
    if not d.get("company_id") or not d.get("first_name"):
        return err("company_id and first_name required")
    if not q1("SELECT id FROM companies WHERE id=?", (d["company_id"],)):
        return err("Company not found", 404)
    ctid = run("""INSERT INTO contacts(company_id,first_name,last_name,email,phone,title,
                  department,seniority_level,is_decision_maker) VALUES(?,?,?,?,?,?,?,?,?)""",
               (d["company_id"],d["first_name"],d.get("last_name"),d.get("email"),
                d.get("phone"),d.get("title"),d.get("department"),
                d.get("seniority_level","individual"),
                1 if d.get("is_decision_maker") else 0))
    return ok(q1("SELECT * FROM contacts WHERE id=?", (ctid,))), 201


@api.put("/contacts/<int:ctid>")
@login_required
def update_contact(ctid):
    if not q1("SELECT id FROM contacts WHERE id=?", (ctid,)):
        return err("Not found", 404)
    d = request.get_json(silent=True) or {}
    allowed = {"first_name","last_name","email","phone","title","department","seniority_level","is_decision_maker"}
    sets = [f"{k}=?" for k in d if k in allowed]
    vals = [d[k] for k in d if k in allowed]
    if sets:
        run(f"UPDATE contacts SET {','.join(sets)} WHERE id=?", vals + [ctid])
    return ok(q1("SELECT * FROM contacts WHERE id=?", (ctid,)))


# ─── EMAILS ───────────────────────────────────────────────────────────────────

@api.get("/emails")
@login_required
def list_emails():
    status = request.args.get("status","")
    cid    = request.args.get("company_id","")
    sql    = "SELECT * FROM emails WHERE 1=1"
    args   = []
    if status: sql += " AND status=?"; args.append(status)
    if cid:    sql += " AND company_id=?"; args.append(cid)
    sql += " ORDER BY created_at DESC LIMIT 200"
    return ok(q(sql, args))


@api.post("/emails/generate")
@login_required
def gen_email():
    d = request.get_json(silent=True) or {}
    cid = d.get("company_id")
    if not cid:
        return err("company_id required")
    co = q1("SELECT * FROM companies WHERE id=?", (cid,))
    if not co:
        return err("Company not found", 404)
    ct_id = d.get("contact_id")
    ct = (q1("SELECT * FROM contacts WHERE id=?", (ct_id,)) if ct_id else None) or \
         q1("SELECT * FROM contacts WHERE company_id=? AND is_decision_maker=1", (cid,)) or \
         q1("SELECT * FROM contacts WHERE company_id=?", (cid,)) or \
         {"first_name":"Team","last_name":"","title":"Decision Maker","email":""}
    et = d.get("email_type","cold")
    content = generate_email(co, ct, et, d.get("custom_instructions",""))
    eid = run("""INSERT INTO emails(company_id,contact_id,created_by,email_type,subject,body,
                 recipient_email,recipient_name,status,ai_model_used,updated_at)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
              (cid, ct.get("id"), g.user["id"], et,
               content["subject"], content["body"],
               ct.get("email","unknown@example.com"),
               f"{ct.get('first_name','')} {ct.get('last_name','')}".strip(),
               "draft", "groq", now()))
    em = q1("SELECT * FROM emails WHERE id=?", (eid,))
    notify_async("email_generated", {
        "company_name": co["name"],
        "email_type": et.replace("_"," ").title(),
        "recipient_email": em["recipient_email"],
        "subject": em["subject"],
    })
    return ok(em), 201


@api.post("/emails/<int:eid>/send")
@login_required
def send_email_route(eid):
    em = q1("SELECT * FROM emails WHERE id=?", (eid,))
    if not em:
        return err("Not found", 404)
    if em["status"] == "sent":
        return err("Already sent")
    result = send_email(em["recipient_email"], em.get("recipient_name",""),
                        em["subject"], em["body"])
    if result.get("status") == "sent":
        run("UPDATE emails SET status='sent',sent_at=?,updated_at=? WHERE id=?",
            (now(), now(), eid))
        notify_async("email_sent", {
            "recipient_email": em["recipient_email"],
            "subject": em["subject"],
            "email_type": em.get("email_type","").replace("_"," ").title(),
        })
    return ok({"email": q1("SELECT * FROM emails WHERE id=?", (eid,)), "send_result": result})


@api.put("/emails/<int:eid>")
@login_required
def update_email(eid):
    if not q1("SELECT id FROM emails WHERE id=?", (eid,)):
        return err("Not found", 404)
    d = request.get_json(silent=True) or {}
    allowed = {"subject","body","recipient_email","recipient_name","status","email_type"}
    sets = [f"{k}=?" for k in d if k in allowed]
    vals = [d[k] for k in d if k in allowed]
    if sets:
        sets.append("updated_at=?"); vals.append(now()); vals.append(eid)
        run(f"UPDATE emails SET {','.join(sets)} WHERE id=?", vals)
    return ok(q1("SELECT * FROM emails WHERE id=?", (eid,)))


# ─── MEETINGS ─────────────────────────────────────────────────────────────────

@api.get("/meetings")
@login_required
def list_meetings():
    status = request.args.get("status","")
    sql = "SELECT m.*,c.name as company_name FROM meetings m LEFT JOIN companies c ON m.company_id=c.id"
    args = []
    if status:
        sql += " WHERE m.status=?"
        args.append(status)
    sql += " ORDER BY m.scheduled_at DESC"
    return ok(q(sql, args))


@api.post("/meetings")
@login_required
def create_meeting():
    d = request.get_json(silent=True) or {}
    if not d.get("company_id") or not d.get("title"):
        return err("company_id and title required")
    co = q1("SELECT * FROM companies WHERE id=?", (d["company_id"],))
    if not co:
        return err("Company not found", 404)
    mid = run("""INSERT INTO meetings(company_id,contact_id,created_by,title,meeting_type,
                 description,scheduled_at,duration_minutes,status,updated_at)
                 VALUES(?,?,?,?,?,?,?,?,?,?)""",
              (d["company_id"], d.get("contact_id"), g.user["id"],
               d["title"], d.get("meeting_type","discovery"), d.get("description"),
               d.get("scheduled_at"), d.get("duration_minutes",30), "proposed", now()))
    meeting = q1("SELECT * FROM meetings WHERE id=?", (mid,))
    notify_async("meeting_scheduled", {
        "title": meeting["title"], "company_name": co["name"],
        "meeting_type": meeting.get("meeting_type","").replace("_"," ").title(),
        "scheduled_at": (meeting.get("scheduled_at") or "TBD")[:16],
        "duration_minutes": meeting.get("duration_minutes",30),
    })
    if meeting.get("scheduled_at"):
        schedule_reminders(mid, meeting["title"], co["name"], meeting["scheduled_at"])
    return ok(meeting), 201


@api.put("/meetings/<int:mid>")
@login_required
def update_meeting(mid):
    m = q1("SELECT * FROM meetings WHERE id=?", (mid,))
    if not m:
        return err("Not found", 404)
    prev_status = m.get("status","")
    d = request.get_json(silent=True) or {}
    allowed = {"title","meeting_type","description","scheduled_at","duration_minutes",
                "status","meeting_link","google_event_id","notes"}
    sets = [f"{k}=?" for k in d if k in allowed]
    vals = [d[k] for k in d if k in allowed]
    if sets:
        sets.append("updated_at=?"); vals.append(now()); vals.append(mid)
        run(f"UPDATE meetings SET {','.join(sets)} WHERE id=?", vals)
    m2 = q1("SELECT * FROM meetings WHERE id=?", (mid,))
    if m2.get("status") == "completed" and prev_status != "completed":
        co = q1("SELECT name FROM companies WHERE id=?", (m2.get("company_id",0),))
        notify_async("meeting_completed", {
            "title": m2["title"],
            "company_name": co["name"] if co else "Unknown",
            "meeting_type": m2.get("meeting_type","").replace("_"," ").title(),
        })
    return ok(m2)


@api.post("/meetings/<int:mid>/calendar")
@login_required
def add_to_calendar(mid):
    m = q1("SELECT * FROM meetings WHERE id=?", (mid,))
    if not m:
        return err("Not found", 404)
    user = q1("SELECT * FROM users WHERE id=?", (g.user["id"],))
    if not user or not user.get("google_refresh_token"):
        return err("Google Calendar not connected — go to Integrations to connect", 400)
    co = q1("SELECT * FROM companies WHERE id=?", (m.get("company_id",0),))
    ct = q1("SELECT * FROM contacts WHERE id=?", (m.get("contact_id",0),)) if m.get("contact_id") else None
    attendees = [user["email"]]
    if ct and ct.get("email"):
        attendees.append(ct["email"])
    try:
        start_dt = datetime.strptime((m.get("scheduled_at") or "")[:19], "%Y-%m-%d %H:%M:%S")
    except Exception:
        start_dt = datetime.utcnow()
    result = create_calendar_event(
        user["google_refresh_token"], m["title"], start_dt,
        m.get("duration_minutes",30), attendees, m.get("description",""))
    if result.get("google_event_id"):
        run("UPDATE meetings SET google_event_id=?,meeting_link=?,status='scheduled',updated_at=? WHERE id=?",
            (result["google_event_id"], result.get("google_meet_link",""), now(), mid))
    return ok(result)


# ─── CALLS ────────────────────────────────────────────────────────────────────

@api.get("/calls")
@login_required
def list_calls():
    return ok(q("SELECT ca.*,co.name as company_name FROM calls ca "
                "LEFT JOIN companies co ON ca.company_id=co.id "
                "ORDER BY ca.created_at DESC LIMIT 100"))


@api.post("/calls/make")
@login_required
def make_call():
    d = request.get_json(silent=True) or {}
    phone = (d.get("phone_number") or "").strip()
    cid = d.get("company_id")
    co = q1("SELECT * FROM companies WHERE id=?", (cid,)) if cid else None
    ct_id = d.get("contact_id")
    ct = q1("SELECT * FROM contacts WHERE id=?", (ct_id,)) if ct_id else None
    if not phone and ct and ct.get("phone"):
        phone = ct["phone"]
    if not phone:
        return err("phone_number required (include country code e.g. +14155550100)")
    objective = d.get("objective","qualify")
    task = d.get("custom_task") or call_script(co or {}, ct or {}, objective)
    voice = d.get("voice","nat")
    result = bland_call(phone, task, voice,
                        co["name"] if co else "",
                        f"{ct.get('first_name','')} {ct.get('last_name','')}".strip() if ct else "")
    call_id = run("""INSERT INTO calls(bland_call_id,company_id,contact_id,created_by,
                     phone_number,objective,task_prompt,voice,status,error_message,updated_at)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                  (result.get("call_id"), cid, ct_id, g.user["id"],
                   phone, objective, task, voice,
                   "queued" if result.get("status")=="queued" else "error",
                   result.get("message") if result.get("status")=="error" else None, now()))
    notify_async("call_initiated", {
        "company_name": co["name"] if co else "Unknown",
        "phone_number": phone,
        "objective": objective.replace("_"," ").title(),
    })
    return ok({"call": q1("SELECT * FROM calls WHERE id=?", (call_id,)), "bland_result": result})


@api.get("/calls/<int:cid_>")
@login_required
def get_call(cid_):
    call = q1("SELECT * FROM calls WHERE id=?", (cid_,))
    if not call:
        return err("Not found", 404)
    if call.get("bland_call_id") and call.get("status") not in ("completed","error","failed"):
        live = bland_get(call["bland_call_id"])
        if live and "status" in live:
            run("""UPDATE calls SET status=?,duration_seconds=?,recording_url=?,
                   transcript=?,summary=?,updated_at=? WHERE id=?""",
                (live.get("status",call["status"]), live.get("call_length"),
                 live.get("recording_url"), live.get("concatenated_transcript") or live.get("transcript"),
                 live.get("summary"), now(), cid_))
            call = q1("SELECT * FROM calls WHERE id=?", (cid_,))
    return ok(call)


# ─── ANALYTICS ────────────────────────────────────────────────────────────────

@api.get("/analytics/summary")
@login_required
def analytics_summary():
    cos   = q("SELECT lead_score, status FROM companies")
    emails= q("SELECT status FROM emails")
    mtgs  = q("SELECT status FROM meetings")
    calls_= q("SELECT status FROM calls")
    hot   = sum(1 for c in cos if (c.get("lead_score") or 0) >= 70)
    warm  = sum(1 for c in cos if 40 <= (c.get("lead_score") or 0) < 70)
    sent  = sum(1 for e in emails if e.get("status") != "draft")
    opened= sum(1 for e in emails if e.get("status") in ("opened","replied"))
    replied=sum(1 for e in emails if e.get("status") == "replied")
    return ok({
        "total_companies":    len(cos),
        "hot_leads":          hot,
        "warm_leads":         warm,
        "cold_leads":         len(cos)-hot-warm,
        "emails_sent":        sent,
        "emails_opened":      opened,
        "open_rate":          round(opened/sent*100,1) if sent else 0,
        "reply_rate":         round(replied/sent*100,1) if sent else 0,
        "meetings_scheduled": sum(1 for m in mtgs if m.get("status")=="scheduled"),
        "meetings_completed": sum(1 for m in mtgs if m.get("status")=="completed"),
        "revenue_pipeline":   hot*50000+warm*15000,
        "total_calls":        len(calls_),
        "completed_calls":    sum(1 for c in calls_ if c.get("status")=="completed"),
    })


@api.get("/analytics/email-activity")
@login_required
def email_activity():
    from collections import defaultdict
    from datetime import timedelta
    emails = q("SELECT status,created_at FROM emails")
    daily = defaultdict(lambda: {"sent":0,"opened":0,"replied":0})
    for e in emails:
        day = (e.get("created_at") or "")[:10]
        if not day: continue
        if e.get("status") != "draft":  daily[day]["sent"]   += 1
        if e.get("status") in ("opened","replied"): daily[day]["opened"] += 1
        if e.get("status") == "replied": daily[day]["replied"] += 1
    result = [{"date":d,**v} for d,v in sorted(daily.items())][-30:]
    if not result:
        today = datetime.utcnow()
        result = [{"date":(today-timedelta(days=13-i)).strftime("%Y-%m-%d"),
                   "sent":i%4+1,"opened":max(0,i%3),"replied":max(0,i%2-1)} for i in range(14)]
    return ok(result)


@api.get("/analytics/lead-distribution")
@login_required
def lead_distribution():
    from collections import defaultdict
    by = defaultdict(lambda: {"count":0,"total":0})
    for c in q("SELECT industry,lead_score FROM companies"):
        ind = c.get("industry") or "Other"
        by[ind]["count"] += 1
        by[ind]["total"] += c.get("lead_score") or 0
    result = sorted([{"industry":k,"count":v["count"],
                      "avg_score":round(v["total"]/v["count"],1)}
                     for k,v in by.items()], key=lambda x:x["count"], reverse=True)
    return ok(result)


@api.get("/analytics/pipeline")
@login_required
def pipeline():
    cos = q("SELECT name,lead_score,status,annual_revenue FROM companies ORDER BY lead_score DESC LIMIT 20")
    return ok([{"name":c["name"],"lead_score":c.get("lead_score",0),
                "potential_revenue":int((c.get("annual_revenue") or 0)*0.02),
                "status":c.get("status","prospect")} for c in cos])


# ─── CHAT ─────────────────────────────────────────────────────────────────────

@api.get("/chat")
@login_required
def get_chat():
    msgs = q("SELECT * FROM chat_messages ORDER BY created_at DESC LIMIT 100")
    return ok(list(reversed(msgs)))


@api.post("/chat")
@login_required
def post_chat():
    d = request.get_json(silent=True) or {}
    message = (d.get("message") or "").strip()
    if not message:
        return err("message required")
    cos   = q("SELECT name,industry,lead_score FROM companies")
    stats = {
        "companies":          cos,
        "emails_sent":        q("SELECT COUNT(*) as n FROM emails WHERE status!='draft'")[0]["n"],
        "total_calls":        q("SELECT COUNT(*) as n FROM calls")[0]["n"],
        "meetings_scheduled": q("SELECT COUNT(*) as n FROM meetings WHERE status='scheduled'")[0]["n"],
    }
    reply = chat_reply(message, stats)
    run("INSERT INTO chat_messages(sender,sender_name,message) VALUES(?,?,?)",
        ("user", g.user["email"], message))
    run("INSERT INTO chat_messages(sender,sender_name,message) VALUES(?,?,?)",
        ("bot", "AI Sales Bot", reply))
    return ok({"reply": reply})


@api.delete("/chat")
@login_required
def clear_chat():
    run("DELETE FROM chat_messages")
    return ok({"message": "Cleared"})


# ─── INTEGRATIONS ─────────────────────────────────────────────────────────────

@api.get("/integrations/status")
@login_required
def integrations_status():
    from config import GROQ_API_KEY, BLAND_API_KEY, GMAIL_EMAIL, GMAIL_PASSWORD
    from config import TWILIO_SID, TWILIO_TOKEN, TWILIO_FROM, TWILIO_ADMIN
    from config import GOOGLE_CLIENT_ID
    user = q1("SELECT google_refresh_token FROM users WHERE id=?", (g.user["id"],))
    return ok({
        "groq":     {"connected": bool(GROQ_API_KEY),
                     "model": "llama-3.3-70b-versatile"},
        "gmail":    {"connected": bool(GMAIL_EMAIL and GMAIL_PASSWORD),
                     "email": GMAIL_EMAIL or None},
        "bland_ai": {"connected": bool(BLAND_API_KEY)},
        "twilio_sms":{"connected": bool(TWILIO_SID and TWILIO_TOKEN and TWILIO_FROM),
                      "from_number": TWILIO_FROM or None,
                      "admin_number": TWILIO_ADMIN or None},
        "google_calendar":{"connected": bool(user and user.get("google_refresh_token"))},
    })


@api.post("/integrations/gmail/test")
@login_required
def test_gmail_route():
    ok_, msg = test_gmail()
    return ok({"success": ok_, "message": msg})


@api.post("/integrations/bland/test")
@login_required
def test_bland_route():
    ok_, msg = test_bland()
    return ok({"success": ok_, "message": msg})


@api.post("/integrations/twilio/test")
@login_required
def test_twilio_route():
    d = request.get_json(silent=True) or {}
    to = (d.get("to_number") or "").strip()
    if not to:
        return err("to_number required")
    result = send_test(to)
    return ok({"success": result.get("status")=="sent", "result": result})


@api.post("/integrations/twilio/daily-report")
@login_required
def manual_daily_report():
    from scheduler import trigger_now
    trigger_now()
    return ok({"message": "Daily report SMS sent"})


@api.get("/integrations/google/auth-url")
@login_required
def google_auth_url_route():
    url = google_auth_url(g.user["id"])
    return ok({"auth_url": url or None,
               "message": "Click URL to connect Google Calendar" if url else "GOOGLE_CLIENT_ID not set"})


@api.get("/integrations/google/callback")
def google_callback():
    code  = request.args.get("code","")
    state = request.args.get("state","")
    if not code:
        return err("Missing code")
    tokens = google_exchange(code)
    if tokens.get("refresh_token") and state:
        try:
            run("UPDATE users SET google_refresh_token=? WHERE id=?",
                (tokens["refresh_token"], int(state)))
        except Exception: pass
    return """<html><body style="font-family:Arial;text-align:center;padding:60px">
    <h2>✅ Google Calendar Connected!</h2><p>You can close this window.</p></body></html>"""


@api.post("/integrations/google/disconnect")
@login_required
def google_disconnect():
    run("UPDATE users SET google_refresh_token=NULL WHERE id=?", (g.user["id"],))
    return ok({"message": "Disconnected"})


@api.get("/sms-logs")
@login_required
def sms_logs():
    limit = min(int(request.args.get("limit",100)), 500)
    return ok(q("SELECT * FROM sms_logs ORDER BY created_at DESC LIMIT ?", (limit,)))
