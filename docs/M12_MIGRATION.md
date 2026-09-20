# M12 — product migration and performance audit

Validated locally on September 19, 2026, against M11 commit `ee071e2`.
This milestone changes application architecture and presentation, not football models.

## 1. Measured Streamlit baseline

`scripts/profile_streamlit.py` drives actual Streamlit AppTest interactions with a populated Sleeper league. The uninstrumented run measures wall time; a separate call-profile run identifies work. These are separate measurements: Python tracing materially inflates timings and is not a user-latency benchmark.

| Interaction | Original M11, wall ms | Shared-service reference UI, wall ms |
| --- | ---: | ---: |
| Startup | 847 | 811 |
| Connect and construct first league | 11,489 | 5,741 |
| Overview → My Team | 4,434–4,467 | 32–36 |
| My Team → Waivers | 4,427–4,483 | 32–34 |
| Waivers → Ask | 4,436–4,445 | 29–30 |
| Ask → Overview | 4,454–4,466 | 38–39 |

Two complete navigation cycles were measured per implementation. These local single-machine samples are not production percentiles. AppTest excludes browser paint. The cold connection comparison includes the initial league selection; a distinct second-league cold latency was not benchmarked.

### Diagnostic inclusive call timings (instrumented baseline only)

| Work | Cold connection ms | Warm navigation ms |
| --- | ---: | ---: |
| Sleeper user/leagues | 187 | cached |
| Sleeper roster / metadata | 124 / 357 | cached |
| Football datasets and indexes, including nflverse loads | 28,392 | cached wrapper reused |
| Weekly schedule load/build | 481 / 97 | cached wrapper reused |
| Identity load/mapping | 6,167 / 1,807 | cached wrapper reused |
| News fetch | 204 | cached raw batch |
| News entity resolution | 8,823 | 8,362–8,527 |
| Lineup optimizer | 4.0 | 4.0–4.3 |
| Waiver engine | 67.9 | 63.2–64.1 |
| Opportunity engine | 4.3 | 4.0–4.6 |
| Memory reconcile | 5.1 | 5.3–5.8 |
| Overview / Team / Waivers / Ask render | — | 46.7 / 32.0 / 15.8 / 5.9 |

Inclusive timings overlap and must not be added. Provider load/index preparation is combined in the existing wrapper; it does not isolate each HTTP transfer. Copilot state was reconstructed on every rerun; its construction is now explicitly timed by the shared service.

## 2. Root causes

- All four navigation actions re-entered the connected-app orchestration, even though Streamlit had cached provider responses.
- Warm navigation made **zero provider HTTP requests** in the traced run. The dominant issue was not repeated network fetching.
- Each rerun resolved the same 22 news stories against the active player universe, invoking `_name_pattern` 16,115 times and name normalization roughly 32,530 times. Raw-news caching did not cache resolved facts. The regex working set also exceeded Python's small internal regex cache.
- Player contexts, opportunities, roles, roster needs, optimizer, waiver ranking, feed integration, memory reconciliation, and copilot preparation were repeated regardless of the selected page.
- Large mutable arguments passed through Streamlit cache wrappers add hashing/deserialization work. This audit did not separately quantify that overhead.
- The data layer uses CSV dictionaries, not pandas DataFrames. There was no evidence of repeated dataframe loading. Rendering alone was not the main bottleneck.

## 3. Cache and refresh policy

Navigation reads a reusable `LeagueIntelligenceSnapshot`; it never triggers domain construction while that snapshot is fresh. Providers are bounded cached inputs, separate from the normalized presentation object.

| Cache | TTL / bound | Invalidation |
| --- | --- | --- |
| Connection + leagues | 15 min; provider cache 64 entries total | Username/season; explicit refresh |
| Snapshot | 5 min; 32 snapshots | User ID, league, season, scoring settings, starting slots; explicit refresh |
| Rosters / NFL week | 5 min | League / explicit refresh |
| Player metadata / resolved identities | 1 hour | Explicit refresh; identities use current metadata |
| Schedule, current stats/snaps and derived indexes | 6 hours | NFL state/scoring key; explicit refresh |
| Previous-season stats/snaps, identity rows | 24 hours | Season/TTL |
| Injury rows | 1 hour | TTL / explicit refresh |
| Resolved news facts | 15 min | TTL / explicit refresh; freshness recalculated on snapshot construction |
| Prior copilot intent + answer | 1 hour; 256 entries | User, league, season, conversation UUID |

Snapshot cadence controls automatic refresh. Provider TTLs control which inputs are refreshed during that build; provider expiry does not independently force page construction. Connection changes are observed on its TTL or explicit refresh. Historical datasets and identity source rows retain their longer TTL even on manual refresh.

Cold reads are single-flight under striped locks. Expired snapshots return immediately and refresh in a two-thread pool; failures retain the last successful snapshot with a visible stale/error state and 30-second retry backoff. Explicit refresh bypasses backoff and refreshes league settings. A newly selected league/settings key must finish its first build. Cached presentation is invalidated after feedback, without rebuilding football intelligence or advancing memory observations.

