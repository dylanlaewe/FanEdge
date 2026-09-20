# M15: pre-beta validation and release candidate

September 20, 2026. Starting commit: `1768d5f2aba2b85962aa35c3284afee1cab97336`. No new major fantasy feature. **NO-GO for 5–10 independent user invitations until the release checklist's external gates are resolved.** This document describes implementation and local evidence, not a deployed or legally cleared beta.

## 1–6. Providers, audit tools and release gates

1. **Provider audit:** `BETA_PROVIDERS.md` inventories every runtime data/asset source, authentication, request/cache behavior, storage, attribution, failure and rights disposition. ESPN accessibility is not treated as permission. Sleeper intended-use classification and nflverse upstream source scope remain review items.
2. **Configuration:** optional news, headshots, logos, AI prose and ADP default off. `/api/capabilities` and UI expose mode; imagery falls back locally. Essential football data remains enabled for local validation, not silently certified for distribution.
3. **Multi-league harness:** `scripts/audit_league.py --username USER --league ID --output PATH` supports explicit league selection and configurable position. It produces scoring/slots, lineup evidence, waivers/watchlist, partners/packages/rejections, proactive events, three grounded Ask goals and data-quality/freshness details. It uses a temporary isolated DB and never writes audits to the product DB.
4. **Human labels:** separate `.labels.json`, reviewer, GOOD/DEFENSIBLE/QUESTIONABLE/BAD plus reason. No feedback into algorithms. IDs bind labels to actual audit items; mismatched, unknown or duplicate labels fail validation. Existing outputs are not overwritten.
5. **Aggregation:** `calibration_report.py` groups labels by feature, league format, position, recommendation type and evidence confidence. Missing labels remain UNREVIEWED. Trade rejection totals are per search/goal, not unique packages across searches. `beta_report.py --audit ...` includes these separate labels without importing them into production storage.
6. **Gates:** `BETA_RELEASE_CHECKLIST.md` and `beta-gates.json` explicitly distinguish PASS/FAIL. The machine gate cannot turn missing/BAD labels or single-owner coverage into GO. Provider rights, independent calibration/human review, trusted identity, unassisted usability, target deployment and rollback remain FAIL.

## 7–9. Performance evidence and changes

Measurements are local production Next/FastAPI, real providers and one league; no network/CPU throttling. They are not statistically robust p95s or promises about a remote host. Cold document means fresh React/query state; backend cache state is described separately.

| Measurement | Evidence |
|---|---|
| Before parallel fetch, isolated backend snapshot | 5,312.8ms total; Sleeper 435.7; football datasets/indexes 3,640.2; identity 1,201.1 |
| First parallel-fetch run | 5,376.8ms total; football datasets/indexes 1,542.1; identity 3,423.9. Provider variance offset the faster dataset stage |
| Final isolated audit | 2,620.3ms total; Sleeper 290.5; datasets/indexes 1,537.2; identity 758.7; context/roles 27.5; lineup 1.8; waivers 1.6; opportunity 0.2; disabled news 0.03; SQLite 2.4 |
| Presentation / serialization | 2.25ms normalized model preparation; 0.28ms JSON serialization; isolated snapshot 38,320 raw bytes |
| Cold document, warmed backend, desktop | Home 92.3ms; Team 101.8; Market/Waivers 60.1; Ask 83.8 |
| Cold document, warmed backend, mobile | Home 109.0ms; Team 81.4; Market/Waivers 52.8; Ask 59.4 |
| First drawer / lazy trade surface | Desktop 61ms / 274ms; mobile 61ms / 89ms. These click-to-visible measurements include automation synchronization |
| Warm navigation, desktop/tablet/mobile | Actual route changes 44.6–96.6ms in the clean run; a separate run reached 105.4ms on tablet Team. Clicking already-active Home (~13ms) is excluded from speed claims |
| Warm drawer | 49–140ms across widths. It reuses normalized player data; additional recorded requests are telemetry, not a football refetch |
| Cached raw API routes | Median ~1.5–3.4ms across samples; full snapshot ~2–3ms. Optional instrumentation adds small SQLite overhead |
| Ask / trade API | First RB plan 58–66ms; identical repeat ~2–3ms. First BEST_UPGRADE search 34.7ms including engine; repeated ~2.4–2.7ms |
| Browser Ask with actual interaction | Clean weekly plan 440ms; RB plan 120ms; includes typing/click/assertion overhead, not just backend time |

