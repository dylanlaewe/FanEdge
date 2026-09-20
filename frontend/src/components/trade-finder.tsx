"use client";
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeftRight, LockKeyhole, Search, Sparkles } from "lucide-react";
import { request, title } from "@/lib/api";
import type { Player } from "@/lib/types";
import type {
  TradeAnalysis,
  TradeIdea,
  TradeImpact,
  TradeOverview,
  TradeSearch,
} from "@/lib/trades";
import { useFanEdge, useLeague } from "./providers";
import { EmptyState, PlayerAvatar, PlayerChip, Skeleton } from "./primitives";

function Impact({
  label,
  impact,
  reasons,
  players,
}: {
  label: string;
  impact: TradeImpact;
  reasons: string[];
  players: Record<string, Player>;
}) {
  const name = (id: string | null) =>
    id ? players[id]?.name || "Player unavailable" : "Empty slot";
  return (
    <section className="trade-impact">
      <h4>
        {label} <span className="badge blue">{title(impact.label)}</span>
      </h4>
      {reasons.map((reason) => (
        <p key={reason}>{reason}</p>
      ))}
      <details>
        <summary>Lineup & depth changes</summary>
        {impact.changes.length ? (
          impact.changes.map((change) => (
            <p className="trade-change" key={change.slot}>
              <b>{change.slot}</b>
              <span>
                {name(change.before)} <span aria-label="becomes">→</span>{" "}
                {name(change.after)}
              </span>
            </p>
          ))
        ) : (
          <p>Starting assignment stays unchanged.</p>
        )}
        {Object.keys(impact.before).map((pos) => (
          <div className="trade-depth" key={pos}>
            <b>{pos}</b>
            <span>
              {title(impact.before[pos].status)} →{" "}
              {title(impact.after[pos].status)}
            </span>
            <small>
              {impact.before[pos].usable_depth} →{" "}
              {impact.after[pos].usable_depth} usable players
            </small>
          </div>
        ))}
        <p className="source-note">
          Evidence-score change: {impact.lineup_delta > 0 ? "+" : ""}
          {impact.lineup_delta.toFixed(1)}. This is not projected fantasy
          points.
        </p>
      </details>
      {!!impact.required_drops.length && (
        <p className="trade-warning">
          Roster space required: {impact.required_drops.map(name).join(", ")}.
          Review this conditional cut first.
        </p>
      )}
    </section>
  );
}

export function TradeIdeaCard({
  idea,
  players,
  onAnalyze,
  onVariation,
  onProtect,
  onView,
}: {
  idea: TradeIdea;
  players: Record<string, Player>;
  onAnalyze?: () => void;
  onVariation?: () => void;
  onProtect?: (id: string) => void;
  onView?: () => void;
}) {
  return (
    <article className="trade-idea">
      <header>
        <span className="eyebrow">
          TRADE IDEA · {idea.outgoing.length} FOR {idea.incoming.length}
        </span>
        <span
          className={`badge ${idea.fit === "QUESTIONABLE_FIT" ? "warning" : "lime"}`}
        >
          {title(idea.fit)}
        </span>
      </header>
      <div className="trade-exchange">
        <section>
          <h3>You send</h3>
          {idea.outgoing.map(
            (id) =>
              players[id] && (
                <div className="trade-asset" key={id}>
                  <PlayerChip player={players[id]} />
                  {onProtect && (
                    <button
                      className="icon-button"
                      aria-label={`Protect ${players[id].name}`}
                      onClick={() => onProtect(id)}
                    >
                      <LockKeyhole size={14} />
                    </button>
                  )}
                </div>
              ),
          )}
        </section>
        <ArrowLeftRight className="trade-arrows" aria-hidden="true" size={24} />
        <section>
          <h3>
            <span>{idea.partner_name}</span> sends
          </h3>
          {idea.incoming.map(
            (id) => players[id] && <PlayerChip key={id} player={players[id]} />,
          )}
        </section>
      </div>
      <div className="trade-fit">
        <Impact
          label="Why it helps you"
          impact={idea.user_impact}
          reasons={idea.why_you}
          players={players}
        />
        <Impact
          label="Why they might consider it"
          impact={idea.partner_impact}
          reasons={idea.why_them}
          players={players}
        />
      </div>
      <details
        className="trade-evidence"
        onToggle={(event) => {
          if (event.currentTarget.open) onView?.();
        }}
      >
        <summary>What you give up · risks · evidence</summary>
        {idea.give_up.map((reason) => (
          <p key={reason}>{reason}</p>
        ))}
        {idea.risks.map((risk) => (
          <p key={risk}>{risk}</p>
        ))}
        <p>
          Relative evidence-value balance: {Math.round(idea.value_ratio * 100)}{" "}
          / 100. A package consistency check, not an acceptance estimate.
        </p>
      </details>
      <footer>
        <span>
          <Sparkles size={14} /> {title(idea.confidence)} evidence confidence{" "}
          <small>Not the chance they accept</small>
        </span>
        <div>
          {onAnalyze && (
            <button className="secondary-button" onClick={onAnalyze}>
              Analyze trade
            </button>
          )}
          {onVariation && (
            <button className="text-button" onClick={onVariation}>
              Try variation
            </button>
          )}
        </div>
      </footer>
    </article>
  );
}

