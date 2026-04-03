"""Tests for _transition_phase() and _should_advance_phase() state machine logic."""

import pytest

from autoresearch_x.models import (
    Decision,
    PlannerSummaryStatus,
    RunMode,
    RunState,
)
from autoresearch_x.coordinator import _transition_phase, _should_advance_phase


# ======================================================================
# Helpers
# ======================================================================


def _make_state(mode: RunMode, phase: str, phase_iteration: int = 0) -> RunState:
    """Create a minimal RunState for testing phase transitions."""
    return RunState(
        tag="test-tag",
        mode=mode,
        target="test: benchmark",
        current_phase=phase,
        phase_iteration=phase_iteration,
    )


def _planner_text(status: str, files: list[str] | None = None, reason: str = "test") -> str:
    """Generate a mock Planner output with summary block.

    Produces valid YAML with proper list syntax for files.
    """
    if files:
        files_yaml = "\n".join(["  - " + f for f in files])
        files_block = f"\n{files_yaml}"
    else:
        files_block = "\n  []" if files is None else "\n  []"
    return f"Analysis body.\n---\nstatus: {status}\nfiles:{files_block}\nreason: {reason}"


# NOTE: _transition_phase() always increments phase_iteration at the end
# (line 972). After a transition that resets to 0, phase_iteration becomes 1.
# After no transition, phase_iteration = original + 1.


# ======================================================================
# _should_advance_phase
# ======================================================================


class TestShouldAdvancePhase:
    """Test the _should_advance_phase() helper function."""

    # DEBUG mode
    def test_debug_observe_to_diagnose_with_diagnosis_complete(self):
        assert _should_advance_phase(
            PlannerSummaryStatus.DIAGNOSIS_COMPLETE, "observe", "diagnose"
        ) is True

    def test_debug_observe_to_diagnose_with_observation(self):
        assert _should_advance_phase(
            PlannerSummaryStatus.OBSERVATION, "observe", "diagnose"
        ) is False

    def test_debug_diagnose_to_fix_with_fix_proposed(self):
        assert _should_advance_phase(
            PlannerSummaryStatus.FIX_PROPOSED, "diagnose", "fix"
        ) is True

    def test_debug_diagnose_to_fix_with_wrong_status(self):
        assert _should_advance_phase(
            PlannerSummaryStatus.OBSERVATION, "diagnose", "fix"
        ) is False

    # INVESTIGATE mode
    def test_investigate_gather_to_analyze_with_gather_complete(self):
        assert _should_advance_phase(
            PlannerSummaryStatus.GATHER_COMPLETE, "gather", "analyze"
        ) is True

    def test_investigate_gather_to_analyze_with_wrong_status(self):
        assert _should_advance_phase(
            PlannerSummaryStatus.GATHER_MORE, "gather", "analyze"
        ) is False

    def test_investigate_analyze_to_conclude_with_analysis_complete(self):
        assert _should_advance_phase(
            PlannerSummaryStatus.ANALYSIS_COMPLETE, "analyze", "conclude"
        ) is True

    def test_investigate_analyze_to_conclude_with_wrong_status(self):
        assert _should_advance_phase(
            PlannerSummaryStatus.GATHER_MORE, "analyze", "conclude"
        ) is False

    # Unknown transition
    def test_unknown_transition_returns_false(self):
        assert _should_advance_phase(
            PlannerSummaryStatus.OBSERVATION, "unknown", "phase"
        ) is False


# ======================================================================
# _transition_phase — DEBUG mode
# ======================================================================


