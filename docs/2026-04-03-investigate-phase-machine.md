# Design: INVESTIGATE Phase State Machine

**Author**: Morgan
**Date**: 2026-04-03
**Status**: Draft — Pending review
**Source of truth**: `skills/autoresearch-x/ref-investigate-mode.md`

---

## 1. Overview

INVESTIGATE 模式的目标是结构化调研：通过 gather→analyze→conclude 三阶段状态机，确保每个结论都有可验证的证据支撑。

设计参考：`ref-investigate-mode.md`（Toulmin evidence chain + ACH hypothesis matrix）。

## 2. State Machine

```
gather ──[gather_complete]──→ analyze
analyze ──[analysis_complete]──→ conclude
analyze ──[gather_more]──→ gather   (回退：发现新方向，保留已有发现)
conclude ──[Planner-driven]──→ gather (回退：结论被新证据推翻)
```

**关键特性**：
- gather 回退是**累积性**的（不 drop findings），session context 自然保留历史
- Planner agentic 读历史：prompt 只给 results.tsv 概览，Planner 自主决定要不要深入读 iteration 文件
- Worker 不读历史，只按 Planner 指令执行

### 2.1 Trigger Rules

| 转换 | 触发源 | 条件 |
|------|--------|------|
| gather→analyze | Planner-driven | `PlannerSummaryStatus.GATHER_COMPLETE` |
| analyze→conclude | Planner-driven | `PlannerSummaryStatus.ANALYSIS_COMPLETE` |
| analyze→gather | Planner-driven | `PlannerSummaryStatus.GATHER_MORE` |
| conclude→gather | Planner-driven | 需要新增枚举值或复用 `GATHER_MORE`（见 §5） |

### 2.2 和 DEBUG 的区别

| 维度 | DEBUG | INVESTIGATE |
|------|-------|-------------|
| 角色 | Planner/Worker/Evaluator | Planner/Worker（无 Evaluator） |
| 回退 | decision-driven (KEEP/DISCARD) | Planner-driven |
| 回退语义 | fix DISCARD → observe（推翻，重来） | gather_more → gather（累积，不 drop） |
| 完成条件 | metric 达标 | Planner status=conclusion_ready |

## 3. API Design

### 3.1 `PlannerSummaryStatus` (models.py)

```python
class PlannerSummaryStatus(str, Enum):
    # DEBUG
    OBSERVATION = "observation"
    DIAGNOSIS_COMPLETE = "diagnosis_complete"
    FIX_PROPOSED = "fix_proposed"
    # INVESTIGATE
    GATHER_COMPLETE = "gather_complete"     # gather→analyze
    GATHER_MORE = "gather_more"             # analyze→gather (回退)
    ANALYSIS_COMPLETE = "analysis_complete"  # analyze→conclude
    CONCLUSION_READY = "conclusion_ready"    # conclude→结束
    REINVESTIGATE = "reinvestigate"          # conclude→gather (回退，见 §5)
```

### 3.2 `_PHASE_TRANSITION_RULES` (coordinator.py)

```python
_PHASE_TRANSITION_RULES = {
    RunMode.DEBUG: {
        ("observe", "diagnose"): 8,          # threshold
        ("diagnose", "fix"): None,           # Planner-driven
    },
    RunMode.INVESTIGATE: {
        ("gather", "analyze"): None,         # Planner-driven
        ("analyze", "conclude"): None,       # Planner-driven
    },
}
```

### 3.3 `_transition_phase()` (coordinator.py)

```python
def _transition_phase(
    state: RunState,
    planner_text: Optional[str] = None,
    decision: Optional[Decision] = None,
) -> bool:
    """
    1. Decision-driven backward (DEBUG only):
       - fix → observe (KEEP)
       - fix → observe (DISCARD)
    2. Planner-driven backward (INVESTIGATE):
       - analyze + GATHER_MORE → gather
       - conclude + REINVESTIGATE → gather
    3. Planner-driven forward (both modes, via _should_advance_phase):
       - DEBUG: observe→diagnose (threshold 8), diagnose→fix (FIX_PROPOSED)
       - INVESTIGATE: gather→analyze (GATHER_COMPLETE), analyze→conclude (ANALYSIS_COMPLETE)
    """
```

