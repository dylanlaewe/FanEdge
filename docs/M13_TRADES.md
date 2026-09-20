# M13 — League-wide trade discovery

Validated September 19, 2026 (September 20 UTC), NFL week 2. This is a conservative current-season discovery engine, not a market-price oracle or a prediction of manager acceptance. M14 is not included.

## Model and boundaries

`trades.py` is deterministic and provider-independent. It reuses the M12 snapshot's identities, league-scored production, opportunities, participation, roles, availability, and actual ownership. It does not change the existing lineup optimizer, waiver ranking, schedule, identity, or role algorithms. The React application performs no football calculations.

1. **Profiles:** Every roster receives an optimal eligible starting assignment, positional starter/bench quality, available depth, injury/bye pressure, and role-quality counts. Reserve, taxi, and practice-squad assets are excluded from tradable pools but remain owned for waiver exclusion. Ambiguous ownership is not tradable.
2. **Need/surplus:** Dedicated-slot demand and actual flex assignments define occupied/required slots. Too few usable options gives STRONG NEED. A starter below 75% of the league positional baseline gives NEED. One useful backup gives SURPLUS; two give STRONG SURPLUS; otherwise BALANCED. Missing positional evidence is UNKNOWN, never a fabricated need. A useful backup exceeds both waiver replacement by one evidence unit and 65% of typical starter quality. Injury and bye pressures are separately exposed.
3. **Partners:** Three fit units per surplus/need alignment. Four more for meaningful opposing starting-unit strengths at different positions (gap at least two evidence units or 15% of the positional baseline). Stable roster-ID tie breaks are deliberate. This is a coarse shortlist, not proof that any package works; every candidate must subsequently pass both simulations. All rosters are browsable, including zero-fit teams.
4. **Relative value:** Neutralize current matchup/bye/status penalties in the existing evidence comparison score; retain blended historical/current production, usage, participation, role and trend. A no-history sample under four games receives a further 0.55–1.0 weight. Internal value is `6 + .35*quality + positive(quality-waiver) + .3*positive(quality-typical)`. These units are not projected points, dollars, consensus rankings, or fantasy trade market value. Unavailable players are excluded rather than offered cheaply because of injury.
5. **Replacement:** Median of the top three unowned positive-evidence players at the position. Typical starter baseline is the median of the top league-owned players needed for that position; flex demand is fractionally allocated among eligible positions for this baseline only. Actual lineup assignment uses exact eligibility, not fractional slots. Missing baselines remain null.
6. **Protection/block:** Explicit locks always win. Default locks include above-baseline starters (115%) and the three highest relative-value assigned RB/WR/TE assets. Marking a player willing to move overrides only their automatic lock, never an explicit lock, and never discounts value. Preferences are session/league scoped and reset on connection changes. They are not persisted as durable user preferences in M13.
7. **Generation:** Up to ten eligible assets per roster; two-player combinations use the first seven. A specific target moves to the front. Generate only 1:1, 2:1, 1:2; prune by partner fit, target, goal, availability and value before simulation. A specific player request may bypass the coarse partner-fit gate, not quality filters. Diversify to at most two variations per partner/incoming package; return at most 30.
8. **Two-sided utility:** Each side must improve starter evidence by at least one unit or useful depth by two. Neither starting lineup can lose more than one evidence unit. Useful backup depth is capped at one QB/TE backup in single-starter formats, two otherwise. A third QB is not a meaningful depth benefit. Best upgrade and positional/depth goals have additional goal checks.
9. **Simulation:** Exact maximum-weight slot assignment via a bounded Hungarian solver, with explicit empty-slot detection. Remove outgoing, add incoming, reassign both complete lineups, and recompute depth/needs. Capacity is checked. If a 1:2 requires a cut, only a low-value existing bench asset below 70% of the lowest incoming value can be conditionally released; the proposed cut is prominent. No roster is actually changed.
10. **Quality filters:** Reject duplicates, unsupported evidence/formats, invalid ownership, unavailable/reserved assets, protected outgoing players, unsupported package sizes, unfilled lineups, unsafe capacity overflow, value balance below 0.72, one-sided utility, and goal/target mismatches. Trading away two simulated starters requires a gain of at least `max(3, 10% of their combined quality)` and HIGH evidence on all assets, on either side, even with automatic locks disabled. Quiet results are intentional.
11. **Confidence:** The weakest asset controls package confidence. HIGH requires at least four current games and HIGH existing role evidence; MODERATE requires two games or historical evidence; otherwise LOW. This measures evidence support, not acceptance. Recent verified news is included as reported risk context, not invented manager motivation or a speculative price adjustment.