Local acceptance bounds: route changes under 250ms; cold documents with a warmed backend under 1.5s; first healthy-provider intelligence under 10s; lazy trade surface under 2s; deterministic Ask interaction under 2s. These protect interaction usability, not a vanity composite. Local runs pass. A failing provider has per-request timeouts; the entire multi-provider build does **not** yet have a strict end-to-end deadline. Actual deployment/slow-network validation is still required.

**Profiling distinction:** resource timing captures document TTFB, script downloads and `/api` requests; readiness marks capture when the data-backed React surface mounts. One measured build loads ~157KB encoded script bodies across shared chunks. TTFB was ~2–15ms; browser/proxy snapshot reads ~20–60ms versus low-single-digit backend cached work. The remaining gap includes JavaScript bootstrap, query orchestration, proxy transfer/decompression and React work; it is **not presented as a pure render CPU measurement**. No new lazy split was justified for the shared dashboard bundle by these local results. Trade data is already fetched only when needed. Main cold backend cost was external data, not football calculation or serialization.

**Fixes:** three shared dataset workers, single-flight caches preserved, identical Ask reuse including repeated follow-ups, and removal of all-league player payloads from search/analyze responses. UI merges returned players with its existing trade overview for impact names. Rankings, optimizer, schedule/bye rules, identity matching and trade valuation remain unchanged. Normal Sleeper metadata refresh now respects a 24-hour cache; operator cache clear/restart can still refetch.

**Payload audit (raw API JSON):** overview ~5.7KB on a clean history / 11.2KB with retained historical signals; Team 17.0KB; lineup 5.3KB; Waivers 9.4KB; events 5.4–10.8KB; history 2.6KB; player detail 1.1KB. Trade overview remains the largest at 284KB because its selectors/profiles use all roster identities and values, but it is not sent to Home/Team/Ask. Empty trade-search response is now 2,557 bytes instead of repeating that league player mapping. Main snapshots were ~38–46KB depending on history; Next/browser compression reduced one observed transfer to ~3.9KB. Do not compare raw and compressed sizes as if they were the same quantity.

## 10–15. Operations, abuse, AI and observability

10. Internal token-protected status/cache/prune commands and a refresh CLI live outside Next's public API proxy. Wrong/missing ops credentials fail; cache clear preserves journals. Use a loopback tunnel and single worker. See operations guide for idle-cache and rollback cautions.
11. Per-peer and global sliding limits cover Ask, refresh, trades, connect, snapshots and telemetry. HTTP 429 includes Retry-After. Searches remain bounded; browser requests time out and POSTs do not automatically retry. The original shared operation bucket was split after a browser regression; telemetry allowance was raised after an automated burst exposed dropped impressions. No Ask/cost limit was relaxed for this fix.
12. Optional OpenAI defaults off; max 24k input characters, 320 output tokens, 8s timeout, zero SDK retries, `store=False`, 30 calls/hour and 100/day/process. Process-local budgets reset on restart, so project-side spending controls are still required. Legacy three strategy functions have matching timeout/input/storage controls and 350-token outputs but are not beta endpoints. No live model spend was used for validation.
13. Deterministic answers remain available on disabled/error/timeout/rejected output. Weekly and position plans and trades do not require an LLM. AI mode is visible directly in Ask, not only in a footer. Enabled prose still needs a separate grounding evaluation; heuristic checks cannot certify every fact.
14. Structured request/provider logs contain timestamp, build, normalized route/stage/category/provider and correlation ID. Request metrics/errors also enter separate beta instrumentation. No body, raw question, key or query string is logged by this layer. Standard Uvicorn access logs must remain disabled. Background cache/provider work carries correlation context.
15. Version 15.0 with a commit-derived build or explicit CI `FANEDGE_BUILD_ID`, exposed in health, response headers, capabilities and a subtle footer. Precommit local tests show the starting SHA with `m15-` prefix; deploy with the actual committed SHA.

## 16–24. Product readiness

