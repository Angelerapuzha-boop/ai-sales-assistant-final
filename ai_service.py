"""ai_service.py — Groq llama-3.3-70b with template fallback (never crashes)."""
import json, re, logging, urllib.request, urllib.error
from config import GROQ_API_KEY, GROQ_MODEL, GMAIL_NAME

logger = logging.getLogger("sales.ai")


def _groq(prompt: str, system: str = None, max_tokens: int = 700) -> str:
    if not GROQ_API_KEY:
        return None
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": prompt})
    body = json.dumps({"model": GROQ_MODEL, "messages": msgs,
                       "max_tokens": max_tokens, "temperature": 0.7}).encode()
    try:
        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/chat/completions", data=body,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.loads(r.read())["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.warning(f"Groq error: {e}")
        return None


def company_summary(company: dict) -> str:
    techs = company.get("technologies", "")
    if isinstance(techs, str):
        try: techs = ", ".join(json.loads(techs))
        except: pass
    rev = company.get('annual_revenue') or 0
    emp = company.get('employee_count') or 'N/A'
    p = (f"Write a 2-sentence B2B sales intelligence summary for {company['name']}, "
         f"{company.get('industry','tech')}, {emp} employees, "
         f"${rev:,} revenue, tech: {techs}. Be actionable.")
    result = _groq(p, "B2B sales intelligence expert. Be concise.", 180)
    return result or (
        f"{company['name']} is a leading {company.get('industry','technology')} company with "
        f"{company.get('employee_count','N/A')} employees. "
        f"Strong candidate for AI-powered sales automation.")


def generate_email(company: dict, contact: dict, email_type: str, custom: str = "") -> dict:
    name = f"{contact.get('first_name','Team')} {contact.get('last_name','')}".strip()
    sender = GMAIL_NAME or "AI Sales Team"
    prompts = {
        "cold": f"Write a cold B2B sales email to {name}, {contact.get('title','Decision Maker')} at "
                f"{company['name']} ({company.get('industry','tech')}). "
                f"Product: AI Sales Assistant. {custom}\nFormat:\nSUBJECT: ...\nBODY:\n...",
        "follow_up": f"Write a short follow-up to {name} at {company['name']} — no reply yet.\n"
                     f"Format:\nSUBJECT: ...\nBODY:\n...",
        "meeting_request": f"Write a meeting request to {name} at {company['name']} for 15-min call. "
                           f"Include 3 time slots.\nFormat:\nSUBJECT: ...\nBODY:\n...",
    }
    result = _groq(prompts.get(email_type, prompts["cold"]),
                   "Expert B2B sales copywriter. Concise and persuasive.", 480)
    if result:
        subj, body_lines, in_body = "", [], False
        for line in result.strip().split("\n"):
            if line.upper().startswith("SUBJECT:"):
                subj = line.split(":", 1)[1].strip()
            elif line.upper().strip() == "BODY:":
                in_body = True
            elif in_body:
                body_lines.append(line)
        if subj and body_lines:
            return {"subject": subj, "body": "\n".join(body_lines).strip()}

    templates = {
        "cold": {
            "subject": f"Helping {company['name']} automate sales prospecting",
            "body": f"Hi {name},\n\nI noticed {company['name']} is scaling fast in {company.get('industry','tech')}.\n\n"
                    f"We help companies like yours cut 10+ hours/week of manual sales work with our AI Sales Assistant — "
                    f"it auto-scores leads, writes personalised emails, and forecasts your pipeline.\n\n"
                    f"Would a 15-min call make sense this week?\n\nBest,\n{sender}",
        },
        "follow_up": {
            "subject": f"Following up — {company['name']} + AI Sales",
            "body": f"Hi {name},\n\nJust resurfacing my earlier note.\n\n"
                    f"If improving sales efficiency is on your radar, I'd love to show a quick demo for {company['name']}.\n\n"
                    f"Any availability this month?\n\nThanks,\n{sender}",
        },
        "meeting_request": {
            "subject": f"15 min — AI Sales demo for {company['name']}?",
            "body": f"Hi {name},\n\nI'd love to show how {company['name']} could save time on prospecting.\n\n"
                    f"📅 Three slots:\n• Tuesday 10:00 AM EST\n• Wednesday 2:00 PM EST\n• Thursday 11:00 AM EST\n\n"
                    f"Does any work?\n\nBest,\n{sender}",
        },
    }
    return templates.get(email_type, templates["cold"])


