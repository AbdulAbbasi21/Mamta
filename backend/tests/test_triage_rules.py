import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from triage_rules import apply_safety_net, find_red_keywords  # noqa: E402


def test_red_flag_forces_red_even_if_ai_says_green():
    triage, done, override, _ = apply_safety_net("green", True, ["heavy_bleeding"], ["..."])
    assert (triage, done, override) == ("red", True, True)


def test_red_flag_while_pending_stops_conversation():
    triage, done, override, _ = apply_safety_net("pending", False, ["baby_fast_breathing"], [""])
    assert triage == "red" and done and override


def test_urdu_keyword_forces_red():
    triage, done, override, hits = apply_safety_net("pending", False, [], ["کل سے بہت خون آ رہا ہے"])
    assert triage == "red" and done and override and "بہت خون" in hits


def test_roman_urdu_keyword_forces_red():
    triage, *_ = apply_safety_net("green", True, [], ["Kal se bohat khoon aa raha hai aur chakkar"])
    assert triage == "red"


def test_fits_and_unconscious_keywords():
    assert find_red_keywords(["بچے کو دورے پڑ رہے ہیں"])
    assert find_red_keywords(["وہ بے ہوش ہو گئی"])
    assert find_red_keywords(["bachay ka rang neela ho gaya"])


def test_ai_red_is_never_lowered():
    triage, done, override, _ = apply_safety_net("red", True, [], ["سب ٹھیک ہے"])
    assert triage == "red" and not override


def test_yellow_flag_escalates_green():
    triage, done, override, _ = apply_safety_net("green", True, ["breast_pain"], ["چھاتی میں درد"])
    assert triage == "yellow" and override


def test_yellow_flag_does_not_lower_red():
    triage, *_ = apply_safety_net("red", True, ["breast_pain"], [""])
    assert triage == "red"


def test_clean_green_untouched():
    triage, done, override, hits = apply_safety_net("green", True, [], ["سب ٹھیک ہے، بچہ دودھ پی رہا ہے"])
    assert (triage, done, override, hits) == ("green", True, False, [])


def test_pending_without_danger_stays_pending():
    triage, done, override, _ = apply_safety_net("pending", False, [], ["نہیں"])
    assert (triage, done, override) == ("pending", False, False)
