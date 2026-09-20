"""Run with: uvicorn backend.main:app --port 8000."""

from contextlib import asynccontextmanager
from time import perf_counter
from typing import Annotated

from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from backend import presenter, schemas as api
from backend.services import IntelligenceService, LeagueNotFound
from football_data import FootballDataError
from sleeper_api import SleeperAPIError

load_dotenv()


def create_app(service=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.service = service or IntelligenceService()
        yield
        if service is None:
            app.state.service.close()

    app = FastAPI(title="FanEdge", version="12.0", lifespan=lifespan)

    @app.middleware("http")
    async def timing(request, call_next):
        start = perf_counter()
        response = await call_next(request)
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
        code = (
            404
            if "No Sleeper user" in str(exc) or "Could not find" in str(exc)
            else 502
        )
        return JSONResponse(status_code=code, content={"detail": str(exc)})

    @app.exception_handler(FootballDataError)
    async def football_error(request, exc):
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
        return {"status": "ok", "service": "fanedge", "version": "12.0"}

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
            snap, body.question, body.conversation_id, body.suggested
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