def buying_signals(company: dict) -> list:
    techs = company.get("technologies", "")
    if isinstance(techs, str):
        try: techs = ", ".join(json.loads(techs))
        except: pass
    p = (f"Generate 3 B2B buying signals for {company.get('name','')}, {company.get('industry','')}, "
         f"{company.get('employee_count','')} employees, ${company.get('annual_revenue',0):,} revenue. "
         f'Return ONLY JSON array: [{{"type":"...","name":"...","description":"...","strength":7}}]')
    result = _groq(p, "B2B sales AI. Return valid JSON array only.", 280)
    if result:
        try:
            m = re.search(r'\[.*\]', result, re.DOTALL)
            if m:
                return json.loads(m.group())
        except Exception:
            pass
    # fallback
    signals = []
    if (company.get("employee_count") or 0) > 100:
        signals.append({"type":"scale","name":"Enterprise Scale","description":"Company size indicates budget authority","strength":7})
    if (company.get("annual_revenue") or 0) > 1_000_000:
        signals.append({"type":"revenue","name":"Strong Revenue","description":"Revenue supports investment in tools","strength":8})
    if company.get("technologies"):
        signals.append({"type":"tech","name":"Tech-Forward","description":"Active tech stack signals openness","strength":6})
    return signals or [{"type":"prospect","name":"New Prospect","description":"Standard signals","strength":5}]


def call_script(company: dict, contact: dict, objective: str = "qualify") -> str:
    name = f"{contact.get('first_name','there')} {contact.get('last_name','')}".strip()
    p = (f"Write a concise AI phone call script to {name} at {company.get('name','the company')}. "
         f"Objective: {objective}. Include greeting, value prop, 2 discovery questions, CTA. Under 200 words.")
    result = _groq(p, "Expert B2B sales caller. Natural and concise.", 350)
    return result or (
        f"Hi, may I speak with {name}? ... Hi {name}, calling from AI Sales — "
        f"we help {company.get('industry','technology')} companies automate prospecting. "
        f"Quick question: how does your team currently handle lead qualification? "
        f"We've helped similar companies cut that time by 70%. Worth a 15-min demo this week?")


def chat_reply(message: str, stats: dict) -> str:
    cmd = message.lower().strip()
    cos  = stats.get("companies", [])
    sent = stats.get("emails_sent", 0)
    calls= stats.get("total_calls", 0)
    mtgs = stats.get("meetings_scheduled", 0)

    if any(w in cmd for w in ["show leads","top leads","best leads","hot leads"]):
        top = sorted(cos, key=lambda x: x.get("lead_score",0), reverse=True)[:5]
        lines = ["🔥 Top Leads:\n"]
        for i,c in enumerate(top,1):
            s=c.get("lead_score",0)
            t="🔥" if s>=70 else "🟡" if s>=40 else "❄️"
            lines.append(f"{i}. {t} {c['name']} — {s}/100 ({c.get('industry','N/A')})")
        return "\n".join(lines)

    if any(w in cmd for w in ["analytics","stats","metrics","kpi","numbers"]):
        hot=sum(1 for c in cos if c.get("lead_score",0)>=70)
        warm=sum(1 for c in cos if 40<=c.get("lead_score",0)<70)
        return (f"📊 Analytics Summary\n\n"
                f"🏢 Companies: {len(cos)} | 🔥 Hot: {hot} | 🟡 Warm: {warm}\n"
                f"📧 Emails sent: {sent}\n📞 Calls: {calls}\n📅 Meetings: {mtgs}\n"
                f"💰 Pipeline: ${hot*50000+warm*15000:,}")

    if any(w in cmd for w in ["pipeline","revenue","forecast"]):
        hot=sum(1 for c in cos if c.get("lead_score",0)>=70)
        warm=sum(1 for c in cos if 40<=c.get("lead_score",0)<70)
        return (f"💰 Revenue Pipeline\n\n"
                f"🔥 {hot} hot × $50k = ${hot*50000:,}\n"
                f"🟡 {warm} warm × $15k = ${warm*15000:,}\n"
                f"📊 Total: ${hot*50000+warm*15000:,}")

    if any(w in cmd for w in ["help","hi","hello","hey","start","commands"]):
        return ("👋 AI Sales Assistant\n\n"
                "Commands:\n"
                "📊 analytics — Key metrics\n"
                "🔥 show leads — Top scored leads\n"
                "💰 pipeline — Revenue forecast\n"
                "📋 daily report — Full summary\n"
                "❓ help — This menu\n\n"
                f"AI: {'🟢 Groq Active' if GROQ_API_KEY else '🟡 Template Mode'}")

    # freeform AI
    top5 = sorted(cos, key=lambda x: x.get("lead_score",0), reverse=True)[:5]
    summary = "\n".join([f"- {c['name']}: score={c.get('lead_score',0)}" for c in top5])
    p = (f"You are an AI sales assistant. Answer in 2-3 sentences using this data:\n"
         f"{len(cos)} companies, top:\n{summary}\n{sent} emails sent, {calls} calls, {mtgs} meetings.\n"
         f"Question: {message}")
    result = _groq(p, "Friendly concise AI sales assistant.", 180)
    return result or "🤔 Try: `show leads`, `analytics`, `pipeline`, or `help`"
