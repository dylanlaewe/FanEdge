from opportunity import OpportunityGame, summarize_opportunity


def game(week, *, attempts=None, carries=None, targets=None, receptions=None):
    touches = None if carries is None and receptions is None else (carries or 0) + (receptions or 0)
    return OpportunityGame(week, attempts, None, carries, targets, receptions, touches)


def test_rising_usage_requires_and_uses_multiple_games():
    result = summarize_opportunity([game(1, carries=5), game(2, carries=6), game(3, carries=11), game(4, carries=12)], "RB")
    assert result and result.usage_trend == "RISING"
    assert result.recent_carries == 9.7


def test_falling_and_steady_usage():
    falling = summarize_opportunity([game(1, targets=10), game(2, targets=9), game(3, targets=4), game(4, targets=3)], "WR")
    steady = summarize_opportunity([game(1, targets=7), game(2, targets=8), game(3, targets=7), game(4, targets=8)], "TE")
    assert falling and falling.usage_trend == "FALLING"
    assert steady and steady.usage_trend == "STEADY"


def test_insufficient_sample_and_missing_fields_are_not_fabricated():
    result = summarize_opportunity([game(1, attempts=30), game(2, attempts=32)], "QB")
    assert result and result.usage_trend == "INSUFFICIENT DATA"
    assert result.recent_targets is None
    assert summarize_opportunity([], "RB") is None
