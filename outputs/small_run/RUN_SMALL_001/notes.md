
**[2026-04-13 00:20:02] `CAP_00_00`** _device_ — **Healthy device.** I(1V) = 1.31e-12 A. Normal stress protocol initiated.

**[2026-04-13 00:20:02] `CAP_00_00`** _trend_ — **Stress testing complete** (5 batches). Device status: healthy.

**[2026-04-13 00:20:02] `CAP_00_01`** _device_ — **Healthy device.** I(1V) = 4.49e-12 A. Normal stress protocol initiated.

**[2026-04-13 00:20:02] `CAP_00_01`** _trend_ — **Compliance hit during stress (batch 1).** V_bd = 12.0 V. Dense monitoring activated.

**[2026-04-13 00:20:02] `CAP_00_01`** _trend_ — Protocol switched to DENSE_MONITORING at batch 1. Reason: Compliance hit at 12.0 V during stress batch 1. Switching to dense monitoring.

**[2026-04-13 00:20:02] `CAP_00_01`** _trend_ — **Dense monitoring: device stabilised** after 3 batches.

**[2026-04-13 00:20:02] `CAP_00_02`** _device_ — **Healthy device.** I(1V) = 1.23e-12 A. Normal stress protocol initiated.

**[2026-04-13 00:20:02] `CAP_00_02`** _trend_ — **Stress testing complete** (5 batches). Device status: healthy.

**[2026-04-13 00:20:02] `CAP_01_00`** _device_ — **Contact issue on first health check.** I(Vmax) = -1.06e-13 A. Scheduling retry.

**[2026-04-13 00:20:02] `CAP_01_00`** _device_ — **Persistent contact issue after 1 attempts.** Marking as CONTACT_ISSUE. Consider probe inspection.

**[2026-04-13 00:20:02] `CAP_01_00`** _device_ — **Persistent contact issue after 1 attempts.** Marking as CONTACT_ISSUE. Consider probe inspection.

**[2026-04-13 00:20:02] `CAP_01_01`** _device_ — **Healthy device.** I(1V) = 8.88e-13 A. Normal stress protocol initiated.

**[2026-04-13 00:20:02] `CAP_01_01`** _device_ — **Scheduled control device measurement.** Status: healthy. I(1V) = 8.88e-13 A.

**[2026-04-13 00:20:02] `CAP_01_02`** _device_ — **Healthy device.** I(1V) = 1.60e-12 A. Normal stress protocol initiated.

**[2026-04-13 00:20:02] `CAP_01_02`** _trend_ — **Stress testing complete** (5 batches). Device status: healthy.

**[2026-04-13 00:20:02] `CAP_02_00`** _device_ — **Shorted device detected.** I(1V) = 1.22e-03 A, R_est = 8.17e+02 Ω. Pre-existing short hypothesis supported.

**[2026-04-13 00:20:02] `CAP_02_00`** _device_ — **Shorted device detected.** I(1V) = 1.22e-03 A, R_est = 8.17e+02 Ω. Pre-existing short hypothesis supported.

**[2026-04-13 00:20:02] `CAP_02_01`** _device_ — **Healthy device.** I(1V) = 1.12e-11 A. Normal stress protocol initiated.

**[2026-04-13 00:20:02] `CAP_02_01`** _trend_ — **Compliance hit during stress (batch 1).** V_bd = 8.5 V. Dense monitoring activated.

**[2026-04-13 00:20:02] `CAP_02_01`** _trend_ — Protocol switched to DENSE_MONITORING at batch 1. Reason: Compliance hit at 8.5 V during stress batch 1. Switching to dense monitoring.

**[2026-04-13 00:20:02] `CAP_02_01`** _trend_ — **Device failed during dense monitoring** (batch 3). V_bd = 7.25 V.

**[2026-04-13 00:20:02] `CAP_02_01`** _device_ — Device marked FAILED after 3 stress batches. Reason: Compliance hit during dense monitoring (batch 3). Device has failed.

