# IV-Agent Run Summary

| Field | Value |
|-------|-------|
| Chip ID | `SMALL_CHIP_001` |
| Run ID | `RUN_SMALL_001` |
| Start | 2026-04-16 23:47:58 |
| End | 2026-04-16 23:47:59 |
| Duration | 0 s (0.0 min) |
| Grid | 3 × 3 = 9 devices |
| Operator | ci |
| Mode | Simulation |

## Device Outcomes

| Status | Count |
|--------|-------|
| ✅ Healthy | 5 |
| ⚠️ Degrading | 0 |
| ❌ Failed | 2 |
| ⛔ Shorted | 1 |
| 🔌 Contact issue | 1 |
| ⏭ Skipped | 0 |
| **Total done** | **9** |

Max consecutive failures: **4**

## Active Hypotheses

| Hypothesis | Support | Evidence |
|-----------|---------|---------|
| True Device Degradation | 1.00 | [llm_reasoning] LLM: No immediate diagnostic concern; procee |
| Corner Effect | 0.92 | [llm_reasoning] LLM: No immediate diagnostic concern; procee |
| Local Spatial Defect | 0.53 | [llm_reasoning] LLM: No immediate diagnostic concern; procee |

## Alerts (0 total)

_No alerts raised._

## Experiment Notes (last 20)

**[23:47:59] `CAP_01_02`** — [LLM] LLM analysis [stress_batch] for CAP_01_02: Primary evidence supports TRUE_DEVICE_DEGRADATION. Fabrication note: Corner devices may have non-uniform dielectric at electrode edges. Trend state: stable. Evidence strength is moderate; additional measurements are recommended before drawing firm conclusions.

**[23:47:59] `CAP_01_02`** — **Stress testing complete** (5 batches). Device status: healthy.

**[23:47:59] `CAP_02_00`** — **Shorted device detected.** I(1V) = 1.22e-03 A, R_est = 8.17e+02 Ohm. Pre-existing short hypothesis supported.  
[LLM] LLM analysis [health_check] for CAP_02_00: Primary evidence supports CORNER_EFFECT and LOCAL_SPATIAL_DEFECT. Fabrication note: Corner electrode geometry causes enhanced local field stress. Trend state: insufficient_data. Evidence strength is moderate; additional measurements are recommended before drawing firm conclusions.

**[23:47:59] `CAP_02_00`** — **Shorted device detected.** I(1V) = 1.22e-03 A, R_est = 8.17e+02 Ohm. Pre-existing short hypothesis supported.

**[23:47:59] `CAP_02_01`** — **Healthy device.** I(1V) = 1.12e-11 A. Normal stress protocol initiated.  
[LLM] LLM analysis [health_check] for CAP_02_01: Primary evidence supports TRUE_DEVICE_DEGRADATION. Fabrication note: Corner electrode geometry causes enhanced local field stress. Trend state: insufficient_data. Evidence strength is moderate; additional measurements are recommended before drawing firm conclusions.

**[23:47:59] `CAP_02_01`** — **Compliance hit during stress (batch 1).** V_bd = 8.5 V. Dense monitoring activated.

**[23:47:59] `CAP_02_01`** — Protocol switched to DENSE_MONITORING at batch 1. Reason: Compliance hit at 8.5 V during stress batch 1. Switching to dense monitoring.

**[23:47:59] `CAP_02_01`** — [LLM] LLM analysis [stress_batch] for CAP_02_01: Primary evidence supports CORNER_EFFECT and TRUE_DEVICE_DEGRADATION. Fabrication note: Corner electrode geometry causes enhanced local field stress. Trend state: near_breakdown. Evidence is consistent with a meaningful device-level event.

**[23:47:59] `CAP_02_01`** — **Device failed during dense monitoring** (batch 3). V_bd = 7.25 V.

**[23:47:59] `CAP_02_01`** — Device marked FAILED after 3 stress batches. Reason: Compliance hit during dense monitoring (batch 3). Device has failed.

**[23:47:59]** — **Spatial cluster detected**: 2-device cluster in bottom-left region. Members: CAP_01_00, CAP_02_01. Region: bottom-left.

**[23:47:59] `CAP_02_02`** — **High suspicion despite OK metrics.** Reasons: consecutive_device_failures: 3 consecutive device failures (threshold for suspicion: 2); sudden_failure_after_healthy_streak: 3 consecutive failures following a run of 5 healthy devices — sudden contact or probe degradation suspected. Confirmatory check scheduled.  
[LLM] LLM analysis [health_check] for CAP_02_02: Primary evidence supports CONTACT_DEGRADATION. Fabrication note: Corner electrode geometry causes enhanced local field stress. Trend state: insufficient_data. Evidence is consistent with a meaningful device-level event.

**[23:47:59] `CAP_02_02`** — **Confirmatory check passed** on CAP_02_02. Stress testing initiated.

**[23:47:59] `CAP_02_02`** — **Control device check** (CAP_01_01) triggered by activity on CAP_02_02. Result: HEALTHY ✓. Setup appears stable. Observed issues are likely real device/process behaviour. CONTACT_DEGRADATION or LOCAL_SPATIAL_DEFECT hypothesis strengthened.

**[23:47:59] `CAP_02_02`** — **Compliance hit during stress (batch 1).** V_bd = 9.5 V. Dense monitoring activated.

**[23:47:59] `CAP_02_02`** — Protocol switched to DENSE_MONITORING at batch 1. Reason: Compliance hit at 9.5 V during stress batch 1. Switching to dense monitoring.

**[23:47:59] `CAP_02_02`** — [LLM] LLM analysis [stress_batch] for CAP_02_02: Primary evidence supports CONTACT_DEGRADATION. Fabrication note: Corner electrode geometry causes enhanced local field stress. Control device result: healthy. Trend state: near_breakdown. Evidence is consistent with a meaningful device-level event.

**[23:47:59] `CAP_02_02`** — **Device failed during dense monitoring** (batch 3). V_bd = 7.25 V.

**[23:47:59] `CAP_02_02`** — Device marked FAILED after 3 stress batches. Reason: Compliance hit during dense monitoring (batch 3). Device has failed.

**[23:47:59]** — **Spatial cluster detected**: 3-device cluster in bottom-center region. Members: CAP_01_00, CAP_02_01, CAP_02_02. Region: bottom-center.

## Device Summary Table

| Device | [ix,iy] | Status | Trend | Suspicion | Leakage@1V | Batches |
|--------|---------|--------|-------|-----------|------------|---------|
| CAP_00_00 | [0,0] | healthy | stable | none (0.00) | 1.80e-12 | 5 |
| CAP_00_01 | [1,0] | healthy | stable | none (0.00) | 1.23e-11 | 3 |
| CAP_00_02 | [2,0] | healthy | stable | none (0.00) | 1.58e-12 | 5 |
| CAP_01_00 | [0,1] | contact_issue | insufficient_data | low (0.30) | -1.73e-13 | 0 |
| CAP_01_01 | [1,1] | healthy | insufficient_data | low (0.30) | 1.01e-12 | 0 |
| CAP_01_02 | [2,1] | healthy | stable | none (0.00) | 2.04e-12 | 5 |
| CAP_02_00 | [0,2] | shorted | insufficient_data | medium (0.45) | 1.22e-03 | 0 |
| CAP_02_01 | [1,2] | failed | near_breakdown | critical (1.00) | 3.43e-11 | 3 |
| CAP_02_02 | [2,2] | failed | near_breakdown | critical (1.00) | 1.17e-11 | 3 |

---
_Generated by IV-Agent v0.1.0 on 2026-04-16 23:48:00_