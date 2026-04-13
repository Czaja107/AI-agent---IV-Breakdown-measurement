# IV-Agent Run Summary

| Field | Value |
|-------|-------|
| Chip ID | `DEMO_CHIP_001` |
| Run ID | `RUN_DEMO_001` |
| Start | 2026-04-13 00:21:10 |
| End | 2026-04-13 00:21:10 |
| Duration | 1 s (0.0 min) |
| Grid | 5 × 4 = 20 devices |
| Operator | demo |
| Mode | Simulation |

## Device Outcomes

| Status | Count |
|--------|-------|
| ✅ Healthy | 14 |
| ⚠️ Degrading | 0 |
| ❌ Failed | 5 |
| ⛔ Shorted | 1 |
| 🔌 Contact issue | 0 |
| ⏭ Skipped | 0 |
| **Total done** | **20** |

Max consecutive failures: **6**

## Active Hypotheses

| Hypothesis | Support | Evidence |
|-----------|---------|---------|
| True Device Degradation | 1.00 | [rapid_degradation] trend=rapidly_worsening |
| Corner Effect | 0.90 | [spatial_cluster] 4-device cluster in bottom-center region |
| Local Spatial Defect | 0.75 | [control_device_check] Control device CAP_02_02 checked at r |

## Alerts (0 total)

_No alerts raised._

## Experiment Notes (last 20)

**[00:21:10] `CAP_03_01`** — Protocol switched to DENSE_MONITORING at batch 1. Reason: Compliance hit at 10.5 V during stress batch 1. Switching to dense monitoring.

**[00:21:10] `CAP_03_01`** — **Device failed during dense monitoring** (batch 2). V_bd = 7.75 V.

**[00:21:10] `CAP_03_01`** — Device marked FAILED after 2 stress batches. Reason: Compliance hit during dense monitoring (batch 2). Device has failed.

**[00:21:10] `CAP_03_02`** — **Healthy device.** I(1V) = 1.54e-11 A. Normal stress protocol initiated.

**[00:21:10] `CAP_03_02`** — **Compliance hit during stress (batch 1).** V_bd = 8.5 V. Dense monitoring activated.

**[00:21:10] `CAP_03_02`** — Protocol switched to DENSE_MONITORING at batch 1. Reason: Compliance hit at 8.5 V during stress batch 1. Switching to dense monitoring.

**[00:21:10] `CAP_03_02`** — **Device failed during dense monitoring** (batch 2). V_bd = 8.0 V.

**[00:21:10] `CAP_03_02`** — Device marked FAILED after 2 stress batches. Reason: Compliance hit during dense monitoring (batch 2). Device has failed.

**[00:21:10]** — **Spatial cluster detected**: 4-device cluster in bottom-center region. Members: CAP_02_03, CAP_03_02, CAP_03_01, CAP_03_00. Region: bottom-center.

**[00:21:10] `CAP_03_03`** — **High suspicion despite OK metrics.** Reasons: consecutive_device_failures: 3 consecutive device failures (threshold for suspicion: 2); sudden_failure_after_healthy_streak: 3 consecutive failures following a run of 14 healthy devices — sudden contact or probe degradation suspected. Confirmatory check scheduled.

**[00:21:10] `CAP_03_03`** — **Confirmatory check passed** on CAP_03_03. Stress testing initiated.

**[00:21:10] `CAP_03_03`** — **Control device check** (CAP_02_02) triggered by activity on CAP_03_03. Result: HEALTHY ✓. Setup appears stable. Observed issues are likely real device/process behaviour. CONTACT_DEGRADATION or LOCAL_SPATIAL_DEFECT hypothesis strengthened.

**[00:21:10] `CAP_03_03`** — **Compliance hit during stress (batch 1).** V_bd = 9.5 V. Dense monitoring activated.

**[00:21:10] `CAP_03_03`** — Protocol switched to DENSE_MONITORING at batch 1. Reason: Compliance hit at 9.5 V during stress batch 1. Switching to dense monitoring.

**[00:21:10] `CAP_03_03`** — **Device failed during dense monitoring** (batch 2). V_bd = 8.0 V.

**[00:21:10] `CAP_03_03`** — Device marked FAILED after 2 stress batches. Reason: Compliance hit during dense monitoring (batch 2). Device has failed.

**[00:21:10]** — **Spatial cluster detected**: 5-device cluster in bottom-center region. Members: CAP_02_03, CAP_03_03, CAP_03_02, CAP_03_01, CAP_03_00. Region: bottom-center.

**[00:21:10] `CAP_03_04`** — **Shorted device detected.** I(1V) = 1.25e-03 A, R_est = 7.98e+02 Ω. Pre-existing short hypothesis supported.

**[00:21:10] `CAP_03_04`** — **Shorted device detected.** I(1V) = 1.25e-03 A, R_est = 7.98e+02 Ω. Pre-existing short hypothesis supported.

**[00:21:10]** — **Spatial cluster detected**: 5-device cluster in bottom-center region. Members: CAP_02_03, CAP_03_03, CAP_03_02, CAP_03_01, CAP_03_00. Region: bottom-center.

## Device Summary Table

| Device | [ix,iy] | Status | Trend | Suspicion | Leakage@1V | Batches |
|--------|---------|--------|-------|-----------|------------|---------|
| CAP_00_00 | [0,0] | healthy | stable | none (0.00) | 2.31e-12 | 8 |
| CAP_00_01 | [1,0] | healthy | stable | none (0.00) | 2.35e-12 | 8 |
| CAP_00_02 | [2,0] | healthy | stable | none (0.00) | 1.24e-12 | 8 |
| CAP_00_03 | [3,0] | healthy | stable | low (0.25) | 2.03e-11 | 3 |
| CAP_00_04 | [4,0] | healthy | stable | none (0.00) | 1.98e-12 | 8 |
| CAP_01_00 | [0,1] | healthy | ambiguous | low (0.30) | 1.64e-14 | 8 |
| CAP_01_01 | [1,1] | healthy | ambiguous | none (0.00) | 9.94e-14 | 5 |
| CAP_01_02 | [2,1] | healthy | stable | none (0.00) | 2.28e-12 | 8 |
| CAP_01_03 | [3,1] | healthy | stable | none (0.00) | 2.08e-12 | 8 |
| CAP_01_04 | [4,1] | healthy | stable | none (0.00) | 2.39e-12 | 8 |
| CAP_02_00 | [0,2] | healthy | stable | none (0.00) | 1.83e-12 | 8 |
| CAP_02_01 | [1,2] | healthy | stable | none (0.00) | 3.05e-12 | 8 |
| CAP_02_02 | [2,2] | healthy | insufficient_data | none (0.00) | 1.04e-12 | 0 |
| CAP_02_03 | [3,2] | failed | near_breakdown | medium (0.50) | 1.45e-11 | 2 |
| CAP_02_04 | [4,2] | healthy | stable | none (0.00) | 2.42e-12 | 8 |
| CAP_03_00 | [0,3] | failed | near_breakdown | critical (0.95) | 6.32e-11 | 3 |
| CAP_03_01 | [1,3] | failed | near_breakdown | high (0.75) | 2.01e-11 | 2 |
| CAP_03_02 | [2,3] | failed | near_breakdown | critical (1.00) | 2.35e-11 | 2 |
| CAP_03_03 | [3,3] | failed | near_breakdown | critical (1.00) | 1.75e-11 | 2 |
| CAP_03_04 | [4,3] | shorted | insufficient_data | critical (1.00) | 1.25e-03 | 0 |

---
_Generated by IV-Agent v0.1.0 on 2026-04-13 00:21:11_