# Changelog

All meaningful code and methodology changes are recorded here, per Section 11 of `METHODOLOGY.md`.

## 2026-05-17 — METHODOLOGY.md v1.1
Folded six pre-code clarifications into the methodology document before any implementation work. No model behavior was introduced that was not implied by v1.0; all changes resolve ambiguities flagged during a methodology review:

1. Section 4 — Expansion teams start at exactly 1500 in their debut season with no decay step applied; the decay rule applies normally from season 2 onward. Applies uniformly to the 1967-68 expansion six, Vegas 2017-18, Seattle 2021-22, etc.
2. Section 4 — Franchise rating persists across relocations. The new-city team inherits the prior-city team's most recent rating with no reset. Documented examples cover Atlanta→Calgary, Colorado Rockies→New Jersey, Minnesota North Stars→Dallas, Quebec→Colorado, Hartford→Carolina, Atlanta Thrashers→Winnipeg, and the California/Cleveland→Minnesota merger.
3. Section 5 — Tie outcome weight is 0.50 for both teams (pre-2005-06 seasons only). Added as a row to the outcome weights table; fixed, not tunable.
4. Section 5 — Playoff K=10 is uniform across all playoff games regardless of round or series state. Series-context adjustment remains deferred to V3.
5. Section 5 — `/games/today` must compute live probabilities using the parameter set frozen at the end of validation. Rating state updates as new results land; parameters do not. Stated as a code-level invariant.
6. Sections 2 and 6 — Brier score upper bound tightened from 0.250 to 0.245, bringing Brier target stringency roughly in line with the log-loss target (<0.685).
