"""End-to-end API test in offline demo mode (no network, in-memory DB)."""
import os
import sys

os.environ["USE_MEMORY_DB"] = "true"
os.environ["DEMO_MODE"] = "force"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

client = TestClient(main.app)
main.seed_mod.seed(main.db)


def test_health():
    assert client.get("/health").json()["ok"]


def test_today_list_ranked():
    ms = client.get("/lhw/lhw_shazia/today").json()["mothers"]
    assert len(ms) == 6
    assert [m["riskStatus"] for m in ms[:2]] == ["yellow", "yellow"]
    assert "overdue" in ms[2]["reason"]


def test_red_checkin_creates_alert_and_moves_to_top():
    r = client.post("/checkin/text", data={"motherId": "m_fatima", "text": "Kal se bohat khoon aa raha hai"}).json()
    assert r["triage"] == "red" and r["done"] and r["alertId"]
    today = client.get("/lhw/lhw_shazia/today").json()
    assert today["mothers"][0]["id"] == "m_fatima" and today["alerts"]
    assert client.post(f"/alerts/{r['alertId']}/ack").json()["ok"]


def test_audio_checkin_offline_fixture():
    r = client.post("/checkin/turn", data={"motherId": "m_ayesha", "history": "[]"},
                    files={"audio": ("a.wav", b"RIFF0000WAVE", "audio/wav")}).json()
    assert r["triage"] == "red" and r["source"] == "fixture"


def test_offline_full_green_conversation():
    import json
    history, r = [], None
    answers = ["میں ٹھیک ہوں", "نہیں", "نہیں", "نہیں", "نہیں", "جی ہاں، پی رہا ہے", "نہیں"]
    for a in answers:
        r = client.post("/checkin/text", data={"motherId": "m_kiran", "text": a,
                                               "history": json.dumps(history, ensure_ascii=False)}).json()
        history += [{"role": "mother", "text": a}, {"role": "mamta", "text": r["reply_ur"]}]
        if r["done"]:
            break
    assert r["done"] and r["triage"] == "green"


def test_register_and_visit_flow():
    page = client.post("/register/digitize", data={"lhwId": "lhw_shazia"},
                       files={"image": ("p.jpg", b"fake", "image/jpeg")}).json()
    assert page["rows"] and any(row["low_confidence"] for row in page["rows"])
    saved = client.post("/register/confirm", json={"lhwId": "lhw_shazia", "rows": page["rows"]}).json()
    assert len(saved["ids"]) == len(page["rows"])
    draft = client.post("/visit/note", data={"motherId": "m_saima", "text": "visit"}).json()
    body = {k: draft[k] for k in ("visitType", "motherFindings", "babyFindings", "vaccinesGiven",
                                  "counsellingDone", "referral", "referralReason", "nextVisitDate",
                                  "suggestedRiskStatus", "transcript")}
    body.update(motherId="m_saima", lhwId="lhw_shazia", riskStatusConfirmed="green")
    assert client.post("/visit/confirm", json=body).json()["ok"]
    assert main.db.get("mothers", "m_saima")["riskStatus"] == "green"


def test_monthly_report_template():
    r = client.post("/report/monthly", json={"lhwId": "lhw_shazia", "month": "2026-11"}).json()
    assert "markdown" in r