### 3.4 `_decide()` (coordinator.py)

**当前问题**：`_decide()` 对所有模式统一处理，`metric_value=None` 返回 DISCARD。INVESTIGATE 没有 metric，每轮都是 DISCARD。

**方案**（见 §5 待确认项）：
- INVESTIGATE 模式下 `_decide()` 返回 `None`（跳过 decision-driven 路径）
- 或者 INVESTIGATE 的回退完全走 Planner-driven，`_decide()` 结果不用于 phase transition

### 3.5 `_should_advance_phase()` (coordinator.py)

```python
_ADVANCE_MAP = {
    ("observe", "diagnose"): {PlannerSummaryStatus.DIAGNOSIS_COMPLETE},
    ("diagnose", "fix"): {PlannerSummaryStatus.FIX_PROPOSED},
    ("gather", "analyze"): {PlannerSummaryStatus.GATHER_COMPLETE},
    ("analyze", "conclude"): {PlannerSummaryStatus.ANALYSIS_COMPLETE},
}
```

### 3.6 `check_planner_output()` (coordinator.py)

语义检查：
- `DIAGNOSIS_COMPLETE` → files 非空
- `FIX_PROPOSED` → files 非空
- `GATHER_COMPLETE` → files 非空
- `ANALYSIS_COMPLETE` → files 非空
- `OBSERVATION`, `GATHER_MORE`, `CONCLUSION_READY`, `REINVESTIGATE` → 无 files 约束

### 3.7 `_run_loop()` INVESTIGATE 适配

INVESTIGATE 模式下跳过 Evaluator 步骤（无 metric，不需要 eval）：
```python
if state.mode != RunMode.INVESTIGATE:
    eval_text = _run_evaluator(...)
    metric_value = _extract_metric(eval_text, state.metric_name)
else:
    metric_value = None
    eval_text = ""
```

## 4. Test Design

### 4.1 Unit Tests — `test_planner_summary.py`

| Test Case | Input | Expected |
|-----------|-------|----------|
| `test_parse_gather_complete` | `status: gather_complete\nfiles: [a.py]` | `PlannerSummaryStatus.GATHER_COMPLETE`, files=[a.py] |
| `test_parse_gather_more` | `status: gather_more\nreason: need more` | `PlannerSummaryStatus.GATHER_MORE`, reason="need more" |
| `test_parse_analysis_complete` | `status: analysis_complete\nfiles: [a.py]` | `PlannerSummaryStatus.ANALYSIS_COMPLETE` |
| `test_parse_conclusion_ready` | `status: conclusion_ready` | `PlannerSummaryStatus.CONCLUSION_READY` |
| `test_parse_reinvestigate` | `status: reinvestigate\nreason: contradicted` | `PlannerSummaryStatus.REINVESTIGATE` |

### 4.2 Unit Tests — `test_coordinator.py`

| Test Case | Setup | Verify |
|-----------|-------|--------|
| `test_investigate_gather_to_analyze` | mode=INVESTIGATE, phase=gather, planner status=GATHER_COMPLETE | phase=analyze, phase_iteration=0 |
| `test_investigate_analyze_to_conclude` | mode=INVESTIGATE, phase=analyze, planner status=ANALYSIS_COMPLETE | phase=conclude, phase_iteration=0 |
| `test_investigate_analyze_gather_more` | mode=INVESTIGATE, phase=analyze, planner status=GATHER_MORE | phase=gather, phase_iteration=0 |
| `test_investigate_conclude_reinvestigate` | mode=INVESTIGATE, phase=conclude, planner status=REINVESTIGATE | phase=gather, phase_iteration=0 |
| `test_investigate_no_backward_on_none` | mode=INVESTIGATE, phase=gather, planner status=OBSERVATION | phase=gather (no transition), phase_iteration incremented |
| `test_debug_fix_discard_observe` | mode=DEBUG, phase=fix, decision=DISCARD | phase=observe, phase_iteration=0 |
| `test_debug_observe_threshold_8` | mode=DEBUG, phase=observe, phase_iteration=8, planner status=OBSERVATION | phase=diagnose (threshold trigger) |
| `test_debug_observe_no_transition_below_8` | mode=DEBUG, phase=observe, phase_iteration=3 | phase=observe (no transition) |