## Product integration

12. **Market:** Waivers / Trades / Watchlist. Trade controls include RB, WR, TE, QB, best upgrade, depth, target, partner, protect, and willing-to-move. Provider errors have retry states. Broad searches can correctly return no recommendations.
13. **Results:** Reusable two-sided player cards with photos/fallbacks, protected-player controls, confidence, why each roster benefits, before/after slot and depth details, give-ups, availability/sample/roster-space risks, Analyze and Try variation. Scores are secondary details, not the hero. Mobile stacks the exchange and keeps names/photos visible.
14. **Targeting:** Opponent-owned player drawers expose Explore trade. League roster browsing makes those players reachable even when no trade is recommended. Targets and partners are ownership checked by the server.
15. **Ask:** TRADE_FIND, TRADE_TARGET, TRADE_AWAY, TRADE_ANALYZE and TRADE_PARTNER retrieve the same deterministic engine. Protection phrases are resolved against the user's roster. Ambiguous names ask for clarification. Trade questions do not invoke an LLM. Dynasty/picks/future-upside valuation is refused. Follow-up explanations retain structured evidence and honor updated locks. Explicit reversed `I send` ownership asks for clarification.
16. **Manual analysis:** Select one or two players on each side, with one counterpart roster. The same simulation and quality gates return acceptance or specific rejection reasons. An analyzable rejected deal can still display its QUESTIONABLE FIT evidence; it never enters generated recommendations.
17. **Memory/analytics:** Existing scoped SQLite analytics records TRADE_FINDER_OPENED, TRADE_GOAL_SELECTED, TRADE_RESULTS_GENERATED, TRADE_VIEWED, TRADE_VARIATION_REQUESTED, TRADE_PLAYER_PROTECTED, and TRADE_ANALYZED. Server-generated events include normalized goal/count/acceptance fields. No trade messaging, submission, durable saved-trade feature, or additional private free-text persistence was added.

### API

All routes retain the M12 `?username=...` league-scope check. This is not authentication; M13 does not add authentication.

- `GET /api/leagues/{id}/trades`: all profiles, normalized players, baselines, locks, ranked partners.
- `POST /api/leagues/{id}/trades/search`: typed preferences/goals; bounded structured results.
- `POST /api/leagues/{id}/trades/analyze`: outgoing/incoming IDs plus preferences.
- Existing copilot accepts optional `trade_preferences` and returns optional structured `trades`.

No provider payload is blindly passed to the frontend. No write endpoint to Sleeper exists.

## Performance and validation

18. **Performance:** Engine construction is lazy: ordinary M12 page navigation does not build trade profiles or fetch manager names. Eight cached engines and 64 cached searches expire after five minutes; keys include immutable snapshot ID and canonical preferences. Per-engine assignment memoization is bounded at 4,096 rosters. League names use the existing provider cache. Client queries are account/league/snapshot scoped; refresh clears old displayed results. No synchronous image downloads were added.

Measured locally, not an SLA:

| Measurement | Result |
| --- | --- |
| All 12 initial roster profiles, including cached name lookup | 33.8 ms |
| Default RB search, 211 fully analyzed candidates | 82.4 ms |
| Default WR search, 206 candidates | 82.1 ms |
| Best-upgrade search after preceding positional searches, 598 candidates | 54.2 ms |
| Cold browser-triggered best-upgrade engine search | 262.5 ms |
| Cached trade-search HTTP, 20 requests | 13.3 ms median / 26.1 ms p95 |
| Trade overview HTTP, already cached engine | 29.2 ms |
| Browser click → completed cached search, desktop/tablet/mobile | 95 / 62 / 64 ms |
| Existing route reads, overlapping browser validation | 1.3–2.6 ms medians |
| Existing route reads, quiet run | 1.1–1.7 ms medians |
| Existing Home/Team/Market/Ask navigation | 13–80 ms |

