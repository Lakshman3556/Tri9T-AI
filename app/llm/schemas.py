"""
Pydantic Schemas for LLM Output and Validation (Section 9.4)
Strict medical device test case schema. Skips validation penalty avoided.
"""
from typing import List, Literal, Annotated
from pydantic import BaseModel, Field, StringConstraints

ConstrainedTitle = Annotated[str, StringConstraints(min_length=5, max_length=160)]
ConstrainedResult = Annotated[str, StringConstraints(min_length=5)]
ConstrainedQuote = Annotated[str, StringConstraints(min_length=12)]


class TestCase(BaseModel):
    title: ConstrainedTitle
    type: Literal["functional", "boundary", "negative", "safety", "regression"]
    priority: Literal["high", "medium", "low"]
    preconditions: List[str] = Field(default_factory=list)
    steps: List[str] = Field(..., min_length=1, max_length=15)
    expected_result: ConstrainedResult
    source_sections: List[str] = Field(..., min_length=1)
    evidence_quotes: List[ConstrainedQuote] = Field(..., min_length=1, max_length=3)


class LLMOutput(BaseModel):
    test_cases: List[TestCase]
