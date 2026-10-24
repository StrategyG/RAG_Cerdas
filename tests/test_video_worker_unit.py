from types import SimpleNamespace

from scripts.video_rag_worker import _timestamp, split_segments


def test_timestamp_uses_hh_mm_ss_and_handles_hour_boundaries():
    assert _timestamp(0) == "00:00:00"
    assert _timestamp(3599.9) == "00:59:59"
    assert _timestamp(3600) == "01:00:00"
    assert _timestamp(-5) == "00:00:00"


def test_split_segments_preserves_timestamp_boundaries_and_text():
    segments = [
        SimpleNamespace(text="Ini materi pertama", start=0.2, end=1.4),
        SimpleNamespace(text="bagian kedua", start=1.5, end=2.8),
    ]

    chunks = split_segments(segments, max_words=3)

    assert len(chunks) == 2
    assert chunks[0] == {
        "text": "Ini materi pertama",
        "start_seconds": 0.2,
        "end_seconds": 1.4,
    }
    assert chunks[1] == {
        "text": "bagian kedua",
        "start_seconds": 1.5,
        "end_seconds": 2.8,
    }


def test_split_segments_ignores_empty_transcript_segments():
    segments = [
        SimpleNamespace(text=" ", start=0.0, end=0.3),
        SimpleNamespace(text="Konten relevan", start=0.4, end=1.0),
    ]
    assert split_segments(segments) == [
        {"text": "Konten relevan", "start_seconds": 0.4, "end_seconds": 1.0}
    ]
