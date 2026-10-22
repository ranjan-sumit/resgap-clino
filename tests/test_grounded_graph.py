import json

import pytest

from pipeline import graph_builder as gb
from pipeline import graph_grounded as gg
from tests.test_gap_agents import EVIDENCE, WIKI, handle
from utils.azure_client import ErrorInfo, Failure, Success

CHIP, FLOW, IL8, GENE, SURVEY, MRNA = (handle("a.pdf", 0), handle("a.pdf", 1), handle("a.pdf", 2),
                                        handle("b.pdf", 0), handle("b.pdf", 1), handle("b.pdf", 0))


def ent(i, name, type_="method", imp="high"):
    return {"id": i, "name": name, "type": type_, "importance": imp}


def rel(s, t, r, ref):
    return {"source": s, "target": t, "relation": r, "evidence_ref": ref}


class GraphClient:
    """First call: the graph. Second call (if any): the orphan links. Everything else: communities."""
    def __init__(self, graph, links=None, fail_first=False):
        self.graph, self.links, self.fail_first = graph, links, fail_first
        self.calls = []

    def set_stage(self, s):
        pass

    def chat_json(self, system, user, **kw):
        if "build a knowledge graph from QUOTED EVIDENCE" in system:
            self.calls.append("graph")
            if self.fail_first:
                return Failure(ErrorInfo(kind="timeout", detail="x"))
            return Success(json.dumps(self.graph))
        if "connect unlinked entities" in system:
            self.calls.append("links")
            return Success(json.dumps(self.links or {"relationships": []}))
        if "thematic communities" in system:
            self.calls.append("communities")
            return Success("[]")
        self.calls.append("wiki-graph")
        return Success(json.dumps({"entities": [ent("x", "X")], "relationships": []}))


def graph(entities, relationships):
    return {"entities": entities, "relationships": relationships}


def good():
    return graph(
        [ent("airway_chip", "airway chip", "model_system"), ent("static_culture", "static culture", "method"),
         ent("il8", "IL-8", "biomarker"), ent("mrna", "mRNA delivery", "intervention"),
         ent("survey", "global survey", "method")],
        [rel("airway_chip", "static_culture", "limited_by", CHIP), rel("airway_chip", "il8", "measured_by", FLOW),
         rel("mrna", "airway_chip", "targets", GENE), rel("survey", "mrna", "studied_in", SURVEY)])


def build(client, evidence=EVIDENCE):
    return gb.build_knowledge_graph(WIKI, client, evidence_objects=evidence)


# ── every relation is grounded ──────────────────────────────────────────────────────────────
def test_every_relationship_carries_an_evidence_id_and_the_verbatim_quote():
    out = build(GraphClient(good()))
    assert out["diagnostics"]["grounded"] is True and not out["diagnostics"]["used_fallback"]
    ids = {e["evidence_id"]: e for items in EVIDENCE.values() for e in items}
    assert out["relationships"]
    for r in out["relationships"]:
        assert r["provenance_evidence_ids"] and all(i in ids for i in r["provenance_evidence_ids"])
        ev = ids[r["provenance_evidence_ids"][0]]
        assert r["evidence"] == ev["provenance"]["quote"]            # the passage itself, not a paraphrase
        assert r["grounded"] is True and r["relationship_id"]


def test_a_relationship_that_cites_nothing_real_is_dropped():
    g = good()
    g["relationships"] += [rel("airway_chip", "il8", "associated_with", "E00000000"),
                           rel("airway_chip", "il8", "associated_with", ""),
                           rel("airway_chip", "nonexistent_entity", "treats", CHIP)]
    out = build(GraphClient(g))
    d = out["diagnostics"]
    assert d["dropped_no_evidence"] == 2 and d["dropped_bad_entity"] == 1
    assert len(out["relationships"]) == 4


def test_the_handle_may_be_written_with_brackets():
    g = good()
    g["relationships"][0]["evidence_ref"] = f"[{CHIP}]"
    out = build(GraphClient(g))
    assert any(r["evidence_ref"] == CHIP for r in out["relationships"])


def test_the_paper_of_a_relationship_comes_from_its_evidence_not_the_model():
    out = build(GraphClient(good()))
    papers = {r["paper"] for r in out["relationships"]}
    assert papers <= {"Airway chip paper", "Survey paper"} and len(papers) == 2
    by_id = {e["id"]: e for e in out["entities"]}
    assert "Airway chip paper" in by_id["airway_chip"]["papers"]


