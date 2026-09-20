# M14 — Intelligence calibration and product hardening

Audit: September 19, 2026 US Eastern (September 20 UTC). Baseline: `edd4923`.
This is an evidence audit, not a prediction-accuracy or trade-acceptance study.

## 1. Market evidence research

No ranking database or image collection was copied into this repository. No galleries, prohibited sites or paywalls were scraped. A remotely accessible API is not automatically licensed for commercial use.

| Source / access | Scope, cadence, coverage | Identity quality | Cost / rights / decision |
|---|---|---|---|
| [FantasyPros API](https://www.fantasypros.com/api-data/) — keyed JSON consensus endpoints | NFL redraft and other ranking products; endpoint-specific updates, no SLA assumed | Provider identifiers; a verified crosswalk would be required | Free prototypes; HOF advertised from $8.99/month annually for personal use; commercial agreement required. [Current access guidance](https://support.fantasypros.com/hc/en-us/articles/49749297704475-How-do-I-request-access-to-the-FantasyPros-API) specifically restricts competing products. **Rejected without written permission.** |
| [FantasyCalc documented API](https://fantasycalc.com/api-docs) — `/values/current`, `/players` | Redraft/dynasty; values update multiple times daily; league size, QBs, PPR and TE premium parameters. Docs allow hourly value refresh; terms encourage daily caching | Own ID plus Sleeper, ESPN, MFL and Fleaflicker identifiers: strongest potential crosswalk | [Terms](https://fantasycalc.com/terms-of-usage): commercial use requires express written permission, attribution/backlink, documented endpoints only, no substantial substitute. Public app contact requested before launch; price not published. **Best future candidate, not integrated or contacted.** |
| [Fantasy Football Calculator ADP API](https://help.fantasyfootballcalculator.com/article/42-adp-rest-api) — public JSON | Daily draft sentiment, standard/half/PPR/2QB/dynasty/rookie datasets; not weekly rest-of-season trade prices. [Method](https://help.fantasyfootballcalculator.com/article/34-average-draft-position-adp-data): human mocks, computer selections excluded | FFC IDs are not Sleeper IDs; exact unique name/position/canonical-team join only | Official help explicitly permits free personal and commercial use and requests attribution/link. **Optional gated adapter, disabled by default.** |
| [SportsDataIO](https://sportsdata.io/developers) — licensed API | NFL fantasy feeds, ADP and other data; paid real-time products versus delayed Discovery Lab. DFS projected ownership is not fantasy roster/start percentage | Own player IDs; exact licensed crosswalk/coverage needs confirmation | [Licensing](https://sportsdata.io/help/data-rights-and-licensing-questions): commercial quote; Discovery Lab personal-only, next-day delayed, fantasy advertised $99/month or $599/year. Trial data is scrambled, unsuitable for calibration QA. **Rejected without commercial agreement.** |
| [DynastyProcess values](https://dynastyprocess.com/values/) — public CSV repository | Dynasty horizon, FantasyPros ECR transformed into values; not a redraft weekly market | Cross-provider IDs may help, but cannot solve upstream rights | Public repository availability does not grant upstream FantasyPros redistribution rights. **Rejected: horizon and upstream licensing mismatch.** |
| [Sleeper documented API](https://docs.sleeper.com/) | Existing league ownership and trending add/drop counts; trends are neither prices nor roster/start percentages | Native exact Sleeper IDs | Existing free noncommercial access; commercial licensing contact remains a beta/business blocker. **Keep actual league ownership; do not invent market value from trends or use undocumented ownership endpoints.** |
| [KeepTradeCut FAQ](https://keeptradecut-prod-linux.azurewebsites.net/frequently-asked-questions?open=liquidity) — public explanatory page | Crowdsourced dynasty/redraft sentiment; responds to user input | No authorized machine-readable crosswalk/feed verified | No documented commercial machine-readable feed or price verified in this investigation. **Omitted; no scraping.** |

FantasyPros' [published API terms](https://api.fantasypros.com/public/v2/terms-of-use) and its newer access guidance must be reconciled in an actual commercial agreement, not inferred by this implementation.

### Selected evidence and provenance

`calibration.py` implements FFC draft sentiment only. Set `FANEDGE_MARKET_ADP_ENABLED=1` explicitly to opt in. Default production behavior does not fetch market data. Daily process cache; five-second network timeout; failure never blocks normal intelligence. No user/player/league identity is sent to FFC—only year, league size and scoring format.

Acceptance gates: matching current year, no future date, content at most seven days old, week ≤4, matching team count/scoring, ≥50 mock drafts overall, ≥20 selections per player, positive finite ADP, unambiguous exact name/position/canonical-team identity. Unsupported superflex/2QB and receiving-premium settings skip the adapter. Duplicate/ambiguous identities are omitted, never guessed. Provenance retains source URL, observation date, sample and `DRAFT_SENTIMENT` kind.

One official half-PPR/12-team/2026 probe returned 54 players from 116 drafts, covering September 9–14. The first row had only six selections and fails the sample gate. This is direct evidence that feed availability does not establish usable coverage. No live values are claimed in the default audit. The opt-in happy path, stale/malformed/ambiguous/low-sample paths are fixture-tested, not a claim of full live crosswalk coverage.

## 2. Value Model V2

M13's completed-game/opportunity blend, replacement baseline, positional demand and numerical utility coefficients are retained. No one-league coefficient fit and no loosening of package filters. V2 adds interpretable uncertainty tiers, market provenance and package diagnostics around the existing utility model.

`quality / typical positional starter` determines tiers: below 0.60 Bench; 0.60 Depth; 0.85 Starter; 1.10 High-end; 1.35 Foundation. Missing baseline, LOW confidence, or fewer than four current games **and** fewer than eight historical games forces Speculative. These are league-relative evidence tiers, not universal player prices or talent grades. Corroborated top-two-round ADP can protect a historically supported Starter as High-end; it cannot turn a one-game rookie into an established star.

Both directions of a package are checked. Sending a High-end/Foundation asset across a gap of two or more tiers without an asset near its tier rejects as `STAR_FOR_DEPTH`. Creating a newly uncovered starting position rejects as `DEPTH_DAMAGE`. Existing value balance, both-team incentive, lineup downgrade, quantity-for-quality, supported assets, roster capacity and protected-player gates remain.

Position audit: QB utility remains high because actual output/opportunity is high even in one-QB leagues; replacement and useful-backup caps mitigate but do not prove market calibration. RB historical samples and injury availability matter; WR one-game spikes remain Speculative without a prior; scarce TE baselines can produce high relative tiers. K/DEF/unsupported assets remain outside trade discovery. No claim is made that these boundaries are externally validated market prices.

## 3. Diagnostics and real search findings

`POST /api/leagues/{id}/trades/diagnostics?username=...` accepts the same search options, uses the same cache, and returns considered/rejected/surviving/surfaced counts, primary and overlapping reason counts, full-analyzer entries, protections and calibration status. Normal search responses omit the detailed histogram. Counts concern the bounded candidate universe after partner/pool selection, not every conceivable league trade. Primary reasons partition rejected packages; all-reason counts deliberately overlap. Surviving precedes exclusions, diversity and display limits.

Real default BEST_UPGRADE: **3,120 considered / 3,120 rejected / 0 survived**, 598 entered the full analyzer. Primary reasons: 2,522 VALUE_GAP; 318 STARTER_DOWNGRADE; 110 REDUNDANT_INCOMING_POSITION; 92 STAR_FOR_DEPTH; 73 INVALID_ROSTER; 5 NO_PARTNER_INCENTIVE. RB: 3,120/3,120/0; WR: 3,120/3,120/0; DEPTH: 3,120/3,120/0. These are defaults, not a claim that every targeted search is empty.

Targeted Skattebo/RB: **520 considered / 519 rejected / 1 survived**. Stefon Diggs + Jeremiyah Love for Cam Skattebo remains **QUESTIONABLE**, LOW confidence. Both modeled lineups gain, but one-week evidence, rookie valuation and the partner releasing Kayshon Boutte make acceptance/market realism uncertain. This result is not promoted to GOOD. Start-Diggs versus trade-Diggs is now explicitly explained as alternative paths requiring a new lineup evaluation.

Quiet UX explains the evidence threshold and points to complementary partners, a specific target, waivers/watchlist and optional protection changes. It does not manufacture a package.

## 4. Unified planning and coherence

`action_planner.py` powers broad goals and the weekly plan in the existing Ask surface: improve position, fix lineup, replace injured, add depth and target player. Explicit trade questions keep the M13 trade adapter. The planner compares valid lineup decisions, confirmed available candidates with roster fit, safe unprotected release candidates, bounded trade results, relevant news/events and journal changes.

Action order is deterministic: supported lineup repair (no asset cost), supported waiver (release/claim cost), supported trade (assets/manager agreement), monitor, hold. Confidence and role evidence break ties; exact football utility is not presented as expected points. A lineup swap cannot claim to add roster depth. Releases exclude current starters, recommended starters and protected players. Alternatives are not a combined sequence; trades involving a recommended starter explain the conflict. Provider/snapshot staleness makes the unified planner HOLD. Follow-ups re-evaluate current evidence/protections, not replay old packages.

`quality.py` checks owned/available collisions, unconfirmed waivers/events, bye/schedule contradiction, owned/eligible/unique lineup placements, news provenance, resolved active events, add/drop and start/drop conflicts, and trade ownership/start-trade conflicts. Error-affected actionable records are quarantined across lineup, waiver, news, feed and active memory presentation. Historical resolved changes remain legitimate journal records. Market and Ask share `waiver_is_actionable`: role alone is not an add. Rank calculations themselves were not retuned.

## 5. Freshness and provider isolation

`GET /api/health/data` exposes process-level football providers without usernames, league IDs, credentials or raw error text. The scoped `/api/leagues/{id}/health/data?username=...` additionally reports that roster and memory observation plus coherence issues. The latter has the same existing read-only username/league boundary; this is not a substitute for future access-control design.

Each observed dataset records last successful fetch, attempt, age, threshold, count and warnings. Status distinguishes NOT_FETCHED, OK, EMPTY, DELAYED, STALE, UNAVAILABLE and disabled calibration. Cache reads never become new successful fetches. Stats/snaps/injuries expose season/latest week; scoped checks compare content with the last expected completed week. News retains its latest content timestamp and existing per-fact freshness; a quiet news feed is not automatically a failed fetch. Failed attempts preserve the prior success timestamp. Health is bounded/in-memory, so a restart resets observations.

Thresholds preserve provider policy: Sleeper players/injuries 1h; rosters/NFL state/memory 5m; schedule/current stats/snaps 6h; prior-year data/identities 24h; news 15m; optional ADP 24h. Dataset failures are isolated: failed injuries no longer discard valid stats/snaps. Incomplete football/news observations pause memory absence-based resolution. Required football incompleteness remains unknown rather than zero production.

## 6. Real league quality audit

Available league: Davante Madames, 12-team half-PPR, NFL week 2, actual QB/RB/RB/WR/WR/TE/three FLEX/K + six bench. One league is not an independent multi-league evaluation. Ratings are engineering judgment on evidence, cost and coherence—not outcome accuracy. Rows may refer to the same player in different surfaces; do not sum them as independent trials.

| Surface | GOOD | DEFENSIBLE | QUESTIONABLE | BAD | Evidence / reasoning |
|---|---:|---:|---:|---:|---|
| Top lineup decisions | 0 | 2 | 0 | 0 | Douglas over Gainwell: 91% vs 46% snaps plus current production, but one game. Diggs over Love: snap/history/matchup evidence; not a guarantee. Existing optimizer output unchanged. |
| Immediate waiver adds | 0 | 0 | 0 | 0 | No role-plus-roster-fit add clears the shared rule; absence is not a quality success statistic. |
| Watchlist, all 11 | 2 | 6 | 3 | 0 | GOOD: Noel/Wilson have cited teammate news + actual availability, action MONITOR. DEFENSIBLE: Miller, Raymond, Bourne, Fant, Allen and Chris Moore as low-cost watches; Moore's weaker role warrants caution. QUESTIONABLE: Cousins/Rush/Lock are redundant given two current QBs; classification no longer urges adds, but relevance is weak. |
| Top trade partners | 0 | 3 | 0 | 0 | Worthy of the Win: RB/TE vs WR; Amon-Ra Ra Rasputin: relative QB/RB units; the witching hour: WR/TE. Plausible exploration, not manager intent or accepted packages. |
| All surfaced packages across four default goals + target | 0 | 0 | 1 | 0 | Only targeted Diggs/Love → Skattebo. Structural plausibility, questionable market/evidence certainty. |
| Proactive events, all five | 2 | 3 | 0 | 0 | Noel/Wilson news-supported monitors; cautious Moore monitor plus the two qualified lineup suggestions. |
| Ask weekly plan | 0 | 1 | 0 | 0 | Existing supported swaps first; monitoring alternatives; no forced trade/add. Stronger role evidence breaks equal-confidence ties. |
| Ask “I need an RB” | 0 | 1 | 0 | 0 | Monitor Miller, explain role/fit limits and no supported trade; does not prescribe a release. |

Baseline immediate-add labels: 3 BAD redundant-QB adds and 4 QUESTIONABLE role-only adds. Baseline RB Ask was QUESTIONABLE because it stopped at a quiet trade search. Baseline targeted trade was also QUESTIONABLE and remains so. These are not hidden by a favorable aggregate score. The unchanged recommendation payloads establish no unexpected lineup decision drift.

Live ownership changed during the audit: Bateman initially was available, then appeared on roster 6 (“Buy flowers when it hurts”) in the refreshed Sleeper rosters. FanEdge stopped offering him as available and selected Chris Moore as the weaker same-position news watch. The final counts above grade that final state; the earlier Bateman monitor was GOOD while availability was verified. This was an external league change, not a FanEdge transaction. The journal correctly reflected a changed situation rather than assuming all refreshes must be identical.

## 7. Quality harness and product journeys

`tests/test_quality_harness.py` adds deterministic tier/spike, attributed ADP, low sample, stale/format/duplicate/ambiguous identity, thin/deep roster, injured starter/backup, emerging role, bye, no-safe-release, protected release, lineup/drop conflict, availability quarantine, missing news provenance, resolved memory, complementary and quantity-for-quality trade, quiet/provider-failure and fetch-versus-content-age checks.

It runs alongside the existing engine fixtures: `test_lineup_optimizer.py` (one-game spike, historical corroboration, legal global assignment); `test_opportunity_engine.py` (role expansion without production, touchdown spike suppression, corroboration, quiet/injury); `test_news.py` and memory tests (provenance, stale/reopened/resolved); `test_waiver_engine.py`, `test_trades.py` and API contracts. These assertions test deterministic recommendation quality constraints, not statistical predictive accuracy.

Flows A/I: Home event → cited evidence distinguishes reporting from inference. B: Team → player drawer → swap evidence. C: Market empty immediate adds → Watchlist → player/evidence. D: goal/target → quiet search or tentative package → manual analysis. E/F: weekly/RB cross-feature plan. G: named player analysis. H: unsupported weather refusal. J: refresh → journal lifecycle with no fake new events. Fixture tests cover positive package controls, changed protections and delayed responses independently of live trade volume.

Concrete frontend fixes: stale in-flight trade responses cannot restore results after snapshot/protection/target changes; Market tabs support Left/Right/Home/End and roving focus; quiet waiver/trade copy distinguishes failed filters from no supported action. Existing native drawer Escape/focus restoration, long names, failed images and loading/error recovery are tested. No design restart or new page. The applicable UI skill guidance informed responsive/empty-state review; the legacy Streamlit UI was not changed.

See [QUALITY_SCORECARD.md](QUALITY_SCORECARD.md) for release limitations and final validation/performance results.
