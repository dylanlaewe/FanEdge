"use client";
import Link from "next/link";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  ArrowUp,
  ArrowUpRight,
  Check,
  ChevronDown,
  CircleAlert,
  Home as HomeIcon,
  Layers3,
  LogOut,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  Users,
  Zap,
} from "lucide-react";
import { request, title } from "@/lib/api";
import type { Answer, Connection, League, Snapshot } from "@/lib/types";
import { useFanEdge, useLeague } from "./providers";
import {
  Brand,
  EmptyState,
  EvidencePanel,
  InsightCard,
  PlayerChip,
  PlayerDrawer,
  PlayerRow,
  RecommendationCard,
  Skeleton,
} from "./primitives";

export type View = "home" | "team" | "market" | "ask";
const navigation = [
  { view: "home", label: "Home", icon: HomeIcon },
  { view: "team", label: "Team", icon: Users },
  { view: "market", label: "Market", icon: TrendingUp },
  { view: "ask", label: "Ask FanEdge", icon: Sparkles },
] as const;

export function LeagueSwitcher({ leagues }: { leagues: League[] }) {
  const { account, selectLeague } = useFanEdge();
  return (
    <div className="league-switcher">
      <span className="eyebrow">Your league</span>
      <label>
        <span className="league-glyph">
          <Layers3 size={18} />
        </span>
        <select
          aria-label="Select league"
          value={account?.leagueId || ""}
          onChange={(e) => selectLeague(e.target.value)}
        >
          {leagues.map((l) => (
            <option key={l.id} value={l.id}>
              {l.name}
            </option>
          ))}
        </select>
        <ChevronDown size={14} />
      </label>
    </div>
  );
}
export function Sidebar({ view, leagues }: { view: View; leagues: League[] }) {
  const { disconnect, account } = useFanEdge();
  return (
    <aside className="sidebar">
      <Link href="/home" aria-label="FanEdge home">
        <Brand />
      </Link>
      <span className="sidebar-caption">A sharper way to play.</span>
      <nav aria-label="Primary navigation">
        {navigation.map((item) => (
          <Link
            href={`/${item.view}`}
            key={item.view}
            aria-current={view === item.view ? "page" : undefined}
          >
            <item.icon size={19} />
            <span>{item.label}</span>
            {item.view === "ask" && <span className="ai-pill">AI</span>}
          </Link>
        ))}
      </nav>
      <div className="sidebar-bottom">
        <div className="sidebar-tip">
          <Zap size={18} />
          <strong>Your league. Your edge.</strong>
          <p>Every decision starts with the team you actually manage.</p>
        </div>
        <LeagueSwitcher leagues={leagues} />
        <button className="account-button" onClick={disconnect}>
          <span className="account-initial">
            {account?.username[0]?.toUpperCase()}
          </span>
          <span>
            {account?.username}
            <small>Connected to Sleeper</small>
          </span>
          <LogOut size={15} />
        </button>
      </div>
    </aside>
  );
}
export function MobileNav({ view }: { view: View }) {
  return (
    <nav className="mobile-nav" aria-label="Mobile navigation">
      {navigation.map((item) => (
        <Link
          href={`/${item.view}`}
          key={item.view}
          aria-current={view === item.view ? "page" : undefined}
        >
          <item.icon size={20} />
          <span>{item.view === "ask" ? "AI" : item.label}</span>
        </Link>
      ))}
    </nav>
  );
}