class TestTransitionPhaseDEBUG:
    """Test _transition_phase() for DEBUG mode."""

    # --- forward: observe → diagnose ---

    def test_observe_to_diagnose_at_threshold(self):
        """observe with phase_iteration >= 8 should transition to diagnose."""
        state = _make_state(RunMode.DEBUG, "observe", phase_iteration=8)
        moved = _transition_phase(state)
        assert moved is True
        assert state.current_phase == "diagnose"
        assert state.phase_iteration == 1  # reset to 0, then incremented

    def test_observe_to_diagnose_above_threshold(self):
        state = _make_state(RunMode.DEBUG, "observe", phase_iteration=10)
        moved = _transition_phase(state)
        assert moved is True
        assert state.current_phase == "diagnose"

    def test_observe_no_transition_below_threshold(self):
        """observe with phase_iteration < 8 should NOT transition."""
        state = _make_state(RunMode.DEBUG, "observe", phase_iteration=3)
        moved = _transition_phase(state)
        assert moved is False
        assert state.current_phase == "observe"
        assert state.phase_iteration == 4  # incremented

    def test_observe_no_transition_at_7(self):
        """Edge case: phase_iteration=7 is still below threshold."""
        state = _make_state(RunMode.DEBUG, "observe", phase_iteration=7)
        moved = _transition_phase(state)
        assert moved is False
        assert state.current_phase == "observe"

    # --- forward: diagnose → fix (planner-driven) ---

    def test_diagnose_to_fix_with_fix_proposed(self):
        state = _make_state(RunMode.DEBUG, "diagnose")
        planner = _planner_text("fix_proposed", files=["a.c"])
        moved = _transition_phase(state, planner_text=planner)
        assert moved is True
        assert state.current_phase == "fix"
        assert state.phase_iteration == 1

    def test_diagnose_stays_without_fix_proposed(self):
        state = _make_state(RunMode.DEBUG, "diagnose")
        planner = _planner_text("observation")
        moved = _transition_phase(state, planner_text=planner)
        assert moved is False
        assert state.current_phase == "diagnose"

    # --- backward: fix → observe ---

    def test_fix_keep_goes_to_observe(self):
        """fix + KEEP → observe (re-observe after change)."""
        state = _make_state(RunMode.DEBUG, "fix")
        moved = _transition_phase(state, decision=Decision.KEEP)
        assert moved is True
        assert state.current_phase == "observe"
        assert state.phase_iteration == 1

    def test_fix_discard_goes_to_observe(self):
        """fix + DISCARD → observe (re-observe, not diagnose)."""
        state = _make_state(RunMode.DEBUG, "fix")
        moved = _transition_phase(state, decision=Decision.DISCARD)
        assert moved is True
        assert state.current_phase == "observe"
        assert state.phase_iteration == 1

    # --- no transition for OPTIMIZE ---

    def test_optimize_returns_false(self):
        state = _make_state(RunMode.OPTIMIZE, "observe")
        moved = _transition_phase(state)
        assert moved is False

    # --- no transition when phase is None ---

    def test_no_phase_returns_false(self):
        state = _make_state(RunMode.DEBUG, "observe")
        state.current_phase = None
        moved = _transition_phase(state)
        assert moved is False


# ======================================================================
# _transition_phase — INVESTIGATE mode
# ======================================================================


class TestTransitionPhaseINVESTIGATE:
    """Test _transition_phase() for INVESTIGATE mode."""

    # --- forward: gather → analyze ---

    def test_gather_to_analyze_with_gather_complete(self):
        state = _make_state(RunMode.INVESTIGATE, "gather")
        planner = _planner_text("gather_complete", files=["readme.md"])
        moved = _transition_phase(state, planner_text=planner)
        assert moved is True
        assert state.current_phase == "analyze"
        assert state.phase_iteration == 1

    def test_gather_stays_without_gather_complete(self):
        state = _make_state(RunMode.INVESTIGATE, "gather")
        planner = _planner_text("observation")
        moved = _transition_phase(state, planner_text=planner)
        assert moved is False
        assert state.current_phase == "gather"

    # --- forward: analyze → conclude ---

    def test_analyze_to_conclude_with_analysis_complete(self):
        state = _make_state(RunMode.INVESTIGATE, "analyze")
        planner = _planner_text("analysis_complete", files=["a.c", "b.c"])
        moved = _transition_phase(state, planner_text=planner)
        assert moved is True
        assert state.current_phase == "conclude"
        assert state.phase_iteration == 1

    def test_analyze_stays_without_analysis_complete(self):
        state = _make_state(RunMode.INVESTIGATE, "analyze")
        planner = _planner_text("observation")
        moved = _transition_phase(state, planner_text=planner)
        assert moved is False
        assert state.current_phase == "analyze"

    # --- backward: analyze → gather (gather_more) ---

    def test_analyze_gather_more_goes_to_gather(self):
        """analyze + planner status=gather_more → gather (fall back, preserve findings)."""
        state = _make_state(RunMode.INVESTIGATE, "analyze", phase_iteration=3)
        planner = _planner_text("gather_more", reason="need more data on X")
        moved = _transition_phase(state, planner_text=planner)
        assert moved is True
        assert state.current_phase == "gather"
        assert state.phase_iteration == 1

    # --- backward: conclude → gather (REINVESTIGATE) ---

    def test_conclude_reinvestigate_goes_to_gather(self):
        """conclude + planner status=reinvestigate → gather (conclusion contradicted)."""
        state = _make_state(RunMode.INVESTIGATE, "conclude")
        planner = _planner_text("reinvestigate", reason="new evidence contradicts conclusion")
        moved = _transition_phase(state, planner_text=planner)
        assert moved is True
        assert state.current_phase == "gather"
        assert state.phase_iteration == 1

    # --- INVESTIGATE should NOT trigger DEBUG backward ---

    def test_investigate_does_not_use_debug_backward(self):
        """INVESTIGATE mode with decision=DISCARD in gather phase should not crash or transition."""
        state = _make_state(RunMode.INVESTIGATE, "gather")
        moved = _transition_phase(state, decision=Decision.DISCARD)
        # DEBUG backward is gated by mode == DEBUG, so INVESTIGATE is unaffected
        assert moved is False
        assert state.current_phase == "gather"

    # --- INVESTIGATE should not trigger DEBUG observe threshold ---

    def test_investigate_gather_no_threshold_transition(self):
        """INVESTIGATE gather phase should NOT auto-transition via iteration threshold."""
        state = _make_state(RunMode.INVESTIGATE, "gather", phase_iteration=100)
        moved = _transition_phase(state)
        # INVESTIGATE gather→analyze is Planner-driven (None), not threshold
        assert moved is False
        assert state.current_phase == "gather"

    # --- phase_iteration always increments ---

    def test_phase_iteration_increments_on_no_transition(self):
        state = _make_state(RunMode.INVESTIGATE, "gather", phase_iteration=5)
        _transition_phase(state)
        assert state.phase_iteration == 6


