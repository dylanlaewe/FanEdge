"use client";
import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { request, title } from "@/lib/api";
import { useFanEdge, useLeague } from "./providers";

export function useBetaEvent() {
  const { account } = useFanEdge();
  const path = usePathname().slice(1) || "home";
  return (event: string, event_id?: string) => {
    if (!account) return;
    request(
      `/api/leagues/${encodeURIComponent(account.leagueId)}/beta/analytics?username=${encodeURIComponent(account.username)}`,
      { event, feature: path, event_id },
    ).catch(() => {});
  };
}

export function Helpful({ id }: { id: string }) {
  const { endpoint } = useLeague();
  const path = usePathname().slice(1) || "home";
  const [state, setState] = useState("");
  const [pending, setPending] = useState(false);
  const track = useBetaEvent();
  useEffect(() => {
    track("recommendation_viewed", id);
  }, [id]); // mount-level impression, not an attention claim
  async function send(category: string) {
    setPending(true);
    try {
      await request(endpoint("beta/feedback"), {
        category,
        feature: path,
        event_id: id,
      });
      setState(category);
    } catch {
      setState("ERROR");
    } finally {
      setPending(false);
    }
  }
  return (
    <div className="beta-helpful" aria-label="Recommendation feedback">
      {["HELPFUL", "NOT_HELPFUL"].map((value) => (
        <button
          key={value}
          disabled={pending}
          aria-pressed={state === value}
          onClick={() => send(value)}
        >
          {title(value)}
        </button>
      ))}
      {state === "ERROR" && (
        <small role="alert">Could not save. Please retry.</small>
      )}
      {state && state !== "ERROR" && (
        <small role="status">Thanks — saved.</small>
      )}
    </div>
  );
}

export function BetaPanel({ view }: { view: string }) {
  const { endpoint, data } = useLeague();
  const [category, setCategory] = useState("CONFUSING");
  const [text, setText] = useState("");
  const [status, setStatus] = useState("");
  const info = useQuery({
    queryKey: ["capabilities"],
    queryFn: () =>
      request<Record<string, string | boolean>>("/api/capabilities"),
    staleTime: 300_000,
  });
  const track = useBetaEvent();
  useEffect(() => {
    track(view);
  }, [view]);
  useEffect(() => {
    if (!data) return;
    performance.mark(`fanedge:ready:${view}`);
    const key = `fanedge-ready:${data.league.id}`;
    if (!sessionStorage.getItem(key)) {
      track("intelligence_ready");
      sessionStorage.setItem(key, "1");
    }
  }, [data?.league.id, view]);
  return (
    <footer className="beta-panel">
      <details>
        <summary>Beta · Send feedback</summary>
        <p>
          Feedback includes this league, screen, build and data freshness.
          Optional text is stored on FanEdge’s server for up to 30 days with
          scheduled maintenance. Don’t include secrets or private information.
        </p>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            setStatus("Sending…");
            try {
              await request(endpoint("beta/feedback"), {
                category,
                feature: view,
                text: text || null,
              });
              setStatus("Thanks — feedback saved.");
              setText("");
            } catch {
              setStatus("Could not save feedback. Please retry.");
            }
          }}
        >
          <label>
            What happened?
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
            >
              {[
                "CONFUSING",
                "BAD_RECOMMENDATION",
                "MISSING_FEATURE",
                "DATA_LOOKS_WRONG",
                "SLOW",
                "OTHER",
              ].map((v) => (
                <option key={v}>{v}</option>
              ))}
            </select>
          </label>
          <label>
            Anything else? (optional)
            <textarea
              maxLength={1000}
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
          </label>
          <button className="secondary-button" disabled={status === "Sending…"}>
            Send feedback
          </button>
          <span role="status">{status}</span>
        </form>
      </details>
      <small>
        {info.data
          ? `Build ${info.data.build} · ${info.data.ai_enabled ? "AI phrasing enabled" : "AI phrasing off · grounded answers available"} · ${info.data.news_enabled ? "News enabled" : "News off"} · ${info.data.player_images_enabled ? "Player photos on" : "Player photos off"}`
          : "Checking beta capabilities…"}
      </small>
      <small>
        Data: <a href="https://docs.sleeper.com/">Sleeper</a> ·{" "}
        <a href="https://github.com/nflverse/nflverse-data">nflverse</a> (
        <a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>);
        transformed by FanEdge. No endorsement or warranties. Not affiliated
        with the NFL or its teams.
      </small>
    </footer>
  );
}