**[2026-04-13 00:20:02]** _spatial_ — **Spatial cluster detected**: 2-device cluster in bottom-left region. Members: CAP_01_00, CAP_02_01. Region: bottom-left.

**[2026-04-13 00:20:02] `CAP_02_02`** _device_ — **High suspicion despite OK metrics.** Reasons: consecutive_device_failures: 3 consecutive device failures (threshold for suspicion: 2); sudden_failure_after_healthy_streak: 3 consecutive failures following a run of 5 healthy devices — sudden contact or probe degradation suspected. Confirmatory check scheduled.

**[2026-04-13 00:20:02] `CAP_02_02`** _device_ — **Confirmatory check passed** on CAP_02_02. Stress testing initiated.

**[2026-04-13 00:20:02] `CAP_02_02`** _hypothesis_ — **Control device check** (CAP_01_01) triggered by activity on CAP_02_02. Result: HEALTHY ✓. Setup appears stable. Observed issues are likely real device/process behaviour. CONTACT_DEGRADATION or LOCAL_SPATIAL_DEFECT hypothesis strengthened.

**[2026-04-13 00:20:02] `CAP_02_02`** _trend_ — **Compliance hit during stress (batch 1).** V_bd = 9.5 V. Dense monitoring activated.

**[2026-04-13 00:20:02] `CAP_02_02`** _trend_ — Protocol switched to DENSE_MONITORING at batch 1. Reason: Compliance hit at 9.5 V during stress batch 1. Switching to dense monitoring.

**[2026-04-13 00:20:02] `CAP_02_02`** _trend_ — **Device failed during dense monitoring** (batch 3). V_bd = 7.25 V.

**[2026-04-13 00:20:02] `CAP_02_02`** _device_ — Device marked FAILED after 3 stress batches. Reason: Compliance hit during dense monitoring (batch 3). Device has failed.

**[2026-04-13 00:20:02]** _spatial_ — **Spatial cluster detected**: 3-device cluster in bottom-center region. Members: CAP_01_00, CAP_02_01, CAP_02_02. Region: bottom-center.

**[2026-04-13 00:20:32] `CAP_00_00`** _device_ — **Healthy device.** I(1V) = 1.31e-12 A. Normal stress protocol initiated.

**[2026-04-13 00:20:32] `CAP_00_00`** _trend_ — **Stress testing complete** (5 batches). Device status: healthy.

**[2026-04-13 00:20:32] `CAP_00_01`** _device_ — **Healthy device.** I(1V) = 4.49e-12 A. Normal stress protocol initiated.

**[2026-04-13 00:20:32] `CAP_00_01`** _trend_ — **Compliance hit during stress (batch 1).** V_bd = 12.0 V. Dense monitoring activated.

**[2026-04-13 00:20:32] `CAP_00_01`** _trend_ — Protocol switched to DENSE_MONITORING at batch 1. Reason: Compliance hit at 12.0 V during stress batch 1. Switching to dense monitoring.

**[2026-04-13 00:20:32] `CAP_00_01`** _trend_ — **Dense monitoring: device stabilised** after 3 batches.

**[2026-04-13 00:20:32] `CAP_00_02`** _device_ — **Healthy device.** I(1V) = 1.23e-12 A. Normal stress protocol initiated.

**[2026-04-13 00:20:32] `CAP_00_02`** _trend_ — **Stress testing complete** (5 batches). Device status: healthy.

**[2026-04-13 00:20:32] `CAP_01_00`** _device_ — **Contact issue on first health check.** I(Vmax) = -1.06e-13 A. Scheduling retry.

**[2026-04-13 00:20:32] `CAP_01_00`** _device_ — **Persistent contact issue after 1 attempts.** Marking as CONTACT_ISSUE. Consider probe inspection.

**[2026-04-13 00:20:32] `CAP_01_00`** _device_ — **Persistent contact issue after 1 attempts.** Marking as CONTACT_ISSUE. Consider probe inspection.

**[2026-04-13 00:20:32] `CAP_01_01`** _device_ — **Healthy device.** I(1V) = 8.88e-13 A. Normal stress protocol initiated.