# ======================================================================
# Integration — multi-iteration phase flows
# ======================================================================


class TestInvestigateFullFlow:
    """Integration: INVESTIGATE happy path gather→analyze→conclude."""

    def test_gather_to_analyze_to_conclude(self):
        """Happy path: gather → analyze → conclude (planner-driven)."""
        state = _make_state(RunMode.INVESTIGATE, "gather")
        assert state.current_phase == "gather"
        assert state.phase_iteration == 0

        # Iteration 1: gather stays (no planner status)
        moved = _transition_phase(state)
        assert moved is False
        assert state.current_phase == "gather"
        assert state.phase_iteration == 1

        # Iteration 2: gather stays
        moved = _transition_phase(state)
        assert moved is False
        assert state.current_phase == "gather"
        assert state.phase_iteration == 2

        # Iteration 3: gather → analyze (GATHER_COMPLETE)
        planner = _planner_text("gather_complete", files=["dmesg.log", "syslog"])
        moved = _transition_phase(state, planner_text=planner)
        assert moved is True
        assert state.current_phase == "analyze"
        assert state.phase_iteration == 1

        # Iteration 4: analyze stays
        planner = _planner_text("observation")
        moved = _transition_phase(state, planner_text=planner)
        assert moved is False
        assert state.current_phase == "analyze"
        assert state.phase_iteration == 2

        # Iteration 5: analyze → conclude (ANALYSIS_COMPLETE)
        planner = _planner_text("analysis_complete", files=["a.c", "b.c"])
        moved = _transition_phase(state, planner_text=planner)
        assert moved is True
        assert state.current_phase == "conclude"
        assert state.phase_iteration == 1

        # Iteration 6: conclude stays (waiting for conclusion_ready)
        planner = _planner_text("observation")
        moved = _transition_phase(state, planner_text=planner)
        assert moved is False
        assert state.current_phase == "conclude"
        assert state.phase_iteration == 2


