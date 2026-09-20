# M15 release gates

**Decision: NO-GO for inviting 5–10 independent users yet.** A committed release candidate is not launch authorization. FAIL includes missing evidence, not just a reproduced bug. `beta-gates.json` is the machine-readable evidence input; the aggregator also enforces actual audit coverage and labels.

| Gate | Status | Evidence / remaining action |
|---|---|---|
| Provider rights/configuration | FAIL | Optional ESPN/AI/ADP off; source inventory complete. Resolve Sleeper intended-use and nflverse upstream scope before distribution |
| Data integrity | PASS, local scope | Existing Rams/ownership/lineup/news provenance tests and real-league audit find no contradiction; repeat across new leagues |
| Recommendation safety | FAIL | No known BAD found in operator review, but final independent human release sample is unreviewed. Complete labels, no BAD or UNREVIEWED allowed |
| Independent calibration | FAIL | One real owner/league only. At least two genuinely independent owners/leagues, then 5–10 testers after remaining gates |
| AI grounding | PASS, default configuration | Deterministic answers; unsupported requests and simulated AI errors tested. Optional model prose is off and not certified |
| Local performance | PASS | Warm reads/navigation preserved; cold-route and payload findings in M15_RELEASE.md; deployment measurements still pending |
| Graceful errors | PASS, local scope | Tests cover provider errors, stale background refresh, optional AI failure, rate-limit response and recovery UI |
| Desktop/tablet/mobile | PASS, operator scope | Production build at 1440/768/390, core flows and fallback images; not independent usability proof |
| Feedback/analytics | PASS, implementation | Contextual server feedback, bounded text, safe session analytics, read-only report and retention command tested. Deploy daily retention before release |
| Secrets | PASS, source scope | Git/source scan, no committed DBs/keys or browser key. Does not substitute for hosting security review |
| Authentication/isolation | FAIL | Sleeper username does not establish ownership. Verify trusted per-tester identity boundary before private journal/feedback use |
| Unassisted UX | FAIL | Obtain actual tester observation using BETA_TEST_SCRIPT.md; operator familiarity is not evidence |
| Deployment | FAIL | Confirm TLS, invite access, loopback-only backend, one worker, request/body bounds at gateway, log/backup permissions and scheduled 30-day retention |
| Rollback | FAIL | Rehearse backup/restore and known-good artifact rollback without re-enabling unresolved providers |

The owner must attach dated evidence and re-run audit aggregation to change these gates. Do not edit a FAIL to PASS solely to produce a GO. No scheduled jobs, provider licensing agreements, independent testers, hosted release or adoption figures were invented during M15.