function Connect() {
  const { connect } = useFanEdge();
  const [username, setUsername] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const data = await request<Connection>(
        `/api/users/${encodeURIComponent(username.trim())}/leagues`,
      );
      if (!data.leagues.length)
        throw new Error("No NFL leagues were found for the current season.");
      connect(data);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }
  return (
    <main className="connect-page">
      <div className="connect-top">
        <Brand />
        <span>Fantasy football, with an edge.</span>
      </div>
      <div className="connect-grid">
        <section className="connect-copy">
          <span className="eyebrow">
            <span className="signal-dot" /> YOUR FANTASY FRONT OFFICE
          </span>
          <h1>
            Know your team.
            <br />
            See your next move<span>.</span>
          </h1>
          <p>
            Your players, your league, and the intelligence to make every week
            count.
          </p>
          <div className="connect-features">
            <span>
              <Users size={18} /> Your real roster
            </span>
            <span>
              <TrendingUp size={18} /> League-aware opportunities
            </span>
            <span>
              <Sparkles size={18} /> A copilot with context
            </span>
          </div>
          <div className="field-lines" aria-hidden="true">
            <i />
            <i />
            <i />
            <span>FANEDGE</span>
            <i />
            <i />
            <i />
          </div>
        </section>
        <section className="connect-panel">
          <span className="connect-symbol">
            <Zap size={28} />
          </span>
          <h2>Bring your league.</h2>
          <p>Connect your Sleeper username to get your weekly edge.</p>
          <form onSubmit={submit}>
            <label htmlFor="username">Sleeper username</label>
            <input
              id="username"
              autoComplete="username"
              placeholder="Your Sleeper username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              maxLength={100}
            />
            <button
              className="primary-button"
              disabled={loading || !username.trim()}
            >
              {loading ? (
                <>
                  <RefreshCw className="spin" size={17} /> Finding your leagues…
                </>
              ) : (
                <>
                  Connect my team <ArrowRight size={18} />
                </>
              )}
            </button>
          </form>
          {error && (
            <p role="alert" className="error-message">
              {error}
            </p>
          )}
          <div className="connect-trust">
            <ShieldCheck size={15} /> Public, read-only access. No password
            needed.
          </div>
          <p className="connect-footnote">
            You stay in control. FanEdge never changes your lineup or makes
            transactions.
          </p>
        </section>
      </div>
    </main>
  );
}

export function AppShell({
  view,
  data,
  children,
  refreshing,
  onRefresh,
}: {
  view: View;
  data?: Snapshot;
  children: ReactNode;
  refreshing: boolean;
  onRefresh: () => void;
}) {
  const { account } = useFanEdge();
  const leagues = useQuery({
    queryKey: ["leagues", account?.username],
    queryFn: () =>
      request<Connection>(
        `/api/users/${encodeURIComponent(account!.username)}/leagues`,
      ),
    enabled: !!account,
    staleTime: 900_000,
  });
  const options = leagues.data?.leagues || (data ? [data.league] : []);
  return (
    <div className="app-shell">
      <Sidebar view={view} leagues={options} />
      <div className="workspace">
        <header className="topbar">
          <div className="mobile-brand">
            <Brand />
          </div>
          <div className="team-context">
            <span className="week-tag">WEEK {data?.meta.week || "—"}</span>
            <span>
              <strong>{data?.league.team_name || "Your team"}</strong>
              <small>
                {data?.league.name || "Preparing your league"} ·{" "}
                {data?.league.scoring || ""}
              </small>
            </span>
          </div>
          <div className="topbar-actions">
            <span className="sync-state">
              <span
                className={`signal-dot ${data?.meta.stale ? "stale" : ""}`}
              />
              {refreshing
                ? "Updating…"
                : data?.meta.stale
                  ? "Last saved snapshot"
                  : "League connected"}
            </span>
            <button
              className="icon-button"
              onClick={onRefresh}
              disabled={refreshing}
              aria-label="Refresh league data"
            >
              <RefreshCw size={17} className={refreshing ? "spin" : ""} />
            </button>
          </div>
        </header>
        <div className="mobile-league">
          <LeagueSwitcher leagues={options} />
        </div>
        <main className={`main-content ${view === "ask" ? "chat-main" : ""}`}>
          {children}
        </main>
      </div>
      <MobileNav view={view} />
      <PlayerDrawer />
    </div>
  );
}

