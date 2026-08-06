import re
from typing import Any, Iterable

from app.schemas.law_manual import (
    SUPPORTED_LAW_NAMES,
    LawManualQuery,
)
from app.tools.law_api_client import LawApiResponseError, law_corpus_cache


SEARCH_STOP_WORDS = {
    "관련",
    "근거",
    "내용",
    "알려줘",
    "알려주세요",
    "무엇",
    "뭐야",
    "어떻게",
    "대한",
    "관한",
    "법령",
    "법률",
    "시행령",
    "조항",
}


def _search_tokens(keyword: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[가-힣A-Za-z0-9]+", keyword)
        if len(token) >= 2 and token not in SEARCH_STOP_WORDS
    ]


def _article_score(article: dict[str, Any], keyword: str) -> int:
    normalized_keyword = " ".join(keyword.split()).lower()
    title = str(article.get("article_title", "")).lower()
    content = str(article.get("content", "")).lower()
    score = 0
    if normalized_keyword and normalized_keyword in title:
        score += 20
    if normalized_keyword and normalized_keyword in content:
        score += 12
    for token in _search_tokens(keyword):
        normalized_token = token.lower()
        if normalized_token in title:
            score += 8
        occurrences = content.count(normalized_token)
        score += min(occurrences, 5) * 2
    return score


def _selected_law_names(query: LawManualQuery) -> list[str]:
    return query.law_names or list(SUPPORTED_LAW_NAMES)


def _article_evidence(article: dict[str, Any]) -> dict[str, Any]:
    content = str(article.get("content", ""))
    delegation_targets = [
        target
        for target in ("대통령령", "고용노동부령", "총리령", "부령")
        if target in content
    ]
    return {
        "law_name": article.get("law_name", ""),
        "law_id": article.get("law_id", ""),
        "law_type": article.get("law_type", ""),
        "article_number": article.get("article_number"),
        "article_branch": article.get("article_branch", 0),
        "article_label": article.get("article_label", ""),
        "article_title": article.get("article_title", ""),
        "content": content,
        "delegation_targets": delegation_targets,
        "paragraphs": article.get("paragraphs", []),
        "promulgation_date": article.get("promulgation_date", ""),
        "effective_date": article.get("effective_date", ""),
        "article_effective_date": article.get(
            "article_effective_date",
            "",
        ),
        "source_url": article.get("source_url", ""),
        "cache_status": article.get("cache_status", "fresh"),
    }


def _iter_articles(
    laws: dict[str, dict[str, Any]],
    law_names: Iterable[str],
) -> Iterable[dict[str, Any]]:
    for law_name in law_names:
        law = laws.get(law_name, {})
        cache_status = law.get("cache_status", "fresh")
        for article in law.get("articles", []):
            yield {**article, "cache_status": cache_status}


def _search_articles(
    laws: dict[str, dict[str, Any]],
    *,
    law_names: list[str],
    keyword: str,
    limit: int,
) -> list[dict[str, Any]]:
    scored = []
    for article in _iter_articles(laws, law_names):
        score = _article_score(article, keyword)
        if score > 0:
            scored.append((score, article))
    scored.sort(
        key=lambda item: (
            item[0],
            -int(item[1].get("article_number") or 0),
        ),
        reverse=True,
    )
    return [_article_evidence(article) for _, article in scored[:limit]]


def execute_law_manual_query(query: LawManualQuery) -> dict[str, Any]:
    laws = law_corpus_cache.get_all()
    law_names = _selected_law_names(query)

    if query.operation == "get_law_overview":
        items = []
        for law_name in law_names:
            law = laws[law_name]
            items.append(
                {
                    key: law.get(key, "")
                    for key in (
                        "law_name",
                        "law_id",
                        "law_type",
                        "promulgation_date",
                        "effective_date",
                        "ministry",
                        "source_url",
                        "cache_status",
                    )
                }
            )
            items[-1]["article_count"] = len(law.get("articles", []))
        return {
            "items": items,
            "total_items": len(items),
            "source": "national_law_open_api",
        }

    if query.operation == "get_law_article":
        law_name = law_names[0]
        for article in _iter_articles(laws, [law_name]):
            if (
                article.get("article_number") == query.article_number
                and article.get("article_branch", 0) == query.article_branch
            ):
                return _article_evidence(article)
        branch = f"의{query.article_branch}" if query.article_branch else ""
        raise LawApiResponseError(
            f"'{law_name}' 제{query.article_number}조{branch}를 찾을 수 없습니다."
        )

    if query.operation == "compare_law_articles":
        items = []
        per_law_limit = max(1, min(3, query.limit))
        for law_name in law_names:
            items.extend(
                _search_articles(
                    laws,
                    law_names=[law_name],
                    keyword=query.keyword or "",
                    limit=per_law_limit,
                )
            )
        return {
            "items": items,
            "total_items": len(items),
            "comparison_laws": law_names,
            "keyword": query.keyword,
            "source": "national_law_open_api",
        }

    items = _search_articles(
        laws,
        law_names=law_names,
        keyword=query.keyword or "",
        limit=query.limit,
    )
    return {
        "items": items,
        "total_items": len(items),
        "keyword": query.keyword,
        "source": "national_law_open_api",
    }
