"""Knowledge-graph display data, and the wiki cache rule that fed it."""
import math
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.graph_builder import layout_positions, prepare_network_diagram_data
from pipeline import wiki_compiler
from pipeline.wiki_compiler import _page_is_empty, compile_wiki_page
from utils.azure_client import Success


def _edge(a, b):
    return {"source_idx": a, "target_idx": b}


class LayoutTests(unittest.TestCase):
    def test_empty_and_single_node(self):
        self.assertEqual(layout_positions(0, []), [])
        self.assertEqual(layout_positions(1, []), [(0.0, 0.0)])

    def test_is_deterministic(self):
        edges = [_edge(0, 1), _edge(1, 2), _edge(2, 3)]
        self.assertEqual(layout_positions(5, edges), layout_positions(5, edges))

    def test_linked_nodes_end_up_closer_than_unlinked_ones(self):
        # two triangles, no link between them
        edges = [_edge(0, 1), _edge(1, 2), _edge(0, 2), _edge(3, 4), _edge(4, 5), _edge(3, 5)]
        p = layout_positions(6, edges)
        d = lambda a, b: math.dist(p[a], p[b])
        within = (d(0, 1) + d(1, 2) + d(0, 2) + d(3, 4) + d(4, 5) + d(3, 5)) / 6
        across = (d(0, 3) + d(1, 4) + d(2, 5)) / 3
        self.assertLess(within, across)

    def test_no_two_nodes_share_a_position(self):
        p = layout_positions(12, [_edge(0, 1), _edge(1, 2)])
        self.assertEqual(len({(round(x, 3), round(y, 3)) for x, y in p}), 12)

    def test_isolated_nodes_are_placed_outside_the_connected_cluster(self):
        p = layout_positions(5, [_edge(0, 1), _edge(1, 2)])
        cluster_r = max(math.hypot(*p[i]) for i in (0, 1, 2))
        for i in (3, 4):
            self.assertGreater(math.hypot(*p[i]), cluster_r)

    def test_self_loops_and_duplicate_edges_do_not_break_it(self):
        self.assertEqual(len(layout_positions(3, [_edge(0, 0), _edge(0, 1), _edge(1, 0)])), 3)


class DiagramDataTests(unittest.TestCase):
    def _graph(self):
        return {"entities": [
            {"id": "a", "name": "A", "type": "disease", "importance": "high"},
            {"id": "b", "name": "B", "type": "biomarker", "importance": "low"},
            {"id": "c", "name": "C", "type": "method"}],
            "relationships": [{"source": "a", "target": "b", "relation": "predicts"}]}

    def test_every_node_gets_a_position(self):
        nodes = prepare_network_diagram_data(self._graph())["nodes"]
        self.assertTrue(all("x" in n and "y" in n for n in nodes))

    def test_invented_types_get_a_real_colour_not_grey(self):
        nodes = {n["name"]: n for n in prepare_network_diagram_data(self._graph())["nodes"]}
        self.assertNotEqual(nodes["A"]["color"], "#8b949e")
        self.assertNotEqual(nodes["B"]["color"], "#8b949e")
        self.assertEqual(nodes["C"]["color"], "#3fb950")           # known type keeps its colour

    def test_same_invented_type_always_gets_the_same_colour(self):
        a = prepare_network_diagram_data(self._graph())["nodes"][0]["color"]
        b = prepare_network_diagram_data(self._graph())["nodes"][0]["color"]
        self.assertEqual(a, b)

    def test_edges_resolve_to_node_indexes(self):
        edges = prepare_network_diagram_data(self._graph())["edges"]
        self.assertEqual((edges[0]["source_idx"], edges[0]["target_idx"]), (0, 1))


class EmptyWikiPageCacheTests(unittest.TestCase):
    def test_empty_page_detection(self):
        self.assertTrue(_page_is_empty({"title": "x", "key_findings": [], "methods": []}))
        self.assertFalse(_page_is_empty({"key_findings": ["f"]}))
        self.assertFalse(_page_is_empty({"key_concepts": ["c"]}))

    def _paper(self):
        return {"filename": "p.pdf", "full_text": "some text", "sections": {"A": "body " * 50}, "char_count": 9}

    def _tree(self):
        from pipeline.page_index import build_tree
        return build_tree(self._paper())

    def test_a_cached_empty_page_is_ignored_and_recompiled(self):
        client = MagicMock()
        client.chat_json.return_value = Success('{"title": "T", "key_findings": ["real"]}')
        with patch.object(wiki_compiler, "get_cached_wiki_page",
                          return_value={"title": "p.pdf", "key_findings": []}), \
             patch.object(wiki_compiler, "save_cached_wiki_page"):
            page = compile_wiki_page(self._paper(), self._tree(), client)
        self.assertEqual(page["key_findings"], ["real"])
        client.chat_json.assert_called_once()

    def test_an_empty_result_is_not_written_to_the_cache(self):
        client = MagicMock()
        client.chat_json.return_value = Success('{"title": "T", "key_findings": []}')
        with patch.object(wiki_compiler, "get_cached_wiki_page", return_value=None), \
             patch.object(wiki_compiler, "save_cached_wiki_page") as save:
            compile_wiki_page(self._paper(), self._tree(), client)
        save.assert_not_called()

    def test_a_good_result_is_still_cached(self):
        client = MagicMock()
        client.chat_json.return_value = Success('{"title": "T", "key_findings": ["x"]}')
        with patch.object(wiki_compiler, "get_cached_wiki_page", return_value=None), \
             patch.object(wiki_compiler, "save_cached_wiki_page") as save:
            compile_wiki_page(self._paper(), self._tree(), client)
        save.assert_called_once()

    def test_stage_version_was_bumped_past_the_bad_cache(self):
        self.assertGreaterEqual(wiki_compiler.WIKI_STAGE_VERSION, 2)


if __name__ == "__main__":
    unittest.main()
