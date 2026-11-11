"""Pydantic models. The same classes are passed to Gemini as `response_schema`,
so Gemini is forced to return JSON in exactly this shape, and we validate it again here."""
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

Triage = Literal["green", "yellow", "red", "pending"]
Risk = Literal["green", "yellow", "red"]

Flag = Literal[
    "heavy_bleeding", "fits", "severe_headache_vision", "fever_foul_discharge", "breathlessness",
    "breast_pain", "painful_urination", "wound_problem", "low_mood", "mild_fever",
    "baby_not_feeding", "baby_fast_breathing", "baby_fits", "baby_temperature",
    "baby_jaundice_severe", "baby_jaundice_mild", "baby_weight", "unsure",
]


# ---------- 6.1 Triage ----------
class TriageAnswers(BaseModel):
    """What the mother has answered so far, one field per danger-sign question (short English summary)."""
    bleeding: Optional[str] = None
    fever_discharge: Optional[str] = None
    headache_vision_fits: Optional[str] = None
    breast: Optional[str] = None
    baby_feeding_activity: Optional[str] = None
    baby_breathing_fever_jaundice: Optional[str] = None


class TriageResult(BaseModel):
    reply_ur: str = Field(description="What Mamta says next, in simple spoken Urdu (Urdu script).")
    done: bool = Field(description="True when screening is finished and triage is final.")
    triage: Triage
    flags: List[Flag] = Field(default_factory=list)
    answers: Optional[TriageAnswers] = None
    transcript_turn: str = Field(description="Exact transcription of the mother's latest message.")
    confidence: Optional[float] = Field(default=None, description="0..1 confidence in the triage.")
    selfcare_ur: List[str] = Field(default_factory=list, description="2-4 short practical home-care tips in Urdu script for minor complaints. Never medicine names or doses.")
    selfcare_en: List[str] = Field(default_factory=list, description="The same tips in simple English.")
    summary_en: Optional[str] = Field(default=None, description="One-line English summary for the LHW of everything the mother reported so far (symptoms, mother and baby).")
    recommended_specialty: Optional[Literal["gynaecologist", "paediatrician", "emergency", "none"]] = Field(
        default=None, description="Which doctor she should see: emergency if RED, gynaecologist for mother problems, paediatrician for baby problems, none if GREEN.")


class Transcript(BaseModel):
    transcript: str = Field(description="Exact words spoken, in Urdu script (keep English words as spoken).")
    clear: bool = Field(description="False if the audio was too unclear/noisy to transcribe reliably.")


# ---------- 6.2 Register digitizer ----------
class RegisterRow(BaseModel):
    serial: Optional[str] = None
    motherName: str
    guardianName: Optional[str] = None
    houseNo: Optional[str] = None
    deliveryDate: Optional[str] = Field(default=None, description="YYYY-MM-DD")
    deliveryPlace: Optional[Literal["home", "facility", "unknown"]] = None
    parity: Optional[int] = None
    babySex: Optional[Literal["M", "F", "unknown"]] = None
    babyBirthWeightKg: Optional[float] = None
    vaccinesGiven: List[str] = Field(default_factory=list)
    pncVisitDates: List[str] = Field(default_factory=list)
    remarks: Optional[str] = None
    low_confidence: List[str] = Field(default_factory=list,
                                      description="Field names the model is unsure about.")


class RegisterPage(BaseModel):
    rows: List[RegisterRow]
    page_notes: Optional[str] = None


class RegisterConfirm(BaseModel):
    lhwId: str
    rows: List[RegisterRow]


# ---------- 6.3 Visit note ----------
class VisitDraft(BaseModel):
    visitType: Literal["routine", "follow_up", "referral_check"]
    motherFindings: List[str] = Field(default_factory=list)
    babyFindings: List[str] = Field(default_factory=list)
    vaccinesGiven: List[str] = Field(default_factory=list)
    counsellingDone: List[Literal["breastfeeding", "danger_signs", "family_planning",
                                  "nutrition", "hygiene"]] = Field(default_factory=list)
    referral: bool = False
    referralReason: Optional[str] = None
    nextVisitDate: Optional[str] = None
    suggestedRiskStatus: Risk
    transcript: str


class VisitConfirm(VisitDraft):
    motherId: str
    lhwId: str
    riskStatusConfirmed: Risk  # what the LHW actually chose (human in the loop)
    date: Optional[str] = None


class ReportRequest(BaseModel):
    lhwId: str
    month: str  # YYYY-MM
