"""One function per Gemini task. Every call:
  1. sends a system prompt + input (audio / image / text),
  2. forces JSON output with response_schema (our Pydantic models),
  3. validates the JSON with Pydantic,
  4. retries once (with the fallback model), then raises GeminiUnavailable.
Callers (main.py) then use demo fixtures or a safe fallback, so the app never crashes on stage.

DEMO_MODE env:
  false  -> on failure return safe fallback only
  true   -> on failure serve fixtures from demo_fixtures/ (offline insurance)
  force  -> never call Gemini, always serve fixtures (e.g. Wi-Fi is dead)
"""
import json
import logging
import os
from datetime import date
from pathlib import Path
from typing import List, Optional, Type, TypeVar

from pydantic import BaseModel

import prompts
from schemas import RegisterPage, Transcript, TriageResult, VisitDraft

log = logging.getLogger("mamta.gemini")
T = TypeVar("T", bound=BaseModel)

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-flash-latest")
FIXTURES = Path(__file__).parent / "demo_fixtures"


class GeminiUnavailable(Exception):
    pass


LAST_ERROR = {"error": None}  # shown in /health to debug key/model problems


def demo_mode() -> str:
    return os.getenv("DEMO_MODE", "true").lower()


_client = None


def _get_client():
    global _client
    if _client is None:
        from google import genai
        from google.genai import types
        key = os.getenv("GEMINI_API_KEY")
        timeout_ms = int(os.getenv("GEMINI_TIMEOUT_MS", "15000"))  # never hang on stage
        if key:
            _client = genai.Client(api_key=key, http_options=types.HttpOptions(api_version="v1beta", timeout=timeout_ms))  # AI Studio key
        else:  # Vertex AI with service account / Cloud Run identity
            _client = genai.Client(vertexai=True, project=os.getenv("FIREBASE_PROJECT_ID"),
                                   location=os.getenv("VERTEX_LOCATION", "us-central1"))
    return _client


def _generate(system: str, parts: list, schema: Type[T]) -> T:
    if demo_mode() == "force":
        raise GeminiUnavailable("DEMO_MODE=force")
    from google.genai import types

    last_err = None
    for model in (MODEL, FALLBACK_MODEL):
        try:
            cfg = dict(system_instruction=system, response_mime_type="application/json",
                       response_schema=schema, temperature=0.2)
            if model.startswith("gemini-2.5"):
                cfg["thinking_config"] = types.ThinkingConfig(thinking_budget=0)  # faster replies
            resp = _get_client().models.generate_content(
                model=model, contents=parts, config=types.GenerateContentConfig(**cfg))
            result = resp.parsed if isinstance(resp.parsed, schema) else schema.model_validate_json(resp.text)
            log.info("Gemini %s OK -> %s", model, schema.__name__)
            return result
        except Exception as e:  # noqa: BLE001
            last_err = e
            LAST_ERROR["error"] = f"{model}: {str(e)[:300]}"
            log.warning("Gemini %s failed: %s", model, e)
    raise GeminiUnavailable(str(last_err))


def _audio_part(data: bytes, mime: str):
    from google.genai import types
    return types.Part.from_bytes(data=data, mime_type=mime or "audio/wav")