export function Dashboard({ view }: { view: View }) {
  const { account, ready } = useFanEdge();
  const query = useLeague();
  const [refreshing, setRefreshing] = useState(false);
  const [actionError, setActionError] = useState("");
  if (!ready)
    return (
      <div className="boot">
        <Brand />
        <Skeleton />
      </div>
    );
  if (!account) return <Connect />;
  async function refresh() {
    setRefreshing(true);
    setActionError("");
    try {
      await request(query.endpoint("refresh"), {});
      await query.refetch();
    } catch (e) {
      setActionError((e as Error).message);
    } finally {
      setRefreshing(false);
    }
  }
  async function feedback(id: string, status: string) {
    try {
      await request(query.endpoint(`events/${id}/feedback`), { status });
      await query.refetch();
    } catch (e) {
      setActionError((e as Error).message);
    }
  }
  return (
    <AppShell
      view={view}
      data={query.data}
      refreshing={refreshing || !!query.data?.meta.refreshing}
      onRefresh={refresh}
    >
      {(actionError || query.data?.meta.refresh_error) && (
        <div className="error-message" role="alert">
          {actionError || query.data?.meta.refresh_error}
        </div>
      )}
      {query.isError && !query.data ? (
        <EmptyState title="Your league could not load">
          <span>{query.error.message}</span>
          <button className="secondary-button" onClick={() => query.refetch()}>
            Try again
          </button>
        </EmptyState>
      ) : !query.data ? (
        <>
          <div className="page-heading">
            <span className="eyebrow">BUILDING YOUR EDGE</span>
            <h1>Getting your team ready</h1>
            <p>Connecting the roster, matchups, and current league evidence.</p>
          </div>
          <Skeleton />
        </>
      ) : (
        <>
          {query.data.meta.warnings.length > 0 && (
            <details className="data-notice">
              <summary>
                <CircleAlert size={15} /> Some evidence is unavailable
              </summary>
              {query.data.meta.warnings.map((w) => (
                <p key={w}>{w}</p>
              ))}
            </details>
          )}
          {view === "home" && <Home data={query.data} feedback={feedback} />}
          {view === "team" && <Team data={query.data} />}
          {view === "market" && <Market data={query.data} />}
          {view === "ask" && (
            <Ask
              key={query.data.league.id}
              data={query.data}
              endpoint={query.endpoint}
            />
          )}
        </>
      )}
    </AppShell>
  );
}

function Home({
  data,
  feedback,
}: {
  data: Snapshot;
  feedback: (id: string, status: string) => void;
}) {
  const [history, setHistory] = useState(false);
  const changes = data.events.filter((e) => e.lifecycle !== "ACTIVE");
  return (
    <>
      <div className="page-heading horizontal">
        <div>
          <span className="eyebrow">YOUR WEEK, IN FOCUS</span>
          <h1>Your edge</h1>
          <p>The situations that matter to your team.</p>
        </div>
        <button
          className="secondary-button"
          onClick={() => setHistory(!history)}
        >
          <ClockIcon />
          {history ? "Your edge" : "Decision journal"}
        </button>
      </div>
      <div className="home-layout">
        <section>
          <div className="feed-summary">
            <span>
              <span className="live-dot" />
              {data.events.length} situations worth your attention
            </span>
            <small>
              {changes.length
                ? `${changes.length} changed since your last check`
                : "No new material changes"}
            </small>
          </div>
          {history ? (
            <div className="journal">
              <h2>Decision journal</h2>
              {data.history.length ? (
                data.history.map((h, i) => (
                  <article key={`${h.id}-${i}`}>
                    <span className="eyebrow">
                      WEEK {h.week} · {title(h.lifecycle)}
                    </span>
                    <h3>{h.player_name || title(h.type)}</h3>
                    <p>
                      {title(h.action)}
                      {h.feedback && ` · ${title(h.feedback)}`}
                    </p>
                    {h.outcome && <p>{title(h.outcome)}</p>}
                    {h.recommended_points != null &&
                      h.alternative_points != null && (
                        <p>
                          Completed points: recommended{" "}
                          {h.recommended_points.toFixed(1)} · alternative{" "}
                          {h.alternative_points.toFixed(1)}
                        </p>
                      )}
                    <EvidencePanel
                      evidence={h.evidence.map((detail) => ({
                        label: "Decision evidence",
                        detail,
                        source: "FanEdge memory",
                      }))}
                    />
                  </article>
                ))
              ) : (
                <EmptyState title="Your journal starts here">
                  Decisions will appear as FanEdge builds your weekly history.
                </EmptyState>
              )}
            </div>
          ) : data.events.length ? (
            data.events.map((event) => (
              <InsightCard key={event.id} event={event} onFeedback={feedback} />
            ))
          ) : (
            <EmptyState title="Your plan holds">
              No evidence-backed change needs your attention right now.
            </EmptyState>
          )}
        </section>
        <aside className="right-rail">
          <section className="week-plan">
            <span className="section-label">
              <Zap size={16} /> The game plan
            </span>
            <h2>
              Make your next move
              <br />
              with confidence.
            </h2>
            <div className="plan-item">
              <Users size={17} />
              <span>
                Lineup decisions
                <small>
                  {data.recommendations.length
                    ? `${data.recommendations.length} comparisons to review`
                    : "No material change needed"}
                </small>
              </span>
              <strong>{data.recommendations.length}</strong>
            </div>
            <div className="plan-item">
              <TrendingUp size={17} />
              <span>
                On your radar<small>Available in your league</small>
              </span>
              <strong>{data.waivers.length}</strong>
            </div>
            <Link className="primary-button" href="/ask">
              Talk it through <Sparkles size={16} />
            </Link>
          </section>
          <section className="rail-roster">
            <span className="section-label">In your lineup</span>
            {data.starters
              .filter((slot) => slot.player)
              .slice(0, 3)
              .map((slot) => (
                <PlayerChip key={slot.id} player={slot.player!} />
              ))}
            <Link href="/team">
              View your whole team <ArrowRight size={14} />
            </Link>
          </section>
          <p className="source-note">
            <ShieldCheck size={14} /> Built from your league and verified
            evidence. Every recommendation has a reason.
          </p>
        </aside>
      </div>
    </>
  );
}
function ClockIcon() {
  return <Layers3 size={15} />;
}