export function TradeFinder() {
  const {
    account,
    tradePreferences,
    setTradePreferences,
    tradeTarget,
    setTradeTarget,
  } = useFanEdge();
  const { endpoint, data: snapshot } = useLeague();
  const query = useQuery({
    queryKey: [
      "trade-overview",
      account?.username,
      account?.leagueId,
      snapshot?.meta.id,
    ],
    queryFn: () => request<TradeOverview>(endpoint("trades")),
    staleTime: 60_000,
  });
  const [goal, setGoal] = useState("BEST_UPGRADE");
  const [partner, setPartner] = useState("");
  const [result, setResult] = useState<TradeSearch | null>(null);
  const [resultGoal, setResultGoal] = useState("");
  const [analysis, setAnalysis] = useState<TradeAnalysis | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [outgoing, setOutgoing] = useState<string[]>([]);
  const [incoming, setIncoming] = useState<string[]>([]);
  const [manualPartner, setManualPartner] = useState("");
  const [showTeams, setShowTeams] = useState(false);
  const generation = useRef(0);
  useEffect(() => {
    generation.current += 1;
    setResult(null);
    setAnalysis(null);
    setPending(false);
    return () => {
      generation.current += 1;
    };
  }, [snapshot?.meta.id, tradePreferences, tradeTarget]);
  const track = (event: string) =>
    request(endpoint("analytics"), { event }).catch(() => {});
  useEffect(() => {
    void track("TRADE_FINDER_OPENED");
  }, [account?.leagueId]); // scoped entry event
  const data = query.data;
  if (query.isPending) return <Skeleton />;
  if (!data)
    return (
      <EmptyState title="Trade context could not load">
        <button className="secondary-button" onClick={() => query.refetch()}>
          Try again
        </button>
      </EmptyState>
    );
  const mine = data.teams.find((team) => team.roster_id === data.user_team_id)!;
  const others = data.teams.filter(
    (team) => team.roster_id !== data.user_team_id,
  );
  const protectedIds = new Set([
    ...tradePreferences.protected,
    ...(tradePreferences.protect_core
      ? data.default_protected.filter(
          (id) => !tradePreferences.trade_block.includes(id),
        )
      : []),
  ]);
  function protect(id: string) {
    setAnalysis(null);
    setTradePreferences((p) => ({
      ...p,
      protected: [...new Set([...p.protected, id])],
      trade_block: p.trade_block.filter((pid) => pid !== id),
    }));
    void track("TRADE_PLAYER_PROTECTED");
  }
  const options = () => ({
    ...tradePreferences,
    goal,
    target_id: tradeTarget,
    partner_id: partner || null,
  });
  async function find(variation = false, chosenPartner = partner) {
    const requestGeneration = ++generation.current;
    setPending(true);
    setError("");
    setAnalysis(null);
    if (variation) void track("TRADE_VARIATION_REQUESTED");
    try {
      const found = await request<TradeSearch>(endpoint("trades/search"), {
        ...options(),
        partner_id: chosenPartner || null,
        exclude_ids: variation ? result?.ideas.map((i) => i.id) || [] : [],
      });
      if (requestGeneration !== generation.current) return;
      setResult(found);
      setResultGoal(goal);
    } catch (e) {
      if (requestGeneration === generation.current)
        setError((e as Error).message);
    } finally {
      if (requestGeneration === generation.current) setPending(false);
    }
  }
  async function analyze(send: string[], receive: string[]) {
    const requestGeneration = ++generation.current;
    setPending(true);
    setError("");
    try {
      const evaluated = await request<TradeAnalysis>(
        endpoint("trades/analyze"),
        {
          ...options(),
          partner_id: null,
          target_id: null,
          outgoing: send,
          incoming: receive,
        },
      );
      if (requestGeneration !== generation.current) return;
      setAnalysis(evaluated);
    } catch (e) {
      if (requestGeneration === generation.current)
        setError((e as Error).message);
    } finally {
      if (requestGeneration === generation.current) setPending(false);
    }
  }
  return (
    <div className="trade-workspace">
      <div className="trade-intro">
        <div>
          <span className="eyebrow">YOUR LEAGUE IS THE ADVANTAGE</span>
          <h2>Find the fit. Then make your move.</h2>
          <p>
            Discover ideas grounded in all {data.teams.length} rosters—not just
            similar player values.
          </p>
        </div>
        <ArrowLeftRight size={30} />
      </div>
      <div className="trade-controls">
        <label className="section-label">What do you need?</label>
        <div className="filter-pills trade-goals">
          {[
            ["RB", "RB"],
            ["WR", "WR"],
            ["TE", "TE"],
            ["QB", "QB"],
            ["BEST_UPGRADE", "Best upgrade"],
            ["DEPTH", "Add depth"],
          ].map(([value, label]) => (
            <button
              key={value}
              aria-pressed={goal === value}
              onClick={() => {
                setGoal(value);
                void track("TRADE_GOAL_SELECTED");
              }}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="trade-filters">
          <label>
            Target a player
            <select
              aria-label="Trade target"
              value={tradeTarget || ""}
              onChange={(e) => setTradeTarget(e.target.value || null)}
            >
              <option value="">Discover across the league</option>
              {others.map((team) => (
                <optgroup label={team.team_name} key={team.roster_id}>
                  {team.player_ids
                    .filter((id) =>
                      ["QB", "RB", "WR", "TE"].includes(
                        data.players[id]?.position,
                      ),
                    )
                    .map((id) => (
                      <option value={id} key={id}>
                        {data.players[id]?.name} · {data.players[id]?.position}
                      </option>
                    ))}
                </optgroup>
              ))}
            </select>
          </label>
          <label>
            Partner
            <select
              aria-label="Trade partner"
              value={partner}
              onChange={(e) => setPartner(e.target.value)}
            >
              <option value="">All complementary teams</option>
              {others.map((team) => (
                <option value={team.roster_id} key={team.roster_id}>
                  {team.team_name}
                </option>
              ))}
            </select>
          </label>
        </div>
        <details className="trade-protections">
          <summary>
            <LockKeyhole size={15} /> Protect / willing to move{" "}
            <span>
              {protectedIds.size} protected ·{" "}
              {tradePreferences.trade_block.length} on block
            </span>
          </summary>
          <label className="trade-core">
            <input
              type="checkbox"
              checked={tradePreferences.protect_core}
              onChange={(e) =>
                setTradePreferences((p) => ({
                  ...p,
                  protect_core: e.target.checked,
                }))
              }
            />
            Protect high-importance starters by default. Marking one willing to
            move overrides only its automatic lock.
          </label>
          <div className="trade-preferences">
            {mine.player_ids
              .filter((id) =>
                ["QB", "RB", "WR", "TE"].includes(data.players[id]?.position),
              )
              .map((id) => (
                <div className="trade-preference" key={id}>
                  <PlayerAvatar player={data.players[id]} />
                  <span>
                    <b>{data.players[id].name}</b>
                    <small>{data.players[id].position}</small>
                  </span>
                  <button
                    aria-label={`Protect ${data.players[id].name}`}
                    aria-pressed={protectedIds.has(id)}
                    onClick={() =>
                      protectedIds.has(id)
                        ? setTradePreferences((p) => ({
                            ...p,
                            protected: p.protected.filter((v) => v !== id),
                            trade_block:
                              data.default_protected.includes(id) &&
                              p.protect_core
                                ? [...new Set([...p.trade_block, id])]
                                : p.trade_block,
                          }))
                        : protect(id)
                    }
                  >
                    <LockKeyhole size={14} />
                    Protect
                  </button>
                  <button
                    aria-pressed={tradePreferences.trade_block.includes(id)}
                    onClick={() =>
                      setTradePreferences((p) => ({
                        ...p,
                        trade_block: p.trade_block.includes(id)
                          ? p.trade_block.filter((v) => v !== id)
                          : [...p.trade_block, id],
                      }))
                    }
                  >
                    Willing to move
                  </button>
                </div>
              ))}
          </div>
        </details>
        <div className="trade-submit">
          <p>
            No messages or trade offers are sent. Every idea must help both
            rosters.
          </p>
          <button
            className="primary-button"
            disabled={pending}
            onClick={() => find()}
          >
            <Search size={16} />
            {pending ? "Simulating both rosters…" : "Find trades"}
          </button>
        </div>
      </div>
      {error && (
        <p role="alert" className="trade-warning">
          {error}
        </p>
      )}
      <div className="trade-partners">
        <div className="section-heading">
          <h3>Best trade partners</h3>
          <button
            className="text-button"
            onClick={() => setShowTeams(!showTeams)}
          >
            {showTeams ? "Hide roster profiles" : "Browse all roster profiles"}
          </button>
        </div>
        <div className="trade-partner-list">
          {data.partners.slice(0, 4).map((team) => (
            <button
              key={team.roster_id}
              aria-pressed={partner === team.roster_id}
              onClick={() => {
                setPartner(team.roster_id);
                void find(false, team.roster_id);
              }}
            >
              <strong>{team.team_name}</strong>
              <span>Needs {team.needs.join(" · ") || "balanced"}</span>
              <small>{team.reasons.join(" ")}</small>
            </button>
          ))}
        </div>
      </div>
      {showTeams && (
        <div className="trade-team-list">
          {data.teams.map((team) => (
            <details key={team.roster_id}>
              <summary>
                {team.team_name}
                {team.roster_id === data.user_team_id ? " · You" : ""}
              </summary>
              <div className="trade-position-list">
                {Object.values(team.positions).map((pos) => (
                  <p key={pos.position}>
                    <b>
                      {pos.position} · {title(pos.status)}
                    </b>
                    <span>{pos.reason}</span>
                  </p>
                ))}
              </div>
              <div className="trade-team-players">
                {team.player_ids.map(
                  (id) =>
                    data.players[id] && (
                      <PlayerChip key={id} player={data.players[id]} />
                    ),
                )}
              </div>
            </details>
          ))}
        </div>
      )}
      <details className="trade-manual">
        <summary>Already have a package? Analyze your own</summary>
        <div className="trade-filters">
          <label>
            I send (up to two)
            <select
              aria-label="Players I send"
              multiple
              value={outgoing}
              onChange={(e) =>
                setOutgoing(
                  [...e.target.selectedOptions].map((o) => o.value).slice(0, 2),
                )
              }
            >
              {mine.player_ids
                .filter((id) =>
                  ["QB", "RB", "WR", "TE"].includes(data.players[id]?.position),
                )
                .map((id) => (
                  <option key={id} value={id}>
                    {data.players[id].name}
                    {protectedIds.has(id) ? " · protected" : ""}
                  </option>
                ))}
            </select>
          </label>
          <div>
            <label>
              Other roster
              <select
                aria-label="Manual trade partner"
                value={manualPartner}
                onChange={(e) => {
                  setManualPartner(e.target.value);
                  setIncoming([]);
                }}
              >
                <option value="">Choose a roster</option>
                {others.map((t) => (
                  <option key={t.roster_id} value={t.roster_id}>
                    {t.team_name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              I receive (up to two)
              <select
                multiple
                aria-label="Players I receive"
                value={incoming}
                onChange={(e) =>
                  setIncoming(
                    [...e.target.selectedOptions]
                      .map((o) => o.value)
                      .slice(0, 2),
                  )
                }
              >
                {others
                  .find((t) => t.roster_id === manualPartner)
                  ?.player_ids.filter((id) =>
                    ["QB", "RB", "WR", "TE"].includes(
                      data.players[id]?.position,
                    ),
                  )
                  .map((id) => (
                    <option key={id} value={id}>
                      {data.players[id].name}
                    </option>
                  ))}
              </select>
            </label>
          </div>
        </div>
        <button
          className="secondary-button"
          disabled={pending || !outgoing.length || !incoming.length}
          onClick={() => analyze(outgoing, incoming)}
        >
          Analyze selected package
        </button>
      </details>
      {analysis && (
        <section className="trade-analysis" aria-live="polite">
          <h3>
            {analysis.accepted
              ? "Package clears the two-sided filters"
              : "This package needs a rethink"}
          </h3>
          {analysis.rejections.map((reason) => (
            <p className="trade-warning" key={reason}>
              {reason}
            </p>
          ))}
          {analysis.idea && (
            <TradeIdeaCard idea={analysis.idea} players={analysis.players} />
          )}
        </section>
      )}
      <section aria-live="polite" className="trade-results">
        {result && (
          <p className="source-note">
            Results for {title(resultGoal)}. Find trades applies your latest
            controls; protected players are always hidden immediately.
          </p>
        )}
        <div className="section-heading">
          <h3>
            {result
              ? `${result.ideas.filter((i) => !i.outgoing.some((id) => protectedIds.has(id))).length} ideas worth exploring`
              : "Your next move starts with fit"}
          </h3>
          {result && (
            <small>
              {result.tested} candidates checked ·{" "}
              {result.elapsed_ms.toFixed(0)} ms engine time
            </small>
          )}
        </div>
        {result ? (
          result.ideas.filter(
            (i) => !i.outgoing.some((id) => protectedIds.has(id)),
          ).length ? (
            result.ideas
              .filter((i) => !i.outgoing.some((id) => protectedIds.has(id)))
              .map((idea) => (
                <TradeIdeaCard
                  key={idea.id}
                  idea={idea}
                  players={result.players}
                  onAnalyze={() => analyze(idea.outgoing, idea.incoming)}
                  onVariation={() => find(true)}
                  onProtect={protect}
                  onView={() => {
                    void track("TRADE_VIEWED");
                  }}
                />
              ))
          ) : (
            <EmptyState title="No trade clears the bar">
              FanEdge didn’t find a trade it can support with enough evidence
              right now. Explore the complementary partners above, target a
              specific player, or review Waivers and Watchlist. Changing a
              protection is optional—not a reason to weaken your roster.
            </EmptyState>
          )
        ) : (
          <p className="source-note">
            Choose a goal, protect your core, then search. We compare actual
            starting slots, usable depth, and league replacement options on both
            sides.
          </p>
        )}
      </section>
      <p className="source-note">
        Current-season evidence only. No dynasty picks, acceptance predictions,
        or automatic transactions. {data.warnings.join(" ")}
      </p>
    </div>
  );
}
