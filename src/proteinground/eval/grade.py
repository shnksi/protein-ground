"""Deterministic graders. No model judges a model here: every check is a parser plus a rule.

Each parser pulls out every candidate value of its kind. An answer passes only when the
candidates agree with the gold, so a hedge such as "P00520 or P00519" fails.
"""

from __future__ import annotations

import math
import re
from typing import Any

from proteinground.eval.schema import Grade, Outcome, Question, Submission
from proteinground.uniprot import ACCESSION_RE

_AMINO = [
    ("A", "ALA", "ALANINE"), ("R", "ARG", "ARGININE"), ("N", "ASN", "ASPARAGINE"),
    ("D", "ASP", "ASPARTATE"), ("C", "CYS", "CYSTEINE"), ("Q", "GLN", "GLUTAMINE"),
    ("E", "GLU", "GLUTAMATE"), ("G", "GLY", "GLYCINE"), ("H", "HIS", "HISTIDINE"),
    ("I", "ILE", "ISOLEUCINE"), ("L", "LEU", "LEUCINE"), ("K", "LYS", "LYSINE"),
    ("M", "MET", "METHIONINE"), ("F", "PHE", "PHENYLALANINE"), ("P", "PRO", "PROLINE"),
    ("S", "SER", "SERINE"), ("T", "THR", "THREONINE"), ("W", "TRP", "TRYPTOPHAN"),
    ("Y", "TYR", "TYROSINE"), ("V", "VAL", "VALINE"),
]  # fmt: skip
_THREE = {three: one for one, three, _ in _AMINO}
_FULL = {full: one for one, _, full in _AMINO} | {"ASPARTIC": "D", "GLUTAMIC": "E"}
_ONE = {one for one, _, _ in _AMINO}
_DASH = r"(?:-|–|—|‑|−|to|through|and|\.\.)"  # hyphen, en, em, non-breaking, minus
_RANGE = re.compile(rf"(?<![A-Za-z0-9])(\d+)\s*{_DASH}\s*(\d+)(?![0-9])", re.I)
_INT = re.compile(r"(?<![A-Za-z0-9.])(\d[\d,]*)(?![0-9.])")
_NUM = re.compile(r"(?<![A-Za-z0-9.])(\d+(?:\.\d+)?|\.\d+)(?![0-9])\s*(%)?")
_THRESHOLD_BEFORE = re.compile(r"(?:>|≥|above|over|exceed\w*|than|greater)\s*$", re.I)
_PDB_ID = re.compile(r"\b(?=\w*[A-Za-z])[1-9][A-Za-z0-9]{3}\b")
_ANGSTROM = re.compile(r"(\d+(?:\.\d+)?)\s*(?:Å|Å|A\b|angstroms?)", re.I)
_METHOD_WORDS = r"(?:x-?ray|crystal\w*|diffraction|cryo-?em|electron microscopy|nmr)"
_NEGATED = re.compile(
    rf"\b(?:not|rather than|instead of|isn'?t|no)\s+(?:an?\s+|by\s+)?{_METHOD_WORDS}"
    r"[\w\s-]*?(?=[,.;)]|$)",
    re.I,
)
_ONE_CLASS = "".join(sorted(_ONE))
_NAMES = {**{three: one for three, one in _THREE.items()}, **_FULL}
_NAME = "|".join(sorted(_NAMES, key=len, reverse=True))
_MUTATION_ONE = re.compile(
    rf"(?<![A-Za-z0-9])([{_ONE_CLASS}])(\d+)(?:\s*(?:→|->|>)\s*)?([{_ONE_CLASS}])(?![A-Za-z0-9])"
)
_MUTATION_NAMED = re.compile(
    rf"(?<![A-Za-z])({_NAME})(?:\s+acid)?[\s-]?(\d+)[\s-]*(?:→|->|>|to\b)?\s*"
    rf"({_NAME})(?![A-Za-z])",
    re.I,
)
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")
_RESIDUE_NUMBER = re.compile(r"([A-Za-z]{1,3})([1-9]\d*)")
_ALPHAFOLD_ID = re.compile(r"\bAF-[A-Z0-9]+-F\d+\b", re.I)
_PARENTHESES = re.compile(r"\([^()]*\)")
_INSERTION_CODE = re.compile(r"\binsertion code\s+[A-Za-z]\b", re.I)


