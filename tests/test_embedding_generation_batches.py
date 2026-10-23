import numpy as np
import pytest

from rag_pipeline import MODEL_DIMS, MODEL_ID, embed_document


DOCUMENT_ID = "041f30c6-5957-49c0-a29b-e3c29a4e1ab0"


class FakeModel:
    def encode(self, inputs, **kwargs):
        assert all(text.startswith("passage: ") for text in inputs)
        return np.ones((len(inputs), MODEL_DIMS), dtype=np.float32)


class FakeClient:
    def __init__(self, activation_by_call):
        self.activation_by_call = activation_by_call
        self.rpc_calls = []

    def list_chunks(self, document_id):
        assert document_id == DOCUMENT_ID
        return [
            {
                "chunk_id": f"00000000-0000-0000-0000-{index:012d}",
                "content_sha256": f"{index:064x}",
                "text_content": f"chunk {index}",
            }
            for index in range(1, 4)
        ]

    def rpc(self, name, body):
        assert name == "rag_worker_store_embeddings"
        self.rpc_calls.append(body)
        call_index = len(self.rpc_calls) - 1
        return {
            "stored": len(body["p_items"]),
            "activated_documents": self.activation_by_call[call_index],
        }


def test_embed_document_allows_intermediate_batches_before_generation_activation():
    # A generation cannot activate after batch one while later chunks remain unembedded.
    client = FakeClient([0, 1])

    result = embed_document(client, FakeModel(), DOCUMENT_ID, batch_size=2)

    assert result == {
        "chunks_seen": 3,
        "embeddings_stored": 3,
        "activated_documents": 1,
    }
    assert [len(call["p_items"]) for call in client.rpc_calls] == [2, 1]
    assert all(call["p_model"] == MODEL_ID for call in client.rpc_calls)


def test_embed_document_fails_after_all_batches_if_generation_never_activates():
    client = FakeClient([0, 0])

    with pytest.raises(RuntimeError, match="did not activate exactly one complete"):
        embed_document(client, FakeModel(), DOCUMENT_ID, batch_size=2)

    # All chunks were attempted before the completion gate was evaluated.
    assert [len(call["p_items"]) for call in client.rpc_calls] == [2, 1]
