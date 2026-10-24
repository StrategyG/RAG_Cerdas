"""Content-based hierarchical multi-label classification, with explicit ambiguity."""

from im19.contracts import PipelineError

TAXONOMY = {
    "Trading": ["Technical Analysis", "Trading Psychology", "Risk Management"],
    "Cryptocurrency": ["Blockchain", "Crypto Markets"],
    "Investasi": ["Valuation", "Portfolio Management", "Behavioral Finance"],
    "Ekonomi": ["Macroeconomics", "Microeconomics"],
    "Keuangan": ["Personal Finance", "Accounting"],
    "Bisnis": ["Entrepreneurship", "Marketing"],
    "Manajemen": ["Operations", "Leadership"],
    "Psikologi": ["Behavioral Finance", "Cognition", "Trading Psychology"],
    "Filsafat": ["Ethics", "Logic"],
    "Teknologi": ["Software", "Engineering"],
    "Artificial Intelligence": ["Machine Learning", "RAG"],
    "Hukum": ["Regulation", "Legal Theory"],
    "Sejarah": ["World History", "Local History"],
    "Pendidikan": ["Pedagogy", "Learning"],
    "Kesehatan": ["Medicine", "Public Health"],
    "Lainnya": ["Unclassified"],
}


class Classifier:
    def __init__(self, model):
        self.model = model

    def classify(self, chunks):
        labels, ambiguous = {}, False
        for chunk in chunks:
            result = self.model.json(
                'Classify this content, not the filename. Return {"labels":[{"category":str,"subcategory":str}],'
                '"ambiguous":bool}. Use only supplied taxonomy; multiple labels permitted.',
                {"taxonomy": TAXONOMY, "source_text": chunk.text},
            )
            if (
                set(result) != {"labels", "ambiguous"}
                or type(result["ambiguous"]) is not bool
                or not isinstance(result["labels"], list)
                or len(result["labels"]) > 8
            ):
                raise PipelineError("NEEDS_HUMAN_REVIEW", "CLASSIFICATION_SCHEMA")
            ambiguous |= result["ambiguous"] or not result["labels"]
            for label in result["labels"]:
                if set(label) != {"category", "subcategory"} or label[
                    "subcategory"
                ] not in TAXONOMY.get(label["category"], []):
                    raise PipelineError("NEEDS_HUMAN_REVIEW", "CLASSIFICATION_TAXONOMY")
                key = (label["category"], label["subcategory"])
                labels.setdefault(key, []).append(chunk.chunk_id)
        return {
            "status": "NEEDS_REVIEW" if ambiguous or not labels else "CLASSIFIED",
            "labels": [
                {"category": k[0], "subcategory": k[1], "source_chunk_ids": ids}
                for k, ids in labels.items()
            ],
            "model_version": self.model.version,
            "method": "per_chunk_content_multilabel",
            "calibrated": False,
        }
