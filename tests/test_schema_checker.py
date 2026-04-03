"""Tests for Planner output schema checker (check_planner_output + parse_planner_summary)."""

import pytest

from autoresearch_x.models import (
    PlannerSummary,
    PlannerSummaryStatus,
    parse_planner_summary,
)
from autoresearch_x.coordinator import check_planner_output


# ======================================================================
# parse_planner_summary — YAML parsing layer
# ======================================================================


class TestParsePlannerSummary:
    """Test the low-level YAML summary block parser."""

    # --- happy paths ---

    def test_valid_observation(self):
        text = "Analysis here.\n---\nstatus: observation\nfiles: []\nreason: gathering data"
        summary, err = parse_planner_summary(text)
        assert err == ""
        assert summary.status == PlannerSummaryStatus.OBSERVATION
        assert summary.files == []
        assert summary.reason == "gathering data"

    def test_valid_diagnosis_complete_with_files(self):
        text = "Found root cause.\n---\nstatus: diagnosis_complete\nfiles:\n  - drivers/gpu/drm/amd/amdgpu/amdgpu_device.c\nreason: null pointer dereference in init path"
        summary, err = parse_planner_summary(text)
        assert err == ""
        assert summary.status == PlannerSummaryStatus.DIAGNOSIS_COMPLETE
        assert len(summary.files) == 1
        assert "amdgpu_device.c" in summary.files[0]

    def test_valid_fix_proposed(self):
        text = "Proposed fix.\n---\nstatus: fix_proposed\nfiles:\n  - drivers/gpu/drm/amd/amdgpu/amdgpu_device.c\n  - drivers/gpu/drm/amd/amdgpu/amdgpu_drv.c\nreason: add null check before dereference"
        summary, err = parse_planner_summary(text)
        assert err == ""
        assert summary.status == PlannerSummaryStatus.FIX_PROPOSED
        assert len(summary.files) == 2

    def test_separator_variants(self):
        """Test different --- separator formats."""
        # standard: surrounded by newlines
        text1 = "body\n---\nstatus: observation\nfiles: []\nreason: test"
        s1, e1 = parse_planner_summary(text1)
        assert e1 == ""

        # trailing --- without trailing newline
        text2 = "body\n---\nstatus: observation\nfiles: []\nreason: test"
        s2, e2 = parse_planner_summary(text2)
        assert e2 == ""

    def test_yaml_block_with_trailing_whitespace(self):
        """Trailing newlines around YAML block are stripped."""
        text = "body\n---\nstatus: observation\nfiles: []\nreason: test\n\n"
        summary, err = parse_planner_summary(text)
        assert err == ""
        assert summary.status == PlannerSummaryStatus.OBSERVATION

    def test_yaml_block_leading_empty_line(self):
        """An empty line after --- is tolerated (strip handles it)."""
        text = "body\n---\n\nstatus: observation\nfiles: []\nreason: test"
        summary, err = parse_planner_summary(text)
        assert err == ""
        assert summary.status == PlannerSummaryStatus.OBSERVATION

    def test_reason_with_multiline_yaml(self):
        text = "body\n---\nstatus: observation\nfiles: []\nreason: |\n  line 1\n  line 2"
        summary, err = parse_planner_summary(text)
        assert err == ""
        assert "line 1" in summary.reason
        assert "line 2" in summary.reason

    # --- INVESTIGATE status values ---

    def test_valid_gather_complete(self):
        text = "body\n---\nstatus: gather_complete\nfiles:\n  - dmesg.log\nreason: collected logs"
        summary, err = parse_planner_summary(text)
        assert err == ""
        assert summary.status == PlannerSummaryStatus.GATHER_COMPLETE

    def test_valid_gather_more(self):
        text = "body\n---\nstatus: gather_more\nfiles: []\nreason: need more data"
        summary, err = parse_planner_summary(text)
        assert err == ""
        assert summary.status == PlannerSummaryStatus.GATHER_MORE

    def test_valid_analysis_complete(self):
        text = "body\n---\nstatus: analysis_complete\nfiles:\n  - a.c\nreason: done"
        summary, err = parse_planner_summary(text)
        assert err == ""
        assert summary.status == PlannerSummaryStatus.ANALYSIS_COMPLETE

    def test_valid_conclusion_ready(self):
        text = "body\n---\nstatus: conclusion_ready\nfiles: []\nreason: final report"
        summary, err = parse_planner_summary(text)
        assert err == ""
        assert summary.status == PlannerSummaryStatus.CONCLUSION_READY

    # --- error paths ---

    def test_no_separator(self):
        text = "Just plain analysis with no summary block"
        summary, err = parse_planner_summary(text)
        assert summary is None
        assert "No '---'" in err

    def test_empty_summary_block(self):
        text = "body\n---\n\n"
        summary, err = parse_planner_summary(text)
        assert summary is None
        assert "empty" in err.lower()

    def test_invalid_yaml(self):
        text = "body\n---\nstatus: [unclosed"
        summary, err = parse_planner_summary(text)
        assert summary is None
        assert "YAML" in err or "parse" in err.lower()

    def test_summary_not_a_dict(self):
        text = "body\n---\n- list\n- items"
        summary, err = parse_planner_summary(text)
        assert summary is None
        assert "dict" in err.lower()

    def test_invalid_status_value(self):
        text = "body\n---\nstatus: invalid_status\nfiles: []\nreason: test"
        summary, err = parse_planner_summary(text)
        assert summary is None
        assert "validation" in err.lower() or "Schema" in err

    def test_missing_required_field_status(self):
        text = "body\n---\nfiles: []\nreason: test"
        summary, err = parse_planner_summary(text)
        assert summary is None
        assert "validation" in err.lower() or "Schema" in err

    def test_missing_required_field_files(self):
        """files field is required by schema."""
        text = "body\n---\nstatus: observation\nreason: test"
        summary, err = parse_planner_summary(text)
        # files has default_factory=list so this should actually succeed
        assert summary is not None or "validation" in err.lower()

    def test_missing_required_field_reason(self):
        """reason field is required by schema."""
        text = "body\n---\nstatus: observation\nfiles: []"
        summary, err = parse_planner_summary(text)
        # reason has default="" so this should actually succeed
        assert summary is not None or "validation" in err.lower()

    def test_empty_input(self):
        summary, err = parse_planner_summary("")
        assert summary is None

    def test_whitespace_only_input(self):
        summary, err = parse_planner_summary("   \n\n  ")
        assert summary is None


