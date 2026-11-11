"""Mamta backend — FastAPI.  Run:  uvicorn main:app --reload --port 8000
All prompts, schemas and API keys stay on the server. The Flutter app only talks to these endpoints
(and listens to Firestore `alerts` for live updates)."""
import base64
import json
import logging
import os
from datetime import date, datetime
from typing import List, Optional

from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")  # works no matter which folder you start from

from fastapi import FastAPI, File, Form, HTTPException, UploadFile  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import RedirectResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

import gemini_client as gem  # noqa: E402
import prompts  # noqa: E402
import seed as seed_mod  # noqa: E402
import triage_rules  # noqa: E402
import tts  # noqa: E402
from firestore_db import db, now_iso  # noqa: E402
from schemas import RegisterConfirm, ReportRequest, TriageResult, VisitConfirm  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("mamta")

app = FastAPI(title="Mamta API", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
# Web version of the app (no build step): http://localhost:8000/app/
app.mount("/app", StaticFiles(directory=Path(__file__).parent / "web", html=True), name="web")


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/app/")

VISIT_SCHEDULE = [1, 3, 7, 42]  # Pakistan / WHO postnatal contact days
RISK_RANK = {"red": 3, "yellow": 2, "green": 1}

FLAG_LABELS = {
    "heavy_bleeding": "Heavy bleeding", "fits": "Fits / convulsions",
    "severe_headache_vision": "Severe headache / blurred vision",
    "fever_foul_discharge": "Fever / foul discharge", "breathlessness": "Breathlessness / chest pain",
    "breast_pain": "Breast pain / redness", "painful_urination": "Painful urination",
    "wound_problem": "Wound pain / discharge", "low_mood": "Low mood / sadness", "mild_fever": "Mild fever",
    "baby_not_feeding": "Baby not feeding / floppy", "baby_fast_breathing": "Baby fast breathing",
    "baby_fits": "Baby fits", "baby_temperature": "Baby too hot / cold",
    "baby_jaundice_severe": "Baby yellow palms/soles", "baby_jaundice_mild": "Baby mild yellow face",
    "baby_weight": "Baby not gaining weight", "unsure": "Mother unsure — needs check",
}

AUDIO_MIME = {"wav": "audio/wav", "webm": "audio/webm", "m4a": "audio/mp4", "mp4": "audio/mp4",
              "aac": "audio/aac", "mp3": "audio/mp3", "ogg": "audio/ogg", "opus": "audio/ogg", "flac": "audio/flac"}


@app.on_event("startup")
def _startup():
    if db.kind == "memory":
        log.warning("In-memory DB: seeding demo data automatically")
        seed_mod.seed(db)


# ------------------------------------------------------------------ helpers
def _mime(upload: UploadFile, default: str) -> str:
    ct = (upload.content_type or "").lower()
    if ct and ct != "application/octet-stream":
        return ct.split(";")[0]
    ext = (upload.filename or "").rsplit(".", 1)[-1].lower()
    return AUDIO_MIME.get(ext, {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                                "webp": "image/webp", "heic": "image/heic"}.get(ext, default))


def _days_since(iso: Optional[str]) -> Optional[int]:
    if not iso:
        return None
    try:
        return (date.today() - date.fromisoformat(iso[:10])).days
    except ValueError:
        return None


def _mother_ctx(mother_id: str):
    mother = db.get("mothers", mother_id)
    if not mother:
        raise HTTPException(404, f"mother {mother_id} not found")
    lhw = db.get("lhws", mother.get("lhwId", "")) or {"name": "Lady Health Worker", "nameUr": "لیڈی ہیلتھ ورکر"}
    days = _days_since(mother.get("deliveryDate")) or 0
    ctx = {"days_postpartum": days, "baby_age_days": days,
           "lhw_name": lhw.get("nameUr") or lhw.get("name"), "mother_name": mother.get("name"),
           "today": date.today().isoformat()}
    return mother, lhw, ctx


def _reason(flags: List[str]) -> str:
    return ", ".join(FLAG_LABELS.get(f, f) for f in flags) or "Reported concern"


# ------------------------------------------------------------------ endpoints
@app.get("/health")
def health():
    return {"ok": True, "demoMode": gem.demo_mode(), "db": db.kind, "model": gem.MODEL,
            "geminiKey": bool(os.getenv("GEMINI_API_KEY")), "lastGeminiError": gem.LAST_ERROR}


@app.post("/demo/reset")
def demo_reset():
    return seed_mod.seed(db)


# ------------------------------------------------------------------ demo login
# Hackathon demo login: mother = registered phone number, LHW = phone + 4-digit PIN.
# (Production would use Firebase Authentication with phone OTP.)
def _norm_phone(p: str) -> str:
    d = "".join(ch for ch in (p or "") if ch.isdigit())
    if d.startswith("0"):
        d = "92" + d[1:]
    return d


@app.post("/auth/mother")
def auth_mother(body: dict):
    phone = _norm_phone(body.get("phone", ""))
    for m in db.all("mothers"):
        if phone and _norm_phone(m.get("phone") or "") == phone:
            return {"role": "mother", "id": m["id"], "name": m.get("name"), "nameUr": m.get("nameUr")}
    raise HTTPException(401, "Phone number not registered with any Lady Health Worker")


@app.post("/auth/lhw")
def auth_lhw(body: dict):
    phone, pin = _norm_phone(body.get("phone", "")), str(body.get("pin", ""))
    for l in db.all("lhws"):
        if _norm_phone(l.get("phone") or "") == phone and str(l.get("pin")) == pin:
            return {"role": "lhw", "id": l["id"], "name": l.get("name"), "area": l.get("area")}
    raise HTTPException(401, "Wrong phone number or PIN")


# ------------------------------------------------------------------ doctors & appointments
# SAMPLE directory created by the team for the demo (fictional doctors, not real listings).
DOCTORS = [
    {"id": "d1", "name": "Dr. Ayesha Malik (sample)", "specialty": "Gynaecologist / Obstetrician", "for": ["mother"],
     "clinic": "Mamta Women's Clinic", "address": "Main Murree Road, Bhara Kahu, Islamabad", "distanceKm": 1.2,
     "timings": "Mon–Sat 10:00–14:00", "fee": 1500, "phone": "+92510000001", "emergency": False,
     "hours": [(10,14)]},
    {"id": "d2", "name": "Dr. Sana Rehman (sample)", "specialty": "Gynaecologist", "for": ["mother"],
     "clinic": "Shifa Care Clinic", "address": "Simly Dam Road, Bhara Kahu", "distanceKm": 2.5,
     "timings": "Mon–Fri 17:00–21:00", "fee": 2000, "phone": "+92510000002", "emergency": False,
     "hours": [(17,21)]},
    {"id": "d3", "name": "Dr. Imran Qureshi (sample)", "specialty": "Paediatrician (newborn)", "for": ["baby"],
     "clinic": "Little Steps Child Clinic", "address": "Phulgran Chowk, Bhara Kahu", "distanceKm": 1.8,
     "timings": "Mon–Sat 09:00–13:00, 18:00–20:00", "fee": 1200, "phone": "+92510000003", "emergency": False,
     "hours": [(9,13),(18,20)]},
    {"id": "d4", "name": "Lady Medical Officer, Govt. BHU (sample)", "specialty": "General / maternal care", "for": ["mother", "baby"],
     "clinic": "Basic Health Unit Bhara Kahu", "address": "Near Union Council office, Bhara Kahu", "distanceKm": 0.9,
     "timings": "Mon–Sat 08:00–14:00", "fee": 0, "phone": "+92510000004", "emergency": False,
     "hours": [(8,14)]},
    {"id": "d5", "name": "24/7 Emergency — District Hospital (sample)", "specialty": "Emergency obstetric & newborn care", "for": ["mother", "baby"],
     "clinic": "District Hospital Emergency", "address": "Park Road, Islamabad", "distanceKm": 9.5,
     "timings": "Open 24 hours", "fee": 0, "phone": "1122", "emergency": True, "hours": []},
]
def _next_slots(hours, n=4, sunday_closed=True):
    """Next free 30-minute slots from the doctor's opening hours (today, then the next days)."""
    from datetime import datetime as _dt, timedelta as _td
    now, out = _dt.now(), []
    for day in range(0, 4):
        d = (now + _td(days=day)).replace(minute=0, second=0, microsecond=0)
        if sunday_closed and d.weekday() == 6:
            continue
        for start, end in hours:
            t = d.replace(hour=start)
            while t.hour < end and len(out) < n:
                if t > now + _td(minutes=30):
                    label = "Today" if day == 0 else ("Tomorrow" if day == 1 else t.strftime("%a %d %b"))
                    out.append(f"{label} {t.strftime('%I:%M %p').lstrip('0')}")
                t += _td(minutes=30 if day == 0 else 90)
        if len(out) >= n:
            break
    return out


BABY_FLAGS = {"baby_not_feeding", "baby_fast_breathing", "baby_fits", "baby_temperature", "baby_jaundice_severe",
              "baby_jaundice_mild", "baby_weight"}


@app.get("/doctors")
def doctors(triage: str = "green", flags: str = "", specialty: str = ""):
    fl = [f for f in flags.split(",") if f]
    who = "baby" if (specialty == "paediatrician" or (fl and all(f in BABY_FLAGS for f in fl))) else "mother"
    docs = [d for d in DOCTORS if who in d["for"]]
    if triage == "red":  # emergency first
        docs.sort(key=lambda d: (not d["emergency"], d["distanceKm"]))
    else:
        docs = [d for d in docs if not d["emergency"]]
        docs.sort(key=lambda d: d["distanceKm"])
    docs = [{**d, "slots": _next_slots(d["hours"]) if d["hours"] else ["Open now — go directly"]} for d in docs]
    return {"for": who, "doctors": docs, "note": "Sample directory for the demo"}


@app.post("/appointments")
def book(body: dict):
    doc = next((d for d in DOCTORS if d["id"] == body.get("doctorId")), None)
    if not doc:
        raise HTTPException(404, "doctor not found")
    mother = db.get("mothers", body.get("motherId", "")) or {}
    appt = {"motherId": body.get("motherId"), "motherName": mother.get("name"), "lhwId": mother.get("lhwId"),
            "doctorId": doc["id"], "doctorName": doc["name"], "clinic": doc["clinic"], "address": doc["address"],
            "slot": body.get("slot"), "fee": doc["fee"], "status": "booked", "createdAt": now_iso()}
    appt_id = db.add("appointments", appt)
    return {"ok": True, "id": appt_id, **appt}


@app.get("/mothers/{mother_id}/appointments")
def mother_appointments(mother_id: str):
    return sorted(db.where("appointments", "motherId", mother_id), key=lambda a: a.get("createdAt", ""), reverse=True)


@app.get("/mothers/{mother_id}")
def get_mother(mother_id: str):
    mother, lhw, ctx = _mother_ctx(mother_id)
    return {**mother, "daysPostpartum": ctx["days_postpartum"], "lhwName": lhw.get("name"),
            "lhwPhone": lhw.get("phone")}


def _run_checkin(mother_id: str, history_json: str, audio: Optional[bytes], mime: str, text: Optional[str]):
    mother, lhw, ctx = _mother_ctx(mother_id)
    try:
        history = json.loads(history_json or "[]")
    except json.JSONDecodeError:
        history = []

    source = "gemini"
    try:
        result = gem.triage_turn(ctx, history, audio=audio, mime=mime, text=text)
    except gem.GeminiUnavailable as e:
        mode = gem.demo_mode()
        first_turn = not any(h.get("role") == "mother" for h in history)
        if mode == "force" and audio and first_turn:
            # Stage insurance ONLY when Wi-Fi is dead (DEMO_MODE=force): replay the recorded demo turn
            source = "fixture"
            try:
                result = gem._load_fixture("checkin_audio", TriageResult)
            except FileNotFoundError:
                result = gem.offline_triage(ctx, history, "")
        elif text and mode in ("true", "force"):
            # Offline rule-based screening on her real words (same 6 questions, same order)
            source = "offline_rules"
            result = gem.offline_triage(ctx, history, text)
        elif audio:
            source = "fallback"
            result = TriageResult(reply_ur="معاف کیجیے، آواز سمجھ نہیں آئی۔ براہِ کرم دوبارہ بولیں یا لکھ کر بتائیں۔",
                                  done=False, triage="pending", flags=[], transcript_turn="", confidence=0.0)
        else:
            source = "fallback"
            result = TriageResult(reply_ur=prompts.FALLBACK_UR.format(**ctx), done=True, triage="yellow",
                                  flags=["unsure"], transcript_turn=text or "", confidence=0.0)
        log.warning("Gemini unavailable (%s) -> %s", e, source)
    finally:
        audio = None  # privacy: raw audio is never stored

    # Short path for minor complaints: one combined safety question, then finish (never for danger signs)
    prior_mother = [h.get("text", "") for h in history if h.get("role") == "mother"]
    latest = (text or result.transcript_turn or "").lower()
    denial = any(w in latest for w in ["nahi", "nahin", "نہیں", "kuch nahi", "theek", "ٹھیک", "no ", "none", "sab sahi", "خیریت"])
    if source == "gemini" and not result.done and not result.flags:
        if not prior_mother:
            r0 = result.reply_ur or ""
            ack = r0.split("۔")[0] if "۔" in r0 and ("؟" not in r0 or r0.index("۔") < r0.index("؟")) else "شکریہ"
            result.reply_ur = ack + "۔ " + prompts.COMBINED_Q_UR
        elif len(prior_mother) >= 1 and denial:
            alltext = " ".join(prior_mother + [latest]).lower()
            key = "gas" if any(w in alltext for w in ["gas", "گیس", "qabz", "قبض", "pait", "پیٹ", "bloat", "aphara", "اپھارہ"]) else "general"
            result.done, result.triage = True, "green"
            result.reply_ur = prompts.GREEN_DONE_UR
            if not result.selfcare_ur:
                result.selfcare_ur, result.selfcare_en = prompts.SELFCARE[key]
            result.recommended_specialty = "none"
            result.summary_en = result.summary_en or f"Minor complaint ({key}); no danger signs reported."

    # Deterministic safety net — can only escalate
    mother_texts = [h.get("text", "") for h in history if h.get("role") == "mother"]
    mother_texts += [result.transcript_turn or "", text or ""]
    triage, done, override, hits = triage_rules.apply_safety_net(
        result.triage, result.done, list(result.flags), mother_texts)
    reply = result.reply_ur
    if override and triage == "red":
        reply = prompts.RED_ADVICE_UR.format(**ctx)
    elif override and triage == "yellow":
        reply = prompts.YELLOW_ADVICE_UR.format(**ctx)

    checkin_id = alert_id = None
    if done:
        flags = list(result.flags)
        checkin_id = db.add("checkins", {
            "motherId": mother_id, "lhwId": mother.get("lhwId"), "createdAt": now_iso(),
            "turns": history + [{"role": "mother", "text": result.transcript_turn},
                                {"role": "mamta", "text": reply}],
            "answers": result.answers.model_dump() if result.answers else {},
            "triage": triage, "flags": flags, "keywordHits": hits, "adviceUr": reply,
            "ruleOverride": override, "confidence": result.confidence, "source": source,
            "summary": result.summary_en,
        })
        update = {"lastCheckinAt": now_iso()}
        # AI may only raise the mother's risk; lowering it is the LHW's decision (visit confirm)
        if RISK_RANK.get(triage, 0) >= RISK_RANK.get(mother.get("riskStatus"), 0):
            update.update(riskStatus=triage, riskReason=(result.summary_en or _reason(flags)) if triage != "green" else "")
        db.set("mothers", mother_id, update, merge=True)
        if triage in ("red", "yellow"):
            alert_id = db.add("alerts", {
                "motherId": mother_id, "motherName": mother.get("name"), "motherPhone": mother.get("phone"),
                "lhwId": mother.get("lhwId"), "checkinId": checkin_id, "level": triage,
                "signs": [FLAG_LABELS.get(f, f) for f in flags] or (["Danger words: " + ", ".join(hits)] if hits else []),
                "summary": result.summary_en, "motherSaid": result.transcript_turn,
                "daysPostpartum": ctx["days_postpartum"],
                "createdAt": now_iso(), "acknowledgedAt": None,
            })

    mp3 = tts.synthesize(reply)
    return {
        "reply_ur": reply, "done": done, "triage": triage, "flags": result.flags,
        "transcript_turn": result.transcript_turn, "confidence": result.confidence,
        "ruleOverride": override, "audio_base64": base64.b64encode(mp3).decode() if mp3 else None,
        "disclaimer_ur": prompts.DISCLAIMER_UR, "checkinId": checkin_id, "alertId": alert_id,
        "source": source, "aiGenerated": True, "summary": result.summary_en,
        "selfcare_ur": result.selfcare_ur if done else [], "selfcare_en": result.selfcare_en if done else [],
        "specialty": "emergency" if triage == "red" else (result.recommended_specialty or ("none" if triage == "green" else "gynaecologist")),
        "lhwName": lhw.get("name"), "lhwNotified": bool(alert_id),
    }


@app.post("/checkin/turn")
async def checkin_turn(motherId: str = Form(...), audio: UploadFile = File(...), history: str = Form("[]")):
    data = await audio.read()
    return _run_checkin(motherId, history, data, _mime(audio, "audio/wav"), None)


@app.post("/transcribe")
async def transcribe(audio: UploadFile = File(...), firstTurn: bool = Form(False)):
    """Step 1 of a voice turn: speech -> text. The mother sees the text and confirms it
    (or re-records) before it is used for screening. Raw audio is not stored."""
    data = await audio.read()
    try:
        t = gem.transcribe(data, _mime(audio, "audio/wav"))
        return {"transcript": t.transcript, "clear": t.clear, "source": "gemini", "aiGenerated": True}
    except gem.GeminiUnavailable:
        if gem.demo_mode() == "force" and firstTurn:  # only when Wi-Fi is dead
            return {"transcript": "کل سے بہت خون آ رہا ہے اور چکر آ رہے ہیں", "clear": True,
                    "source": "fixture", "aiGenerated": True}
        return {"transcript": "", "clear": False, "source": "fallback", "aiGenerated": True}


@app.post("/checkin/text")
async def checkin_text(motherId: str = Form(...), text: str = Form(...), history: str = Form("[]")):
    return _run_checkin(motherId, history, None, "", text)


@app.get("/lhw/{lhw_id}/alerts")
def lhw_alerts(lhw_id: str):
    alerts = [a for a in db.where("alerts", "lhwId", lhw_id) if not a.get("acknowledgedAt")]
    return sorted(alerts, key=lambda a: a.get("createdAt", ""), reverse=True)


@app.get("/lhw/{lhw_id}/today")
def lhw_today(lhw_id: str):
    lhw = db.get("lhws", lhw_id)
    open_alerts = lhw_alerts(lhw_id)
    out = []
    for m in db.where("mothers", "lhwId", lhw_id):
        days = _days_since(m.get("deliveryDate")) or 0
        last_visit_day = -1
        if m.get("lastVisitDate") and m.get("deliveryDate"):
            last_visit_day = (date.fromisoformat(m["lastVisitDate"][:10]) - date.fromisoformat(m["deliveryDate"][:10])).days
        due = [d for d in VISIT_SCHEDULE if last_visit_day < d <= days]
        overdue_by = days - max(due) if due else 0
        alert = next((a for a in open_alerts if a["motherId"] == m["id"]), None)
        risk = m.get("riskStatus", "green")
        if risk == "red":
            rank, reason = 0, "RED: " + (m.get("riskReason") or "danger sign reported")
        elif risk == "yellow":
            rank, reason = 1, "YELLOW: " + (m.get("riskReason") or "needs visit within 24h")
        elif due:
            rank, reason = 2, f"Day-{max(due)} visit overdue by {overdue_by} day(s)" if overdue_by else f"Day-{max(due)} visit due today"
        else:
            nxt = next((d for d in VISIT_SCHEDULE if d > max(days, last_visit_day)), None)
            rank = 3
            reason = f"Routine — next visit day {nxt} (in {nxt - days} days)" if nxt else "Postnatal visits complete"
        appts = sorted(db.where("appointments", "motherId", m["id"]), key=lambda a: a.get("createdAt", ""))
        out.append({**m, "daysPostpartum": days, "rank": rank, "reason": reason, "overdueBy": overdue_by,
                    "alert": alert, "appointment": appts[-1] if appts else None})
    out.sort(key=lambda x: (x["rank"], -(x["alert"] is not None), -x["overdueBy"], x["daysPostpartum"]))
    return {"lhw": lhw, "mothers": out, "alerts": open_alerts, "db": db.kind}


@app.post("/alerts/{alert_id}/ack")
def ack_alert(alert_id: str):
    if not db.get("alerts", alert_id):
        raise HTTPException(404, "alert not found")
    db.set("alerts", alert_id, {"acknowledgedAt": now_iso()}, merge=True)
    return {"ok": True}


@app.post("/register/digitize")
async def register_digitize(lhwId: str = Form(...), image: UploadFile = File(...)):
    data = await image.read()
    source = "gemini"
    try:
        page = gem.digitize_register(data, _mime(image, "image/jpeg"))
    except gem.GeminiUnavailable as e:
        if gem.demo_mode() != "force":
            raise HTTPException(503, "AI service busy — please try again in a moment") from e
        page, source = gem.register_fixture(), "fixture"
    return {"lhwId": lhwId, **page.model_dump(), "source": source, "aiGenerated": True, "saved": False}


@app.post("/register/confirm")
def register_confirm(body: RegisterConfirm):
    ids = []
    for r in body.rows:
        pnc = sorted(d for d in r.pncVisitDates if d)
        ids.append(db.add("mothers", {
            "name": r.motherName, "guardianName": r.guardianName, "houseNo": r.houseNo, "phone": None,
            "lhwId": body.lhwId, "deliveryDate": r.deliveryDate or date.today().isoformat(),
            "deliveryPlace": r.deliveryPlace or "unknown", "parity": r.parity, "babySex": r.babySex,
            "babyName": None, "babyBirthWeightKg": r.babyBirthWeightKg, "vaccinesGiven": r.vaccinesGiven,
            "language": "ur", "riskStatus": "green", "riskReason": "", "lastCheckinAt": None,
            "lastVisitDate": pnc[-1] if pnc else None, "remarks": r.remarks, "source": "register",
        }))
    return {"ok": True, "ids": ids}


@app.post("/visit/note")
async def visit_note(motherId: str = Form(...), audio: Optional[UploadFile] = File(None),
                     text: Optional[str] = Form(None)):
    mother, _, ctx = _mother_ctx(motherId)
    data = await audio.read() if audio else None
    source = "gemini"
    try:
        draft = gem.structure_visit(ctx, data, _mime(audio, "audio/wav") if audio else "", text)
    except gem.GeminiUnavailable as e:
        if gem.demo_mode() != "force":
            raise HTTPException(503, "AI service busy — please try again in a moment") from e
        draft, source = gem.visit_fixture(), "fixture"
    return {"motherId": motherId, "motherName": mother.get("name"), **draft.model_dump(),
            "source": source, "aiGenerated": True, "saved": False}


@app.post("/visit/confirm")
def visit_confirm(body: VisitConfirm):
    data = body.model_dump()
    data["date"] = body.date or date.today().isoformat()
    data["createdAt"] = now_iso()
    vid = db.add("visits", data)
    db.set("mothers", body.motherId, {
        "riskStatus": body.riskStatusConfirmed,  # the LHW's decision, may lower risk
        "riskReason": (body.referralReason or "; ".join(body.motherFindings + body.babyFindings))
        if body.riskStatusConfirmed != "green" else "",
        "lastVisitDate": data["date"],
    }, merge=True)
    for a in db.where("alerts", "motherId", body.motherId):  # visiting closes open alerts
        if not a.get("acknowledgedAt"):
            db.set("alerts", a["id"], {"acknowledgedAt": now_iso()}, merge=True)
    return {"ok": True, "id": vid}


@app.post("/report/monthly")
def report_monthly(body: ReportRequest):
    in_month = lambda iso: (iso or "").startswith(body.month)  # noqa: E731
    mothers = db.where("mothers", "lhwId", body.lhwId)
    checkins = [c for c in db.where("checkins", "lhwId", body.lhwId) if in_month(c.get("createdAt"))]
    visits = [v for v in db.where("visits", "lhwId", body.lhwId) if in_month(v.get("date"))]
    alerts = [a for a in db.where("alerts", "lhwId", body.lhwId) if in_month(a.get("createdAt"))]
    stats = {
        "month": body.month, "mothers_registered": len(mothers),
        "deliveries_this_month": sum(in_month(m.get("deliveryDate")) for m in mothers),
        "voice_checkins": len(checkins), "red_alerts": sum(a["level"] == "red" for a in alerts),
        "yellow_alerts": sum(a["level"] == "yellow" for a in alerts), "home_visits": len(visits),
        "referrals": sum(bool(v.get("referral")) for v in visits),
        "current_risk": {k: sum(m.get("riskStatus") == k for m in mothers) for k in ("red", "yellow", "green")},
    }
    try:
        md, source = gem.monthly_report(stats), "gemini"
    except gem.GeminiUnavailable:
        source = "template"
        md = (f"# Monthly report — {body.month} (draft)\n\n" + "\n".join(f"- **{k}**: {v}" for k, v in stats.items())
              + "\n\n_Auto-generated draft. Please review before submitting._")
    return {"markdown": md, "stats": stats, "source": source, "aiGenerated": True}
