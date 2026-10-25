"""Validated, versioned contracts. Model scores are not truth probabilities."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
import json
import math
import re
from typing import Any
from uuid import UUID, uuid5, NAMESPACE_URL


class PipelineError(Exception):
    """Safe status code only: never include provider bodies or secrets."""

    def __init__(self, status: str, code: str):
        self.status, self.code = status, code
        super().__init__(f"{status}:{code}")


def stable_id(*parts: str) -> str:
    return str(uuid5(NAMESPACE_URL, json.dumps(parts, ensure_ascii=False)))


def digest(text: str) -> str:
    return sha256(text.encode()).hexdigest()


def number(value: Any, low: float = 0, high: float = 100) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ValueError("Expected finite numeric score")
    if not low <= value <= high:
        raise ValueError("Score outside rubric range")
    return float(value)


@dataclass(frozen=True)
class Page:
    locator: str
    text: str
    page_number: int | None
    blocks: list[dict] = field(default_factory=list)
    ocr_confidence: float | None = None
    ocr_used: bool = False
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    document_id: str
    locator: str
    text: str
    page_start: int | None
    page_end: int | None
    content_hash: str


KNOWLEDGE_TYPES = {
    "concept",
    "definition",
    "principle",
    "methodology",
    "causal_relation",
    "formula",
    "procedure",
    "case_study",
    "risk",
    "limitation",
    "factual_claim",
    "opinion",
    "assumption",
    "supporting_evidence",
}


@dataclass(frozen=True)
class KnowledgeUnit:
    knowledge_id: str
    document_id: str
    concept: str
    category: str
    subcategory: str
    knowledge_type: str
    claim: str
    evidence_text: str
    page_start: int | None
    page_end: int | None
    source_chunk_ids: list[str]
    locator: str
    model_version: str
    content_hash: str
    confidence: float | None = None
    verification_status: str = "unverified"
    review_status: str = "pending"

    def __post_init__(self):
        UUID(self.document_id)
        UUID(self.knowledge_id)
        if self.knowledge_type not in KNOWLEDGE_TYPES or not self.source_chunk_ids:
            raise ValueError("Invalid knowledge type or missing provenance")
        if not self.claim.strip() or not self.evidence_text.strip() or not self.locator:
            raise ValueError("Empty knowledge/evidence/locator")
        if self.page_start is not None:
            if (
                type(self.page_start) is not int
                or self.page_start < 1
                or self.page_end != self.page_start
            ):
                raise ValueError("PDF knowledge must have exact one-based page mapping")
        elif self.page_end is not None:
            raise ValueError("Unpaged sources cannot invent page numbers")
        elif self.locator.startswith("video:seconds:"):
            match = re.fullmatch(r"video:seconds:(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)", self.locator)
            if not match:
                raise ValueError("Video requires an exact timestamp interval")
            start, end = map(float, match.groups())
            if not math.isfinite(start) or not math.isfinite(end) or end <= start:
                raise ValueError("Invalid video timestamp interval")
        elif not self.locator.startswith("epub:"):
            raise ValueError("Unpaged knowledge requires an EPUB or video locator")
        if self.confidence is not None:
            raise ValueError("Uncalibrated extraction confidence must be null")

    def to_dict(self):
        return asdict(self)


def strict_json(raw: str, max_chars: int = 100_000) -> Any:
    if not isinstance(raw, str) or len(raw) > max_chars:
        raise ValueError("Invalid or oversized model response")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError("Non-finite JSON value")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)