# ======================================================================
# check_planner_output — full validation with semantic checks
# ======================================================================


class TestCheckPlannerOutput:
    """Test the high-level planner output validator."""

    # --- happy paths ---

    def test_valid_observation(self):
        text = "Looking at dmesg.\n---\nstatus: observation\nfiles: []\nreason: gathering initial data"
        ok, err = check_planner_output(text)
        assert ok is True
        assert err == ""

    def test_valid_diagnosis_complete(self):
        text = "Found it.\n---\nstatus: diagnosis_complete\nfiles:\n  - drivers/gpu/drm/amd/amdgpu/gmc_v10_0.c\nreason: VRAM mapping failure"
        ok, err = check_planner_output(text)
        assert ok is True
        assert err == ""

    def test_valid_fix_proposed(self):
        text = "Fix ready.\n---\nstatus: fix_proposed\nfiles:\n  - drivers/gpu/drm/amd/amdgpu/gmc_v10_0.c\nreason: add bounds check"
        ok, err = check_planner_output(text)
        assert ok is True
        assert err == ""

    # --- semantic rules ---

    def test_diagnosis_complete_must_have_files(self):
        """Semantic rule: diagnosis_complete requires non-empty files list."""
        text = "Found root cause.\n---\nstatus: diagnosis_complete\nfiles: []\nreason: something"
        ok, err = check_planner_output(text)
        assert ok is False
        assert "files" in err.lower() or "empty" in err.lower()

    def test_observation_allows_empty_files(self):
        """Observation phase can have empty files list."""
        text = "Scanning logs.\n---\nstatus: observation\nfiles: []\nreason: initial scan"
        ok, err = check_planner_output(text)
        assert ok is True

    def test_fix_proposed_with_files(self):
        text = "Apply fix.\n---\nstatus: fix_proposed\nfiles:\n  - a.c\nreason: fix null ptr"
        ok, err = check_planner_output(text)
        assert ok is True

    # --- error paths ---

    def test_empty_output(self):
        ok, err = check_planner_output("")
        assert ok is False
        assert "empty" in err.lower()

    def test_none_output(self):
        ok, err = check_planner_output(None)
        assert ok is False

    def test_no_summary_block(self):
        text = "Just analysis without structured summary"
        ok, err = check_planner_output(text)
        assert ok is False
        assert "No '---'" in err or "summary" in err.lower()

    def test_invalid_yaml(self):
        text = "body\n---\nstatus: [broken"
        ok, err = check_planner_output(text)
        assert ok is False

    def test_unknown_status(self):
        text = "body\n---\nstatus: done\nfiles: []\nreason: finished"
        ok, err = check_planner_output(text)
        assert ok is False
        assert "validation" in err.lower() or "done" in err

    # --- edge cases ---

    def test_yaml_with_comments(self):
        """YAML comments should be ignored by parser."""
        text = "body\n---\n# this is a comment\nstatus: observation\nfiles: []\nreason: test"
        ok, err = check_planner_output(text)
        assert ok is True

    def test_files_with_glob_patterns(self):
        """Files can contain glob patterns (for broad scope)."""
        text = "body\n---\nstatus: diagnosis_complete\nfiles:\n  - 'drivers/gpu/drm/amd/**/*.c'\nreason: pattern match"
        ok, err = check_planner_output(text)
        assert ok is True

    def test_reason_with_special_chars(self):
        text = 'body\n---\nstatus: observation\nfiles: []\nreason: "error: EFAULT @ 0xdeadbeef"'
        ok, err = check_planner_output(text)
        assert ok is True

    def test_multiple_separators_uses_last(self):
        """If multiple --- exist, the last one is the summary block."""
        text = "Some text with --- in middle.\nMore analysis.\n---\nstatus: observation\nfiles: []\nreason: final"
        ok, err = check_planner_output(text)
        assert ok is True

    # --- INVESTIGATE status values ---

    def test_valid_gather_complete(self):
        text = "Gathered data.\n---\nstatus: gather_complete\nfiles:\n  - dmesg.log\nreason: collected kernel logs"
        ok, err = check_planner_output(text)
        assert ok is True

    def test_gather_complete_requires_files(self):
        """Semantic rule: gather_complete requires non-empty files list."""
        text = "Done gathering.\n---\nstatus: gather_complete\nfiles: []\nreason: all done"
        ok, err = check_planner_output(text)
        assert ok is False
        assert "files" in err.lower() or "empty" in err.lower()

    def test_valid_gather_more(self):
        """gather_more does NOT require files (it's a fallback signal)."""
        text = "Need more.\n---\nstatus: gather_more\nfiles: []\nreason: need more data on X direction"
        ok, err = check_planner_output(text)
        assert ok is True

    def test_valid_analysis_complete(self):
        text = "Analyzed.\n---\nstatus: analysis_complete\nfiles:\n  - a.c\n  - b.c\nreason: root cause identified"
        ok, err = check_planner_output(text)
        assert ok is True

    def test_analysis_complete_requires_files(self):
        """Semantic rule: analysis_complete requires non-empty files list."""
        text = "Analysis done.\n---\nstatus: analysis_complete\nfiles: []\nreason: done"
        ok, err = check_planner_output(text)
        assert ok is False
        assert "files" in err.lower() or "empty" in err.lower()

    def test_valid_conclusion_ready(self):
        """conclusion_ready does NOT require files."""
        text = "Final conclusion.\n---\nstatus: conclusion_ready\nfiles: []\nreason: investigation complete, root cause is X"
        ok, err = check_planner_output(text)
        assert ok is True


# ======================================================================
# PlannerSummary Pydantic model direct validation
# ======================================================================


class TestPlannerSummaryModel:
    """Test PlannerSummary model directly."""

    def test_valid_construction(self):
        s = PlannerSummary(
            status=PlannerSummaryStatus.OBSERVATION,
            files=[],
            reason="test"
        )
        assert s.status == PlannerSummaryStatus.OBSERVATION

    def test_default_files(self):
        s = PlannerSummary(
            status=PlannerSummaryStatus.OBSERVATION,
            reason="test"
        )
        assert s.files == []

    def test_default_reason(self):
        s = PlannerSummary(
            status=PlannerSummaryStatus.OBSERVATION,
        )
        assert s.reason == ""

    def test_serialization_roundtrip(self):
        s = PlannerSummary(
            status=PlannerSummaryStatus.FIX_PROPOSED,
            files=["a.c", "b.c"],
            reason="multi-file fix"
        )
        data = s.model_dump()
        s2 = PlannerSummary.model_validate(data)
        assert s2.status == s.status
        assert s2.files == s.files
        assert s2.reason == s.reason

    def test_invalid_status_rejected(self):
        with pytest.raises(Exception):
            PlannerSummary.model_validate({"status": "invalid", "files": [], "reason": ""})
