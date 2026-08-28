"""
Tests for the Data Quality screen (Clinova Phase 5, Epic 5.8).

This screen was twice deferred on the belief that its data is not persisted.
Several of these tests exist specifically to pin down that this was wrong --
if `ref_resolution_diagnostics` or `ref_diagnostics.papers` ever stop being
written, the screen must fail loudly here rather than quietly render empty.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.services import copy_text
from apps.api.services.quality_service import (
    _funnel_note, _per_paper_completeness, _per_paper_references, _trust_statuses,
)

client = TestClient(app)
PROJECT_ID = "Healthcare AI"


class QualityRouteTests(unittest.TestCase):
    def test_returns_real_persisted_quality_data(self):
        r = client.get(f"/api/projects/{PROJECT_ID}/quality")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIsNone(body["empty_reason"])
        self.assertTrue(body["basis_run"]["run_id"])
        # The three datasets whose absence was the stated reason for deferring
        # this screen. All three are real.
        self.assertTrue(body["measures"])
        self.assertTrue(body["reference_funnel"])
        self.assertTrue(body["trust_statuses"])
        self.assertTrue(body["per_paper_references"])

    def test_unknown_project_is_an_honest_empty_not_a_500(self):
        body = client.get("/api/projects/does-not-exist/quality").json()
        self.assertTrue(body["empty_reason"])
        self.assertIsNone(body["basis_run"])
        self.assertEqual(body["measures"], [])

    def test_every_measure_carries_a_basis_whether_recorded_or_not(self):
        body = client.get(f"/api/projects/{PROJECT_ID}/quality").json()
        for m in body["measures"]:
            self.assertTrue(m["basis"].strip(), m["key"])
            self.assertTrue(m["source"].strip(), m["key"])
            if not m["recorded"]:
                # Never a fabricated 0% standing in for "not measured" --
                # especially on the screen whose subject is honesty.
                self.assertIsNone(m["value"], m["key"])
                self.assertEqual(m["display"], "Not recorded", m["key"])

    def test_trust_statuses_are_chips_not_bare_tones(self):
        body = client.get(f"/api/projects/{PROJECT_ID}/quality").json()
        for t in body["trust_statuses"]:
            chip = t["status"]
            # A bare `tone` string crossing the API boundary would be exactly
            # the "never a bare color" violation common.py exists to prevent.
            self.assertTrue(chip["label"].strip())
            self.assertTrue(chip["reason"].strip(), chip["code"])
            self.assertIn(chip["tone"], {"positive", "caution", "critical", "neutral", "unknown"})

    def test_icons_distinguish_status_families(self):
        body = client.get(f"/api/projects/{PROJECT_ID}/quality").json()
        icons = [t["status"]["icon"] for t in body["trust_statuses"]]
        self.assertEqual(len(icons), len(set(icons)), "each trust status needs its own icon shape")


class TrustStatusTests(unittest.TestCase):
    def test_absent_status_is_not_recorded_rather_than_zero(self):
        # The resolver has no REJECTED code path, so it never emits that key.
        rows, note, dupes = _trust_statuses({
            "status_counts": {"VERIFIED": 71, "ACCEPTED": 0, "QUARANTINED": 1, "UNRESOLVED": 0},
            "duplicates_removed": 3,
        })
        by_code = {r.status.code: r for r in rows}
        self.assertTrue(by_code["ACCEPTED"].recorded, "an emitted 0 is a real measurement")
        self.assertEqual(by_code["ACCEPTED"].count, 0)
        self.assertFalse(by_code["REJECTED"].recorded, "a never-emitted status is not a zero")
        self.assertIn("Rejected", note)
        self.assertEqual(dupes, 3)

    def test_no_diagnostics_yields_nothing_rather_than_five_zeroes(self):
        rows, note, dupes = _trust_statuses(None)
        self.assertEqual(rows, [])
        self.assertIsNone(note)
        self.assertIsNone(dupes)


class FunnelNoteTests(unittest.TestCase):
    """The real run reads Detected 114 -> Parsed 0 -> Resolved 72. Drawn
    without explanation that looks like a bug in the screen."""

    def _funnel(self, **counts):
        from apps.api.models.corpus import ReferenceFunnelStage
        return [ReferenceFunnelStage(key=k, label=k.title(), count=v) for k, v in counts.items()]

    def test_explains_a_funnel_that_widens(self):
        note = _funnel_note(self._funnel(detected=114, parsed=0, resolved=72, fallback_parsed=65))
        self.assertIsNotNone(note)
        self.assertIn("72", note)
        self.assertIn("65", note)

    def test_silent_when_the_funnel_narrows_normally(self):
        self.assertIsNone(_funnel_note(self._funnel(detected=100, parsed=90, resolved=80)))


class PerPaperTests(unittest.TestCase):
    def test_flags_a_paper_the_llm_structured_nothing_for(self):
        rows = _per_paper_references({"papers": [
            {"filename": "a.pdf", "raw_entries": 22, "structured_entries": 0,
             "combined_entries": 22, "dois": 2},
            {"filename": "b.pdf", "raw_entries": 30, "structured_entries": 30,
             "combined_entries": 30, "dois": 10},
        ]})
        self.assertIn("fallback", rows[0].note)
        self.assertIsNone(rows[1].note, "a normally-structured paper needs no caveat")

    def test_completeness_fields_render_in_checklist_order_not_jsonb_order(self):
        # JSONB does not preserve Python dict insertion order, so the service
        # must impose the order rather than trust what comes back.
        rows = _per_paper_completeness([{
            "filename": "a.pdf", "present_count": 2, "total_fields": 16,
            "achievable_field_count": 11, "completeness_score": 0.125,
            "achievable_completeness_score": 0.182,
            "fields": {
                "figures": {"status": "empty", "confidence": "low"},
                "title": {"status": "present", "confidence": "medium"},
                "doi": {"status": "present", "confidence": "high"},
            },
        }])
        self.assertEqual([f.field for f in rows[0].fields], ["title", "doi", "figures"])

    def test_missing_scores_yield_no_rows_at_all(self):
        self.assertEqual(_per_paper_completeness(None), [])

    def test_consumes_the_real_scorer_output_not_a_hand_written_shape(self):
        """The view model's field names were written by hand against a
        reading of corpus_quality.py. This feeds a genuine
        score_paper_completeness() result straight through, so a rename on
        either side fails here instead of silently rendering zeroes."""
        from pipeline.corpus_quality import FIELD_CHECKLIST, score_paper_completeness

        score = score_paper_completeness(
            {"fields": {"doi": {"value": "10.1000/x", "confidence": "high", "source": "crossref"}}},
            {"title": "A Real Title", "source_file": "a.pdf", "methods": ["m"],
             "key_findings": [], "limitations": None},
            ref_count=12, has_figures=True,
        )
        rows = _per_paper_completeness([{**score, "filename": "a.pdf"}])
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.filename, "a.pdf")
        self.assertEqual(len(row.fields), len(FIELD_CHECKLIST))
        self.assertEqual(row.present_count, sum(1 for f in row.fields if f.status == "present"))
        self.assertGreater(row.present_count, 0)
        # The three statuses must survive the mapping distinctly -- collapsing
        # "no extraction path exists" into "attempted and came back empty" is
        # the exact information loss corpus_quality.py exists to detect.
        self.assertEqual({f.status for f in row.fields}, {"present", "empty", "not_extracted"})
        self.assertGreater(row.achievable_completeness_score, row.completeness_score)


class CopyTextTests(unittest.TestCase):
    """The API's own copy must come from packages/branding/copy.json.

    Six services hardcoded "Runs created in the Streamlit workspace appear
    here automatically" -- a sentence that became false when the web app
    gained its own New Run screen. Centralising the web app's copy in Slice
    12 fixed only the React half; the API kept serving the false claim.
    """

    def test_api_empty_reason_comes_from_copy_json(self):
        import json
        from apps.api import settings
        raw = json.loads((settings.BRANDING_DIR / "copy.json").read_text(encoding="utf-8"))
        self.assertEqual(copy_text.no_runs_in_project(), raw["common"]["no_runs_body"])

    def test_no_service_hardcodes_the_stale_streamlit_sentence(self):
        services = Path(__file__).resolve().parent.parent / "apps" / "api" / "services"
        offenders = [
            p.name for p in services.glob("*.py")
            if "Runs created in the Streamlit" in p.read_text(encoding="utf-8")
        ]
        self.assertEqual(offenders, [], "empty-state copy belongs in copy.json, not in a service")

    def test_unknown_key_raises_instead_of_returning_blank(self):
        # A silently blank empty_reason would look like a rendering bug and
        # would be a bare value with no basis (NFR-8).
        with self.assertRaises(KeyError):
            copy_text.common("no_such_key")


if __name__ == "__main__":
    unittest.main()
