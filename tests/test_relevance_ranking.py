"""The relevance ranking is computed locally: no network, no key, deterministic."""
from unittest.mock import patch

from pipeline.relevance_ranking import RANKER, rerank_candidates

GAP = "CFTR modulator rescue in human airway chip infection models"
PASSAGES = [
    "Stock price forecasting with recurrent neural networks. We predict daily prices.",
    "CFTR modulators rescue ion transport in a human airway chip model of cystic fibrosis infection.",
    "A survey of airway disease. Airway disease is common.",
    "Modulator therapy outcomes in patients: a registry study of CFTR modulators.",
]


def test_the_closest_passage_comes_first_and_the_unrelated_one_last():
    ranking = rerank_candidates(GAP, PASSAGES)
    assert [r["index"] for r in ranking][0] == 1 and [r["index"] for r in ranking][-1] == 0
    assert all(ranking[i]["score"] >= ranking[i + 1]["score"] for i in range(len(ranking) - 1))


def test_every_passage_is_ranked_exactly_once():
    ranking = rerank_candidates(GAP, PASSAGES)
    assert sorted(r["index"] for r in ranking) == [0, 1, 2, 3]


def test_the_same_input_gives_the_same_order():
    assert rerank_candidates(GAP, PASSAGES) == rerank_candidates(GAP, PASSAGES)


def test_nothing_to_rank_gives_nothing():
    assert rerank_candidates("query", []) == [] and rerank_candidates("", ["a passage"]) == []


def test_a_query_of_only_stop_and_framing_words_keeps_the_original_order():
    assert [r["index"] for r in rerank_candidates("the missing gap of this", PASSAGES)] == [0, 1, 2, 3]


def test_a_shared_two_word_phrase_outranks_the_same_words_scattered():
    passages = ["airway chip models of infection", "chip design, and infection of the airway in models"]
    assert rerank_candidates("airway chip", passages)[0]["index"] == 0


def test_a_common_word_counts_for_less_than_a_rare_one():
    passages = ["cystic fibrosis fibrosis fibrosis", "bronchiectasis in cystic patients"]
    assert rerank_candidates("cystic bronchiectasis", passages)[0]["index"] == 1


def test_it_never_touches_the_network():
    with patch("socket.socket", side_effect=AssertionError("network used")):
        assert rerank_candidates(GAP, PASSAGES)
    assert RANKER == "token-overlap-v1"
