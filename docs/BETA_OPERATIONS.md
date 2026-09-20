# Beta operations and privacy

## Configuration / launch

Use `.env.example`; all optional visual/news/AI/ADP flags default off. `/api/capabilities` exposes booleans and build only. `/health` gives process health/build; `/api/health/data` distinguishes fetch/content freshness. Process health is not a promise that feeds are current. Set `FANEDGE_BUILD_ID` to the deployment SHA. Otherwise it is derived once from Git at startup; local dirty builds require a descriptive override for test records.

Start one worker: `.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000 --no-access-log`. Build/start Next in `frontend`. Keep backend loopback-only. Configure structured `fanedge.beta` INFO logging and retention at deployment; standard access logs are disabled to avoid username/query logging. Never expose `.env`, SQLite, `/internal`, or API docs on the public gateway. The app currently treats a Sleeper username as a **public lookup, not authentication**. It cannot prove that the visitor owns that account; feedback/journal manipulation is possible without a trusted identity boundary. This is a release blocker, not solved by rate limiting. An invite-only deployment still needs account-to-session binding before treating journal/feedback as trusted private user data.

## Controls

Create an independent random `FANEDGE_OPS_TOKEN` of at least 32 characters; do not print it or put it in `NEXT_PUBLIC_*`. `/internal/ops/*` is outside Next's `/api` proxy and rejects absent/incorrect credentials with 404. Use a loopback SSH tunnel, not a public admin panel:

```sh
.venv/bin/python scripts/beta_ops.py status
.venv/bin/python scripts/beta_ops.py clear-cache
.venv/bin/python scripts/beta_ops.py refresh --username USER --league LEAGUE_ID
.venv/bin/python scripts/beta_ops.py prune-telemetry
```

Cache clearing preserves journals/feedback; avoid during active requests. Background refresh pending returns 409. Use a service restart for a guaranteed idle cold cache (an already in-flight request can repopulate a cleared cache). Refresh returns the old snapshot immediately while background work proceeds; check snapshot ID, refreshing/error state and data health. Do not equate HTTP 200 with fresh provider evidence.

## Limits / failure behavior

Sliding 60-second limits by socket peer: refresh 2, Ask 12, trades 30, connect 20, snapshots 30, telemetry 300, other reads 180. A second process-wide bucket is ten times each limit. Behind Next, the peer is the Next server, so the conservative bucket is shared by testers; no untrusted forwarded header can bypass it. HTTP 429 includes Retry-After 60 and an understandable retry message. No automatic POST retries. Client timeout 60s. Provider request timeouts: Sleeper 10s, nflverse 8s, ESPN 10s if opted in, FFC 5s. These bound individual requests, not a strict wall-clock deadline for the entire multi-provider cold build. Three shared workers fetch independent football datasets; cache/single-flight guards avoid repeated work. Trades retain bounded candidate search. Identical snapshot/conversation/protection-scoped Ask calls share results for 30s. Conversations remain in RAM for 1h; no questions enter normal analytics.

OpenAI: explicit Ask only, no Home/Team/Market generation and no render-triggered generation. Weekly/position planning and trade requests remain deterministic. Optional generic answer phrasing uses gpt-4o-mini, max 24k characters in, 320 tokens out, 8s timeout, no SDK retries, `store=False`; unsupported/ambiguous requests skip it. Legacy strategy/lineup/waiver functions cap 350 output tokens and 24k characters, are not beta routes. Core decisions remain authoritative. The heuristic prose validator is **not a formal hallucination proof**, which is another reason optional prose remains off for this candidate. Tests simulate timeout/error/rejected output; they are not a model evaluation.

## Feedback and instrumentation

`beta_events` is separate from production recommendations. Product feedback stores category, optional text (1,000 chars), event/recommendation ID, league/user ID, screen, build, snapshot ID/time, provider freshness and enabled capabilities. Helpful/Not helpful is evaluative only; Save/Done/Dismiss still records a journal action. Labels from offline audits never enter production algorithms.

Session ID is a random browser-tab UUID in sessionStorage; it is not authenticated identity. Return-session means a saved account in a new tab session, not verified retention. Analytics captures page mounts, recommendation component mounts (not proof of attention), evidence opens, trade searches, intent taxonomy and feedback. Never raw questions, provider dumps, API keys or request query strings. Optional feedback text is intentionally user-supplied and must be treated as sensitive. Restrict DB and backups to the operator.

Schedule daily `prune-telemetry` before beta: deletes beta rows older than 30 days; no scheduled job is silently installed by the app. Operational logs and backups also need 30-day expiry. Existing decision/news memory tables are durable until operator deletion and are not touched by telemetry pruning; document this separately to testers and honor deletion requests. Audit JSON/labels contain league data: store privately outside Git, retain only as long as needed for the release review. Synthetic and operator validation records must not be claimed as independent users.

```sh
.venv/bin/python scripts/beta_report.py --db .fanedge/fanedge.db
.venv/bin/python scripts/audit_league.py --username USER --league LEAGUE_ID --output /private/audit.json
# Review audit.json; edit only audit.labels.json with reviewer, label, optional reason.
.venv/bin/python scripts/calibration_report.py /private/audit.json --gates docs/beta-gates.json
```

The beta report is read-only and excludes identifiers, feedback text and question contents. It reports actual retained counts, intent/action usage, route latency/error samples, and points to separate quality labels. Empty data stays zero; historical absence is not evidence of no failures. Release gates fail closed on missing reviews, BAD/unreviewed recommendations or fewer than two independently owned leagues. Two leagues is a minimum diversity prerequisite, not statistical proof of quality.

## Deployment and rollback (must rehearse on target host)

Build immutable images/artifacts from a tested SHA. Back up SQLite with SQLite's backup API while stopped or consistently online; protect backups. Run health, capability and core workflow checks behind the actual TLS/invite gateway. Test identity separation, process restarts, scheduled retention and rate limits through that gateway. Pin one worker; scaling requires shared quotas/storage first.

Rollback: stop traffic/writes, take a consistent DB backup, deploy the prior known-good commit `1768d5f2aba2b85962aa35c3284afee1cab97336`, preserve optional-provider restrictions externally (the previous code does not enforce M15 flags), restore DB only if necessary and explicitly approved, smoke-test health/connect/read views, then restore traffic. M15 tables are additive; old code ignores them. Do not roll back to a version that re-enables unresolved providers for testers. No actual deployment or remote rollback rehearsal has been claimed.