Home/Team/Market navigation issued zero API requests in the connected M12 walkthrough. Ask issued its existing analytics request. Cold provider/snapshot fetching is separate from trade search and retains M12 behavior. Repeat HTTP calls may reuse an earlier search, whose `elapsed_ms` reports original engine computation rather than current cached request duration.

19. **Tests:** Deterministic fixtures cover profile need/surplus/balanced/shallow/injury/bye states, replacement/value, complementary/noncomplementary partners, all package shapes, locks/block, default core override, reserve/unknown/unsupported formats, duplicate/invalid ownership, slot assignment, capacity, goal filters, two-starter safeguards, third-QB depth, target/variation determinism, typed API/cache behavior, all five Ask routes, dynasty refusal, follow-up locks, and explicit trade direction. Playwright covers discovery, protections, manual analysis, targeting through the drawer, structured Ask cards, mobile overflow, long names/fallbacks, league switching and existing navigation/error recovery. Live walkthrough uses the real connected roster at 1440, 768 and 390 pixels. Screenshots remain outside the repository.

Reproduce:

```sh
.venv/bin/python -m compileall -q backend trades.py copilot.py sleeper_api.py scripts tests
.venv/bin/python -m pytest -q
.venv/bin/python scripts/validate_trades.py --all-rosters --output /tmp/fanedge-trades-validation.json
.venv/bin/python scripts/benchmark_api.py --trades --samples 20
cd frontend
npm run typecheck
npm run build
npm test
FANEDGE_LIVE=1 npm test
```

The opt-in live trade test deliberately targets the September 19 sample (Cam Skattebo) to inspect a real nonempty card. Future roster/provider changes may require choosing a different real target; deterministic fixtures are the stable regression suite. `validate_trades.py --recheck <prior reports...>` re-analyzes historical outputs, including bad examples, instead of quietly deleting them from the audit.

## Real-league audit and tuning

Final automated gate: **197 Python tests passed**, including the Rams/schedule regression suite; **9 Playwright tests passed** with live checks enabled. Python compilation, production Next build/TypeScript, FastAPI 13.0 health, focused new-module Ruff checks, whitespace checks, and production dependency audit passed (zero npm vulnerabilities). Two pre-existing Starlette/httpx deprecation warnings remain. A staged-file secret-pattern check found no credential/private-key matches; this is a pattern scan, not a comprehensive security audit.

20. **Availability:** TKelceLoveMachine exposed one 2026 league: **Davante Madames**, 12 teams, Half PPR, QB / RB / RB / WR / WR / TE / FLEX / FLEX / FLEX / K, six bench slots. A second username was requested but none was available during validation. No second-league validation is claimed. Eleven other roster viewpoints below are hypothetical evaluations of the same league, not additional connected accounts or leagues.

All 12 profiles were generated. Top coarse fits: Worthy of the Win, Amon-Ra Ra Rasputin, the witching hour, JSeNd zone (tied fit score). RB and WR goals, a locked Christian McCaffrey, and a specific Jahmyr Gibbs target were tested. Final broad searches for this user's RB, WR, TE, best upgrade and depth correctly returned zero. A targeted Cam Skattebo request returned one LOW-confidence idea. Default protected players: Christian McCaffrey, Saquon Barkley, Travis Etienne, Christian Watson.

21. **Before tuning:** An initial bench-surplus-only partner gate generated nothing in this three-FLEX league. Adding opposing starting-unit strengths found candidates but exposed poor packages. Across two subsequent passes, **11 unique user-roster packages** were manually inspected: **0 plausible / 5 questionable / 6 bad**. These are qualitative engineering judgments, not ground-truth market labels or manager feedback.

| User sends → receives | Before | Problem / rationale | Final recheck |
| --- | --- | --- | --- |
| Jeremiyah Love → Jayden Daniels | Bad | Redundant third-QB depth counted as useful | Rejected |
| Jeremiyah Love → Justin Herbert | Bad | Same redundant depth error | Rejected |
| Diggs + Jameson Williams → Olave | Questionable | Two starting options concentrated into a questionable-status player | Rejected |
| Etienne + Jameson Williams → Olave | Questionable | Two starters lost for a small modeled gain | Rejected |
| Saquon + Diggs → Olave | Bad | Important starter exposed too casually; thin consolidation justification | Rejected |
| McCaffrey + Saquon → Gibbs | Bad | Mathematical balance badly understates concentration risk | Rejected |
| McCaffrey + Diggs → Gibbs | Bad | Two important starters for marginal improvement | Rejected |
| Diggs + Jeremiyah Love → Cam Skattebo | Questionable | Coherent RB/WR exchange, but rookie sample and counterpart cut remain substantial risks | Survives, LOW |
| Etienne → Allgeier + Mike Evans | Questionable | Other side loses two starters for a small gain | Rejected |
| McCaffrey → Matthew Golden + Javonte Williams | Questionable | Opposite-side consolidation and short-sample uncertainty | Rejected |
| Saquon → Matthew Golden + Allgeier | Bad | Weak support for giving up importance on one side and two starters on the other | Rejected |

