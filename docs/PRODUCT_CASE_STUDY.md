# FanEdge: from fantasy dashboard to evidence-first decisions

FanEdge is a Sleeper-connected fantasy-football decision product built through fifteen milestones. It is a release candidate, not a validated business: no independent adoption, retention, revenue or recommendation-accuracy percentage is claimed.

## The problem and product thesis

Fantasy managers already have standings and statistics. The harder task is deciding what deserves attention this week and understanding why. FanEdge's thesis became proactive, league-aware decisions with visible evidence, not another chart collection or an unconstrained chatbot.

## Evolution and lessons

1. **M1: real integration.** Connect a Sleeper username, select an actual league, honor its scoring and roster. Read-only access keeps control with the manager.
2. **M2–M4: football intelligence.** Weekly context, league-owned versus available players, waivers, lineup slots and opportunity signals. Functional analytics outgrew a weak, generic interface.
3. **M4.1: correctness before features.** A false-bye incident revealed that missing schedule coverage could masquerade as a football fact. Canonical team identities and complete-schedule requirements made unknown distinct from bye. The Rams regression remains a release check.
4. **M5–M6: evidence and decisions.** Role, usage and matchup evidence became supporting inputs to weekly actions. Sparse samples reduce confidence; absence of evidence is not evidence of absence.
5. **M7–M7.1: consumer UI.** Sports-native player identity, stronger names, lineup rows, swaps, responsive navigation and image fallbacks replaced a grid of metrics. M15 deliberately disables optional remote imagery until usage rights are resolved: visual polish cannot substitute for permission.
6. **M8: proactive opportunity engine.** Prioritized events explain who matters, what changed and what to consider. No fabricated action volume; holding or watching can be the right outcome.
7. **M9: memory and journal.** Lifecycle/state reconciliation distinguishes new, continuing and resolved signals. Save/Done/Dismiss records intent, not a Sleeper transaction or causal proof of improved results.
8. **M10: attributed news.** Structured, source-linked reports can influence intelligence without model-memory news. Optional news is now off pending source review; historical evidence is not silently rewritten.
9. **M11: grounded copilot.** Intent routing retrieves league context and produces deterministic answers, optionally phrased by an LLM. Unsupported demand stays explicit.
10. **M12: architecture changed for interaction speed.** Full Streamlit reruns produced measured navigation around **4.4–4.5 seconds**. Next.js plus FastAPI, normalized snapshots and client caching brought measured warmed navigation to **46–95ms** in the migration audit. These are local measurements from different interaction paths, not an internet-wide SLA. The Python football engines were preserved rather than reimplemented in JavaScript.
11. **M13: league-wide trade discovery.** Complementary roster needs and before/after lineup evidence guide exploration. Protected players, bounded candidate searches and two-sided checks reject unsupported ideas.
12. **M14: calibration instead of more features.** A formal real-league audit found proactive events strongest, watchlists mixed, lineup advice defensible and package generation insufficiently calibrated. Default searches often rejected every package; inventing attractive results would have been worse product behavior. One league cannot establish general quality.
13. **M15: release discipline.** Provider dispositions, fail-closed optional capabilities, per-league audit/label tooling, structured observability, rate/cost bounds, contextual feedback, privacy-conscious analytics and explicit release gates. Independent reviews and deployment verification remain visible blockers.

## Engineering decisions worth keeping

Football logic is deterministic and independently tested. AI is optional presentation, not the authority for ownership, schedule, player identity or actions. A single snapshot is shared across views; player drawers reuse available data. Independent provider fetches now use a three-worker pool, and trade search responses no longer repeat the entire league's player graph. Warm reads remain millisecond-scale locally; cold provider latency remains variable and is measured separately.

The evaluation workflow separates recommendations, human judgments and analytics. A helpful vote is not a GOOD recommendation label; a click is not successful advice; an operator test is not an acquired user. Machine release gates fail on missing evidence rather than assigning a flattering composite score.

## Current outcome

The product is useful enough to inspect and test, but the responsible M15 recommendation is **NO-GO for independent beta invitations until the remaining gates are met**. The most important next evidence is permission clarity, genuinely different league audits, and testers who can complete core tasks without developer guidance. See `BETA_RELEASE_CHECKLIST.md` for current evidence rather than extrapolating from this case study.
