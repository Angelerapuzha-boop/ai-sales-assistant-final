"""Pure sqlite3 database — zero external dependencies. Uses /tmp on Render."""
import sqlite3, os, json, logging
from contextlib import contextmanager
from datetime import datetime, timedelta

logger = logging.getLogger("sales.db")

def _get_path():
    from config import DB_PATH
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    return DB_PATH

def _connect():
    p = _get_path()
    conn = sqlite3.connect(p, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

@contextmanager
def get_conn():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def q(sql, args=()):
    with get_conn() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]

def q1(sql, args=()):
    with get_conn() as c:
        r = c.execute(sql, args).fetchone()
        return dict(r) if r else None

def run(sql, args=()):
    with get_conn() as c:
        return c.execute(sql, args).lastrowid

def now():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

def init_db():
    with get_conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            full_name TEXT NOT NULL,
            password TEXT NOT NULL,
            role TEXT DEFAULT 'sales_rep',
            is_active INTEGER DEFAULT 1,
            google_refresh_token TEXT,
            last_login TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            industry TEXT,
            employee_count INTEGER,
            annual_revenue INTEGER,
            website TEXT,
            city TEXT,
            country TEXT,
            description TEXT,
            technologies TEXT,
            status TEXT DEFAULT 'prospect',
            lead_score INTEGER DEFAULT 0,
            ai_summary TEXT,
            linkedin_url TEXT,
            funding_stage TEXT,
            created_by INTEGER,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
            first_name TEXT NOT NULL,
            last_name TEXT,
            email TEXT,
            phone TEXT,
            title TEXT,
            department TEXT,
            seniority_level TEXT DEFAULT 'individual',
            is_decision_maker INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS emails (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
            contact_id INTEGER,
            created_by INTEGER,
            email_type TEXT DEFAULT 'cold',
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            recipient_email TEXT NOT NULL,
            recipient_name TEXT,
            status TEXT DEFAULT 'draft',
            sent_at TEXT,
            ai_model_used TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS meetings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
            contact_id INTEGER,
            created_by INTEGER,
            title TEXT NOT NULL,
            meeting_type TEXT DEFAULT 'discovery',
            description TEXT,
            scheduled_at TEXT,
            duration_minutes INTEGER DEFAULT 30,
            status TEXT DEFAULT 'proposed',
            meeting_link TEXT,
            google_event_id TEXT,
            notes TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bland_call_id TEXT,
            company_id INTEGER,
            contact_id INTEGER,
            created_by INTEGER,
            phone_number TEXT NOT NULL,
            objective TEXT DEFAULT 'qualify',
            task_prompt TEXT,
            voice TEXT DEFAULT 'nat',
            status TEXT DEFAULT 'queued',
            duration_seconds INTEGER,
            recording_url TEXT,
            transcript TEXT,
            summary TEXT,
            error_message TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS lead_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER UNIQUE REFERENCES companies(id) ON DELETE CASCADE,
            total_score INTEGER DEFAULT 0,
            revenue_score INTEGER DEFAULT 0,
            employee_score INTEGER DEFAULT 0,
            industry_score INTEGER DEFAULT 0,
            buying_signal_score INTEGER DEFAULT 0,
            department_signal_score INTEGER DEFAULT 0,
            email_activity_score INTEGER DEFAULT 0,
            tier TEXT DEFAULT 'cold',
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS buying_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
            signal_type TEXT NOT NULL,
            signal_name TEXT NOT NULL,
            signal_description TEXT,
            strength INTEGER DEFAULT 5,
            source TEXT DEFAULT 'ai',
            detected_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS sms_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            to_number TEXT NOT NULL,
            from_number TEXT,
            body TEXT NOT NULL,
            status TEXT DEFAULT 'sent',
            event_type TEXT,
            error_msg TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT NOT NULL,
            sender_name TEXT,
            message TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );
        """)
    logger.info("✅ DB tables ready")
    _seed()

def _seed():
    import hashlib
    from config import SECRET_KEY
    if q1("SELECT 1 FROM users WHERE email='admin@salesai.com'"):
        return
    pw = hashlib.sha256(("Admin@123456" + SECRET_KEY).encode()).hexdigest()
    admin_id = run("INSERT INTO users(email,full_name,password,role) VALUES(?,?,?,?)",
                   ("admin@salesai.com", "System Admin", pw, "admin"))
    demos = [
        ("Stripe","FinTech",4000,7500000000,"stripe.com","San Francisco","USA",91,"opportunity",'["Python","Go","React"]'),
        ("Notion","SaaS",400,300000000,"notion.so","San Francisco","USA",78,"qualified",'["TypeScript","React"]'),
        ("Vercel","Technology",350,200000000,"vercel.com","San Francisco","USA",74,"prospect",'["Next.js","Rust"]'),
        ("Figma","Design",1000,400000000,"figma.com","San Francisco","USA",85,"qualified",'["C++","WebAssembly"]'),
        ("Linear","Software",80,50000000,"linear.app","San Francisco","USA",62,"prospect",'["TypeScript"]'),
        ("Retool","SaaS",300,100000000,"retool.com","San Francisco","USA",55,"prospect",'["React","Node.js"]'),
        ("PlanetScale","Database",150,60000000,"planetscale.com","San Mateo","USA",38,"cold",'["MySQL","Go"]'),
        ("Loom","Technology",200,80000000,"loom.com","San Francisco","USA",44,"prospect",'["React","WebRTC"]'),
        ("Airtable","SaaS",800,350000000,"airtable.com","San Francisco","USA",82,"opportunity",'["React","AWS"]'),
        ("Miro","Software",1500,400000000,"miro.com","Amsterdam","Netherlands",77,"qualified",'["React","Kubernetes"]'),
    ]
    phones = ["+14155550100","+14155550101","+14155550102","+14155550103","+14155550104",
              "+14155550105","+14155550106","+14155550107","+14155550108","+31201234567"]
    for (name,ind,emp,rev,web,city,country,score,status,techs), phone in zip(demos, phones):
        cid = run("""INSERT INTO companies(name,industry,employee_count,annual_revenue,website,
                     city,country,lead_score,status,technologies,created_by,description)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (name,ind,emp,rev,web,city,country,score,status,techs,admin_id,f"Leading {ind} company"))
        run("""INSERT INTO contacts(company_id,first_name,last_name,email,phone,title,
               department,seniority_level,is_decision_maker) VALUES(?,?,?,?,?,?,?,?,?)""",
            (cid,"Alex","Johnson",f"alex@{web}",phone,"VP of Engineering","Engineering","vp",1))
        run("""INSERT INTO lead_scores(company_id,total_score,revenue_score,employee_score,
               industry_score,buying_signal_score,department_signal_score,email_activity_score,tier)
               VALUES(?,?,80,70,80,75,60,50,?)""",
            (cid, score, "hot" if score>=70 else "warm" if score>=40 else "cold"))
        run("""INSERT INTO buying_signals(company_id,signal_type,signal_name,signal_description,strength,source)
               VALUES(?,?,?,?,?,?)""",
            (cid,"hiring","Rapid Hiring","20+ open engineering roles",8,"demo"))
    cids = [r["id"] for r in q("SELECT id FROM companies LIMIT 8")]
    for i,(cid,st,et) in enumerate(zip(cids,
        ["sent","sent","opened","replied","draft","sent","opened","sent"],
        ["cold","follow_up","meeting_request","cold","cold","follow_up","meeting_request","cold"])):
        run("""INSERT INTO emails(company_id,created_by,email_type,subject,body,
               recipient_email,recipient_name,status,ai_model_used)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (cid,admin_id,et,"Quick question about your growth strategy",
             "Hi Alex,\n\nI noticed your company is scaling fast.\n\nWe help companies automate sales with AI. Worth a 15-min call?\n\nBest,\nAI Sales Team",
             f"alex@demo{i}.com","Alex Johnson",st,"groq"))
    for i,(t,mt) in enumerate([("Discovery Call","discovery"),("Product Demo","demo"),
                                ("Follow-up","follow_up"),("Negotiation","negotiation")]):
        sched = (datetime.utcnow() + timedelta(days=i+1)).strftime("%Y-%m-%d %H:%M:%S")
        run("""INSERT INTO meetings(company_id,created_by,title,meeting_type,scheduled_at,duration_minutes,status)
               VALUES(?,?,?,?,?,?,?)""",
            (cids[i % len(cids)],admin_id,t,mt,sched,30,"scheduled"))
    logger.info("✅ Demo data seeded: 10 companies, 8 emails, 4 meetings")