News regexes have a bounded 4,096-entry cache. This is the only change inside a pre-existing domain-related module; extraction rules are unchanged.

## 4–6. Architecture, endpoints, and contracts

`Next.js → same-origin /api proxy → FastAPI → IntelligenceService → existing Python modules → Sleeper / nflverse / ESPN / SQLite`.

- `backend/services.py`: orchestration, provider/snapshot caching, copilot scope.
- `backend/cache.py`: bounded single-flight TTL/stale-while-revalidate.
- `backend/presenter.py`: normalized product presentation, no raw provider payloads.
- `backend/schemas.py`: Pydantic contracts and input validation.
- `backend/main.py`: thin routes, dependency/lifespan setup, safe provider failures, server timing.

Endpoints:

- `GET /health`, `GET /api/users/{username}/leagues`
- `GET /api/leagues/{id}/{snapshot,overview,roster,lineup,waivers,events,history}`
- `GET /api/leagues/{id}/players/{player_id}`
- `POST /api/leagues/{id}/refresh`
- `POST /api/leagues/{id}/copilot`
- `POST /api/leagues/{id}/events/{event_id}/feedback`
- `POST /api/leagues/{id}/analytics`

League routes require `?username=…` and validate that the selected league is in that user's Sleeper league list. This is scope checking, **not authentication**. OpenAPI is available at `/docs` and `/openapi.json`. Core models include `Player`, `Team`, `Matchup`, `Metric`, `LineupSlot`, `Recommendation`, `WaiverCandidate`, `OpportunityEvent`, `NewsEvidence`, `Evidence`, `JournalEntry`, `SnapshotMeta`, `Snapshot`, and `CopilotResponse`. Responses never require the browser to interpret nflverse rows, Sleeper roster internals, optimizer internals, or RSS.

## 7–15. Frontend and design

- **Structure:** App Router `/home`, `/team`, `/market`, `/ask`, shared root provider, typed client contracts, lightweight Lucide icons, Tailwind/PostCSS, and original semantic CSS. No Streamlit CSS/HTML copied.
- **Primitives:** AppShell, Sidebar, MobileNav, LeagueSwitcher, PlayerAvatar, TeamLogo, PlayerRow, StatusBadge, RoleBadge, Metric, Matchup, InsightCard, RecommendationCard, EvidencePanel, PlayerDrawer, EmptyState, Skeleton.
- **Home:** compact league/week header, prioritized player-first events, separate fact/inference text, semantic event accents, evidence/news sources, Save/Done/Dismiss, decision journal, and contextual game-plan rail.
- **Team:** real league slots, dense starter/bench lists, matchup/status/production/opportunity/role columns where space permits, actionable two-player comparisons, no projection claims.
- **Market:** qualified Waivers and more tentative Watchlist, position/search filters, ranked player identity, ownership, labeled metrics, reasons, and drawer access. Qualification presentation is not a reranking of engine results.
- **Ask:** first-class full-height conversation, compact suggestions, persistent composer, contextual player rail, structured actions/player chips/confidence/evidence, hypothetical and fallback states. Optional model phrasing remains secondary to the existing deterministic answer. No new conversational intelligence was added.
- **Drawer:** native modal dialog with Escape/focus behavior; headshot, team, matchup, status, role, workload, snaps, trend, reporting, and evidence. It does not navigate or rebuild the snapshot.
- **Mobile:** deliberate bottom navigation, compact two-line roster rows, wrapping names, stacked workspace, full-screen drawer, persistent chat composer. Tablet retains a narrower sidebar and reduces roster columns.
- **Loading:** one TanStack Query snapshot cache shared across routes; request deduplication, 60-second stale/refetch interval, 30-minute inactive retention, skeleton on first build, cached background refresh and explicit errors. Polling accelerates to 1.5 seconds only while the server reports an active refresh. League changes clear conversation/drawer state, including late responses from the old league.

Images reuse the centralized ESPN CDN resolver and 32-team canonical metadata from M7. Browser lazy loading/CDN caching, initials fallback, and no Python image downloads. Team colors are contextual; lime remains FanEdge branding.

## 16–19. Parity and validation

`scripts/validate_parity.py` runs the committed M11 app and migrated service with the **same captured real provider inputs** and separate temporary databases. All 13 comparisons passed: roster, slots, lineup decisions, waiver candidates, drop candidates, roster needs, opportunity feed, news facts, matchup index, identities, existing contexts, opportunities, and role profiles. M12 additionally constructs context for other league-rostered players used by the drawer/copilot. No rankings, schedule rules, role rules, or identity matching were rewritten in TypeScript.

