# FanEdge product quality scorecard — M14

September 19–20, 2026. Baseline `edd4923`; one real league plus deterministic engine/API/browser fixtures. Categories are engineering judgments, not invented percentages. See [full research, diagnostics, grading counts and reasoning](M14_CALIBRATION.md).

| Area | Status | Evidence and limitation |
|---|---|---|
| DATA INTEGRITY | PASS WITH LIMITATIONS | Ownership/availability, schedule, eligibility and provenance invariants; isolated provider failure and central fetch-age telemetry. Completeness cannot prove provider facts are correct; health resets per process. |
| LINEUP QUALITY | PASS WITH LIMITATIONS | Both real suggestions defensible and unchanged; global assignment, injury/bye/eligibility and one-game-spike regressions pass. Limited week-two samples; not projected points or a player-lock service. |
| WAIVER QUALITY | PASS WITH LIMITATIONS | Role plus roster fit required consistently across Market/Ask; no unconfirmed add or recommended-starter release. Three redundant-QB watches remain QUESTIONABLE; watchlist relevance needs more work. |
| TRADE QUALITY | NEEDS WORK | Four default searches correctly quiet; rejection histograms reconcile. Targeted Diggs/Love → Skattebo remains QUESTIONABLE/LOW confidence. Tiers improve rejection transparency and uncertainty handling, not verified market calibration. |
| NEWS RELEVANCE | PASS WITH LIMITATIONS | Real attributable teammate-availability monitors distinguish facts/inference; refreshed ownership removed the now-rostered Bateman and surfaced a cautious Moore watch. Sparse coverage is unknown, not no news. |
| AI GROUNDING | PASS WITH LIMITATIONS | Deterministic weekly/positional planner, safe costs, explicit alternatives and unsupported weather refusal. Optional model prose was disabled for the real audit; not evaluated as free-form reasoning quality. |
| CROSS-FEATURE CONSISTENCY | PASS WITH LIMITATIONS | Error records quarantined from actions/active memory; start/drop suppressed and start/trade explained. Separate engine confidence labels have different scopes; one-game role confidence can differ from a two-signal comparison confidence. |
| PERFORMANCE | PASS WITH LIMITATIONS | Cached football pages remain low-single-digit milliseconds; navigation remains local. Cold public-provider latency varies; concurrent build/browser activity produces significant outliers. Measurements below must not be interpreted as controlled statistical trials. |
| UI RELIABILITY | PASS WITH LIMITATIONS | Responsive browser walkthroughs and fixture checks, failed images, long names, empty/error states, drawer Escape/focus, Market keyboard tabs and in-flight trade invalidation. Accessibility is a scoped keyboard/layout audit, not full WCAG certification. |

## Before beta

Commercial Sleeper rights and appropriate rights/terms for existing news/assets require review. FantasyCalc and FantasyPros commercial/competing-product permission is **BLOCKED pending agreement**; neither is integrated. FFC is usable only as guarded optional draft sentiment, not an in-season market. Need independent leagues/formats, later-season samples and actual outcome review before claiming recommendation accuracy. Authentication, rate limits and multi-user operational controls remain outside this milestone; do not mistake a developer health endpoint for production authorization.

## Validation record

**224 Python tests passed** (197 baseline + 27 M14), including Rams schedule/identity regressions, engine, API, planner, provider isolation and coherence. Two existing test-client deprecation warnings remain. **12 Playwright tests passed**, including three opt-in live journeys at 1440/768/390px. Production Next build, TypeScript, Python compilation, startup and health checks passed. Production npm audit: zero reported vulnerabilities. Targeted secret-pattern scan and `git diff --check` passed. A separate responsive re-run also passed; it exposed timing outliers reported below.

No screenshots, provider dumps, local journals or secrets are committed. `scripts/audit_quality.py` reproduces the normalized real-league review without changing the persistent journal. Browser fixtures test positive trade flows even when live searches are quiet.

## Performance observations

These measurements share a development machine, public providers and evolving real-league state. They are not controlled distribution estimates. Cached API measurements use 20 requests per route; Ask uses five deterministic requests. Browser navigation measures click to visible heading/next animation frame, drawer timings include automation overhead.

| Path | M13 baseline | M14 observed |
|---|---:|---:|
| First real snapshot, instrumented total | 4,836 ms | Final 3,569 ms; other runs 5,020–6,550 ms, dominated by public dataset latency |
| Home/overview cached API median | 2.684 ms | 2.778–3.438 ms |
| Team/roster cached API median | 3.049 ms | 1.829–2.046 ms |
| Lineup cached API median | 1.543 ms | 1.603–1.940 ms |
| Market/waivers cached API median | 1.511 ms | 1.901–2.655 ms |
| Snapshot cached API median | 2.256 ms | 2.165–2.259 ms |
| Cached trade search API median | 8.896 ms | 10.732–10.942 ms; responses include normalized league players |
| First trade search | 251 ms HTTP / 237 ms engine | Loaded run 755/684 ms; subsequently warmed engine 35.54 ms. Profile cache state differs; not an apples-to-apples speedup claim |
| Ask RB API | Not recorded | First 48.5 ms; warm median 52.2 ms |
| Browser Ask response journey | Not recorded | Weekly 560 ms; RB 284 ms; named player 124 ms; unsupported 159 ms; recent changes 194 ms |

M12's reference local-navigation band was 46–95 ms; M13's reported later run was 13–80 ms. M14 full-suite Home 45–63 ms, Market/Waivers 45–75 ms, Ask navigation 45–50 ms; Team 105–272 ms. A separate run gave warmed Team 58 ms tablet / 96 ms mobile but a **732 ms first-desktop Team outlier**. Drawer 69–80 ms in the full suite, 46–156 ms in the repeat. Home/Team/waiver navigation and drawers issued zero football API requests; Ask emitted entry analytics only. Trade browser requests are lazy and separate from normal page navigation.

Conclusion: server cache boundaries and normal local navigation remain intact; cold-route/browser tail latency is **not proven resolved** and needs controlled device profiling before beta. Do not claim every navigation meets 95 ms. No trade filter was weakened to improve a benchmark or fill an empty page.
