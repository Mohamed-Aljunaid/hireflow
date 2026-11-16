import pytest

from app.agents.claim_checker import (
    Unit,
    check_claims,
    deterministic_problems,
    drop_bullets,
    feedback_lines,
)
from app.agents.schemas.content import ClaimCheck, ClaimFinding, TailoredBullet, TailoredBullets
from app.agents.schemas.cv import ParsedCV
from app.agents.schemas.research import CompanyBrief, CompanyFact
from tests.fakes import FakeLLMClient, all_supported, flag_units, sample_extraction

CV_INDEX = {"exp-1.b2": "Cut p95 latency 40% by introducing Redis caching.", "exp-1": "Role"}
FACTS = {"co-1": "Founded in 2015."}


def bullet(id_: str, text: str, refs: list[str]) -> Unit:
    return Unit(id_, text, refs, [], needs_cv_ref=True)


@pytest.fixture
def cv() -> ParsedCV:
    return ParsedCV.from_extraction(sample_extraction())


# ---------- deterministic layer ----------


def test_supported_unit_has_no_problems() -> None:
    units = [bullet("tb-1", "Cut p95 latency 40% with Redis.", ["exp-1.b2"])]
    assert deterministic_problems(units, CV_INDEX, FACTS) == {}


@pytest.mark.parametrize(
    ("unit", "problem"),
    [
        (bullet("tb-1", "Cut latency 90%.", ["exp-1.b2"]), "not in the cited sources: ['90']"),
        (bullet("tb-1", "Did things.", []), "cites no CV item"),
        (bullet("tb-1", "Did things.", ["exp-9"]), "cites unknown CV items ['exp-9']"),
        (Unit("p-1", "Founded 2015.", [], ["co-2"], False), "cites unknown company facts ['co-2']"),
        # A number is only allowed if the *cited* source states it:
        (bullet("tb-1", "Grew users 40%.", ["exp-1"]), "numbers not in the cited sources: ['40']"),
    ],
)  # fmt: skip
def test_deterministic_catches(unit: Unit, problem: str) -> None:
    found = deterministic_problems([unit], CV_INDEX, FACTS)[unit.id]
    assert any(problem in p for p in found), found


def test_numbers_from_company_facts_and_thousands_separators() -> None:
    units = [
        Unit("p-1", "Since 2015 you have grown.", [], ["co-1"], False),
        bullet("tb-1", "Served 2,000,000 requests.", ["x"]),
    ]
    problems = deterministic_problems(units, {"x": "Served 2000000 requests"}, FACTS)
    assert problems == {}


def test_paragraph_may_cite_nothing() -> None:
    units = [Unit("p-1", "I would welcome a conversation.", [], [], False)]
    assert deterministic_problems(units, CV_INDEX, FACTS) == {}


# ---------- with the LLM layer ----------


async def test_llm_flags_are_merged(cv: ParsedCV) -> None:
    units = [
        bullet("tb-1", "Led migration of a monolith to FastAPI on Kubernetes.", ["exp-1.b1"]),
        bullet("tb-2", "Cut p95 latency 90%.", ["exp-1.b2"]),
    ]
    llm = FakeLLMClient(responses={ClaimCheck: flag_units({"tb-1": "Kubernetes not stated"})})

    problems = await check_claims(units, cv, None, llm, effort="high")

    assert problems["tb-1"] == ["Kubernetes not stated"]
    assert problems["tb-2"] == ["numbers not in the cited sources: ['90']"]
    assert llm.calls[0].effort == "high"
    # The checker sees each unit with the full text of what it cites.
    assert "[exp-1.b1] Led migration of a monolith" in llm.calls[0].user


async def test_unit_skipped_by_llm_counts_as_unsupported(cv: ParsedCV) -> None:
    units = [bullet("tb-1", "Built HL7 pipeline.", ["exp-2.b1"]), bullet("tb-2", "x", ["exp-1"])]
    only_first = ClaimCheck(findings=[ClaimFinding(unit_id="tb-1", supported=True)])
    llm = FakeLLMClient(responses={ClaimCheck: only_first})

    problems = await check_claims(units, cv, None, llm)

    assert problems == {"tb-2": ["not verified by the claim checker"]}


async def test_unknown_unit_ids_from_llm_ignored(cv: ParsedCV) -> None:
    findings = ClaimCheck(
        findings=[
            ClaimFinding(unit_id="tb-1", supported=True),
            ClaimFinding(unit_id="tb-77", supported=False, problems=["?"]),
        ]
    )
    llm = FakeLLMClient(responses={ClaimCheck: findings})
    assert await check_claims([bullet("tb-1", "x", ["exp-1"])], cv, None, llm) == {}


async def test_unsupported_without_reason_gets_default(cv: ParsedCV) -> None:
    findings = ClaimCheck(findings=[ClaimFinding(unit_id="tb-1", supported=False)])
    llm = FakeLLMClient(responses={ClaimCheck: findings})
    problems = await check_claims([bullet("tb-1", "x", ["exp-1"])], cv, None, llm)
    assert problems == {"tb-1": ["not supported by the cited sources"]}


async def test_company_facts_resolved_from_brief(cv: ParsedCV) -> None:
    brief = CompanyBrief(
        company="N",
        summary="s",
        facts=[CompanyFact(id="co-1", text="Founded in 2015.", category="other", source_id="x")],
    )
    llm = FakeLLMClient(responses={ClaimCheck: all_supported})
    units = [Unit("p-1", "Founded in 2015, you...", [], ["co-1"], False)]

    assert await check_claims(units, cv, brief, llm) == {}
    assert "[co-1] Founded in 2015." in llm.calls[0].user


async def test_no_units_no_llm_call(cv: ParsedCV) -> None:
    llm = FakeLLMClient()
    assert await check_claims([], cv, None, llm) == {}
    assert llm.calls == []


# ---------- helpers ----------


def test_feedback_lines_and_drop() -> None:
    tailored = TailoredBullets(
        bullets=[
            TailoredBullet(id="tb-1", text="ok", source_cv_refs=["a"]),
            TailoredBullet(id="tb-2", text="bad", source_cv_refs=["b"]),
        ]
    )
    units = [bullet(b.id, b.text, b.source_cv_refs) for b in tailored.bullets]
    problems = {"tb-2": ["p1", "p2"]}

    assert feedback_lines(units, problems) == ['[tb-2] "bad" -> p1; p2']
    dropped = drop_bullets(tailored, problems)
    assert [b.id for b in dropped.bullets] == ["tb-1"]
    assert dropped.warnings == [
        "Removed bullet tb-2 after rewrites still failed the claim check: p1; p2"
    ]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Cut p95 latency 40% on EC2 and S3 with K8s.", {"40"}),  # identifiers ignored
        ("Built an HL7 pipeline.", set()),
        ("Served 2M requests/day, 2,000 rps, 3.5x faster.", {"2", "2000", "3.5"}),
        ("Python 3.12 since 2019", {"3.12", "2019"}),  # versions are real claims
    ],
)
def test_numbers_ignores_identifier_digits(text: str, expected: set[str]) -> None:
    from app.agents.claim_checker import numbers

    assert numbers(text) == expected
