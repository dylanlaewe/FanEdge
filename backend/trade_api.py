"""Trade API boundary. Discovery never writes to Sleeper or changes a roster."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from backend import presenter
from backend import schemas as api

router = APIRouter(prefix="/api/leagues/{league_id}/trades", tags=["Trades"])


def context(
    request: Request,
    league_id: str,
    username: Annotated[str, Query(min_length=1, max_length=100)],
):
    service = request.app.state.service
    snapshot, _ = service.get_snapshot(username, league_id)
    return service, snapshot


def players_for(engine, snapshot, ids=None):
    return {
        pid: presenter.player(engine.players[pid], snapshot.state)
        for pid in (engine.owners if ids is None else ids)
        if pid in engine.players
    }


TradeContext = Annotated[tuple, Depends(context)]


@router.get("", response_model=api.TradeOverview)
def overview(ctx: TradeContext):
    service, snapshot = ctx
    engine = service.trade_engine(snapshot)
    return {
        **engine.overview(),
        "players": players_for(engine, snapshot),
        "snapshot_id": snapshot.id,
    }


@router.post("/search", response_model=api.TradeSearch)
def search(body: api.TradeRequest, ctx: TradeContext):
    service, snapshot = ctx
    try:
        value = service.find_trades(snapshot, body.options())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    ids = {pid for idea in value["ideas"] for pid in (*idea["incoming"], *idea["outgoing"])}
    return {**value, "players": players_for(service.trade_engine(snapshot), snapshot, ids)}


@router.post("/diagnostics")
def diagnostics(body: api.TradeRequest, ctx: TradeContext):
    service, snapshot = ctx
    try:
        return service.find_trades(snapshot, body.options())["diagnostics"]
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.post("/analyze", response_model=api.TradeAnalysis)
def analyze(body: api.TradeAnalyzeRequest, ctx: TradeContext):
    service, snapshot = ctx
    engine = service.trade_engine(snapshot)
    result = engine.analyze(body.outgoing, body.incoming, body.options())
    service.repository.record_analytics(
        snapshot.scope,
        "TRADE_ANALYZED",
        metadata={
            "accepted": result["accepted"],
            "sent_count": len(body.outgoing),
            "received_count": len(body.incoming),
        },
    )
    return {**result, "players": players_for(engine, snapshot, set(body.outgoing + body.incoming))}
