from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from threading import RLock
from time import monotonic
from typing import Any, Callable, Iterable, Optional
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree

import httpx

from app.config import (
    LAW_API_BASE_URL,
    LAW_API_CACHE_TTL_SECONDS,
    LAW_API_OC,
    LAW_API_TIMEOUT_SECONDS,
)
from app.schemas.law_manual import SUPPORTED_LAW_NAMES


class LawApiError(RuntimeError):
    pass


class LawApiConfigurationError(LawApiError):
    pass


class LawApiResponseError(LawApiError):
    pass


def _clean_text(value: Optional[str]) -> str:
    return " ".join((value or "").split())


def _node_text(node: Optional[ElementTree.Element]) -> str:
    if node is None:
        return ""
    return _clean_text(" ".join(node.itertext()))


def _child_text(node: ElementTree.Element, tag: str) -> str:
    return _node_text(node.find(tag))


def _as_int(value: str, default: int = 0) -> int:
    normalized = value.strip()
    return int(normalized) if normalized.isdigit() else default


def _absolute_law_url(value: str) -> str:
    if not value:
        return "https://www.law.go.kr"
    parsed = urlsplit(urljoin("https://www.law.go.kr", value))
    public_query = urlencode(
        [
            (key, query_value)
            for key, query_value in parse_qsl(
                parsed.query,
                keep_blank_values=True,
            )
            if key.lower() != "oc"
        ]
    )
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, public_query, "")
    )


def _article_label(article_number: int, article_branch: int) -> str:
    suffix = f"의{article_branch}" if article_branch else ""
    return f"제{article_number}조{suffix}"