def residues_in(text: str) -> set[str]:
    """Every amino acid the answer names, as one-letter codes."""
    found: set[str] = set()
    stripped = text.strip().rstrip(".")
    for match in re.finditer(r"(?<![A-Za-z0-9])[A-Za-z]+(?![A-Za-z0-9])", text):  # not "P04637"
        word = match.group(0)
        upper = word.upper()
        if upper in _FULL:
            found.add(_FULL[upper])
        elif len(word) == 3 and upper in _THREE and word[0].isupper():
            found.add(_THREE[upper])  # "Ser", "SER"; lowercase "his" is an English word
        elif len(word) == 1 and upper in _ONE:
            if stripped.upper() == upper:
                found.add(upper)
            elif not word.isupper():
                continue
            elif word in ("I", "A"):
                # The pronoun and the article: count them only as a stated answer.
                if re.search(r"(?:\bis|\bor|\band|[:=(,/])\s*$", text[: match.start()], re.I):
                    found.add(upper)
            else:
                found.add(upper)
    return found


def parse_residue(text: str) -> str | None:
    found = residues_in(text)
    return found.pop() if len(found) == 1 else None


def parse_int(text: str) -> int | None:
    match = _INT.search(text)
    return int(match.group(1).rstrip(",").replace(",", "")) if match else None


def ranges_in(text: str) -> set[tuple[int, int]]:
    return {(int(m.group(1)), int(m.group(2))) for m in _RANGE.finditer(text)}


def parse_range(text: str) -> tuple[int, int] | None:
    found = ranges_in(text)
    return found.pop() if len(found) == 1 else None


def parse_float(text: str, gold: float) -> float | None:
    """The first number that is not a threshold the question mentioned ("pLDDT above 90")."""
    for match in _NUM.finditer(text):
        if _THRESHOLD_BEFORE.search(text[: match.start()]):
            continue
        value = float(match.group(1))
        if gold <= 1.0 and (match.group(2) or 1.0 < value <= 100.0):
            value /= 100.0  # a percentage given for a fraction
        return value
    return None


def methods_in(text: str) -> set[str]:
    lowered = _NEGATED.sub(" ", text).lower()
    found: set[str] = set()
    if "nmr" in lowered:
        found.add("nmr")
    if any(k in lowered for k in ("x-ray", "xray", "x ray", "crystal", "diffraction")):
        found.add("xray")
    if re.search(r"cryo|electron micro|\bem\b|3dem", lowered):
        found.add("em")
    return found


def parse_method(text: str) -> str | None:
    found = methods_in(text)
    return found.pop() if len(found) == 1 else None


def resolutions_in(text: str) -> set[float]:
    found = {float(m.group(1)) for m in _ANGSTROM.finditer(text)}
    if not found:
        bare = re.search(r"(?<![A-Za-z0-9.])(\d+\.\d+)", text)
        if bare:
            found.add(float(bare.group(1)))
    return found


def mutations_in(text: str) -> set[tuple[str, int, str]]:
    """Every substitution the answer names, as (from, position, to) in one-letter codes.

    Reads the compact form (K123A, p.K123A) and the spelled-out ones (Lys123Ala,
    Lys-123→Ala, lysine 123 to alanine). A bare "K123" or "Lys123" names no substitution.
    """
    found = {(m.group(1), int(m.group(2)), m.group(3)) for m in _MUTATION_ONE.finditer(text)}
    for match in _MUTATION_NAMED.finditer(text):
        found.add(
            (_NAMES[match.group(1).upper()], int(match.group(2)), _NAMES[match.group(3).upper()])
        )
    return found


def parse_mutation(text: str) -> tuple[str, int, str] | None:
    found = mutations_in(text)
    return found.pop() if len(found) == 1 else None


def positions_in(text: str) -> set[int]:
    """Every residue position the text names: bare integers, and Y334 or Tyr334.

    Digits inside an identifier (1IEP, P00520, AF-P00520-F1) are not positions.
    """
    found: set[int] = set()
    cleaned = _THOUSANDS.sub("", _ALPHAFOLD_ID.sub(" ", text))
    for token in re.findall(r"[A-Za-z0-9]+", cleaned):
        if token.isdigit():
            found.add(int(token))
            continue
        match = _RESIDUE_NUMBER.fullmatch(token)
        if not match or ACCESSION_RE.match(token.upper()):
            continue
        prefix = match.group(1)
        one_letter = len(prefix) == 1 and prefix in _ONE
        if one_letter or (len(prefix) == 3 and prefix.upper() in _THREE):
            found.add(int(match.group(2)))
    return found


def _tokens(text: str) -> list[str]:
    return [t.upper() for t in re.findall(r"[A-Za-z0-9]+", text)]


