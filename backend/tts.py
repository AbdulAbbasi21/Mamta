"""Text-to-speech for Mamta's Urdu replies -> audio bytes (MP3 or WAV).

Order: 1) Google Cloud Text-to-Speech (ur-IN voice, needs service account)
       2) Gemini TTS model (needs only GEMINI_API_KEY)
       3) cached audio from an earlier successful run (demo_fixtures/tts_cache/)
If all fail we return None and the app uses the device's own voice.
"""
import hashlib
import io
import logging
import os
import re
import wave
from pathlib import Path
from typing import Optional

log = logging.getLogger("mamta.tts")
CACHE = Path(__file__).parent / "demo_fixtures" / "tts_cache"
VOICE = os.getenv("TTS_VOICE", "ur-IN-Wavenet-A")

_client = None
_cloud_ok = True  # stop retrying Cloud TTS after the first credential failure


def _cache_path(text: str) -> Path:
    return CACHE / (hashlib.sha1(text.strip().encode("utf-8")).hexdigest()[:16] + ".bin")


def _cloud_tts(text: str) -> bytes:
    global _client
    from google.cloud import texttospeech as tts
    if _client is None:
        _client = tts.TextToSpeechClient()
    resp = _client.synthesize_speech(
        input=tts.SynthesisInput(text=text),
        voice=tts.VoiceSelectionParams(language_code="ur-IN", name=VOICE),
        audio_config=tts.AudioConfig(audio_encoding=tts.AudioEncoding.MP3, speaking_rate=0.92),
        timeout=10,
    )
    return resp.audio_content


def _pcm_to_wav(pcm: bytes, rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def _gemini_tts(text: str) -> bytes:
    from google.genai import types
    import gemini_client
    resp = gemini_client._get_client().models.generate_content(
        model=os.getenv("GEMINI_TTS_MODEL", "gemini-3.8-flash-lite-tts"),
        contents=f"Read this aloud in warm, calm Urdu: {text}",
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=os.getenv("GEMINI_TTS_VOICE", "Kore")))),
        ),
    )
    part = resp.candidates[0].content.parts[0].inline_data
    mime = (part.mime_type or "").lower()
    if "wav" in mime or part.data[:4] == b"RIFF" or part.data[:3] == b"ID3":
        return part.data
    m = re.search(r"rate=(\d+)", mime)
    return _pcm_to_wav(part.data, int(m.group(1)) if m else 24000)


def synthesize(text: str) -> Optional[bytes]:
    """Returns MP3 or WAV bytes (the app detects which from the first bytes)."""
    global _cloud_ok
    if not text:
        return None
    path = _cache_path(text)
    if os.getenv("DEMO_MODE", "").lower() == "force":
        return path.read_bytes() if path.exists() else None
    audio = None
    if _cloud_ok:
        try:
            audio = _cloud_tts(text)
        except Exception as e:  # noqa: BLE001
            _cloud_ok = False
            import gemini_client
            gemini_client.LAST_ERROR["cloud_tts"] = str(e)[:200]
            log.warning("Cloud TTS unavailable (%s) -> using Gemini TTS", str(e)[:150])
    if audio is None and os.getenv("GEMINI_API_KEY"):
        try:
            audio = _gemini_tts(text)
        except Exception as e:  # noqa: BLE001
            log.warning("Gemini TTS failed: %s", str(e)[:200])
            import gemini_client
            gemini_client.LAST_ERROR["tts"] = str(e)[:300]
    if audio:
        CACHE.mkdir(parents=True, exist_ok=True)
        path.write_bytes(audio)
        return audio
    if path.exists():
        log.warning("[DEMO FIXTURE] serving cached TTS %s", path.name)
        return path.read_bytes()
    return None
