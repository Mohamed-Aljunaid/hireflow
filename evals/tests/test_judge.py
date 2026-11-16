from pydantic import BaseModel

from evals.judge import FabricationJudgment, UnitJudgment, judge_units

CV = "Cut p95 latency 40% by introducing Redis caching. Built HL7 pipelines."
JOB = "We are a team of 12 in Lisbon."


class FakeJudge:
    def __init__(self, judgment: FabricationJudgment) -> None:
        self.judgment, self.prompts = judgment, []

    async def structured(self, *, system, user, output_model: type[BaseModel], effort=None):
        self.prompts.append(user)
        return self.judgment


def judgment(**claims: list[str]) -> FabricationJudgment:
    return FabricationJudgment(
        units=[
            UnitJudgment(unit_id=k.replace("_", "-"), unsupported_claims=v)
            for k, v in claims.items()
        ]
    )


async def test_clean_units_have_no_claims_and_prompt_has_raw_sources() -> None:
    llm = FakeJudge(judgment(tb_1=[], p_1=[]))
    units = {"tb-1": "Cut p95 latency 40% with Redis.", "p-1": "Your team of 12 sounds great."}

    assert await judge_units(units, CV, JOB, llm) == {"tb-1": [], "p-1": []}
    assert "<cv>\n" + CV in llm.prompts[0] and "[tb-1] Cut p95 latency" in llm.prompts[0]


async def test_judge_claims_and_code_number_check_are_combined() -> None:
    llm = FakeJudge(judgment(tb_1=["Kubernetes is not on the CV"], tb_2=[]))
    units = {"tb-1": "Ran Redis on Kubernetes.", "tb-2": "Cut latency 70%."}

    result = await judge_units(units, CV, JOB, llm)

    assert result["tb-1"] == ["Kubernetes is not on the CV"]
    assert result["tb-2"] == ["numbers not in the CV or posting: ['70']"]


async def test_unit_skipped_by_judge_counts_as_fabricated() -> None:
    llm = FakeJudge(judgment(tb_1=[]))
    result = await judge_units({"tb-1": "ok", "tb-2": "also ok"}, CV, JOB, llm)
    assert result["tb-2"] == ["not judged (judge skipped this unit)"]


async def test_no_units_no_call() -> None:
    llm = FakeJudge(judgment())
    assert await judge_units({}, CV, JOB, llm) == {}
    assert llm.prompts == []