function Team({ data }: { data: Snapshot }) {
  const [showMoves, setShowMoves] = useState(true);
  return (
    <>
      <div className="page-heading horizontal">
        <div>
          <span className="eyebrow">THE ROSTER ROOM</span>
          <h1>Your team</h1>
          <p>
            {data.starters.length} starting slots · {data.bench.length} bench
            players · {data.league.scoring}
          </p>
        </div>
        <button
          className="secondary-button"
          onClick={() => setShowMoves(!showMoves)}
        >
          <ArrowUpRight size={16} />
          {data.recommendations.length} lineup decisions
        </button>
      </div>
      {showMoves && data.recommendations.length > 0 && (
        <div className="recommendation-grid">
          {data.recommendations.map((r) => (
            <RecommendationCard key={r.slot} recommendation={r} />
          ))}
        </div>
      )}
      <div className="roster-section">
        <div className="table-section">
          <h2>Starting lineup</h2>
          <span>Week {data.meta.week}</span>
        </div>
        <div className="table-head">
          <span>Slot</span>
          <span>Player</span>
          <span>Matchup</span>
          <span>Fantasy / G</span>
          <span>Opportunity</span>
          <span>Role</span>
        </div>
        {data.starters.map((slot) =>
          slot.player ? (
            <PlayerRow
              key={slot.id}
              player={slot.player}
              slot={slot.label}
              note={data.recommendations
                .find((r) => r.alternative?.id === slot.player?.id)
                ?.action.replaceAll("_", " ")
                .toLowerCase()}
            />
          ) : (
            <div className="empty-slot" key={slot.id}>
              <span className="slot">{slot.label}</span>Empty starting slot
            </div>
          ),
        )}
      </div>
      <div className="roster-section">
        <div className="table-section">
          <h2>Bench</h2>
          <span>{data.bench.length} players</span>
        </div>
        {data.bench.map((player) => (
          <PlayerRow key={player.id} player={player} slot="BN" />
        ))}
      </div>
      <p className="source-note">
        Fantasy points reflect completed games under your league scoring. Select
        any player for the full evidence.
      </p>
    </>
  );
}

