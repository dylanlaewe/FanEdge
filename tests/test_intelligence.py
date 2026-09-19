from football_data import NFLState
from intelligence import (
    Role, RoleTrend, build_availability_changes, build_historical_index,
    build_participation_index, classify_role, current_evidence_weight,
)
from opportunity import PlayerOpportunity


def opportunity(games=4, targets=6, trend="STEADY"):
    return PlayerOpportunity(games, None, None, None, None, targets, targets, 4, 4, 4, 4, trend)


def test_current_weight_is_conservative_and_team_change_weakens_prior():
    assert current_evidence_weight(1) == .25
    assert current_evidence_weight(2) == .5
    assert current_evidence_weight(4) == 1
    assert current_evidence_weight(1, team_changed=True) == .62


def test_historical_baseline_and_missing_rookie():
    rows = [{"season":"2025","season_type":"REG","week":"1","player_display_name":"Veteran","player_id":"g1","team":"BUF","position":"WR","targets":"8","receptions":"5","receiving_yards":"50"}]
    index = build_historical_index(rows, 2025, {"rec":1,"rec_yd":.1})
    assert index[("gsis","g1")].points_per_game == 10
    assert index[("gsis","g1")].targets_per_game == 8
    assert ("gsis","rookie") not in index


def test_participation_rising_falling_missing_and_partial():
    def rows(player, shares):
        return [{"season":"2026","game_type":"REG","week":str(i+1),"player":player,"pfr_player_id":player,"position":"WR","team":"BUF","offense_snaps":"40" if share is not None else "","offense_pct":"" if share is None else str(share)} for i,share in enumerate(shares)]
    state = NFLState(2026, 6, "regular")
    index = build_participation_index(rows("up", [.3,.35,.55,.7]) + rows("down", [.8,.75,.5,.4]) + rows("partial", [None,.5]), state)
    assert index[("pfr","up")].trend == RoleTrend.EXPANDING
    assert index[("pfr","down")].trend == RoleTrend.SHRINKING
    assert index[("pfr","partial")].season_snap_share == .5
    assert index[("pfr","partial")].trend == RoleTrend.INSUFFICIENT
    assert ("pfr","missing") not in index


def test_role_expanding_stable_shrinking_and_insufficient():
    from intelligence import ParticipationSummary
    def part(trend, snap=.4): return ParticipationSummary(4,snap,snap,30,30,None,None,None,trend)
    assert classify_role("WR", opportunity(targets=3, trend="RISING"), part(RoleTrend.EXPANDING))[0] == Role.EMERGING
    assert classify_role("WR", opportunity(targets=6), part(RoleTrend.STABLE,.6))[1] == RoleTrend.STABLE
    assert classify_role("WR", opportunity(targets=6, trend="FALLING"), part(RoleTrend.SHRINKING,.6))[0] == Role.DECLINING
    assert classify_role("WR", opportunity(games=1), None)[1] == RoleTrend.INSUFFICIENT


def test_teammate_changes_filter_status_and_position():
    rows = [
        {"season_type":"REG","week":"1","team":"BUF","position":"RB","gsis_id":"a","full_name":"Alpha","report_status":"Questionable"},
        {"season_type":"REG","week":"2","team":"BUF","position":"RB","gsis_id":"a","full_name":"Alpha","report_status":"Out"},
        {"season_type":"REG","week":"2","team":"BUF","position":"WR","gsis_id":"b","full_name":"Beta","report_status":"Out"},
        {"season_type":"REG","week":"2","team":"BUF","position":"RB","gsis_id":"c","full_name":"Gamma","report_status":"Unknown"},
    ]
    result = build_availability_changes(rows, NFLState(2026,2,"regular"))
    assert result[("BUF","RB")][0].previous_status == "Questionable"
    assert result[("BUF","RB")][0].current_status == "Out"
    assert len(result[("BUF","RB")]) == 1
    assert result[("BUF","WR")][0].teammate == "Beta"