- **160 Python tests passed:** all 140 existing tests plus 20 backend/cache tests. Existing Rams/schedule, role, optimizer, waiver, opportunity, news, memory, and copilot regressions remain intact.
- API coverage: health, leagues, all read endpoints, copilot/follow-up isolation, missing user/league/player, provider failures, partial evidence, feedback/history, changed scoring refresh, single-flight cache, background failure, memory not advancing on navigation, and OpenAPI.
- **6 browser tests passed** (5 fixture-based integration tests plus the opt-in live walkthrough): connection, cached navigation, Team/Market/Watchlist, player drawer, keyboard dismissal, structured Ask/evidence, loading/error recovery, long names, broken images, mobile overflow, and delayed-response league isolation.
- Production Next build, TypeScript check, Python compilation, Streamlit startup/health, FastAPI health, diff whitespace check, dependency audit, and secret-pattern scan are part of the handoff validation.
- The Python test environment emits two upstream deprecation warnings from Starlette's httpx/AnyIO compatibility layer; no test failures.

## 20. Product performance

Final backend benchmark: real local HTTP, fresh backend process, 20 consecutive requests per endpoint after first construction. Connection was **130 ms**; first snapshot **3,708 ms**. Earlier first-snapshot sample was 4,484 ms. Cold requests remain provider-dependent.

| Cached endpoint | Median ms | p95 ms |
| --- | ---: | ---: |
| Overview | 2.29 | 3.13 |
| Roster | 1.96 | 2.68 |
| Lineup | 1.77 | 2.10 |
| Waivers | 1.75 | 2.44 |
| Events | 1.77 | 2.66 |
| History | 1.67 | 2.52 |
| Snapshot | 2.89 | 4.96 |

Browser measurement uses a production Next.js build, real connected league, click-event performance mark to visible target heading plus the next animation frame. This measures UI response, not completion of lazy remote images. Final warmed route samples:

| Width | Home | Team | Market | Ask |
| --- | ---: | ---: | ---: | ---: |
| 1440 | already selected | 95 ms | 47 ms | 47 ms |
| 768 | 46 ms | 63 ms | 63 ms | 46 ms |
| 390 | 48 ms | 75 ms | 64 ms | 47 ms |

All measured changed-route samples met the local **<300 ms** goal. No navigation snapshot reads were required; Ask sends one non-blocking analytics request. These are a small local sample, not a production SLA. A separate benchmark overlapping CPU-heavy background rebuild observed individual read tails up to **263 ms**; Python thread/GIL contention is still a scaling consideration.

The parity run's service build timings (provider payloads already captured; not network latency) were: dataset/index construction 1,903 ms; identity 597 ms; Sleeper normalization/copy 302 ms; contexts/roles 30 ms; news 80 ms; lineup 1.8 ms; waivers 1.6 ms; opportunity 0.2 ms; SQLite 2.5 ms; copilot preparation 0.07 ms; total 2,917 ms.

Reproduce:

```bash
.venv/bin/python scripts/profile_streamlit.py --no-profile --output /tmp/reference-wall.json
.venv/bin/python scripts/validate_parity.py
.venv/bin/python scripts/benchmark_api.py
.venv/bin/python -m pytest -q
cd frontend
npm ci
npm run build
npm run typecheck
npx playwright install chromium
npm test
FANEDGE_LIVE=1 npm test
```

The baseline was collected before editing M11. To reprofile M11 now, use a separate checkout of `ee071e2` with the profiling script; do not overwrite current work. Live tests require both servers, internet, and the real test username. Default frontend tests use deterministic fixtures and skip the live test.

## 21. Screens inspected

Actual screenshots reviewed at **1440, 768, and 390 px**: Home, Team, Market, Ask, and Player Drawer; additional Watchlist and mobile structured-chat response checks. Long-name, missing-image, questionable-status and empty/error states are exercised in browser tests. No horizontal document overflow or browser page errors in the live run. Screenshots are temporary `/tmp/fanedge-m12-screens` artifacts, not repository assets. Market metric labels were added after visual review to remove ambiguous bare numbers.

## 22–23. Remaining boundaries and legacy status

- No authentication, payments, projections, trade finder, notifications, social, or weather added. No next milestone begun.
- Process-local caches/conversation context are designed for one backend worker. Multi-worker/distributed hosting needs a shared cache/session strategy; cold process restarts rebuild intelligence.
- First connection remains several seconds; cached navigation is fast. A complete expired snapshot refresh is one background job, not independently streamed news/football sub-jobs.
- SQLite needs durable storage. Public Sleeper username scope is not proof of account ownership, so journal mutation APIs must not be exposed as an authenticated public product yet.
- Client contracts are manually maintained against Pydantic/OpenAPI and checked in tests; automated type generation is a future maintenance improvement.
- Chat survives navigation but not a browser reload; only the preceding intent/answer is retained server-side. Mobile soft-keyboard behavior has browser emulation coverage, not physical-device testing.
- CDN headshots can lag team changes or fail; fallback works and canonical team text remains authoritative. Providers can be temporarily unavailable; one live test encountered a real Sleeper 502 before a successful retry.
- Legacy AI strategy/explanation buttons remain in the reference UI; their useful decision content is covered by the structured Ask/lineup/waiver surfaces, not duplicated as separate new-product buttons.
- Streamlit is explicitly marked legacy/reference and consumes the same `IntelligenceService`. Its old presentation remains for comparison; duplicate domain orchestration has been removed.

Commit and push identifiers are reported in the completion message (a commit cannot contain its own final hash).