### 4.3 Integration Tests

| Test Case | Scenario | Verify |
|-----------|----------|--------|
| `test_investigate_full_flow` | gather→gather→analyze→conclude (happy path) | 每阶段正确转换，最终 status=conclusion_ready 结束循环 |
| `test_investigate_analyze_fallback` | gather→analyze→gather→analyze→conclude | analyze→gather 回退后正确重新进入 analyze |
| `test_investigate_conclude_fallback` | gather→analyze→conclude→gather→analyze→conclude | conclude 回退后正确重新流转 |

### 4.4 Edge Cases

- `check_planner_output()`: `gather_complete` 但 files 为空 → 返回 False
- `_transition_phase()`: INVESTIGATE 模式下传入 decision → 不应触发 DEBUG 的 backward 路径
- `_transition_phase()`: OPTIMIZE 模式 → 直接 return False

## 5. Open Questions (需要 @waynejing 确认)

### Q1: INVESTIGATE 的 `_decide()` 处理

**问题**：INVESTIGATE 没有 metric，`_decide()` 返回 DISCARD。这个 DISCARD 会触发 `_transition_phase()` 的 decision-driven backward 路径（当前代码中 conclude+DISCARD→gather）。

**选项**：
- **A**：`_decide()` 对 INVESTIGATE 返回 `None`，`_transition_phase()` 跳过 decision-driven 路径。回退完全走 Planner-driven。
- **B**：INVESTIGATE 跳过 Evaluator + `_decide()` 调用，直接走 Planner-driven forward/backward。
- **C**：保持现状（无 metric 默认 DISCARD），conclude 阶段靠 max_iterations 兜底。

**推荐**：**B**。INVESTIGATE 没有 Evaluator 是已确认的设计，跳过 Evaluator 和 `_decide()` 是自然推论。回退完全走 Planner-driven（`GATHER_MORE`, `REINVESTIGATE`）。

### Q2: conclude 回退的 Planner status 值

**选项**：
- 新增 `REINVESTIGATE` 枚举值（语义：结论被推翻，重新调查）
- 复用 `GATHER_MORE`（语义模糊：gather_more 在 analyze 阶段已有含义）

**推荐**：新增 `REINVESTIGATE`。语义更精确——conclude→gather 是"推翻结论重新来过"，和 analyze→gather（"发现新方向"）语义不同。

### Q3: INVESTIGATE Evaluator 步骤

**问题**：`_run_loop()` 当前对所有模式都调用 `_run_evaluator()`。INVESTIGATE 没有 eval_command，Evaluator 会失败或返回空。

**方案**：INVESTIGATE 模式下跳过 `_run_evaluator()` 调用，`metric_value=None`, `eval_text=""`。

## 6. File Changes Summary

| File | Change |
|------|--------|
| `models.py` | `PlannerSummaryStatus` 新增 `GATHER_COMPLETE`, `GATHER_MORE`, `ANALYSIS_COMPLETE`, `CONCLUSION_READY`, `REINVESTIGATE` |
| `coordinator.py` | `_PHASE_TRANSITION_RULES` DEBUG threshold 2→8, INVESTIGATE Planner-driven |
| `coordinator.py` | `_transition_phase()` 修正 fix DISCARD→observe + INVESTIGATE 回退 |
| `coordinator.py` | `_should_advance_phase()` 新增辅助函数 |
| `coordinator.py` | `check_planner_output()` 适配新 status |
| `coordinator.py` | `_run_loop()` INVESTIGATE 跳过 Evaluator |
| `coordinator.py` | `_decide()` INVESTIGATE 特殊处理（待确认 Q1） |