function Market({ data }: { data: Snapshot }) {
  const [tab, setTab] = useState<"WAIVERS" | "WATCHLIST">("WAIVERS");
  const [position, setPosition] = useState("All");
  const [search, setSearch] = useState("");
  const values = data.waivers.filter(
    (w) =>
      w.category === tab &&
      (position === "All" || w.player.position === position) &&
      w.player.name.toLowerCase().includes(search.toLowerCase()),
  );
  return (
    <>
      <div className="page-heading horizontal">
        <div>
          <span className="eyebrow">FIND YOUR NEXT ADVANTAGE</span>
          <h1>The market</h1>
          <p>Available players. Opportunities that fit your league.</p>
        </div>
        <span className="availability-label">
          <Check size={15} /> League ownership verified
        </span>
      </div>
      <div className="market-tabs" role="tablist" aria-label="Market view">
        {(["WAIVERS", "WATCHLIST"] as const).map((value) => (
          <button
            role="tab"
            aria-selected={tab === value}
            key={value}
            onClick={() => setTab(value)}
          >
            {title(value)}
            <span>
              {data.waivers.filter((w) => w.category === value).length}
            </span>
          </button>
        ))}
      </div>
      <div className="market-toolbar">
        <div className="filter-pills" aria-label="Position filter">
          {["All", "QB", "RB", "WR", "TE"].map((p) => (
            <button
              key={p}
              aria-pressed={position === p}
              onClick={() => setPosition(p)}
            >
              {p}
            </button>
          ))}
        </div>
        <label className="player-search">
          <Search size={16} />
          <input
            placeholder="Find a player"
            aria-label="Find a player"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
      </div>
      <div className="market-intro">
        <strong>
          {tab === "WAIVERS"
            ? "Players worth a closer look"
            : "Potential before the production"}
        </strong>
        <span>
          {tab === "WAIVERS"
            ? "Role, usage, and your roster shape the shortlist."
            : "Interesting signals. More evidence needed before a move."}
        </span>
      </div>
      <div className="market-list">
        {values.length ? (
          values.map((w, i) => (
            <article className="market-player" key={w.player.id}>
              <div className="market-rank">
                {String(i + 1).padStart(2, "0")}
              </div>
              <div className="market-player-content">
                <PlayerRow player={w.player} slot={w.player.position} />
                <div className="market-reason">
                  <span className="badge blue">
                    {tab === "WAIVERS" ? "Available" : "Watch"}
                  </span>
                  <p>{w.reasons.join(" · ")}</p>
                </div>
              </div>
            </article>
          ))
        ) : (
          <EmptyState title="No players match this view">
            Try another position or check the other market tab.
          </EmptyState>
        )}
      </div>
    </>
  );
}

