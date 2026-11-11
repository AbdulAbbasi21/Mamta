# AI Disclosure — Mamta

## AI models used in the product
| Model / API | Used for |
|---|---|
| **Gemini Flash** (`gemini-flash-latest`, fallback `gemini-3.1-flash-lite`) via the `google-genai` SDK | Urdu audio understanding and the triage conversation; handwritten register transcription (vision); structuring spoken visit notes; drafting the monthly report. Every call uses `response_mime_type="application/json"` + `response_schema`, and the result is validated with Pydantic. |
| **Google Cloud Text-to-Speech** (`ur-IN-Wavenet-A`) and **Gemini TTS** (`gemini-3.8-flash-lite-tts`) | Speaking Mamta's replies in Urdu. |
| Browser text-to-speech (Web Speech API) | Fallback voice only, used when Cloud TTS audio is unavailable. |

## Google technologies
Gemini API (Google AI Studio key), Firebase Firestore (+ Firebase JS SDK), Firebase security rules, Google Cloud Text-to-Speech, Gemini TTS, Google Fonts, Google Cloud Run. *(Firebase Cloud Messaging: planned, not implemented.)*

## AI coding assistants used to build it
- **[TEAM TO FILL — e.g. Claude (Anthropic), Cursor, GitHub Copilot, ChatGPT]**
- How they were used: **[TEAM TO FILL]** (e.g. generating the initial FastAPI backend, web frontend, tests and documentation from our written specification; the team reviewed, ran, tested and modified the code).

## Third-party libraries and APIs
**Backend (`backend/requirements.txt`):** fastapi, uvicorn, python-multipart, python-dotenv, pydantic, google-genai, firebase-admin, google-cloud-texttospeech, pytest, httpx.

**Web app (`backend/web/`):** plain HTML/CSS/JavaScript, Firebase JS SDK (CDN, optional), Google Fonts (Noto Nastaliq Urdu, Inter). No frameworks.

## Datasets
None external. All seed data (`backend/seed.py`) and register pages were created by the team. **No real patient data** was used. The danger-sign criteria are adapted from the **WHO recommendations on maternal and newborn care for a positive postnatal experience (2022)**.

## Limitations
- Prototype only; **not clinically validated** and not a medical device.
- Urdu speech recognition accuracy varies with accent, dialect (Punjabi, Pashto, Saraiki) and background noise.
- The Urdu voice uses the `ur-IN` locale, so some pronunciations differ from Pakistani Urdu.
- The keyword safety net is deliberately over-sensitive (it can only escalate), so it may raise false RED alerts.
- Handwriting transcription can be wrong, which is why every row must be confirmed by the LHW.
- `DEMO_MODE` can serve cached responses; these are labelled "offline demo data" in the UI.
