"""Run with: uvicorn backend.main:app --port 8000."""

from contextlib import asynccontextmanager
from time import perf_counter
import os
import secrets
from uuid import uuid4
from typing import Annotated

from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from backend import presenter, schemas as api
from backend.services import IntelligenceService, LeagueNotFound
from football_data import FootballDataError
from sleeper_api import SleeperAPIError
from beta_config import capabilities, build_version
from backend.beta import BetaStore, RateLimiter, log_request, EVENTS, correlation_id
from pydantic import BaseModel, Field
from typing import Literal


class BetaEvent(BaseModel):
    event: str = Field(max_length=40)
    feature: Literal["home", "team", "market", "waivers", "trades", "ask"] | None = None
    event_id: str | None = Field(default=None, max_length=200)


class BetaFeedback(BaseModel):
    category: Literal["HELPFUL", "NOT_HELPFUL", "CONFUSING", "BAD_RECOMMENDATION", "MISSING_FEATURE", "DATA_LOOKS_WRONG", "SLOW", "OTHER"]
    feature: Literal["home", "team", "market", "waivers", "trades", "ask"]
    event_id: str | None = Field(default=None, max_length=200)
    text: str | None = Field(default=None, max_length=1000)

load_dotenv()


def create_app(service=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.service = service or IntelligenceService()
        app.state.beta = BetaStore(app.state.service.repository.path)
        yield
        if service is None:
            app.state.service.close()

    app = FastAPI(title="FanEdge", version="15.0", lifespan=lifespan)
    limiter = RateLimiter()
    from backend.trade_api import router as trade_router

    app.include_router(trade_router)

    @app.middleware("http")
    async def timing(request, call_next):
        start = perf_counter()
        correlation = uuid4().hex
        correlation_id.set(correlation)
        path = request.url.path
        bucket, limit = next(((name, limit) for marker, name, limit in (
            ("/refresh", "refresh", 2), ("/copilot", "ask", 12),
            ("/trades/", "trade", 30), ("/snapshot", "snapshot", 30),
            ("/users/", "connect", 20), ("/beta/", "telemetry", 300),
        ) if marker in path), ("read", 180))
        client = request.client.host if request.client else "unknown"
        if not limiter.allow((client, bucket), limit) or not limiter.allow(("global", bucket), limit * 10):
            response = JSONResponse(status_code=429, content={"detail": "Please wait a minute before trying again."}, headers={"Retry-After": "60"})
        else:
            try:
                response = await call_next(request)
            except Exception:
                response = JSONResponse(status_code=500, content={"detail": "FanEdge could not complete this request. Please retry."})
        route = getattr(request.scope.get("route"), "path", "/unmatched")
        category = "OK" if response.status_code < 400 else "RATE_LIMIT" if response.status_code == 429 else "PROVIDER_UNAVAILABLE" if response.status_code == 502 else "REQUEST_ERROR"
        record = log_request(route, category, correlation, (perf_counter() - start) * 1000, provider=getattr(request.state, "provider", None))
        try:
            request.app.state.beta.record("request", category=category, context=record)
        except Exception:
            pass  # Instrumentation must never break intelligence.
        response.headers["X-Request-ID"] = correlation
        response.headers["X-FanEdge-Build"] = build_version()
        response.headers["Server-Timing"] = (
            f"app;dur={(perf_counter() - start) * 1000:.2f}"
        )
        response.headers["Cache-Control"] = "private, no-store"
        return response

    @app.exception_handler(LeagueNotFound)
    async def missing(request, exc):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(SleeperAPIError)
    async def sleeper_error(request, exc):
        request.state.provider = "Sleeper"
        code = (
            404
            if "No Sleeper user" in str(exc) or "Could not find" in str(exc)
            else 502
        )
        return JSONResponse(status_code=code, content={"detail": str(exc)})

    @app.exception_handler(FootballDataError)
    async def football_error(request, exc):
        request.state.provider = "nflverse"
        return JSONResponse(
            status_code=502,
            content={"detail": "Football data is unavailable. Please retry."},
        )

    def svc(request: Request):
        return request.app.state.service

    def snapshot(
        league_id: str,
        username: Annotated[str, Query(min_length=1, max_length=100)],
        service=Depends(svc),
    ):
        return service.get_snapshot(username, league_id)

    def product(result=Depends(snapshot), service=Depends(svc)):
        snap, status = result
        model = presenter.present(snap, service.repository)
        return model.model_copy(update={"meta": model.meta.model_copy(update=status)})

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "fanedge", "version": "15.0", "build": build_version()}

    @app.get("/api/capabilities")
    def provider_capabilities():
        return {"build": build_version(), **capabilities()}

    def session(request):
        value = request.headers.get("X-FanEdge-Session", "")
        try:
            from uuid import UUID
            return str(UUID(value))
        except ValueError:
            return None

    @app.post("/api/beta/analytics", status_code=204)
    def anonymous_analytics(body: BetaEvent, request: Request):
        if body.event not in {"landing", "connect_started", "return_session"}:
            raise HTTPException(422, "Unknown pre-connect event.")
        request.app.state.beta.record(body.event, session_id=session(request))

    @app.post("/api/leagues/{league_id}/beta/analytics", status_code=204)
    def beta_analytics(body: BetaEvent, request: Request, result=Depends(snapshot)):
        if body.event not in EVENTS:
            raise HTTPException(422, "Unknown analytics event.")
        snap = result[0]
        request.app.state.beta.record(body.event, session_id=session(request),
            user_id=snap.scope.sleeper_user_id, league_id=snap.scope.league_id,
            feature=body.feature, event_id=body.event_id)

    @app.post("/api/leagues/{league_id}/beta/feedback", status_code=201)
    def beta_feedback(body: BetaFeedback, request: Request, result=Depends(snapshot), service=Depends(svc)):
        snap = result[0]
        request.app.state.beta.record("feedback", session_id=session(request),
            user_id=snap.scope.sleeper_user_id, league_id=snap.scope.league_id,
            feature=body.feature, event_id=body.event_id, category=body.category,
            text=body.text, context={"snapshot_id": snap.id, "built_at": snap.built_at,
                "providers": service.data_health(snap)["providers"], "capabilities": capabilities()})
        return {"status": "received"}

    @app.post("/internal/ops/{operation}")
    def ops(operation: str, request: Request, service=Depends(svc)):
        token = os.getenv("FANEDGE_OPS_TOKEN", "")
        if not token or len(token) < 32 or not secrets.compare_digest(request.headers.get("Authorization", ""), f"Bearer {token}"):
            raise HTTPException(404, "Not found.")
        if operation == "status":
            return {"build": build_version(), "capabilities": capabilities(), "health": service.data_health()}
        if operation == "prune-telemetry":
            return {"removed": request.app.state.beta.prune()}
        if operation == "clear-cache":
            caches = (service.providers, service.snapshots, service.conversations,
                      service.trade_engines, service.trade_results, service.ask_results)
            if any(cache.pending for cache in caches):
                raise HTTPException(409, "Refresh in progress; retry when idle.")
            for cache in caches:
                with cache.lock:
                    cache.entries.clear()
                    cache.errors.clear()
                    cache.retry_after.clear()
            return {"status": "cleared"}
        raise HTTPException(404, "Unknown operation.")

    @app.get("/api/health/data")
    def data_health(service=Depends(svc)):
        return service.data_health()

    @app.get("/api/leagues/{league_id}/health/data")
    def league_data_health(result=Depends(snapshot), service=Depends(svc)):
        return service.data_health(result[0])

    @app.get("/api/users/{username}/leagues", response_model=api.Connection)
    def connect(username: str, service=Depends(svc)):
        user, leagues = service.connect(username)
        name = str(user.get("display_name") or user.get("username") or username)
        return api.Connection(
            username=username,
            leagues=[presenter.league(item, name) for item in leagues],
        )

    @app.get("/api/leagues/{league_id}/snapshot", response_model=api.Snapshot)
    def full_snapshot(value=Depends(product)):
        return value

    @app.post("/api/leagues/{league_id}/refresh", response_model=api.Snapshot)
    def refresh(
        league_id: str,
        username: Annotated[str, Query(min_length=1, max_length=100)],
        service=Depends(svc),
    ):
        snap, status = service.get_snapshot(username, league_id, refresh=True)
        result = presenter.present(snap, service.repository)
        return result.model_copy(update={"meta": result.meta.model_copy(update=status)})

    @app.get("/api/leagues/{league_id}/overview", response_model=api.Overview)
    def overview(value=Depends(product)):
        return api.Overview(meta=value.meta, league=value.league, events=value.events)

    @app.get("/api/leagues/{league_id}/roster", response_model=api.RosterResponse)
    def roster(value=Depends(product)):
        return api.RosterResponse(starters=value.starters, bench=value.bench)

    @app.get("/api/leagues/{league_id}/lineup", response_model=list[api.Recommendation])
    def lineup(value=Depends(product)):
        return value.recommendations

    @app.get(
        "/api/leagues/{league_id}/waivers", response_model=list[api.WaiverCandidate]
    )
    def waivers(position: str | None = None, value=Depends(product)):
        return [
            item
            for item in value.waivers
            if not position or item.player.position == position.upper()
        ]

    @app.get(
        "/api/leagues/{league_id}/events", response_model=list[api.OpportunityEvent]
    )
    def events(value=Depends(product)):
        return value.events

    @app.get("/api/leagues/{league_id}/history", response_model=list[api.JournalEntry])
    def history(value=Depends(product)):
        return value.history

    @app.get("/api/leagues/{league_id}/players/{player_id}", response_model=api.Player)
    def player(player_id: str, result=Depends(snapshot)):
        snap, _ = result
        value = next(
            (p for p in snap.state.active_players if p.player_id == player_id), None
        )
        if value is None:
            raise HTTPException(404, "Player not found in current intelligence.")
        return presenter.player(value, snap.state)

    @app.post("/api/leagues/{league_id}/copilot", response_model=api.CopilotResponse)
    def copilot(
        body: api.CopilotRequest, result=Depends(snapshot), service=Depends(svc)
    ):
        snap, _ = result
        conversation, intent, answer = service.ask(
            snap,
            body.question,
            body.conversation_id,
            body.suggested,
            body.trade_preferences.model_dump() if body.trade_preferences else None,
        )
        players = {p.player_id: p for p in snap.state.active_players}
        return api.CopilotResponse(
            conversation_id=conversation,
            model_text=answer.model_text,
            answer=answer.answer,
            why=list(answer.why),
            action=answer.action,
            watch_for=answer.watch_for,
            confidence=answer.confidence,
            hypothetical=answer.hypothetical,
            unsupported=answer.unsupported,
            provider_fallback=answer.provider_fallback,
            evidence=[api.Evidence(**item.__dict__) for item in answer.evidence],
            players=[
                presenter.player(players[pid], snap.state)
                for pid in answer.player_ids
                if pid in players
            ],
            intent=intent.primary_intent,
            trades=answer.trades,
            plan=answer.plan,
        )

    @app.post("/api/leagues/{league_id}/events/{event_id}/feedback")
    def feedback(
        event_id: str,
        body: api.FeedbackRequest,
        result=Depends(snapshot),
        service=Depends(svc),
    ):
        snap, _ = result
        try:
            service.record_feedback(snap.scope, event_id, body.status)
        except KeyError:
            raise HTTPException(404, "Recommendation not found.") from None
        return {"status": body.status}

    @app.post("/api/leagues/{league_id}/analytics", status_code=204)
    def analytics(
        body: api.AnalyticsRequest, result=Depends(snapshot), service=Depends(svc)
    ):
        service.repository.record_analytics(result[0].scope, body.event)

    return app


app = create_app()
