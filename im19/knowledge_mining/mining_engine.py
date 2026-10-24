"""Structured mining with exact evidence binding; LLM output is always unverified."""

import re
from im19.contracts import (
    KNOWLEDGE_TYPES,
    KnowledgeUnit,
    PipelineError,
    digest,
    stable_id,
)

INJECTION = re.compile(
    r"ignore\s+(all\s+|previous\s+|system\s+)*instructions|<\|im_start\|>|\[INST\]|"
    r"reveal.{0,30}(secret|token)|execute\s+(this\s+)?(command|code)",
    re.I,
)


def injection_signal(text):
    return bool(INJECTION.search(text))


class MiningEngine:
    def __init__(self, model, max_units_per_chunk=12):
        self.model, self.limit = model, max_units_per_chunk

    def mine(self, chunks, classification):
        units = {}
        for chunk in chunks:
            result = self.model.json(
                'Extract explicit knowledge only. Return {"units":[{"concept":str,"knowledge_type":str,'
                '"claim":str,"evidence_text":str}]}. Evidence must be an exact contiguous nonempty excerpt '
                "from source_text. Distinguish factual_claim, opinion and assumption. Allowed types: "
                + ", ".join(sorted(KNOWLEDGE_TYPES)),
                {"source_text": chunk.text},
            )
            if (
                set(result) != {"units"}
                or not isinstance(result["units"], list)
                or len(result["units"]) > self.limit
            ):
                raise PipelineError("NEEDS_HUMAN_REVIEW", "MINING_SCHEMA")
            labels = [
                x
                for x in classification["labels"]
                if chunk.chunk_id in x["source_chunk_ids"]
            ]
            label = (
                labels[0]
                if labels
                else {"category": "Lainnya", "subcategory": "Unclassified"}
            )
            for raw in result["units"]:
                if (
                    set(raw) != {"concept", "knowledge_type", "claim", "evidence_text"}
                    or not all(
                        isinstance(v, str) and v.strip() and len(v) <= 4000
                        for v in raw.values()
                    )
                    or raw["evidence_text"] not in chunk.text
                ):
                    raise PipelineError("QUARANTINED", "EVIDENCE_MISMATCH")
                if raw["knowledge_type"] not in KNOWLEDGE_TYPES:
                    raise PipelineError("NEEDS_HUMAN_REVIEW", "KNOWLEDGE_TYPE")
                h = digest(raw["claim"])
                uid = stable_id(
                    chunk.document_id, chunk.chunk_id, h, self.model.version
                )
                units[uid] = KnowledgeUnit(
                    uid,
                    chunk.document_id,
                    raw["concept"],
                    label["category"],
                    label["subcategory"],
                    raw["knowledge_type"],
                    raw["claim"],
                    raw["evidence_text"],
                    chunk.page_start,
                    chunk.page_end,
                    [chunk.chunk_id],
                    chunk.locator,
                    self.model.version,
                    h,
                )
        if not units:
            raise PipelineError("NEEDS_HUMAN_REVIEW", "NO_KNOWLEDGE_MINED")
        return list(units.values())