**[2026-04-13 00:20:32] `CAP_01_01`** _device_ — **Scheduled control device measurement.** Status: healthy. I(1V) = 8.88e-13 A.

**[2026-04-13 00:20:32] `CAP_01_02`** _device_ — **Healthy device.** I(1V) = 1.60e-12 A. Normal stress protocol initiated.

**[2026-04-13 00:20:32] `CAP_01_02`** _trend_ — **Stress testing complete** (5 batches). Device status: healthy.

**[2026-04-13 00:20:32] `CAP_02_00`** _device_ — **Shorted device detected.** I(1V) = 1.22e-03 A, R_est = 8.17e+02 Ω. Pre-existing short hypothesis supported.

**[2026-04-13 00:20:32] `CAP_02_00`** _device_ — **Shorted device detected.** I(1V) = 1.22e-03 A, R_est = 8.17e+02 Ω. Pre-existing short hypothesis supported.

**[2026-04-13 00:20:32] `CAP_02_01`** _device_ — **Healthy device.** I(1V) = 1.12e-11 A. Normal stress protocol initiated.

**[2026-04-13 00:20:32] `CAP_02_01`** _trend_ — **Compliance hit during stress (batch 1).** V_bd = 8.5 V. Dense monitoring activated.

**[2026-04-13 00:20:32] `CAP_02_01`** _trend_ — Protocol switched to DENSE_MONITORING at batch 1. Reason: Compliance hit at 8.5 V during stress batch 1. Switching to dense monitoring.

**[2026-04-13 00:20:32] `CAP_02_01`** _trend_ — **Device failed during dense monitoring** (batch 3). V_bd = 7.25 V.

**[2026-04-13 00:20:32] `CAP_02_01`** _device_ — Device marked FAILED after 3 stress batches. Reason: Compliance hit during dense monitoring (batch 3). Device has failed.

**[2026-04-13 00:20:32]** _spatial_ — **Spatial cluster detected**: 2-device cluster in bottom-left region. Members: CAP_01_00, CAP_02_01. Region: bottom-left.

**[2026-04-13 00:20:32] `CAP_02_02`** _device_ — **High suspicion despite OK metrics.** Reasons: consecutive_device_failures: 3 consecutive device failures (threshold for suspicion: 2); sudden_failure_after_healthy_streak: 3 consecutive failures following a run of 5 healthy devices — sudden contact or probe degradation suspected. Confirmatory check scheduled.

**[2026-04-13 00:20:32] `CAP_02_02`** _device_ — **Confirmatory check passed** on CAP_02_02. Stress testing initiated.

**[2026-04-13 00:20:32] `CAP_02_02`** _hypothesis_ — **Control device check** (CAP_01_01) triggered by activity on CAP_02_02. Result: HEALTHY ✓. Setup appears stable. Observed issues are likely real device/process behaviour. CONTACT_DEGRADATION or LOCAL_SPATIAL_DEFECT hypothesis strengthened.

**[2026-04-13 00:20:32] `CAP_02_02`** _trend_ — **Compliance hit during stress (batch 1).** V_bd = 9.5 V. Dense monitoring activated.

**[2026-04-13 00:20:32] `CAP_02_02`** _trend_ — Protocol switched to DENSE_MONITORING at batch 1. Reason: Compliance hit at 9.5 V during stress batch 1. Switching to dense monitoring.

**[2026-04-13 00:20:32] `CAP_02_02`** _trend_ — **Device failed during dense monitoring** (batch 3). V_bd = 7.25 V.

**[2026-04-13 00:20:32] `CAP_02_02`** _device_ — Device marked FAILED after 3 stress batches. Reason: Compliance hit during dense monitoring (batch 3). Device has failed.

**[2026-04-13 00:20:32]** _spatial_ — **Spatial cluster detected**: 3-device cluster in bottom-center region. Members: CAP_01_00, CAP_02_01, CAP_02_02. Region: bottom-center.
