"""Deterministic safety net. Runs AFTER Gemini on every check-in turn.

Principle: this layer can only ESCALATE risk (green -> yellow -> red). It never lowers it.
If any RED flag is reported, or the mother's own words contain a RED keyword, we force triage=red,
finish the conversation, and mark ruleOverride=True so the LHW can see the rule fired.
"""
from typing import Iterable, List, Tuple

RED_FLAGS = {
    "heavy_bleeding", "fits", "severe_headache_vision", "fever_foul_discharge", "breathlessness",
    "baby_not_feeding", "baby_fast_breathing", "baby_fits", "baby_temperature", "baby_jaundice_severe",
}
YELLOW_FLAGS = {
    "breast_pain", "painful_urination", "wound_problem", "low_mood", "mild_fever",
    "baby_jaundice_mild", "baby_weight", "unsure",
}

# Phrases in the MOTHER's words that always mean RED (Urdu script + Roman Urdu + English).
RED_KEYWORDS = [
    # Urdu script
    "خون بہت", "بہت خون", "بہت زیادہ خون", "خون کے لوتھڑے",
    "دورے", "دورہ پڑ", "جھٹکے",
    "بے ہوش", "بےہوش",
    "سانس نہیں", "سانس لینے میں", "سانس تیز", "سانس پھول",
    "نیلا", "نیلی", "نیلے",
    # Roman Urdu
    "bohat khoon", "bahut khoon", "bohot khoon", "khoon bohat", "khoon bahut",
    "dora", "doray", "dauray", "behosh", "be hosh",
    "saans nahi", "saans tez", "saans phool", "neela", "neeli",
    # English
    "heavy bleeding", "bleeding a lot", "fits", "seizure", "unconscious", "fainted",
    "can't breathe", "cannot breathe", "turning blue",
]

LEVEL = {"pending": 0, "green": 1, "yellow": 2, "red": 3}


def find_red_keywords(texts: Iterable[str]) -> List[str]:
    hits = []
    for t in texts:
        low = (t or "").lower()
        for kw in RED_KEYWORDS:
            if kw in low and kw not in hits:
                hits.append(kw)
    return hits


def apply_safety_net(triage: str, done: bool, flags: List[str],
                     mother_texts: Iterable[str]) -> Tuple[str, bool, bool, List[str]]:
    """Returns (triage, done, rule_override, keyword_hits). Never lowers the AI's triage."""
    keyword_hits = find_red_keywords(mother_texts)
    red_flag = any(f in RED_FLAGS for f in flags)

    if red_flag or keyword_hits:
        override = triage != "red" or not done
        return "red", True, override, keyword_hits

    yellow_flag = any(f in YELLOW_FLAGS for f in flags)
    if done and yellow_flag and LEVEL.get(triage, 0) < LEVEL["yellow"]:
        return "yellow", True, True, keyword_hits

    return triage, done, False, keyword_hits
