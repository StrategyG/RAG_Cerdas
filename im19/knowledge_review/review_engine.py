"""Five logical AI reviewer roles and fail-closed publication policy.

Exact-quote binding proves source attribution, never external factual truth.
No model response can assign externally VERIFIED status or human approval.
"""

from datetime import datetime, timezone
from im19.contracts import PipelineError, number, stable_id
from im19.knowledge_mining.mining_engine import injection_signal

WEIGHTS = {
    "extraction_integrity": 0.20,
    "provenance": 0.20,
    "evidence_strength": 0.20,
    "consistency": 0.15,
    "source_credibility": 0.15,
    "freshness": 0.10,
}
ROLES = {
    "A": "Content Integrity: assess missing text/pages, OCR, corrupted text, structure and exact quotations.",
    "B": "Knowledge Quality: assess clarity, argument, evidence support and methodological limitations.",
    "C": "Fact Verification: distinguish facts/opinions, outdated assertions and absent independent evidence. Never certify truth.",
    "D": "Contradiction Analysis: distinguish direct contradiction, definition, context, period, methodology and complementary views.",
    "E": "Institutional Knowledge Auditor: assess provenance, citations, security and consequential use risk.",
}
RELATIONS = {
    "DIRECT_CONTRADICTION",
    "DEFINITION_DIFFERENCE",
    "CONTEXT_DIFFERENCE",
    "PERIOD_DIFFERENCE",
    "METHODOLOGY_DIFFERENCE",
    "COMPLEMENTARY",
    "DUPLICATE",
}


def score_quality(dimensions):
    if set(dimensions) != set(WEIGHTS):
        raise ValueError("All six rubric dimensions required")
    # Unknown dimensions are not silently renormalized into a passing score.
    if any(v is None for v in dimensions.values()):
        return {"score": None, "status": "NEEDS_REVIEW", "calibrated": False}
    score = round(sum(number(dimensions[k]) * w for k, w in WEIGHTS.items()), 2)
    status = (
        "HIGH_QUALITY"
        if score >= 85
        else "ACCEPTABLE"
        if score >= 70
        else "NEEDS_REVIEW"
        if score >= 50
        else "QUARANTINE"
    )
    return {"score": score, "status": status, "calibrated": False}


class ReviewEngine:
    def __init__(self, model):
        self.model = model

    def review(self, units, chunks, pages, comparison_claims=()):
        by_chunk = {c.chunk_id: c for c in chunks}
        for unit in units:
            sources = [by_chunk.get(cid) for cid in unit.source_chunk_ids]
            if not sources or any(
                s is None
                or s.document_id != unit.document_id
                or s.locator != unit.locator
                or unit.evidence_text not in s.text
                for s in sources
            ):
                raise PipelineError("QUARANTINED", "PROVENANCE_INVALID")
        warnings = sorted({w for p in pages for w in p.warnings})
        injection = any(injection_signal(c.text) for c in chunks)
        results, relations = [], []
        # Review bounded units individually; no silent truncation of a long book.
        comparisons = list(comparison_claims)
        if len(comparisons) > 20:
            raise PipelineError("NEEDS_HUMAN_REVIEW", "COMPARISON_QUOTA")
        allowed_ids = {u.knowledge_id for u in units} | {
            c["knowledge_id"] for c in comparisons
        }
        for unit in units:
            for role, purpose in ROLES.items():
                result = self.model.json(
                    purpose
                    + '\nReturn {"dimensions":{all six supplied keys: number 0..100 or null},'
                    '"findings":[str],"risk":"low"|"high"|"unknown","relations":['
                    '{"target_id":str,"kind":str,"evidence_text":str}]}. Missing metadata/evidence => null, never guess. '
                    "Source credibility and freshness require supplied metadata. Relations only for role D.",
                    {
                        "role": role,
                        "dimensions": list(WEIGHTS),
                        "unit": unit.to_dict(),
                        "extraction_warnings": warnings,
                        "source_metadata": {},
                        "comparison_claims": comparisons if role == "D" else [],
                        "relation_kinds": sorted(RELATIONS),
                    },
                )
                if (
                    set(result) != {"dimensions", "findings", "risk", "relations"}
                    or result["risk"] not in {"low", "high", "unknown"}
                    or not isinstance(result["findings"], list)
                    or len(result["findings"]) > 20
                    or any(
                        not isinstance(f, str) or len(f) > 2000
                        for f in result["findings"]
                    )
                    or not isinstance(result["relations"], list)
                    or len(result["relations"]) > 20
                ):
                    raise PipelineError("NEEDS_HUMAN_REVIEW", "REVIEW_SCHEMA")
                try:
                    score_quality(result["dimensions"])
                except (TypeError, ValueError):
                    raise PipelineError(
                        "NEEDS_HUMAN_REVIEW", "REVIEW_RUBRIC_INVALID"
                    ) from None
                # These dimensions have no supplied external provenance in this pilot.
                result["dimensions"]["source_credibility"] = None
                result["dimensions"]["freshness"] = None
                if role != "D" and result["relations"]:
                    raise PipelineError("NEEDS_HUMAN_REVIEW", "RELATION_ROLE_INVALID")
                for edge in result["relations"]:
                    if (
                        set(edge) != {"target_id", "kind", "evidence_text"}
                        or edge["target_id"] not in allowed_ids
                        or edge["target_id"] == unit.knowledge_id
                        or edge["kind"] not in RELATIONS
                        or not isinstance(edge["evidence_text"], str)
                        or not edge["evidence_text"]
                        or edge["evidence_text"] not in unit.evidence_text
                    ):
                        raise PipelineError("QUARANTINED", "RELATION_EVIDENCE_INVALID")
                    relations.append(
                        {
                            **edge,
                            "source_id": unit.knowledge_id,
                            "evidence_id": stable_id(
                                unit.knowledge_id, unit.evidence_text
                            ),
                            "model_version": self.model.version,
                            "review_status": "pending",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                results.append(
                    {
                        "role": role,
                        "knowledge_id": unit.knowledge_id,
                        "model_version": self.model.version,
                        **result,
                    }
                )
        dimensions = {}
        for key in WEIGHTS:
            values = [r["dimensions"][key] for r in results]
            dimensions[key] = None if any(v is None for v in values) else min(values)
        quality = score_quality(dimensions)
        return {
            "reviews": results,
            "relations": relations,
            "dimensions": dimensions,
            "quality": quality,
            "verification_status": "NOT_EXTERNALLY_VERIFIED",
            "independent_reviewers": False,
            "integrity_ok": not warnings and not injection,
            "risk": "high" if any(r["risk"] == "high" for r in results) else "unknown",
            "warnings": warnings + (["POSSIBLE_PROMPT_INJECTION"] if injection else []),
            "human_approval_required": True,
        }


def publication_decision(
    review,
    classification,
    *,
    access_authorized: bool,
    human_approval: dict | None = None,
):
    if not access_authorized or not review["integrity_ok"]:
        return "QUARANTINED"
    if classification["status"] != "CLASSIFIED":
        return "NEEDS_HUMAN_REVIEW"
    if review["quality"]["status"] == "QUARANTINE":
        return "QUARANTINED"
    # Initial thresholds are uncalibrated: publication requires a separate human decision.
    # That decision never turns NOT_EXTERNALLY_VERIFIED into VERIFIED.
    if (
        not human_approval
        or human_approval.get("decision") != "approve"
        or not human_approval.get("reviewer_id")
        or not human_approval.get("review_run_id")
    ):
        return "NEEDS_HUMAN_REVIEW"
    return "APPROVED_FOR_INDEXING"