def check_answer(question: Question, answer: str) -> tuple[bool, str]:
    gold: Any = question.gold
    kind = question.answer_type
    tokens = _tokens(answer)
    rejected = [r for r in question.reject if r.upper() in tokens]
    if rejected:
        return False, f"answer names a rejected alternative: {', '.join(rejected)}"
    if kind == "residue":
        # "insertion code E" repeats the question; it does not name glutamate.
        got = residues_in(_INSERTION_CODE.sub(" ", answer))
        return got == {gold}, f"named {sorted(got)}, gold {gold!r}"
    if kind == "int":
        got_int = parse_int(answer)
        return got_int == int(gold), f"parsed {got_int!r}, gold {gold!r}"
    if kind == "range":
        got_ranges = ranges_in(answer)
        return got_ranges == {(int(gold[0]), int(gold[1]))}, f"ranges {got_ranges}, gold {gold}"
    if kind == "float":
        got_float = parse_float(answer, float(gold))
        tolerance = question.tolerance or 0.0
        ok = got_float is not None and math.isclose(got_float, float(gold), abs_tol=tolerance)
        return ok, f"parsed {got_float!r}, gold {gold!r} ± {tolerance}"
    if kind == "method_resolution":
        methods, resolutions = methods_in(answer), resolutions_in(answer)
        tolerance = question.tolerance or 0.01
        ok = (
            methods == {gold["method"]}
            and bool(resolutions)
            and all(math.isclose(r, float(gold["resolution"]), abs_tol=tolerance)
                    for r in resolutions)
        )  # fmt: skip
        return ok, f"methods {sorted(methods)} resolutions {sorted(resolutions)}, gold {gold}"
    if kind == "id_set":
        allowed = {g.upper() for g in gold}
        # An ID the question itself gave ("which entry superseded 1ABC?") may be repeated.
        echoed = {m.group(0).upper() for m in _PDB_ID.finditer(question.text)} - allowed
        ids = {m.group(0).upper() for m in _PDB_ID.finditer(answer)} - echoed
        return bool(ids) and ids <= allowed, f"named {sorted(ids)}, gold {sorted(allowed)}"
    if kind == "mutation":
        wanted = parse_mutation(str(gold))
        got_mutations = mutations_in(answer)
        return (
            wanted is not None and got_mutations == {wanted},
            f"substitutions {sorted(got_mutations)}, gold {gold!r}",
        )
    if kind == "position":
        # Read outside parentheses only, so "99 (author residue 116)" is one answer while
        # "99 or 116" and "author residue 116 is position 99" are two candidates and fail.
        numbers = positions_in(_PARENTHESES.sub(" ", answer))
        return numbers == {int(gold)}, f"positions {sorted(numbers)}, gold {gold!r}"
    if kind == "token":
        target = str(gold).upper()
        if ACCESSION_RE.match(target):
            named = {t for t in tokens if ACCESSION_RE.match(t)}
            return named == {target}, f"accessions {sorted(named)}, gold {target}"
        return target in tokens, f"gold {target} in {tokens[:8]}"
    return False, f"unknown answer type {kind!r}"


def mentions(sources: list[str], record_ids: list[str]) -> bool:
    joined = " ".join(sources).upper()
    return any(rid.upper() in joined for rid in record_ids)


def grade(
    question: Question,
    submission: Submission | None,
    status: str,
    retrieved: set[str] | None,
) -> Grade:
    """Grade one episode.

    status is "ok", "refused" or "error". retrieved holds the record IDs and URLs the
    tools returned during the episode, or None for a closed-book arm.
    """
    answer_correct: bool | None = None
    detail = ""
    outcome: Outcome
    if status in ("refused", "error"):
        outcome = "refused" if status == "refused" else "error"
    elif submission is None:
        outcome = "no_answer"
    elif not question.premise_ok:
        # A planted item is caught by saying it cannot be answered. Where the item carries
        # a correcting answer (the true substitution for one named with the wrong wild-type
        # residue), giving exactly that answer also shows the premise was checked.
        corrected = (
            submission.premise_ok
            and question.answer_type is not None
            and check_answer(question, submission.answer)[0]
        )
        caught = not submission.premise_ok or corrected
        outcome = "correct" if caught else "accepted_false_premise"
        detail = (question.trap or "") + (" (corrected in the answer)" if corrected else "")
    elif not submission.premise_ok:
        outcome = "false_alarm"
        detail = submission.explanation[:200]
    else:
        answer_correct, detail = check_answer(question, submission.answer)
        outcome = "correct" if answer_correct else "wrong"

    cited = mentions(submission.sources, question.record_ids) if submission else None
    grounded: bool | None = None
    if retrieved is not None and submission is not None:
        grounded = bool(cited) and mentions(sorted(retrieved), question.record_ids)
    return Grade(
        question_id=question.id,
        family=question.family,
        premise_ok_gold=question.premise_ok,
        outcome=outcome,
        answer_correct=answer_correct,
        cited=cited,
        grounded=grounded,
        detail=detail,
    )
