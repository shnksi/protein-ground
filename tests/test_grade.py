"""Grader controls: right answers pass in natural phrasings; near misses (decoys) fail."""

from __future__ import annotations

from typing import Any

import pytest

from proteinground.eval.grade import (
    check_answer,
    grade,
    parse_float,
    parse_int,
    parse_method,
    parse_range,
    parse_residue,
)
from proteinground.eval.schema import AnswerType, Question, Submission


def question(
    answer_type: AnswerType | None,
    gold: Any,
    tolerance: float | None = None,
    premise_ok: bool = True,
    reject: list[str] | None = None,
) -> Question:
    return Question(
        id="q",
        family="f",
        text="t",
        premise_ok=premise_ok,
        answer_type=answer_type,
        gold=gold,
        tolerance=tolerance,
        record_ids=["P04637"],
        evidence=[],
        reject=reject or [],
    )


def sub(answer: str, premise_ok: bool = True, sources: list[str] | None = None) -> Submission:
    return Submission(
        premise_ok=premise_ok,
        answer=answer,
        explanation="",
        sources=sources if sources is not None else ["P04637"],
    )


@pytest.mark.parametrize("text", ["R", "r", "R (Arg)", "Arg", "Arginine", "It is arginine."])
def test_residue_passes(text: str) -> None:
    assert parse_residue(text) == "R"


@pytest.mark.parametrize("text", ["H", "His", "", "The residue at 175"])
def test_residue_decoys(text: str) -> None:
    assert parse_residue(text) != "R"


def test_int_ignores_digits_inside_accessions() -> None:
    assert parse_int("P04637 has 393 residues") == 393
    assert parse_int("1,210 aa") == 1210


def test_range_forms() -> None:
    for text in ("712-979", "712–979", "residues 712 to 979", "712..979"):
        assert parse_range(text) == (712, 979)
    assert parse_range("713-979") != (712, 979)


def test_float_handles_percentages_for_fractions() -> None:
    assert parse_float("52.7%", 0.527) == pytest.approx(0.527)
    assert parse_float("about 0.53", 0.527) == pytest.approx(0.53)
    assert parse_float("75.06", 75.06) == pytest.approx(75.06)


def test_method_categories() -> None:
    assert parse_method("X-ray diffraction, 1.74 Å") == "xray"
    assert parse_method("Cryo-EM, 2.8 Å") == "em"
    assert parse_method("solution NMR") == "nmr"


def test_method_resolution_needs_both() -> None:
    q = question("method_resolution", {"method": "xray", "resolution": 1.74}, tolerance=0.01)
    assert check_answer(q, "X-ray diffraction, 1.74 Å")[0]
    assert not check_answer(q, "Cryo-EM, 1.74 Å")[0]
    assert not check_answer(q, "X-ray, 1.8 Å")[0]


def test_id_set_takes_the_first_pdb_like_id_and_skips_years() -> None:
    q = question("id_set", ["9IAY"])
    assert check_answer(q, "9IAY (0.95 Å)")[0]
    assert check_answer(q, "Released 2026: 9IAY")[0]
    assert not check_answer(q, "6P0Z, or maybe 9IAY")[0]


def test_reject_list_fails_hedges() -> None:
    q = question("token", "P00520", reject=["P00519"])
    assert check_answer(q, "P00520")[0]
    assert not check_answer(q, "P00520 or P00519")[0]


def test_outcomes() -> None:
    answerable = question("int", 393)
    planted = question(None, None, premise_ok=False)
    assert grade(answerable, sub("393"), "ok", None).outcome == "correct"
    assert grade(answerable, sub("392"), "ok", None).outcome == "wrong"
    assert grade(answerable, sub("", premise_ok=False), "ok", None).outcome == "false_alarm"
    assert grade(planted, sub("", premise_ok=False), "ok", None).outcome == "correct"
    assert grade(planted, sub("1.9 Å"), "ok", None).outcome == "accepted_false_premise"
    assert grade(answerable, None, "ok", None).outcome == "no_answer"
    assert grade(answerable, None, "refused", None).outcome == "refused"


