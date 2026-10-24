"""The eval runner's own logic (the evals themselves run against a real model: scripts/run_evals.py)."""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("run_evals", ROOT / "scripts" / "run_evals.py")
run_evals = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_evals)


def test_language_detection():
    assert run_evals.detect_language("Aap landlord ko ek legal notice bhej sakte hain, kya aapke paas agreement hai?") == "hinglish"
    assert run_evals.detect_language("आप मकान मालिक को कानूनी नोटिस भेज सकते हैं।") == "hindi"
    assert run_evals.detect_language("You can send the landlord a legal notice under the agreement.") == "english"


def test_cases_file_is_well_formed():
    cases = json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))["cases"]
    assert len({c["id"] for c in cases}) == len(cases) >= 10
    for case in cases:
        assert case["turns"] and case["mode"] in ("copilot", "conversation")
        assert case["expect"].get("language") in ("english", "hinglish", "hindi")
        assert all(isinstance(group, list) and group for group in case["expect"].get("keywords", []))
