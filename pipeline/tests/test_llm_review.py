"""Tests for the advisory LLM extraction-QA pass (ADR-0003, R4.10).

The LLM client is faked, so these run without Ollama or a network. The point is
to prove the pass is advisory, robust to bad model output, and mutation-free.
"""

import copy
import json

import pytest

from avgasmap import llm_review
from avgasmap.llm_review import Suggestion, review_records


class FakeClient:
    """Returns a canned response per prompt (keyed by an ICAO substring)."""

    def __init__(self, responses: dict[str, str], default: str = "[]"):
        self._responses = responses
        self._default = default
        self.calls: list[str] = []

    def generate(self, prompt: str) -> str:
        self.calls.append(prompt)
        for key, resp in self._responses.items():
            if key in prompt:
                return resp
        return self._default


def _rec(icao, state="available", grades=None, text="", **cond):
    base = {"on_request": False, "ppr": False, "self_service": False,
            "reserved_for_based": False, "mil_civ_split": False, "has_hours": False,
            "payment": [], "brand": None, "phone": None, "website": None, "email": None}
    base.update(cond)
    return {"icao": icao, "name": icao, "fuel_state": state,
            "avgas_grades": grades or [], "jet_a1": False,
            "conditions": base, "source_text": text, "amdt": None}


# --- Suggestion model -------------------------------------------------------

def test_suggestion_rejects_unknown_kind():
    with pytest.raises(ValueError):
        Suggestion(icao="LFXX", kind="bogus", detail="x")


def test_suggestion_rejects_unknown_confidence():
    with pytest.raises(ValueError):
        Suggestion(icao="LFXX", kind="other", detail="x", confidence="huge")


# --- review_records ---------------------------------------------------------

def test_planted_missing_grade_yields_suggestion():
    rec = _rec("LFXX", state="unknown", grades=[], text="Carburant : UL91 disponible")
    client = FakeClient({"LFXX": json.dumps(
        [{"kind": "missing_grade", "detail": "text says UL91 but grades empty",
          "confidence": "high"}])})
    out = review_records([rec], client=client, model="test")
    assert len(out) == 1
    assert out[0].kind == "missing_grade" and out[0].icao == "LFXX"


def test_clean_record_yields_no_suggestion():
    rec = _rec("LFOK", grades=["100LL"], text="Carburant : 100 LL")
    client = FakeClient({}, default="[]")
    assert review_records([rec], client=client, model="test") == []


def test_malformed_model_output_is_dropped_not_fatal():
    rec = _rec("LFBAD", text="whatever")
    client = FakeClient({"LFBAD": "sorry, I cannot comply (no JSON here)"})
    out = review_records([rec], client=client, model="test")
    assert out == []  # dropped, no exception


def test_failing_client_is_skipped_not_fatal():
    class Boom:
        def generate(self, prompt): raise RuntimeError("model down")
    out = review_records([_rec("LFDN")], client=Boom(), model="test")
    assert out == []


def test_review_does_not_mutate_records():
    rec = _rec("LFIM", grades=["100LL"], text="Carburant : 100 LL")
    before = copy.deepcopy(rec)
    client = FakeClient({"LFIM": json.dumps(
        [{"kind": "other", "detail": "note", "confidence": "low"}])})
    review_records([rec], client=client, model="test")
    assert rec == before  # advisory pass never edits the data


def test_unknown_kind_in_response_maps_to_other():
    rec = _rec("LFZZ", text="x")
    client = FakeClient({"LFZZ": json.dumps(
        [{"kind": "hallucinated_kind", "detail": "d"}])})
    out = review_records([rec], client=client, model="test")
    assert out[0].kind == "other"


# --- prompt hardening (25.5) ------------------------------------------------

def test_prompt_carries_antihallucination_rules():
    # Lock in the rules learned from the 3B false-positive run, so a future edit
    # can't silently drop them.
    rec = _rec("LFAF", grades=["100LL"], text="Carburants / Fuel : 100 LL, Carte TOTAL.",
               brand="TOTAL")
    p = llm_review.build_prompt(rec)
    low = p.lower()
    # Scope is grades + fuel state only; brand/contact are out.
    assert "jet a-1 is not an avgas grade" in low
    assert "lubrifiant" in low                         # lubricant NIL is not fuel NIL
    assert "already contains" in low                   # don't re-report parsed values
    assert "never invent a grade" in low
    # The parsed fields are shown so the model can compare.
    assert "LFAF" in p


def test_default_model_is_qwen3_8b():
    # Chosen by benchmark: best FP/recall balance among CI-runnable models.
    assert llm_review.DEFAULT_MODEL == "qwen3:8b"


def test_suggestion_kinds_are_narrowed_to_grade_and_state():
    # missed_brand/missed_contact were dropped (all false positives in 2 runs).
    assert set(llm_review.SUGGESTION_KINDS) == {"missing_grade", "wrong_state", "other"}


# --- reporting --------------------------------------------------------------

def test_group_by_kind_and_render():
    sugg = [
        Suggestion("LFAA", "missing_grade", "a"),
        Suggestion("LFBB", "missing_grade", "b"),
        Suggestion("LFCC", "wrong_state", "c"),
    ]
    grouped = llm_review.group_by_kind(sugg)
    assert len(grouped["missing_grade"]) == 2 and len(grouped["wrong_state"]) == 1
    md = llm_review.render_suggestions_markdown(sugg, model="test")
    assert "missing_grade (2)" in md and "wrong_state (1)" in md
    assert "advisory" in md.lower()


def test_render_empty_suggestions():
    md = llm_review.render_suggestions_markdown([], model="test")
    assert "No discrepancies" in md


def test_write_suggestions_json(tmp_path):
    path = tmp_path / "out" / "suggestions.json"
    llm_review.write_suggestions([Suggestion("LFAA", "other", "d", "low")], str(path))
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == [{"icao": "LFAA", "kind": "other", "detail": "d", "confidence": "low"}]