def test_grounding_needs_the_record_to_have_been_retrieved() -> None:
    q = question("int", 393)
    fetched = grade(
        q, sub("393"), "ok", {"P04637", "https://www.uniprot.org/uniprotkb/P04637/entry"}
    )
    assert fetched.cited and fetched.grounded
    claimed = grade(q, sub("393"), "ok", set())
    assert claimed.cited and not claimed.grounded
    closed_book = grade(q, sub("393", sources=[]), "ok", None)
    assert closed_book.cited is False and closed_book.grounded is None


THREE = {"A": "Ala", "R": "Arg", "N": "Asn", "D": "Asp", "C": "Cys", "Q": "Gln", "E": "Glu",
         "G": "Gly", "H": "His", "I": "Ile", "L": "Leu", "K": "Lys", "M": "Met", "F": "Phe",
         "P": "Pro", "S": "Ser", "T": "Thr", "W": "Trp", "Y": "Tyr", "V": "Val"}  # fmt: skip
METHOD_NAME = {"xray": "X-ray diffraction", "em": "cryo-EM", "nmr": "solution NMR"}


def natural_and_hedged(q: Question) -> tuple[list[str], list[str]]:
    """Right answers as a model might phrase them, and hedges that must fail."""
    g = q.gold
    if q.answer_type == "residue":
        other = "G" if g != "G" else "A"
        return [g, f"{g} ({THREE[g]})", f"It is {THREE[g]}."], [f"{g} or {other}"]
    if q.answer_type == "int":
        return [str(g), f"{g} residues", f"{g:,} aa"], []
    if q.answer_type == "range":
        a, b = g
        return [f"{a}-{b}", f"residues {a}–{b}", f"{a} to {b}"], [f"{a}-{b} or {a + 1}-{b}"]
    if q.answer_type == "float" and q.family == "af_fraction":
        return [str(g), f"{g * 100:.1f}%", f"Fraction with pLDDT above 90: {g}"], []
    if q.answer_type == "float":
        return [str(g), f"Mean pLDDT {g}", f"about {g}"], []
    if q.answer_type == "method_resolution":
        name, res = METHOD_NAME[g["method"]], g["resolution"]
        return [f"{name}, {res} Å", f"{name} at {res} Å resolution"], [f"X-ray or cryo-EM, {res} Å"]
    if q.answer_type == "id_set":
        return [g[0], f"{g[0]} ({q.text[:0]}best resolution)"], [f"{g[0]} or 1ABC"]
    if q.answer_type == "token" and q.family in ("polymer_uniprot", "accession_lookup"):
        return [g, f"UniProtKB {g}"], [f"{g} or P69905"]
    if q.answer_type == "token":
        hedges = [f"{g} or {q.reject[0]}"] if q.reject else []
        return [g, f"{g} ({q.text.split()[4]})"], hedges
    raise AssertionError(q.answer_type)


def test_real_items_accept_natural_answers_and_reject_hedges(questions: list[Question]) -> None:
    failures = []
    for q in questions:
        if not q.premise_ok:
            continue
        good, bad = natural_and_hedged(q)
        failures += [(q.id, a, "rejected") for a in good if not check_answer(q, a)[0]]
        failures += [(q.id, a, "accepted") for a in bad if check_answer(q, a)[0]]
    assert failures == []


def test_pronoun_and_article_are_not_residues() -> None:
    assert parse_residue("I think it is G") == "G"
    assert parse_residue("It is I (Ile)") == "I"
    assert parse_residue("A serine") == "S"
    assert parse_residue("S or T") is None


def test_float_skips_thresholds_and_keeps_percent_for_fractions_only() -> None:
    assert parse_float("Fraction with pLDDT above 90: 0.527", 0.527) == pytest.approx(0.527)
    assert parse_float("88.4%", 88.38) == pytest.approx(88.4)
    assert parse_float("pLDDT>90 for 52.7% of residues", 0.527) == pytest.approx(0.527)


def test_method_negation_and_hedges() -> None:
    q = question("method_resolution", {"method": "em", "resolution": 2.8}, tolerance=0.01)
    assert check_answer(q, "Cryo-EM, 2.8 Å (not an X-ray crystal structure)")[0]
    assert not check_answer(q, "X-ray or cryo-EM, 2.8 Å")[0]


def test_unicode_dashes_in_ranges() -> None:
    for text in ("712‑979", "712−979", "between 712 and 979"):
        assert parse_range(text) == (712, 979)
