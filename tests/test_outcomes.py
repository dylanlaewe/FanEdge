from football_data import GamePerformance
from memory import LeagueScope, OutcomeStatus
from opportunity_engine import FantasyOpportunity
from outcomes import evaluate_pending_lineup_decisions
from sleeper_api import Player
from storage import SQLiteRepository


def test_completed_lineup_decision_is_evaluated_from_league_scored_games(tmp_path):
    repository = SQLiteRepository(tmp_path / "outcomes.db")
    scope = LeagueScope("u", "l", 2026, 5)
    recommended = Player("1", "Recommended Player", "WR", "LAR")
    alternative = Player("2", "Alternative Player", "WR", "SF")
    decision = FantasyOpportunity(
        "lineup:WR1:1", "LINEUP_OPPORTUNITY", "MEDIUM", recommended,
        alternative, (), ("DIRECT_LINEUP_ALTERNATIVE",), "CONSIDER_START",
        "MODERATE", ("Higher recent production",), 5, 5,
    )
    repository.reconcile(scope, [decision], data_fresh=True)
    performances = {
        ("recommendedplayer", "LAR", "WR"): [GamePerformance(5, 18.4)],
        ("alternativeplayer", "SF", "WR"): [GamePerformance(5, 11.2)],
    }
    assert evaluate_pending_lineup_decisions(repository, scope, 6, performances) == 1
    entry = repository.journal(scope)[0]
    assert entry.outcome == OutcomeStatus.RECOMMENDATION_OUTSCORED_ALTERNATIVE
    assert entry.recommended_points == 18.4


def test_missing_completed_game_data_records_neutral_unavailable_state(tmp_path):
    repository = SQLiteRepository(tmp_path / "outcomes.db")
    scope = LeagueScope("u", "l", 2026, 5)
    recommended = Player("1", "Recommended Player", "WR", "LAR")
    alternative = Player("2", "Alternative Player", "WR", "SF")
    decision = FantasyOpportunity(
        "lineup:WR1:1", "LINEUP_OPPORTUNITY", "MEDIUM", recommended,
        alternative, (), ("DIRECT_LINEUP_ALTERNATIVE",), "CONSIDER_START",
        "MODERATE", ("Higher recent production",), 5, 5,
    )
    repository.reconcile(scope, [decision], data_fresh=True)
    evaluate_pending_lineup_decisions(repository, scope, 6, {})
    assert repository.journal(scope)[0].outcome == OutcomeStatus.UNAVAILABLE_GAME_DATA