def _save_fixture(name: str, obj: BaseModel) -> None:
    """Record real successful Gemini outputs so DEMO_MODE replays them later."""
    try:
        (FIXTURES / "recorded").mkdir(parents=True, exist_ok=True)
        (FIXTURES / "recorded" / f"{name}.json").write_text(obj.model_dump_json(indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _load_fixture(name: str, schema: Type[T]) -> T:
    for p in (FIXTURES / "recorded" / f"{name}.json", FIXTURES / f"{name}.json"):
        if p.exists():
            log.warning("[DEMO FIXTURE] serving %s", p)
            return schema.model_validate_json(p.read_text(encoding="utf-8"))
    raise FileNotFoundError(name)


# ---------------------------------------------------------------- 6.1 triage
def triage_turn(ctx: dict, history: List[dict], audio: Optional[bytes] = None,
                mime: str = "audio/wav", text: Optional[str] = None) -> TriageResult:
    system = prompts.TRIAGE_SYSTEM.format(**ctx)
    latest = "the attached audio recording" if audio else f"this text: {text}"
    parts = [f"Conversation so far (JSON, oldest first):\n{json.dumps(history, ensure_ascii=False)}\n\n"
             f"The mother's latest message is {latest}. Transcribe it into transcript_turn "
             f"and reply following the rules."]
    if audio:
        parts.append(_audio_part(audio, mime))
    result = _generate(system, parts, TriageResult)
    if audio and result.done and result.triage == "red":
        _save_fixture("checkin_audio", result)  # replayed offline for the stage demo
    return result


# Offline scripted screening used when Gemini is unavailable (DEMO_MODE). Same 6 questions, same order.
QUESTIONS_UR = [
    "کیا آپ کو بہت زیادہ خون آ رہا ہے، یعنی ایک گھنٹے میں ایک پیڈ بھر جاتا ہے یا بڑے لوتھڑے آتے ہیں؟",
    "کیا آپ کو بخار ہے، یا بدبودار پانی آ رہا ہے؟",
    "کیا آپ کو بہت تیز سر درد ہے، دھندلا نظر آتا ہے، یا دورے پڑے ہیں؟",
    "کیا آپ کی چھاتی میں درد یا سرخی ہے؟",
    "کیا بچہ ٹھیک سے دودھ پی رہا ہے اور ہاتھ پاؤں ہلا رہا ہے؟",
    "کیا بچے کو سانس لینے میں مشکل، بخار، یا جلد پیلی ہے؟",
]
# flag raised when the answer to question i is "yes" (or "no" for question 5, where yes is good)
_Q_FLAGS = ["heavy_bleeding", "mild_fever", "severe_headache_vision", "breast_pain",
            "baby_not_feeding", "baby_jaundice_mild"]
_YES = ["ہاں", "جی ہاں", "جی", "haan", "han", "ji", "yes", "hai"]
_NO = ["نہیں", "nahi", "nahin", "no", "na"]
GREEN_UR = ("شکریہ! آپ اور بچہ دونوں ٹھیک لگ رہے ہیں۔ بچے کو ہر دو تین گھنٹے بعد اپنا دودھ پلائیں، "
            "اور خود بھی آرام کریں اور پانی زیادہ پئیں۔")


def _says(text: str, words: List[str]) -> bool:
    toks = text.lower().replace("۔", " ").replace(",", " ").split()
    return any(w in toks or (" " in w and w in text.lower()) for w in words)


def offline_triage(ctx: dict, history: List[dict], latest_text: str) -> TriageResult:
    import triage_rules
    mother_turns = [h.get("text", "") for h in history if h.get("role") == "mother"] + [latest_text]
    flags: List[str] = []
    # mother turn 0 is her free description; turn k (k>=1) answers question k-1
    for k, ans in enumerate(mother_turns[1:]):
        if k >= len(QUESTIONS_UR):
            break
        bad = _says(ans, _NO) if k == 4 else (_says(ans, _YES) and not _says(ans, _NO))
        if bad:
            flags.append(_Q_FLAGS[k])
    asked = len(mother_turns) - 1
    red = any(f in triage_rules.RED_FLAGS for f in flags)
    if red or asked >= len(QUESTIONS_UR):
        level = "red" if red else ("yellow" if flags else "green")
        reply = {"red": prompts.RED_ADVICE_UR, "yellow": prompts.YELLOW_ADVICE_UR,
                 "green": GREEN_UR}[level].format(**ctx)
        return TriageResult(reply_ur=reply, done=True, triage=level, flags=flags,
                            transcript_turn=latest_text, confidence=0.5)
    prefix = "شکریہ۔ " if asked else "السلام علیکم، میں ممتا ہوں۔ "
    return TriageResult(reply_ur=prefix + QUESTIONS_UR[asked], done=False, triage="pending",
                        flags=flags, transcript_turn=latest_text, confidence=0.5)


# ---------------------------------------------------------------- speech -> text (mother confirms it)
def transcribe(audio: bytes, mime: str) -> Transcript:
    return _generate(prompts.TRANSCRIBE_SYSTEM, ["Transcribe this audio.", _audio_part(audio, mime)], Transcript)


# ---------------------------------------------------------------- 6.2 register
def digitize_register(image: bytes, mime: str) -> RegisterPage:
    from google.genai import types
    system = prompts.REGISTER_SYSTEM.format(year=date.today().year)
    parts = ["Transcribe every row of this register page.", types.Part.from_bytes(data=image, mime_type=mime)]
    result = _generate(system, parts, RegisterPage)
    _save_fixture("register", result)
    return result


def register_fixture() -> RegisterPage:
    return _load_fixture("register", RegisterPage)


# ---------------------------------------------------------------- 6.3 visit note
def structure_visit(ctx: dict, audio: Optional[bytes], mime: str, text: Optional[str] = None) -> VisitDraft:
    system = prompts.VISIT_SYSTEM.format(**ctx)
    parts = ["Structure this visit note." + (f" Note text: {text}" if text else "")]
    if audio:
        parts.append(_audio_part(audio, mime))
    result = _generate(system, parts, VisitDraft)
    _save_fixture("visit", result)
    return result


def visit_fixture() -> VisitDraft:
    return _load_fixture("visit", VisitDraft)


# ---------------------------------------------------------------- stretch: monthly report
class _Report(BaseModel):
    markdown: str


def monthly_report(stats: dict) -> str:
    parts = [f"Numbers for the month (JSON): {json.dumps(stats, ensure_ascii=False)}"]
    return _generate(prompts.REPORT_SYSTEM, parts, _Report).markdown
