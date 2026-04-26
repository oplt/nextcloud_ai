import pytest

from backend.services.query_writer import plan_retrieval_query


class _FailingLLM:
    async def generate(self, prompt: str) -> str:
        raise AssertionError("self-contained questions should not be rewritten")


@pytest.mark.asyncio
async def test_self_contained_question_is_not_rewritten_from_bad_history() -> None:
    plan = await plan_retrieval_query(
        question="where did the supplier work",
        history=[
            {"role": "user", "content": "where did the supplier work in 2005"},
            {
                "role": "assistant",
                "content": "I could not verify the location prior to 2005.",
            },
        ],
        llm_client=_FailingLLM(),
    )

    assert plan.retrieval_query == "where did the supplier work"
    assert plan.is_follow_up is False
