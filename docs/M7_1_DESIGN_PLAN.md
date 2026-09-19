# M7.1 frontend design plan

## Product frame

FanEdge is an AI fantasy general manager, not an analytics dashboard. The connected experience uses a persistent league/week shell and four jobs: **Overview**, **My Team**, **Waivers**, and **Ask FanEdge**.

## What survives

- Sleeper account, league, roster, scoring, and ownership data
- nflverse schedule, production, opportunity, participation, role, and availability evidence
- deterministic lineup optimizer and waiver ranking
- constrained AI explanations that receive only FanEdge's factual context
- centralized ESPN player/team imagery with designed fallbacks

## Information hierarchy

1. Player or decision
2. Matchup and availability
3. Position-specific workload signal
4. Supporting evidence and provenance

The UI avoids KPI tiles, roster-card grids, oversized heroes, and repeated bordered containers. Player rows are the primary visual unit.

## Shell and pages

- **Desktop:** persistent left navigation, sticky compact league/week header, dense content column.
- **Mobile:** the same navigation becomes a fixed four-item bottom bar; rows retain player imagery and collapse secondary metrics.
- **Overview:** editorial weekly briefing answering what changed, what needs attention, and what to do next.
- **My Team:** actual league slots followed by the bench; lineup recommendations appear next to affected players.
- **Waivers:** position filter, ranked Top Adds, and a quieter Watchlist.
- **Ask FanEdge:** first-class explanation surface with honest capability boundaries and existing strategy generation.

## Visual system

Deep navy surfaces replace flat black. FanEdge lime remains the action color; NFL colors appear only as small identity accents. Borders separate rows sparingly. Typography is compact and sports-editorial, with stronger player names and calmer metadata.

## Reference principles

- Sleeper foregrounds roster/start percentages and weekly lineup decisions.
- ESPN keeps team management, lineup changes, free-agent pickups, and personalized analysis close together.
- Yahoo personalizes fantasy news and keeps add/drop actions central.

These are product principles only; FanEdge retains its own visual identity and intelligence-first hierarchy.
