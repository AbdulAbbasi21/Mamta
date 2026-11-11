"""Reset the database with demo data (no real patients).

    python seed.py          # wipes and recreates lhws, mothers, checkins, alerts, visits
"""
import time
from datetime import date, timedelta

from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")  # works no matter which folder you start from

LHW_ID = "lhw_shazia"
COLLECTIONS = ["lhws", "mothers", "checkins", "alerts", "visits", "appointments"]

# (id, name, nameUr, days postpartum, baby name, weight, place, parity, risk, reason, last visit day)
MOTHERS = [
    ("m_ayesha", "Ayesha Bibi", "عائشہ بی بی", 2, "Hamza", 3.1, "facility", 1, "green", "", 1),
    ("m_fatima", "Fatima Noor", "فاطمہ نور", 5, "Zainab", 2.9, "home", 2, "green", "", 3),
    ("m_rukhsana", "Rukhsana Akhtar", "رخسانہ اختر", 9, "Ali", 2.6, "home", 3, "green", "", 3),
    ("m_saima", "Saima Parveen", "صائمہ پروین", 14, "Maryam", 3.0, "facility", 1, "yellow",
     "Breast pain reported at last visit", 7),
    ("m_nasreen", "Nasreen Kausar", "نسرین کوثر", 28, "Usman", 2.4, "home", 4, "yellow",
     "Low mood / crying often at last check-in", 7),
    ("m_kiran", "Kiran Shahzadi", "کرن شہزادی", 40, "Hira", 3.3, "facility", 2, "green", "", 7),
]


def seed(db) -> dict:
    t0 = time.time()
    for c in COLLECTIONS:
        db.wipe(c)
    today = date.today()
    db.set("lhws", LHW_ID, {
        "name": "Shazia Bibi", "nameUr": "شازیہ بی بی", "phone": "+923001234567", "pin": "1234",
        "area": "Bhara Kahu, Islamabad", "fcmToken": None, "language": "ur",
    })
    for i, (mid, name, name_ur, days, baby, wt, place, parity, risk, reason, last_visit_day) in enumerate(MOTHERS):
        delivery = today - timedelta(days=days)
        db.set("mothers", mid, {
            "name": name, "nameUr": name_ur, "phone": f"+92300000000{i + 1}", "lhwId": LHW_ID,
            "deliveryDate": delivery.isoformat(), "deliveryPlace": place, "parity": parity,
            "babyName": baby, "babyBirthWeightKg": wt, "language": "ur",
            "riskStatus": risk, "riskReason": reason, "lastCheckinAt": None,
            "lastVisitDate": (delivery + timedelta(days=last_visit_day)).isoformat(),
            "houseNo": f"H-{10 + i}", "source": "seed",
        })
    return {"ok": True, "mothers": len(MOTHERS), "seconds": round(time.time() - t0, 2), "db": db.kind}


if __name__ == "__main__":
    from firestore_db import db

    print(seed(db))