class LawApiClient:
    def __init__(
        self,
        *,
        credential: str = LAW_API_OC,
        base_url: str = LAW_API_BASE_URL,
        timeout_seconds: float = LAW_API_TIMEOUT_SECONDS,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        self._credential = credential.strip()
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    def _request_xml(
        self,
        path: str,
        *,
        params: dict[str, Any],
    ) -> ElementTree.Element:
        if not self._credential:
            raise LawApiConfigurationError(
                "국가법령정보 Open API 인증값이 설정되지 않았습니다."
            )

        request_params = {
            "OC": self._credential,
            "type": "XML",
            **params,
        }
        try:
            with httpx.Client(
                timeout=self._timeout_seconds,
                transport=self._transport,
            ) as client:
                response = client.get(
                    f"{self._base_url}/{path.lstrip('/')}",
                    params=request_params,
                )
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise LawApiError("국가법령정보 API 조회 시간이 초과되었습니다.") from exc
        except httpx.HTTPStatusError as exc:
            raise LawApiError(
                "국가법령정보 API가 조회 요청을 거부했습니다."
            ) from exc
        except httpx.HTTPError as exc:
            raise LawApiError("국가법령정보 API에 연결할 수 없습니다.") from exc

        try:
            root = ElementTree.fromstring(response.content)
        except ElementTree.ParseError as exc:
            raise LawApiResponseError(
                "국가법령정보 API 응답을 XML로 해석할 수 없습니다."
            ) from exc

        error_message = _child_text(root, "message") or _child_text(
            root,
            "resultMsg",
        )
        result_code = _child_text(root, "resultCode")
        if result_code and result_code not in {"00", "0"}:
            raise LawApiResponseError(
                error_message or "국가법령정보 API 응답이 올바르지 않습니다."
            )
        return root

    def search_current_law(self, law_name: str) -> dict[str, Any]:
        if law_name not in SUPPORTED_LAW_NAMES:
            raise LawApiError("허용되지 않은 법령입니다.")

        root = self._request_xml(
            "lawSearch.do",
            params={
                "target": "eflaw",
                "search": 1,
                "query": law_name,
                "nw": 3,
                "display": 20,
                "page": 1,
            },
        )
        matches = []
        for law_node in root.findall(".//law"):
            result_name = _child_text(law_node, "법령명한글")
            if result_name != law_name:
                continue
            history_status = _child_text(law_node, "현행연혁코드")
            if history_status and history_status != "현행":
                continue
            matches.append(
                {
                    "law_name": result_name,
                    "law_id": _child_text(law_node, "법령ID"),
                    "law_sequence": _child_text(law_node, "법령일련번호"),
                    "law_type": _child_text(law_node, "법령구분명"),
                    "promulgation_date": _child_text(law_node, "공포일자"),
                    "effective_date": _child_text(law_node, "시행일자"),
                    "ministry": _child_text(law_node, "소관부처명"),
                    "source_url": _absolute_law_url(
                        _child_text(law_node, "법령상세링크")
                    ),
                }
            )

        valid_matches = [item for item in matches if item["law_id"]]
        if not valid_matches:
            raise LawApiResponseError(
                f"현재 시행 중인 '{law_name}' 정보를 찾을 수 없습니다."
            )
        valid_matches.sort(
            key=lambda item: (
                item["effective_date"],
                item["promulgation_date"],
            ),
            reverse=True,
        )
        return valid_matches[0]

    def fetch_current_law(self, law_summary: dict[str, Any]) -> dict[str, Any]:
        law_id = str(law_summary.get("law_id", "")).strip()
        if not law_id:
            raise LawApiResponseError("법령 본문 조회에 필요한 ID가 없습니다.")

        root = self._request_xml(
            "lawService.do",
            params={"target": "eflaw", "ID": law_id},
        )
        basic_info = root.find(".//기본정보")
        actual_name = (
            _child_text(basic_info, "법령명_한글")
            if basic_info is not None
            else ""
        )
        expected_name = str(law_summary.get("law_name", ""))
        if actual_name and actual_name != expected_name:
            raise LawApiResponseError("조회된 법령명이 요청한 법령과 다릅니다.")

        articles = []
        for article_node in root.findall(".//조문단위"):
            if _child_text(article_node, "조문여부") != "조문":
                continue
            article_number = _as_int(_child_text(article_node, "조문번호"))
            article_branch = _as_int(
                _child_text(article_node, "조문가지번호")
            )
            if article_number <= 0:
                continue

            article_content = _child_text(article_node, "조문내용")
            paragraphs = []
            for paragraph_node in article_node.findall("./항"):
                paragraph = {
                    "number": _child_text(paragraph_node, "항번호"),
                    "content": _child_text(paragraph_node, "항내용"),
                    "subparagraphs": [],
                }
                for subparagraph_node in paragraph_node.findall("./호"):
                    subparagraph = {
                        "number": _child_text(subparagraph_node, "호번호"),
                        "content": _child_text(subparagraph_node, "호내용"),
                        "items": [],
                    }
                    for item_node in subparagraph_node.findall("./목"):
                        subparagraph["items"].append(
                            {
                                "number": _child_text(item_node, "목번호"),
                                "content": _child_text(item_node, "목내용"),
                            }
                        )
                    paragraph["subparagraphs"].append(subparagraph)
                paragraphs.append(paragraph)

            content_parts = [article_content]
            for content_tag in ("항내용", "호내용", "목내용"):
                content_parts.extend(
                    _node_text(content_node)
                    for content_node in article_node.findall(
                        f".//{content_tag}"
                    )
                )
            combined_content = "\n".join(
                part for part in content_parts if part
            )
            articles.append(
                {
                    **law_summary,
                    "article_number": article_number,
                    "article_branch": article_branch,
                    "article_label": _article_label(
                        article_number,
                        article_branch,
                    ),
                    "article_title": _child_text(article_node, "조문제목"),
                    "article_effective_date": _child_text(
                        article_node,
                        "조문시행일자",
                    ),
                    "content": combined_content,
                    "paragraphs": paragraphs,
                }
            )

        if not articles:
            raise LawApiResponseError(
                f"'{expected_name}' 본문에서 조문을 찾을 수 없습니다."
            )
        return {
            **law_summary,
            "law_name": actual_name or expected_name,
            "effective_date": (
                _child_text(basic_info, "시행일자")
                if basic_info is not None
                else law_summary.get("effective_date", "")
            ),
            "promulgation_date": (
                _child_text(basic_info, "공포일자")
                if basic_info is not None
                else law_summary.get("promulgation_date", "")
            ),
            "articles": articles,
        }

    def fetch_law_by_name(self, law_name: str) -> dict[str, Any]:
        return self.fetch_current_law(self.search_current_law(law_name))


class LawCorpusCache:
    def __init__(
        self,
        *,
        client_factory: Callable[[], LawApiClient] = LawApiClient,
        ttl_seconds: int = LAW_API_CACHE_TTL_SECONDS,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._client_factory = client_factory
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._lock = RLock()
        self._laws: dict[str, dict[str, Any]] = {}
        self._expires_at: dict[str, float] = {}

    def _fresh(self, law_name: str, now: float) -> bool:
        return (
            law_name in self._laws
            and self._expires_at.get(law_name, 0) > now
        )

    def _fetch_many(self, law_names: Iterable[str]) -> dict[str, dict[str, Any]]:
        names = list(dict.fromkeys(law_names))
        results: dict[str, dict[str, Any]] = {}
        errors: list[LawApiError] = []
        with ThreadPoolExecutor(max_workers=min(4, len(names))) as executor:
            futures = {
                executor.submit(
                    self._client_factory().fetch_law_by_name,
                    law_name,
                ): law_name
                for law_name in names
            }
            for future in as_completed(futures):
                law_name = futures[future]
                try:
                    results[law_name] = future.result()
                except LawApiError as exc:
                    errors.append(exc)
        if errors and not results:
            raise errors[0]
        return results

    def get_all(self) -> dict[str, dict[str, Any]]:
        now = self._clock()
        with self._lock:
            missing = [
                law_name
                for law_name in SUPPORTED_LAW_NAMES
                if not self._fresh(law_name, now)
            ]
            stale = {
                law_name: deepcopy(self._laws[law_name])
                for law_name in missing
                if law_name in self._laws
            }

        if missing:
            try:
                fetched = self._fetch_many(missing)
            except LawApiError:
                if not stale:
                    raise
                fetched = {}
            with self._lock:
                refreshed_at = self._clock()
                for law_name, law in fetched.items():
                    law["cache_status"] = "fresh"
                    self._laws[law_name] = law
                    self._expires_at[law_name] = refreshed_at + self._ttl_seconds
                for law_name, law in stale.items():
                    if law_name not in fetched:
                        law["cache_status"] = "stale"
                        self._laws[law_name] = law

        with self._lock:
            unavailable = [
                law_name
                for law_name in SUPPORTED_LAW_NAMES
                if law_name not in self._laws
            ]
            if unavailable:
                raise LawApiResponseError(
                    "일부 법령 정보를 불러오지 못했습니다: "
                    + ", ".join(unavailable)
                )
            return deepcopy(self._laws)

    def clear(self) -> None:
        with self._lock:
            self._laws.clear()
            self._expires_at.clear()


law_corpus_cache = LawCorpusCache()
