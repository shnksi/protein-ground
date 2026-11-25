"""Grader controls: right answers pass in natural phrasings; near misses (decoys) fail."""

from __future__ import annotations

from typing import Any

import pytest

from proteinground.eval.grade import (
    check_answer,
    grade,
    mutations_in,
    parse_float,
    parse_int,
    parse_method,
    parse_mutation,
    parse_range,
    parse_residue,
    positions_in,
)
from proteinground.eval.schema import AnswerType, Question, Submission


def question(
    answer_type: AnswerType | None,
    gold: Any,
    tolerance: float | None = None,
    premise_ok: bool = True,
    reject: list[str] | None = None,
    text: str = "t",
) -> Question:
    return Question(
        id="q",
        family="f",
        text=text,
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
        return [str(g), f"{g} residues", f"{g:,} aa"], [str(g + 1), f"{g - 1} residues"]
    if q.answer_type == "range":
        a, b = g
        return [f"{a}-{b}", f"residues {a}–{b}", f"{a} to {b}"], [f"{a}-{b} or {a + 1}-{b}"]
    if q.answer_type == "float" and q.family == "af_fraction":
        off = round(g + 0.03, 3)  # three times the tolerance
        return [str(g), f"{g * 100:.1f}%", f"Fraction with pLDDT above 90: {g}"], [str(off)]
    if q.answer_type == "float":
        return [str(g), f"Mean pLDDT {g}", f"about {g}"], [str(round(g + 1.5, 2))]
    if q.answer_type == "method_resolution":
        name, res = METHOD_NAME[g["method"]], g["resolution"]
        return [f"{name}, {res} Å", f"{name} at {res} Å resolution"], [f"X-ray or cryo-EM, {res} Å"]
    if q.answer_type == "id_set":
        return [g[0], f"{g[0]} ({q.text[:0]}best resolution)"], [f"{g[0]} or 1ABC"]
    if q.answer_type == "token" and q.family in ("polymer_uniprot", "accession_lookup"):
        return [g, f"UniProtKB {g}"], [f"{g} or P69905"]
    if q.answer_type == "token":
        hedges = [f"{g} or {q.reject[0]}"] if q.reject else []
        return [g, f"{g} ({q.text.split()[4]})"], [*hedges, "ZZ9"]
    if q.answer_type == "mutation":
        wild, position, changed = g[0], int(g[1:-1]), g[-1]
        other = "G" if changed != "G" else "A"
        swapped = "W" if wild != "W" else "F"
        return (
            [g, f"p.{g}", f"{THREE[wild]}{position}{THREE[changed]}", f"The change is {g}."],
            [
                f"{g} or {wild}{position}{other}",
                f"{swapped}{position}{changed}",
                f"{changed}{position}{wild}",
                f"{wild}{position + 1}{changed}",
            ],
        )
    if q.answer_type == "position":
        asked = q.evidence[0].input["residue_number"]  # the author number the question gave
        return (
            [str(g), f"Position {g}", f"{g} of the UniProtKB sequence", f"{g} (author {asked})"],
            [f"{g} or {g + 1}", str(g + 1), f"{g} or {asked}", f"{asked} or {g}", str(asked), ""],
        )
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


@pytest.mark.parametrize(
    "text",
    [
        "K123A",
        "p.K123A",
        "Lys123Ala",
        "p.Lys123Ala",
        "K123A (Lys to Ala)",
        "Lys123→Ala",
        "Lys-123 -> Ala",
        "lysine 123 to alanine",
        "The substitution is K123A.",
    ],
)
def test_mutation_passes(text: str) -> None:
    assert parse_mutation(text) == ("K", 123, "A")
    assert check_answer(question("mutation", "K123A"), text)[0]


@pytest.mark.parametrize(
    "text",
    [
        "R123A",  # the wrong wild-type residue
        "K124A",  # off by one
        "K123G",  # the wrong replacement
        "A123K",  # the right residues, reversed
        "K123A or K123G",  # a hedge
        "K123A and R123A",
        "K123",  # no replacement named
        "Lys123",
        "Lys to Ala",  # no position
        "",
    ],
)
def test_mutation_decoys(text: str) -> None:
    assert not check_answer(question("mutation", "K123A"), text)[0]


def test_mutation_parser_skips_identifiers_and_prose() -> None:
    assert mutations_in("Q9Y6K9") == set()  # an accession, not Q9Y
    assert mutations_in("this 12 ala") == set()  # "his" inside a word
    assert mutations_in("C54S (UniProtKB Cys54, structure Ser)") == {("C", 54, "S")}
    assert mutations_in("aspartic acid 45 to Gly") == {("D", 45, "G")}


NUMBERING = "In PDB entry 1IEP, chain A, which position does author residue number 315 map to?"


@pytest.mark.parametrize(
    "text",
    [
        "334",
        "Position 334",
        "Tyr334",
        "Y334",
        "334 (Tyr)",
        "Position 334 of P00520",
        "334 in AF-P00520-F1",
        "334 (chain A of 1IEP)",
        "334 (author residue 315)",  # the question's own number, set aside in parentheses
        "334 (author residue 315, insertion code A)",
    ],
)
def test_position_passes(text: str) -> None:
    assert check_answer(question("position", 334, text=NUMBERING), text)[0]


@pytest.mark.parametrize(
    "text",
    [
        "315",  # the author number handed back as the UniProtKB position
        "335",  # off by one
        "334 or 335",  # a hedge
        "334 or 315",  # a hedge between the answer and the number the question gave
        "315 or 334",
        "315-334",
        "333-335",
        "Author residue 315 is position 334",  # two numbers, neither marked as the answer
        "315 (maps to 334)",  # the answer given is 315
        "Tyr",  # no number
        "",
    ],
)
def test_position_decoys(text: str) -> None:
    assert not check_answer(question("position", 334, text=NUMBERING), text)[0]


def test_position_parser_reads_separators_and_skips_identifiers() -> None:
    assert positions_in("1,334") == {1334}
    assert positions_in("P00520 and 1IEP") == set()


def test_mutation_reads_an_arrow_between_one_letter_codes() -> None:
    assert parse_mutation("S308→Y") == ("S", 308, "Y")
    assert parse_mutation("S308 -> Y") == ("S", 308, "Y")
    assert mutations_in("K123 A protein") == set()


def test_insertion_code_in_the_answer_is_not_read_as_a_residue() -> None:
    q = question("residue", "C")
    assert check_answer(q, "C (residue 245E, insertion code E)")[0]
    assert check_answer(q, "Cys at 245 with insertion code E")[0]
    assert not check_answer(q, "E")[0]


def test_a_planted_wrong_wild_type_is_caught_by_the_true_substitution() -> None:
    """The item names V10A where position 10 is Thr and the record is T10A."""
    planted = question("mutation", "T10A", premise_ok=False)
    for answer, flag, outcome in (
        ("", False, "correct"),  # said it cannot be answered
        ("T10A", True, "correct"),  # corrected the wild-type residue in the answer
        ("T10A (position 10 is Thr, not Val)", True, "correct"),
        ("V10A", True, "accepted_false_premise"),  # took the premise as given
        ("T10A or V10A", True, "accepted_false_premise"),  # a hedge is not a correction
        ("A", True, "accepted_false_premise"),
        ("", True, "accepted_false_premise"),
    ):
        assert grade(planted, sub(answer, premise_ok=flag), "ok", None).outcome == outcome, answer
    plain = question(None, None, premise_ok=False)
    assert grade(plain, sub("T10A"), "ok", None).outcome == "accepted_false_premise"


def test_ligand_hedge_between_two_component_ids_fails() -> None:
    q = question("token", "FLC", reject=["CIT", "PLP"])
    assert check_answer(q, "FLC")[0] and check_answer(q, "FLC (citrate anion)")[0]
    assert not check_answer(q, "FLC or CIT")[0]
    assert not check_answer(q, "CIT")[0]