class TestInvestigateAnalyzeFallback:
    """Integration: INVESTIGATE analyze → gather → analyze (GATHER_MORE backtrack)."""

    def test_analyze_gather_more_then_back_to_analyze(self):
        """analyze → gather (gather_more) → analyze (gather_complete)."""
        state = _make_state(RunMode.INVESTIGATE, "analyze", phase_iteration=3)

        # analyze → gather (GATHER_MORE backtrack)
        planner = _planner_text("gather_more", reason="need more data on X")
        moved = _transition_phase(state, planner_text=planner)
        assert moved is True
        assert state.current_phase == "gather"
        assert state.phase_iteration == 1

        # gather stays for a few iterations
        moved = _transition_phase(state)
        assert state.current_phase == "gather"
        assert state.phase_iteration == 2

        # gather → analyze (GATHER_COMPLETE)
        planner = _planner_text("gather_complete", files=["new_data.log"])
        moved = _transition_phase(state, planner_text=planner)
        assert moved is True
        assert state.current_phase == "analyze"
        assert state.phase_iteration == 1

        # analyze → conclude (ANALYSIS_COMPLETE)
        planner = _planner_text("analysis_complete", files=["a.c"])
        moved = _transition_phase(state, planner_text=planner)
        assert moved is True
        assert state.current_phase == "conclude"
        assert state.phase_iteration == 1


class TestInvestigateConcludeFallback:
    """Integration: INVESTIGATE conclude → gather → analyze → conclude (REINVESTIGATE)."""

    def test_conclude_reinvestigate_full_cycle(self):
        """conclude → gather (reinvestigate) → analyze → conclude."""
        state = _make_state(RunMode.INVESTIGATE, "conclude", phase_iteration=2)

        # conclude → gather (REINVESTIGATE backtrack)
        planner = _planner_text("reinvestigate", reason="new evidence contradicts conclusion")
        moved = _transition_phase(state, planner_text=planner)
        assert moved is True
        assert state.current_phase == "gather"
        assert state.phase_iteration == 1

        # gather → analyze
        planner = _planner_text("gather_complete", files=["evidence.log"])
        moved = _transition_phase(state, planner_text=planner)
        assert moved is True
        assert state.current_phase == "analyze"
        assert state.phase_iteration == 1

        # analyze → conclude
        planner = _planner_text("analysis_complete", files=["a.c"])
        moved = _transition_phase(state, planner_text=planner)
        assert moved is True
        assert state.current_phase == "conclude"
        assert state.phase_iteration == 1


class TestInvestigateDecisionIgnored:
    """INVESTIGATE mode should not react to decision parameter."""

    def test_decision_discard_does_not_trigger_debug_backward(self):
        """INVESTIGATE + decision=DISCARD should not trigger fix→observe."""
        for phase in ["gather", "analyze", "conclude"]:
            state = _make_state(RunMode.INVESTIGATE, phase)
            moved = _transition_phase(state, decision=Decision.DISCARD)
            assert state.current_phase == phase
            assert moved is False

    def test_decision_keep_does_not_trigger_debug_backward(self):
        """INVESTIGATE + decision=KEEP should not trigger fix→observe."""
        for phase in ["gather", "analyze", "conclude"]:
            state = _make_state(RunMode.INVESTIGATE, phase)
            moved = _transition_phase(state, decision=Decision.KEEP)
            assert state.current_phase == phase
            assert moved is False


# ======================================================================
# Edge cases
# ======================================================================


class TestTransitionPhaseEdgeCases:
    """Edge cases for _transition_phase()."""

    def test_backward_takes_priority_over_forward(self):
        """When both decision (backward) and planner status (forward) are present,
        backward should take priority."""
        state = _make_state(RunMode.DEBUG, "fix")
        planner = _planner_text("fix_proposed", files=["a.c"])
        moved = _transition_phase(state, planner_text=planner, decision=Decision.DISCARD)
        # DISCARD backward to observe, not forward (fix has no forward rule anyway)
        assert moved is True
        assert state.current_phase == "observe"

    def test_planner_text_none_still_works_for_threshold(self):
        """Threshold-based transitions should work even without planner_text."""
        state = _make_state(RunMode.DEBUG, "observe", phase_iteration=8)
        moved = _transition_phase(state, planner_text=None)
        assert moved is True
        assert state.current_phase == "diagnose"

    def test_planner_text_none_no_planner_driven_transition(self):
        """Planner-driven transitions should NOT fire without planner_text."""
        state = _make_state(RunMode.INVESTIGATE, "gather")
        moved = _transition_phase(state, planner_text=None)
        assert moved is False

    def test_invalid_planner_text_graceful(self):
        """Invalid planner text should not crash, just no transition."""
        state = _make_state(RunMode.INVESTIGATE, "analyze")
        moved = _transition_phase(state, planner_text="not a valid summary block")
        assert moved is False
        assert state.current_phase == "analyze"