The recheck disables automatic core locks, so the ten rejected examples are actually stopped by quality/depth gates, not merely hidden by protection defaults. Explicit protections still cannot be overridden.

22. **After tuning:** Same 11-package user sample: **0 plausible / 1 questionable / 0 bad surfaced; 10 rejected**. Additional same-league viewpoint review found four packages: three plausible, one bad (Mike Evans + Garrett Wilson → Chris Olave). The final strong-evidence two-starter gate rejects that last bad example. Across the **15 manually reviewed package/viewpoint cases**, final surfaced results are **3 plausible / 1 questionable / 0 bad; 11 rejected**. Do not interpret this small, tuned sample as a general accuracy rate. Two of the plausible examples are variants of one strategic fit.

23. **Useful discoveries:**

- **the witching hour → Worthy of the Win:** Jared Goff + DeMario Douglas for Trevor Lawrence. A QB improvement for the former; a WR/flex alternative for the latter offsets the QB change. Both simulated lineups improve (+3.25 / +1.24 evidence units). Counterpart needs a disclosed Jonah Coleman cut. Moderate evidence; a plausible discussion, not a claim they will accept.
- **Amon-Ra Ra Rasputin → She Calls Me Backfield:** Justin Herbert for J.K. Dobbins. Convert quarterback redundancy into an RB/flex option; the other roster gains useful QB cover. +1.72 lineup evidence for the former, +2 useful depth for the latter, with lost QB cover disclosed in the before/after details. Moderate evidence.
- **Same strategic fit, alternate asset:** Jayden Daniels for J.K. Dobbins. The sender can use Herbert while addressing RB. +1.51 lineup evidence and +2 counterpart depth. Moderate evidence. This is an alternative, not a recommendation to execute both deals.
- **User-specific tentative target:** Diggs + Jeremiyah Love for Cam Skattebo, with Let Him Cook. +1.73 / +1.05 evidence units, RB improvement versus WR improvement. LOW confidence and a conditional Kayshon Boutte cut make this **questionable**, not a polished “great trade” endorsement.

24. **Limitations:** One independent league; mostly one completed current-season game; no consensus market/ADP input, manager preferences, future weekly projections, multiweek bye optimization, keeper economics or draft picks. The relative-value model still needs broader out-of-sample validation. Default locks and two-starter safeguards can suppress worthwhile deals. Search is bounded rather than exhaustive. A current bye or doubtful status excludes an asset conservatively, even though a real manager could trade them. Position baselines use available evidence, not guaranteed future replacement performance. These limitations are why an empty broad search is preferable to filling a page.

## Visual and source discipline

Manually inspected real Trade Finder at desktop/tablet/mobile; quiet state, targeted 2:1 player card, protection controls, conditional cut, manual analysis and Ask response. Existing real Team/lineup and Market/Watchlist/Home/Ask pages were rendered in the retained M12 walkthrough; Playwright verified no horizontal overflow. Cards retain FanEdge lime/dark identity, use the existing player image fallback, and stack on mobile. Long protection lists and expanded evidence are intentionally scrollable; a future tighter selector could reduce mobile scrolling.

Team names add one read-only [official Sleeper league-users endpoint](https://docs.sleeper.com/#getting-users-in-a-league); malformed/missing names fall back to explicit roster IDs. No scraping or proprietary asset bundle was introduced. Player photos/logos retain the existing centralized ESPN CDN resolver and fallback policy. Provider availability and commercial licensing/terms remain external dependencies; publicly accessible endpoints/images do not confer redistribution rights.

25–26. The release commit and confirmed GitHub push are reported in the task completion message. No M14 work is included.
