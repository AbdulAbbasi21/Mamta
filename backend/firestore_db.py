"""Tiny database layer.

Uses Firebase Firestore (via firebase-admin) when credentials are available.
If Firestore can't be reached, falls back to an in-memory store so the demo never crashes.
Every function works the same way with both backends.
"""
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

log = logging.getLogger("mamta.db")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MemoryDB:
    kind = "memory"

    def __init__(self):
        self._data: Dict[str, Dict[str, dict]] = {}
        self._lock = threading.Lock()

    def add(self, col: str, data: dict) -> str:
        doc_id = uuid.uuid4().hex[:20]
        self.set(col, doc_id, data)
        return doc_id

    def set(self, col: str, doc_id: str, data: dict, merge: bool = False) -> None:
        with self._lock:
            c = self._data.setdefault(col, {})
            if merge and doc_id in c:
                c[doc_id].update(data)
            else:
                c[doc_id] = dict(data)

    def get(self, col: str, doc_id: str) -> Optional[dict]:
        d = self._data.get(col, {}).get(doc_id)
        return dict(d, id=doc_id) if d else None

    def where(self, col: str, field: str, value: Any) -> List[dict]:
        return [dict(d, id=i) for i, d in self._data.get(col, {}).items() if d.get(field) == value]

    def all(self, col: str) -> List[dict]:
        return [dict(d, id=i) for i, d in self._data.get(col, {}).items()]

    def wipe(self, col: str) -> None:
        self._data[col] = {}


class FirestoreDB:
    kind = "firestore"

    def __init__(self):
        import firebase_admin
        from firebase_admin import credentials, firestore

        if not firebase_admin._apps:
            cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            if cred_path and not os.path.isabs(cred_path):  # relative to backend/
                cred_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), cred_path)
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = cred_path  # also used by Cloud TTS
            project = os.getenv("FIREBASE_PROJECT_ID")
            if cred_path and os.path.exists(cred_path):
                cred = credentials.Certificate(cred_path)
            else:
                cred = credentials.ApplicationDefault()  # works on Cloud Run
            firebase_admin.initialize_app(cred, {"projectId": project} if project else None)
        self.db = firestore.client()
        # Fail fast if Firestore isn't reachable
        list(self.db.collection("lhws").limit(1).stream(timeout=8))

    def add(self, col, data):
        _, ref = self.db.collection(col).add(data)
        return ref.id

    def set(self, col, doc_id, data, merge=False):
        self.db.collection(col).document(doc_id).set(data, merge=merge)

    def get(self, col, doc_id):
        snap = self.db.collection(col).document(doc_id).get()
        return dict(snap.to_dict(), id=snap.id) if snap.exists else None

    def where(self, col, field, value):
        from google.cloud.firestore_v1.base_query import FieldFilter
        q = self.db.collection(col).where(filter=FieldFilter(field, "==", value))
        return [dict(s.to_dict(), id=s.id) for s in q.stream()]

    def all(self, col):
        return [dict(s.to_dict(), id=s.id) for s in self.db.collection(col).stream()]

    def wipe(self, col):
        batch, n = self.db.batch(), 0
        for s in self.db.collection(col).list_documents():
            batch.delete(s)
            n += 1
            if n % 400 == 0:
                batch.commit()
                batch = self.db.batch()
        batch.commit()


def _connect():
    if os.getenv("USE_MEMORY_DB", "").lower() == "true":
        log.warning("USE_MEMORY_DB=true -> using in-memory database")
        return MemoryDB()
    try:
        db = FirestoreDB()
        log.info("Connected to Firestore")
        return db
    except Exception as e:  # noqa: BLE001
        log.warning("Firestore unavailable (%s) -> using in-memory database. "
                    "The Flutter app will poll the backend instead of using live listeners.", e)
        return MemoryDB()


db = _connect()
