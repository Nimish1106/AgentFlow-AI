"""Unit tests for deterministic text chunking (SRS §32)."""

import pytest

from app.rag.chunking import chunk_text


class TestChunkText:
    def test_short_text_is_a_single_chunk(self):
        assert chunk_text("hello world", chunk_size=100, chunk_overlap=10) == [
            "hello world"
        ]

    def test_paragraphs_pack_together_while_they_fit(self):
        text = "one\n\ntwo\n\nthree"
        assert chunk_text(text, chunk_size=100, chunk_overlap=10) == [
            "one\n\ntwo\n\nthree"
        ]

    def test_paragraphs_split_when_they_exceed_chunk_size(self):
        text = "a" * 40 + "\n\n" + "b" * 40 + "\n\n" + "c" * 40
        chunks = chunk_text(text, chunk_size=90, chunk_overlap=10)
        assert chunks == ["a" * 40 + "\n\n" + "b" * 40, "c" * 40]

    def test_every_chunk_respects_the_size_limit(self):
        text = "\n\n".join(f"paragraph {i} " + "x" * 50 for i in range(20))
        chunks = chunk_text(text, chunk_size=200, chunk_overlap=20)
        assert all(len(chunk) <= 200 for chunk in chunks)

    def test_long_paragraph_is_windowed_with_overlap(self):
        text = "x" * 250
        chunks = chunk_text(text, chunk_size=100, chunk_overlap=20)
        # Window step is 80: [0:100], [80:180], [160:250].
        assert [len(c) for c in chunks] == [100, 100, 90]

    def test_windowing_preserves_all_content(self):
        text = "".join(chr(ord("a") + i % 26) for i in range(300))
        chunks = chunk_text(text, chunk_size=100, chunk_overlap=25)
        rebuilt = chunks[0]
        for chunk in chunks[1:]:
            rebuilt += chunk[25:]
        assert rebuilt == text

    def test_blank_input_produces_no_chunks(self):
        assert chunk_text("  \n\n  ", chunk_size=100, chunk_overlap=10) == []

    def test_deterministic_for_the_same_input(self):
        text = "\n\n".join("paragraph " + "y" * 30 for _ in range(10))
        first = chunk_text(text, chunk_size=120, chunk_overlap=30)
        second = chunk_text(text, chunk_size=120, chunk_overlap=30)
        assert first == second

    def test_invalid_chunk_size_rejected(self):
        with pytest.raises(ValueError, match="chunk_size"):
            chunk_text("text", chunk_size=0, chunk_overlap=0)

    @pytest.mark.parametrize("overlap", [-1, 100, 150])
    def test_invalid_overlap_rejected(self, overlap):
        with pytest.raises(ValueError, match="chunk_overlap"):
            chunk_text("text", chunk_size=100, chunk_overlap=overlap)
