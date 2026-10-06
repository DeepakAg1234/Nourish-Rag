"""Refuse medical advice, personal calorie targets, and weight targets in code.

The answer model is not asked to refuse. Out-of-scope questions stop here,
before retrieval. Published population figures stay available to search.
"""

from __future__ import annotations

import re
from collections.abc import Callable

OUT_OF_SCOPE = "out_of_scope"
IN_SCOPE = "in_scope"
IN_SCOPE_POPULATION_GUIDANCE = "in_scope_population_guidance"

# Fixed decline. No citation and no document list, so the model cannot soften it.
OUT_OF_SCOPE_MESSAGE = (
    "This assistant does not give medical advice, personal calorie targets, "
    "or weight targets. Please speak with a qualified professional."
)

# Substrings, matched on the case-folded question. A disease, a drug, or a
# request for a personal diet because of illness is medical advice.
_MEDICAL_PHRASES: tuple[str, ...] = (
    "diabetes",
    "diabetic",
    "diagnosis",
    "diagnose",
    "diagnosed",
    "medication",
    "medications",
    "medicine",
    "medicines",
    "prescription",
    "prescribed",
    "symptom",
    "symptoms",
    "cancer",
    "tumour",
    "tumor",
    "hypertension",
    "what diet should i follow",
    "what should i take",
    "insulin",
    "blood sugar",
)

# Personal calorie target, deficit, or budget. "calorie figures" that a
# document publishes do not match these.
_PERSONAL_CALORIE = re.compile(
    r"(?:"
    r"\b(?:calories?|kcal|caloric)\b.{0,48}\b(?:should\s+i|do\s+i|i\s+should|my|me|deficit|budget)\b"
    r"|"
    r"\b(?:should\s+i|do\s+i|my|deficit|budget)\b.{0,48}\b(?:calories?|kcal|caloric)\b"
    r"|"
    r"\bhow many (?:calories|kcal)\b.{0,48}\b(?:i|my|me|lose|gain)\b"
    r"|"
    r"\b(?:calorie|kcal|caloric) (?:deficit|budget|target)\b"
    r")"
)

# What anyone should weigh, a goal weight, or how much weight to lose or gain.
_WEIGHT_TARGET = re.compile(
    r"(?:"
    r"\b(?:should|do|can)\s+i\s+weigh\b"
    r"|"
    r"\bwhat should (?:i|anyone|a person|someone|people) weigh\b"
    r"|"
    r"\b(?:goal|target|ideal)\s+weight\b"
    r"|"
    r"\bweight\s+(?:loss|gain|target|goal)\b"
    r"|"
    r"\b(?:lose|gain|losing|gaining)\s+weight\b"
    r"|"
    r"\bhow much weight\b"
    r"|"
    r"\b(?:lose|gain|losing|gaining)\s+\d+(?:\.\d+)?\s*(?:kg|kilos?|kilograms?|lb|lbs|pounds?)\b"
    r")"
)

# Published figures: energy share, salt guidance, calorie tables. Checked
# only after the personal-target rules, so a guideline name cannot rescue
# "how many calories should I eat?".
_POPULATION = re.compile(
    r"(?:"
    r"\bshare of (?:total |dietary )?energy\b"
    r"|"
    r"\b(?:proportion|percentage|percent) of (?:total |dietary )?energy\b"
    r"|"
    r"\benergy intake\b"
    r"|"
    r"\bof total energy\b"
    r"|"
    r"\bcalorie figures\b"
    r"|"
    r"\b(?:calories?|kcal)\b.{0,60}\bpublish"
    r"|"
    r"\bpublish(?:ed|es)?\b.{0,60}\b(?:calories?|kcal)\b"
    r"|"
    r"\bpopulation\b"
    r"|"
    r"\bage[- ]bands?\b"
    r"|"
    r"\bfree sugars?\b"
    r"|"
    r"\bsalt\b.{0,48}\b(?:intake|limit|recommendation|recommended|a day|per day|5\s*g)\b"
    r"|"
    r"\b(?:under|less than|below)\s+5\s*g\b"
    r")"
)


def classify(question: str) -> str:
    """Return out_of_scope, in_scope, or in_scope_population_guidance."""
    folded = " ".join(question.casefold().split())
    if _is_out_of_scope(folded):
        return OUT_OF_SCOPE
    if _POPULATION.search(folded):
        return IN_SCOPE_POPULATION_GUIDANCE
    return IN_SCOPE


def screen(question: str, retrieve_fn: Callable[..., list] | None = None) -> dict:
    """Classify, and call retrieve_fn only when the question is in scope.

    Out of scope returns the fixed template and does not call retrieve_fn.
    """
    decision = classify(question)
    if decision == OUT_OF_SCOPE:
        return {
            "decision": OUT_OF_SCOPE,
            "message": OUT_OF_SCOPE_MESSAGE,
            "chunks": None,
        }
    chunks = None if retrieve_fn is None else retrieve_fn(question)
    return {"decision": decision, "message": None, "chunks": chunks}


def _is_out_of_scope(folded: str) -> bool:
    if any(phrase in folded for phrase in _MEDICAL_PHRASES):
        return True
    if _PERSONAL_CALORIE.search(folded):
        return True
    if _WEIGHT_TARGET.search(folded):
        return True
    return False