# ── fixed type lists ────────────────────────────────────────────────────────────────────────
def test_unknown_types_and_relations_map_to_general_ones_with_the_original_kept():
    g = good()
    g["entities"][0]["type"] = "gadget"
    g["relationships"][0]["relation"] = "wibbles"
    out = build(GraphClient(g))
    assert {e["type"] for e in out["entities"]} <= set(gg.SCIENCE_ENTITY_TYPES)
    assert {r["relation"] for r in out["relationships"]} <= set(gg.SCIENCE_RELATIONS)
    assert next(e for e in out["entities"] if e["id"] == "airway_chip")["type_original"] == "gadget"
    assert next(r for r in out["relationships"] if r.get("relation_original") == "wibbles")["relation"] == "associated_with"
    assert out["diagnostics"]["types_normalised"] == 1 and out["diagnostics"]["relations_normalised"] == 1


# ── orphans ─────────────────────────────────────────────────────────────────────────────────
def with_orphans():
    g = good()
    g["entities"] += [ent("shear", "shear flow", "concept"), ent("tissue", "lung tissue", "concept"),
                      ent("gene_therapy", "gene therapy", "intervention")]
    return g


def test_an_entity_named_with_another_in_one_evidence_item_is_linked_without_a_model_call():
    g = good()
    g["entities"].append(ent("shear", "shear flow", "concept"))     # "Static culture lacks any shear flow" names both
    client = GraphClient(g)
    out = build(client)
    d = out["diagnostics"]
    assert d["orphans_after_extraction"] == 1 and d["linked_by_comention"] == 1 and d["orphans_remaining"] == 0
    assert "links" not in client.calls                              # nothing left for the model to do
    link = next(r for r in out["relationships"] if r["linked_by"] == "co-mention")
    assert {link["source"], link["target"]} == {"shear", "static_culture"}
    assert link["evidence"] == "static culture lacks any shear flow" and link["provenance_evidence_ids"]


def test_a_second_model_call_links_what_is_still_unlinked():
    links = {"relationships": [rel("tissue", "il8", "associated_with", FLOW)]}
    client = GraphClient(with_orphans(), links)
    out = build(client)
    assert "links" in client.calls
    d = out["diagnostics"]
    assert d["orphans_after_extraction"] == 3 and d["linked_by_comention"] == 2 and d["linked_by_model"] == 1
    assert d["orphans_remaining"] == 0 and all(not e["orphan"] for e in out["entities"])


def test_orphan_share_stays_below_the_threshold_on_the_golden_corpus():
    out = build(GraphClient(with_orphans(), {"relationships": []}))                 # the model finds nothing more

    d = out["diagnostics"]
    assert d["orphans_remaining"] == 1 and d["orphan_share"] == round(1 / 8, 3) and d["orphan_share"] <= 0.2
    assert [e["id"] for e in out["entities"] if e["orphan"]] == ["tissue"]


def test_a_link_to_a_made_up_item_does_not_count():
    links = {"relationships": [rel("tissue", "il8", "associated_with", "E12345678")]}
    out = build(GraphClient(with_orphans(), links))
    assert out["diagnostics"]["linked_by_model"] == 0 and out["diagnostics"]["orphans_remaining"] == 1


def test_no_second_call_when_nothing_is_orphaned():
    client = GraphClient(good())
    build(client)
    assert "links" not in client.calls


def test_a_failed_link_call_keeps_the_graph_and_says_so():
    class Flaky(GraphClient):
        def chat_json(self, system, user, **kw):
            if "connect unlinked entities" in system:
                return Failure(ErrorInfo(kind="rate_limit", detail="429"))
            return super().chat_json(system, user, **kw)
    out = build(Flaky(with_orphans()))
    assert "orphan_link_error" in out["diagnostics"] and out["diagnostics"]["orphans_remaining"] == 1
    assert out["relationships"]


# ── fallbacks ───────────────────────────────────────────────────────────────────────────────
def test_without_quoted_evidence_the_wiki_graph_is_used():
    bare = {pid: [{**e, "provenance": {**e["provenance"], "quote": None}} for e in items] for pid, items in EVIDENCE.items()}
    client = GraphClient(good())
    out = build(client, bare)
    assert "graph" not in client.calls and "wiki-graph" in client.calls
    assert not out["diagnostics"].get("grounded")


def test_a_failed_grounded_call_falls_back_to_the_wiki_graph_with_the_reason():
    client = GraphClient(good(), fail_first=True)
    out = build(client)
    assert "wiki-graph" in client.calls
    assert out["diagnostics"]["grounded"] is False and "timeout" in out["diagnostics"]["grounded_failure"]


def test_an_empty_grounded_graph_falls_back():
    out = build(GraphClient(graph([], [])))
    assert out["diagnostics"]["grounded"] is False


def test_stats_and_communities_still_work_on_a_grounded_graph():
    out = build(GraphClient(good()))
    assert out["stats"]["entity_count"] == 5 and out["stats"]["relationship_count"] == 4
    assert "network_data" in out and "orphan_concepts" in out
