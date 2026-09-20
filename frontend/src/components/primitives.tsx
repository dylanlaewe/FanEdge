"use client";
import { Helpful, useBetaEvent } from "./beta";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowUpRight,
  Check,
  ChevronRight,
  CircleHelp,
  Clock3,
  ShieldCheck,
  X,
} from "lucide-react";
import type {
  Evidence,
  Insight,
  Player,
  Recommendation,
  Team,
} from "@/lib/types";
import { title } from "@/lib/api";
import { useFanEdge } from "./providers";

export function Brand() {
  return (
    <span className="brand">
      <span className="brand-mark" aria-hidden="true">
        F<span />
      </span>
      fanedge<span className="brand-dot">.</span>
    </span>
  );
}
export function PlayerAvatar({
  player,
  large = false,
}: {
  player: Player;
  large?: boolean;
}) {
  const [failed, setFailed] = useState(false);
  return (
    <span
      className={`avatar ${large ? "large" : ""}`}
      style={{
        background: `linear-gradient(145deg, ${player.team.color}70, #242d3c)`,
      }}
    >
      <span aria-hidden="true">
        {player.name
          .split(" ")
          .slice(0, 2)
          .map((s) => s[0])
          .join("")}
      </span>
      {player.image_url && !failed && (
        <img
          src={player.image_url}
          alt=""
          loading="lazy"
          onError={() => setFailed(true)}
        />
      )}
    </span>
  );
}
export function TeamLogo({ team }: { team: Team }) {
  const [failed, setFailed] = useState(false);
  return (
    <span className="team-logo" title={team.display_name}>
      {team.logo_url && !failed ? (
        <img
          src={team.logo_url}
          alt=""
          loading="lazy"
          onError={() => setFailed(true)}
        />
      ) : null}
      <span>{team.abbreviation}</span>
    </span>
  );
}
export function StatusBadge({ status }: { status: string }) {
  if (status === "NO DESIGNATION") return null;
  const severity = /OUT|IR|DOUBTFUL/.test(status)
    ? "danger"
    : /QUESTIONABLE/.test(status)
      ? "warning"
      : "muted";
  return <span className={`badge ${severity}`}>{title(status)}</span>;
}
export function RoleBadge({ role }: { role: string }) {
  return (
    <span
      className={`badge ${["FEATURED", "EMERGING"].includes(role) ? "lime" : "muted"}`}
    >
      {title(role)}
    </span>
  );
}
export function Metric({
  label,
  value,
  unit = "",
}: {
  label: string;
  value: number | null;
  unit?: string;
}) {
  return (
    <span className="metric">
      <strong>
        {value === null
          ? "—"
          : unit === "%"
            ? Math.round(value)
            : value.toFixed(1)}
        {value !== null ? unit : ""}
      </strong>
      <small>{label}</small>
    </span>
  );
}
export function Matchup({ player }: { player: Player }) {
  const match = player.matchup;
  const kickoff = match.kickoff
    ? new Intl.DateTimeFormat("en-US", {
        weekday: "short",
        hour: "numeric",
        minute: "2-digit",
        timeZone: "America/New_York",
        timeZoneName: "short",
      }).format(new Date(match.kickoff))
    : "Time unconfirmed";
  return (
    <span className="matchup">
      {match.opponent ? (
        <span>
          {match.venue === "home" ? "vs" : "@"}{" "}
          <TeamLogo team={match.opponent} />
        </span>
      ) : (
        <span>
          {match.schedule_status === "BYE" ? "Bye week" : "Matchup unknown"}
        </span>
      )}
      <small>{kickoff}</small>
    </span>
  );
}
export function PlayerChip({ player }: { player: Player }) {
  const { selectPlayer } = useFanEdge();
  return (
    <button className="player-chip" onClick={() => selectPlayer(player)}>
      <PlayerAvatar player={player} />
      <span>
        <strong>{player.name}</strong>
        <small>
          {player.position} · {player.team.abbreviation}
        </small>
      </span>
      <ChevronRight size={15} />
    </button>
  );
}
export function PlayerRow({
  player,
  slot,
  note,
}: {
  player: Player;
  slot: string;
  note?: string;
}) {
  const { selectPlayer } = useFanEdge();
  return (
    <button
      className="player-row"
      onClick={() => selectPlayer(player)}
      aria-label={`View ${player.name}`}
    >
      <span className={`slot ${player.position.toLowerCase()}`}>{slot}</span>
      <span className="identity">
        <PlayerAvatar player={player} />
        <span>
          <strong>{player.name}</strong>
          <span className="subline">
            {player.position} · {player.team.abbreviation}{" "}
            <StatusBadge status={player.status} />
          </span>
          {note && <small className="row-note">{note}</small>}
        </span>
      </span>
      <Matchup player={player} />
      <Metric {...player.metrics[0]} />
      <span className="workload">
        {player.metrics[1] && <Metric {...player.metrics[1]} />}
      </span>
      <span className="row-role">
        <RoleBadge role={player.role} />
      </span>
      <ChevronRight className="row-chevron" size={15} />
    </button>
  );
}
export function EvidencePanel({
  evidence,
  onOpen,
}: {
  evidence: Evidence[];
  onOpen?: () => void;
}) {
  const track = useBetaEvent();
  return (
    <details
      className="evidence"
      onToggle={(e) => {
        if (e.currentTarget.open) {
          onOpen?.();
          track("evidence_opened");
        }
      }}
    >
      <summary>
        <ShieldCheck size={15} /> Evidence <span>{evidence.length}</span>
        <ChevronRight size={14} />
      </summary>
      <div>
        {evidence.length ? (
          evidence.map((item, i) => (
            <div className="evidence-item" key={i}>
              <strong>{item.label}</strong>
              <p>{item.detail}</p>
              <small>{item.source}</small>
              {item.url && (
                <a href={item.url} target="_blank" rel="noreferrer">
                  Read source <ArrowUpRight size={13} />
                </a>
              )}
            </div>
          ))
        ) : (
          <p>No additional evidence supplied.</p>
        )}
      </div>
    </details>
  );
}
export function EmptyState({
  title: label,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="empty-state">
      <CircleHelp size={24} />
      <h3>{label}</h3>
      <p>{children}</p>
    </div>
  );
}
export function Skeleton() {
  return (
    <div
      className="skeleton"
      role="status"
      aria-label="Loading league intelligence"
    >
      <div className="skeleton-title" />
      {[1, 2, 3, 4, 5].map((i) => (
        <div className="skeleton-row" key={i}>
          <i />
          <span />
        </div>
      ))}
      <span className="sr-only">Loading your league intelligence</span>
    </div>
  );
}
export function RecommendationCard({
  recommendation,
}: {
  recommendation: Recommendation;
}) {
  return (
    <article className="recommendation">
      <div className="section-label">
        <ArrowUpRight size={16} /> {title(recommendation.action)}{" "}
        <span>{recommendation.slot}</span>
      </div>
      <div className="comparison">
        <div>
          <small>Move into lineup</small>
          <PlayerChip player={recommendation.player} />
        </div>
        <span className="swap-arrow">⇄</span>
        <div>
          <small>Current starter</small>
          {recommendation.alternative ? (
            <PlayerChip player={recommendation.alternative} />
          ) : (
            <p>Empty slot</p>
          )}
        </div>
      </div>
      <p>{recommendation.reasons.join(" · ")}</p>
      <EvidencePanel evidence={recommendation.evidence} />
      <Helpful
        id={`lineup:${recommendation.slot}:${recommendation.player.id}`}
      />
    </article>
  );
}
const eventTypes: Record<string, { label: string; tone: string }> = {
  LINEUP_OPPORTUNITY: { label: "Lineup move", tone: "lime" },
  INJURY_RISK: { label: "Injury watch", tone: "orange" },
  WAIVER_OPPORTUNITY: { label: "Market opportunity", tone: "blue" },
  BREAKOUT_WATCH: { label: "On the radar", tone: "blue" },
  ROLE_DECLINE: { label: "Role change", tone: "orange" },
  MATCHUP_EDGE: { label: "Matchup edge", tone: "violet" },
  ROSTER_WEAKNESS: { label: "Roster balance", tone: "violet" },
};
export function InsightCard({
  event,
  onFeedback,
}: {
  event: Insight;
  onFeedback: (id: string, status: string) => void;
}) {
  const kind = eventTypes[event.type] || {
    label: title(event.type),
    tone: "blue",
  };
  const { selectPlayer } = useFanEdge();
  return (
    <article className={`insight ${kind.tone}`}>
      <div className="insight-heading">
        <span className="section-label">
          <span className="signal-dot" />
          {kind.label}
        </span>
        <span className="insight-state">
          {event.lifecycle === "ACTIVE" ? "This week" : title(event.lifecycle)}
          {event.news.length > 0 && " · News supported"}
        </span>
      </div>
      <div className="insight-body">
        {event.player && (
          <button
            className="portrait-button"
            onClick={() => selectPlayer(event.player)}
            aria-label={`View ${event.player.name}`}
          >
            <PlayerAvatar player={event.player} large />
          </button>
        )}
        <div className="insight-copy">
          <h3>{event.player?.name || "Your roster"}</h3>
          <p className="insight-meta">
            {event.player
              ? `${event.player.position} · ${event.player.team.display_name}`
              : "League intelligence"}
          </p>
          <p>{event.reasons[0] || title(event.type)}</p>
          {event.reasons[1] && (
            <p className="secondary-reason">{event.reasons[1]}</p>
          )}
        </div>
        <span className="insight-action">
          <ArrowUpRight size={16} />
          {title(event.action)}
        </span>
      </div>
      {event.freshness === "UNCERTAIN" && (
        <p className="warning-text">
          Last verified evidence · freshness uncertain
        </p>
      )}
      <div className="insight-footer">
        <span>
          <ShieldCheck size={13} />
          {title(event.confidence)} confidence
        </span>
        <div>
          {[
            ["SAVED", "Save"],
            ["DONE", "Done"],
            ["DISMISSED", "Dismiss"],
          ].map(([status, label]) => (
            <button
              key={status}
              className={event.feedback === status ? "selected" : ""}
              onClick={() => onFeedback(event.id, status)}
            >
              {event.feedback === status && <Check size={12} />}
              {label}
            </button>
          ))}
        </div>
      </div>
      <Helpful id={event.id} />
      <EvidencePanel
        evidence={[
          ...event.evidence,
          ...event.news.map((n) => ({
            label: n.headline,
            detail: n.detail,
            source: `${n.source} · ${title(n.freshness)}`,
            url: n.url,
          })),
        ]}
      />
    </article>
  );
}
export function PlayerDrawer() {
  const track = useBetaEvent();
  const { selectedPlayer: player, selectPlayer, setTradeTarget } = useFanEdge();
  useEffect(() => {
    if (player) track("player_drawer");
  }, [player?.id]);
  const router = useRouter();
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (player && !ref.current?.open) ref.current?.showModal();
    if (!player && ref.current?.open) ref.current.close();
  }, [player]);
  useEffect(() => {
    if (player) {
      const before = document.body.style.overflow;
      document.body.style.overflow = "hidden";
      return () => {
        document.body.style.overflow = before;
      };
    }
  }, [player]);
  return (
    <dialog
      ref={ref}
      className="player-drawer"
      aria-label="Player details"
      onCancel={() => selectPlayer(null)}
      onClick={(e) => {
        if (e.target === e.currentTarget) selectPlayer(null);
      }}
    >
      {player && (
        <div className="drawer-content">
          <div className="drawer-top">
            <span className="section-label">Player intelligence</span>
            <button
              className="icon-button"
              onClick={() => selectPlayer(null)}
              aria-label="Close player details"
            >
              <X size={20} />
            </button>
          </div>
          <div className="drawer-identity">
            <PlayerAvatar player={player} large />
            <span>
              <span className="eyebrow">
                {player.position} · {player.team.display_name}
              </span>
              <h2>{player.name}</h2>
              <RoleBadge role={player.role} />{" "}
              <StatusBadge status={player.status} />
            </span>
          </div>
          <div className="drawer-match">
            <TeamLogo team={player.team} />
            <Matchup player={player} />
            {player.matchup.difficulty && (
              <span className="badge muted">
                {title(player.matchup.difficulty)}
              </span>
            )}
          </div>
          {player.is_opponent && (
            <button
              className="primary-button drawer-trade"
              onClick={() => {
                setTradeTarget(player.id);
                selectPlayer(null);
                router.push("/market");
              }}
            >
              Explore trade for {player.name}
            </button>
          )}
          <div className="drawer-metrics">
            {player.metrics.map((m) => (
              <Metric key={m.label} {...m} />
            ))}
          </div>
          <section className="drawer-section">
            <h3>Role & opportunity</h3>
            <p>
              {player.trend === "INSUFFICIENT DATA"
                ? "More completed games are needed to establish a reliable trend."
                : title(player.trend)}
            </p>
            <small>
              {title(player.confidence)} evidence confidence
              {player.matchup.evidence_basis &&
                ` · ${title(player.matchup.evidence_basis)} matchup basis`}
            </small>
          </section>
          <section className="drawer-section">
            <h3>Latest relevant reporting</h3>
            {player.news.length ? (
              player.news.map((n, i) => (
                <div className="news-item" key={i}>
                  <span className="badge blue">{title(n.freshness)}</span>
                  <p>{n.detail}</p>
                  {n.url && (
                    <a href={n.url} target="_blank" rel="noreferrer">
                      {n.source} <ArrowUpRight size={13} />
                    </a>
                  )}
                </div>
              ))
            ) : (
              <p className="muted-text">
                No resolved current report is attached to this player. Missing
                coverage is unknown.
              </p>
            )}
          </section>
          <EvidencePanel evidence={player.evidence} />
          <div className="drawer-note">
            <Clock3 size={14} /> Completed-game evidence, not a points
            projection.
          </div>
        </div>
      )}
    </dialog>
  );
}