function Ask({
  data,
  endpoint,
}: {
  data: Snapshot;
  endpoint: (route: string) => string;
}) {
  const { messages, setMessages } = useFanEdge();
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const bottom = useRef<HTMLDivElement>(null);
  useEffect(() => {
    request(endpoint("analytics"), { event: "ask_fanedge_opened" }).catch(
      () => {},
    );
  }, [data.league.id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, pending]);
  async function send(question: string, suggested = false) {
    if (!question.trim() || pending) return;
    setPending(true);
    setError("");
    setInput("");
    const prior = [...messages].reverse().find((m) => m.role === "assistant");
    setMessages((prev) => [...prev, { role: "user", text: question }]);
    try {
      const answer = await request<Answer>(endpoint("copilot"), {
        question,
        conversation_id:
          prior?.role === "assistant" ? prior.answer.conversation_id : null,
        suggested,
      });
      setMessages((prev) => [...prev, { role: "assistant", answer }]);
    } catch (e) {
      setError((e as Error).message);
      setInput(question);
    } finally {
      setPending(false);
    }
  }
  return (
    <div className="chat-workspace">
      <div className="chat-title">
        <span className="ai-symbol">
          <Sparkles size={19} />
        </span>
        <div>
          <h1>Ask FanEdge</h1>
          <p>Your league. Your players. Let’s find your next move.</p>
        </div>
        <span className="badge lime">Connected</span>
      </div>
      <div className="chat-layout">
        <section className="chat-column">
          <div className="conversation" aria-live="polite">
            {!messages.length && (
              <div className="chat-welcome">
                <span className="eyebrow">
                  YOUR PERSONAL FANTASY FRONT OFFICE
                </span>
                <h2>What’s the move?</h2>
                <p>
                  I know your {data.league.scoring} roster, who’s actually
                  available, and the evidence behind your weekly decisions.
                </p>
                <div className="suggestion-grid">
                  {data.suggestions.map((prompt) => (
                    <button key={prompt} onClick={() => send(prompt, true)}>
                      <span>{prompt}</span>
                      <ArrowUpRight size={17} />
                    </button>
                  ))}
                </div>
                <div className="context-strip">
                  <ShieldCheck size={16} />
                  <span>
                    {data.starters.filter((s) => s.player).length +
                      data.bench.length}{" "}
                    rostered players · {data.events.length} current situations ·
                    Week {data.meta.week}
                  </span>
                </div>
              </div>
            )}
            {messages.map((m, i) =>
              m.role === "user" ? (
                <div className="user-message" key={i}>
                  {m.text}
                </div>
              ) : (
                <article className="assistant-message" key={i}>
                  <span className="assistant-label">
                    <Sparkles size={15} /> FANEDGE
                  </span>
                  {m.answer.hypothetical && (
                    <span className="badge warning">Hypothetical</span>
                  )}
                  <h3>{m.answer.answer}</h3>
                  {m.answer.model_text && (
                    <p className="model-phrasing">{m.answer.model_text}</p>
                  )}
                  {m.answer.why.length > 0 && (
                    <ul>
                      {m.answer.why.map((reason, j) => (
                        <li key={j}>{reason}</li>
                      ))}
                    </ul>
                  )}
                  {m.answer.action && (
                    <div className="answer-action">
                      <ArrowUpRight size={16} />
                      <strong>{title(m.answer.action)}</strong>
                      <span>{title(m.answer.confidence)} confidence</span>
                    </div>
                  )}
                  {m.answer.watch_for && (
                    <p className="watch-for">
                      <strong>Watch for</strong> {m.answer.watch_for}
                    </p>
                  )}
                  {m.answer.players.length > 0 && (
                    <div className="answer-players">
                      {m.answer.players.slice(0, 2).map((p) => (
                        <PlayerChip key={p.id} player={p} />
                      ))}
                    </div>
                  )}
                  {m.answer.evidence.length > 0 && (
                    <EvidencePanel
                      evidence={m.answer.evidence}
                      onOpen={() => {
                        request(endpoint("analytics"), {
                          event: "copilot_evidence_opened",
                        }).catch(() => {});
                      }}
                    />
                  )}
                  {m.answer.provider_fallback && (
                    <small className="muted-text">
                      Answer preserved from verified league evidence.
                    </small>
                  )}
                </article>
              ),
            )}
            {pending && (
              <div className="thinking">
                <Sparkles size={16} />
                <span>Checking your league evidence</span>
                <i />
                <i />
                <i />
              </div>
            )}
            {error && (
              <p className="error-message" role="alert">
                {error}
              </p>
            )}
            <div ref={bottom} />
          </div>
          <form
            className="chat-composer"
            onSubmit={(e) => {
              e.preventDefault();
              send(input);
            }}
          >
            <div>
              <textarea
                aria-label="Ask about your team"
                placeholder="Ask about your team…"
                value={input}
                rows={1}
                maxLength={500}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    send(input);
                  }
                }}
              />
              <button
                className="send-button"
                disabled={pending || !input.trim()}
                aria-label="Send message"
              >
                <ArrowUp size={19} />
              </button>
            </div>
            <small>
              Grounded in your league. Missing evidence stays unknown.
            </small>
          </form>
        </section>
        <aside className="chat-context">
          <span className="section-label">
            <Layers3 size={15} /> In context
          </span>
          <div className="context-league">
            <span className="week-tag">WEEK {data.meta.week}</span>
            <h3>{data.league.name}</h3>
            <p>
              {data.league.scoring} · {data.league.team_name}
            </p>
          </div>
          <span className="eyebrow">WORTH TALKING ABOUT</span>
          {data.events
            .filter((e) => e.player)
            .slice(0, 3)
            .map((e) => (
              <div className="context-event" key={e.id}>
                <PlayerChip player={e.player!} />
                <span>
                  {title(e.action)} · {title(e.confidence)}
                </span>
              </div>
            ))}
          <p className="source-note">
            You can ask why, compare players, or explore a hypothetical. Your
            actual roster is never changed.
          </p>
        </aside>
      </div>
    </div>
  );
}
