from __future__ import annotations

from s13code.core.memory.chunking import semantic_chunks
from s13code.core.memory.embeddings import DeterministicEmbedder

TEXT = """Artificial intelligence systems learn patterns from data. Neural networks train on examples.

Cricket is played between two teams. Batters score runs and bowlers take wickets.

Real estate development involves land, approvals, finance, and construction."""


class ExactTopicSuffix:
    def second_topic(self, block: str) -> str:
        for marker in ("Cricket is", "Real estate development"):
            at = block.find(marker)
            if at > 0:
                return block[at:]
        return ""


class TruncatedSuffix:
    def second_topic(self, block: str) -> str:
        # Simulates a model output limit: this is copied from the block but
        # does not reach its end, so accepting it would silently delete text.
        return "Cricket is played between two teams."


class RepeatedSuffix:
    def second_topic(self, block: str) -> str:
        # The final phrase is a valid suffix but appears earlier too. The
        # boundary must be its suffix location, not the first `find()` hit.
        return "Repeat. Repeat."


class FailingSegmenter:
    def second_topic(self, block: str) -> str:
        raise RuntimeError("ollama unavailable")


def test_rohan_v2_rolls_the_exact_second_topic_without_overlap_or_loss():
    chunks = semantic_chunks(TEXT, DeterministicEmbedder(), segmenter=ExactTopicSuffix(),
                             preprocess=False, min_words=1)
    assert [chunk.text.split()[0] for chunk in chunks] == ["Artificial", "Cricket", "Real"]
    assert sum(len(chunk.text.split()) for chunk in chunks) == len(TEXT.split())


def test_partial_llm_suffix_is_rejected_instead_of_dropping_the_tail():
    chunks = semantic_chunks(TEXT, DeterministicEmbedder(), segmenter=TruncatedSuffix(),
                             preprocess=False, min_words=1)
    assert len(chunks) == 1
    assert chunks[0].text == TEXT
    assert chunks[0].segmentation["outcome"] == "non_suffix_rejected_kept_as_block"


def test_repeated_suffix_uses_the_final_suffix_location():
    text = "Intro. Repeat. Repeat. Repeat. Repeat."
    chunks = semantic_chunks(text, DeterministicEmbedder(), segmenter=RepeatedSuffix(),
                             preprocess=False, min_words=1)
    assert [chunk.text for chunk in chunks] == ["Intro. Repeat. Repeat.", "Repeat. Repeat."]
    assert chunks[0].segmentation["suffix_start_char"] == len("Intro. Repeat. Repeat. ")


def test_segmenter_failure_is_visible_in_chunk_manifest_data():
    chunks = semantic_chunks(TEXT, DeterministicEmbedder(), segmenter=FailingSegmenter(),
                             preprocess=False, min_words=1)
    assert len(chunks) == 1
    assert chunks[0].segmentation["outcome"] == "segmenter_failed_fallback_to_block"
    assert "ollama unavailable" in chunks[0].segmentation["error"]