16. First run explains public/read-only access and storage, league choice stays available, errors have retry paths, waiver empty state points to Watchlist, and Ask states the actual AI mode. No full redesign.
17. Trade discovery is visibly **Experimental** and explicitly not a fair-value guarantee. Empty results remain valid.
18. Helpful/Not helpful on events, lineup, waiver/watchlist, trade ideas and Ask answers; Save/Done/Dismiss retained. Product categories and optional bounded text are available in Send feedback. Context includes build, league, screen, event ID when supplied, snapshot and provider freshness. SQLite records are operator-only, not sent to third-party analytics.
19. Funnel captures landing/connect/readiness/pages, component impressions, evidence, trades, intents, votes, feedback and return-tab sessions. UUIDs are not authentication; mounts are not proof of reading. No raw questions in normal analytics.
20. Beta report outputs actual retained users/sessions/activation/adoption, feedback/actions, intents/unsupported demand, errors/latencies and optional quality aggregates. Local test activity is **not independent adoption**. Empty/unavailable evidence is not fabricated. Daily 30-day telemetry pruning must be installed on the target host; existing decision memory is separately durable.
21. Demo deferred: adding another data/analytics mode would complicate release validation without resolving an invitation blocker.
22. `PRODUCT_CASE_STUDY.md` documents the real M1–M15 evolution, false-bye lesson, evidence thesis and measured Streamlit ~4.4–4.5s to Next warm ~46–95ms migration, with no adoption claims.
23. `BETA_TEST_SCRIPT.md` provides ten minutes of natural use, minimal coaching, interview questions and private observer notes.
24. Release checklist covers providers, security, grounding, quality, performance, devices, feedback, errors, deployment and rollback. Gates requiring an external owner/tester/host remain explicitly failed.

## 25–26. Tests and quality

Python: **244 passed**, including all prior 224 tests plus beta coverage: limits, duplicate/follow-up reuse, provider flags, visual fallback, AI timeout/output/storage fallback, feedback bounds/context, telemetry/reporting/retention, ops protection/cache clear, build version, label validation, aggregation and fail-closed gates. Two existing Starlette test-client deprecation warnings remain. Compile and diff checks pass. Browser: **13 passed**, including nine fixture regressions and four opt-in real-provider journeys; desktop/tablet/mobile, connect, Home/Team/Market/Watchlist/Trades/Ask, drawer, feedback, errors, refresh and journal are exercised. The final isolated validation DB report contained seven trade-search events, two Helpful votes and two product-feedback submissions, with **no recorded request errors** at that checkpoint; these are automation/operator test records, not adoption. Dependency scan: `npm audit --omit=dev` reported zero vulnerabilities; this is not a Python/full supply-chain audit. Source secret scan found no recognized credentials/runtime databases; it is heuristic and does not scan Git history.

Private, intentionally uncommitted audit: `.fanedge/audits/m15-rc.json` and `.labels.json`. The application directory has owner-only access on this validation machine. One 12-team half-PPR league, QB/RB/RB/WR/WR/TE/three FLEX/K plus six bench slots. The audit contains 26 review items: two lineup comparisons, eight watches, two proactive events, three Ask responses and eleven ranked partner records. No immediate adds. All four default trade searches reject their 3,120 considered packages; totals across goals are not unique-package counts. BEST_UPGRADE primary reasons: 2,522 value gap, 318 starter downgrade, 110 redundant position, 92 star-for-depth, 73 invalid roster, five no partner incentive. Zero detected integrity issues.

Operator evidence review: Douglas/Gainwell and Diggs/Love comparisons remain defensible, with limited-sample warnings; weekly plan selects Diggs; RB plan monitors Miller rather than forcing an add. Cousins/Rush/Lock remain questionable watches for this two-QB roster. Relative WR-weakness advice is bounded but not differentiated. Partner suggestions are exploration, not endorsed packages. No known BAD was found in this operator review, **but all 26 human release labels remain UNREVIEWED**. Do not convert that statement into an independent quality pass.

News-off reduces the clean feed from the earlier news-enabled audit; this is an intentional capability difference, not a ranking change. A regression found during hardening is fixed: disabling news does not silently declare historical news-supported signals resolved. Their lifecycle confirmation pauses with an explicit warning while fresh deterministic football advice remains usable. Existing historical records are not erased.

## 27–30. Decision and handoff

27. Remaining blockers: provider intended-use/upstream rights disposition; independent leagues and final human labels; verified owner/session separation; unassisted testers; production TLS/invite gateway, log/backup/retention setup, host/network profiling and rollback rehearsal. Existing limitations: sparse current-season evidence, questionable low-fit QB watches, weak trade-package calibration, no formal proof for enabled LLM prose, process-local quotas and a relatively large lazy trade overview. No new major football feature is recommended as a substitute.
28. **NO-GO for 5–10 independent users now.** Local release candidate implementation is suitable for further operator validation; the failed gates require concrete evidence/authority, not more optimistic wording.
29. The commit titled `feat: prepare FanEdge beta release candidate` contains this report; the final response identifies its actual hash (a commit cannot embed its own final hash reliably).
30. Push to the existing GitHub repository is verified after commit; see the completion response for the remote result. No M16 or other feature milestone is begun.
