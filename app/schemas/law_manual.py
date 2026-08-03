from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


SUPPORTED_LAW_NAMES = (
    "산업안전보건법",
    "산업안전보건법 시행령",
    "중대재해 처벌 등에 관한 법률",
    "중대재해 처벌 등에 관한 법률 시행령",
)

LAW_NAME_ALIASES = {
    "산안법": "산업안전보건법",
    "산안법 시행령": "산업안전보건법 시행령",
    "산업안전보건법": "산업안전보건법",
    "산업안전보건법 시행령": "산업안전보건법 시행령",
    "중처법": "중대재해 처벌 등에 관한 법률",
    "중처법 시행령": "중대재해 처벌 등에 관한 법률 시행령",
    "중대재해처벌법": "중대재해 처벌 등에 관한 법률",
    "중대재해처벌법 시행령": "중대재해 처벌 등에 관한 법률 시행령",
    "중대재해 처벌 등에 관한 법률": "중대재해 처벌 등에 관한 법률",
    "중대재해 처벌 등에 관한 법률 시행령": (
        "중대재해 처벌 등에 관한 법률 시행령"
    ),
}

LawManualOperation = Literal[
    "search_law_articles",
    "get_law_article",
    "get_law_overview",
    "compare_law_articles",
]


def canonical_law_name(value: str) -> str:
    normalized = " ".join(value.strip().split())
    return LAW_NAME_ALIASES.get(normalized, normalized)


class LawManualQuery(BaseModel):
    operation: LawManualOperation
    law_names: List[str] = Field(default_factory=list, max_length=4)
    keyword: Optional[str] = Field(default=None, min_length=1, max_length=200)
    article_number: Optional[int] = Field(default=None, gt=0)
    article_branch: int = Field(default=0, ge=0, le=99)
    limit: int = Field(default=5, ge=1, le=10)

    @model_validator(mode="before")
    @classmethod
    def normalize_law_names(cls, value: Any):
        if not isinstance(value, dict):
            return value
        data = dict(value)
        raw_names = data.get("law_names") or []
        if isinstance(raw_names, str):
            raw_names = [raw_names]
        normalized_names = []
        for raw_name in raw_names:
            if not isinstance(raw_name, str):
                continue
            law_name = canonical_law_name(raw_name)
            if law_name in SUPPORTED_LAW_NAMES and law_name not in normalized_names:
                normalized_names.append(law_name)
        data["law_names"] = normalized_names
        return data

    @model_validator(mode="after")
    def validate_operation_requirements(self):
        if self.operation == "get_law_article":
            if len(self.law_names) != 1 or self.article_number is None:
                raise ValueError(
                    "특정 조문 조회에는 법령명 하나와 조문번호가 필요합니다."
                )
        if self.operation == "search_law_articles" and not self.keyword:
            raise ValueError("관련 조문 검색에는 검색어가 필요합니다.")
        if self.operation == "compare_law_articles":
            if len(self.law_names) < 2 or not self.keyword:
                raise ValueError(
                    "법령 비교에는 둘 이상의 법령명과 비교 주제가 필요합니다."
                )
        return self


class LawManualPlan(BaseModel):
    queries: List[LawManualQuery] = Field(min_length=1, max_length=3)
