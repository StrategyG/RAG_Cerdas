import hashlib

import fitz

from rag_pipeline import extract_page_chunks


class CharTokenizer:
    """Test-only predictable tokenizer; production uses the model's tokenizer."""
    def encode(self, text, add_special_tokens=False):
        return list(text)

    def decode(self, tokens, skip_special_tokens=True):
        return "".join(tokens)


def make_pdf() -> bytes:
    doc = fitz.open()
    p1 = doc.new_page()
    p1.insert_text((72, 72), "Alpha beta gamma delta " * 35)
    p2 = doc.new_page()
    p2.insert_text((72, 72), "Trading emotions risk management " * 30)
    data = doc.tobytes()
    doc.close()
    return data


def test_every_chunk_stays_inside_one_real_pdf_page():
    page_count, chunks, stats = extract_page_chunks(make_pdf(), CharTokenizer(), max_tokens=80, overlap=10)
    assert page_count == 2
    assert stats["page_mapping"] == "one_pdf_page_per_chunk"
    assert chunks
    assert all(c["page_start"] == c["page_end"] for c in chunks)
    assert all(1 <= c["page_start"] <= page_count for c in chunks)
    assert len({c["chunk_index"] for c in chunks}) == len(chunks)
    assert all(len(c["content_sha256"]) == 64 for c in chunks)
    assert all(c["content_sha256"] == hashlib.sha256(c["text_content"].encode()).hexdigest() for c in chunks)
    assert {c["page_start"] for c in chunks} == {1, 2}
