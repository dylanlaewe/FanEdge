from dataclasses import replace
from datetime import UTC, datetime, timedelta

from news import (
    Freshness, NewsCategory, NewsEntity, NewsEntityResolver, NewsFact, NewsFactType,
    NewsItem, audit_news, extract_facts, freshness_bucket, parse_espn_rss, reconcile_facts,
)
from sleeper_api import Player


NOW = datetime(2026, 9, 19, 16, tzinfo=UTC)


def story(headline: str, *, summary: str = "", hours: int = 1, source: str = "ESPN", item_id: str = "item") -> NewsItem:
    return NewsItem(item_id, source, (NOW - timedelta(hours=hours)).isoformat(), headline, summary, f"https://example.com/{item_id}")


def resolved_story(headline: str, player: Player, *, summary: str = "", hours: int = 1, item_id: str = "item") -> NewsItem:
    entity = NewsEntity(player.player_id, player.name, player.position, player.team, "exact_normalized_name")
    return replace(story(headline, summary=summary, hours=hours, item_id=item_id), player_entities=(entity,))


def test_rss_parser_normalizes_a_bounded_story() -> None:
    xml = b"""<rss><channel><item><title>Player update</title><description><![CDATA[<p>Useful summary.</p>]]></description><link>https://example.com/a</link><guid>a</guid><pubDate>Sat, 19 Sep 2026 15:00:00 GMT</pubDate></item></channel></rss>"""
    items = parse_espn_rss(xml, now=NOW)
    assert len(items) == 1
    assert items[0].source == "ESPN"
    assert items[0].summary == "Useful summary."
    assert items[0].url == "https://example.com/a"


def test_entity_resolution_exact_team_assisted_ambiguous_and_unresolved() -> None:
    players = [
        Player("1", "Puka Nacua", "WR", "LAR"),
        Player("2", "Josh Allen", "QB", "BUF"),
        Player("3", "Josh Allen", "LB", "JAX"),  # excluded non-fantasy identity
        Player("4", "John Smith", "TE", "KC"),
        Player("5", "John Smith", "WR", "LV"),
    ]
    resolver = NewsEntityResolver(players)
    exact = resolver.resolve_item(story("Puka Nacua is questionable"))
    assisted = resolver.resolve_item(replace(story("Rams' Nacua misses practice"), teams=("LAR",)))
    ambiguous = resolver.resolve_item(story("John Smith is questionable"))
    unresolved = resolver.resolve_item(story("Mystery Player is questionable"))
    assert exact.player_entities[0].player_id == "1"
    assert assisted.player_entities[0].resolution == "team_assisted_unique_last_name"
    assert not ambiguous.player_entities
    assert not unresolved.player_entities


def test_fact_extraction_status_practice_role_transaction_and_speculation() -> None:
    player = Player("1", "Puka Nacua", "WR", "LAR")
    cases = [
        ("Puka Nacua has been ruled out Sunday", NewsFactType.PLAYER_STATUS_CHANGE, "OUT"),
        ("Puka Nacua is questionable for Monday", NewsFactType.PLAYER_STATUS_CHANGE, "QUESTIONABLE"),
        ("Puka Nacua was limited in practice", NewsFactType.PRACTICE_STATUS, "LIMITED"),
        ("Coach expects Puka Nacua to see more touches", NewsFactType.ROLE_COMMENT, "EXPECTED_INCREASED_ROLE"),
        ("Rams released Puka Nacua", NewsFactType.TRANSACTION, "RELEASED"),
    ]
    for index, (headline, fact_type, state) in enumerate(cases):
        facts = extract_facts([resolved_story(headline, player, item_id=str(index))], now=NOW)
        assert any(fact.fact_type == fact_type.value and fact.new_state == state for fact in facts)
    speculative = extract_facts([resolved_story("Puka Nacua could see more touches", player)], now=NOW)
    assert not speculative


def test_fact_is_attached_only_to_nearby_player_clause() -> None:
    first, second = Player("1", "Alpha Runner", "RB", "LAR"), Player("2", "Beta Runner", "RB", "LAR")
    item = story("Alpha Runner is out. Beta Runner will start.")
    item = replace(item, player_entities=(
        NewsEntity("1", first.name, first.position, first.team, "exact"),
        NewsEntity("2", second.name, second.position, second.team, "exact"),
    ))
    facts = extract_facts([item], now=NOW)
    assert [fact.subject_player_id for fact in facts] == ["1"]


def test_freshness_buckets_are_deterministic() -> None:
    assert freshness_bucket((NOW - timedelta(minutes=30)).isoformat(), now=NOW) == Freshness.BREAKING.value
    assert freshness_bucket((NOW - timedelta(hours=20)).isoformat(), now=NOW) == Freshness.RECENT.value
    assert freshness_bucket((NOW - timedelta(days=3)).isoformat(), now=NOW) == Freshness.STALE.value


def fact(state: str, *, hours: int, source: str = "ESPN", authority: str = "REPUTABLE_REPORTING", explicit: bool = True, fact_id: str = "f") -> NewsFact:
    return NewsFact(fact_id, "1", "Puka Nacua", "WR", "LAR", NewsFactType.PLAYER_STATUS_CHANGE.value, None, state, None, "HIGH", (fact_id,), (source,), (f"https://example.com/{fact_id}",), (NOW - timedelta(hours=hours)).isoformat(), f"Puka Nacua is {state.lower()}.", Freshness.RECENT.value, authority, explicit)


def test_newer_fact_overrides_old_and_tracks_superseded_contradiction() -> None:
    winner = reconcile_facts([fact("QUESTIONABLE", hours=12, fact_id="old"), fact("OUT", hours=1, fact_id="new")], now=NOW)[0]
    assert winner.new_state == "OUT"
    assert winner.old_state == "QUESTIONABLE"
    assert winner.superseded_fact_ids == ("old",)


def test_stale_official_fact_does_not_override_current_explicit_report() -> None:
    values = [
        fact("OUT", hours=72, source="NFL", authority="OFFICIAL", fact_id="stale"),
        fact("ACTIVE", hours=1, fact_id="current"),
    ]
    assert reconcile_facts(values, now=NOW)[0].new_state == "ACTIVE"


def test_official_explicit_status_beats_same_age_speculation() -> None:
    values = [
        fact("EXPECTED_TO_PLAY", hours=1, explicit=False, fact_id="spec"),
        fact("OUT", hours=1, source="NFL", authority="OFFICIAL", fact_id="official"),
    ]
    assert reconcile_facts(values, now=NOW)[0].new_state == "OUT"


def test_equivalent_reports_are_deduplicated_with_provenance() -> None:
    values = [fact("OUT", hours=1, source="ESPN", fact_id="one"), fact("OUT", hours=1, source="NFL", authority="OFFICIAL", fact_id="two")]
    result = reconcile_facts(values, now=NOW)
    assert len(result) == 1
    assert set(result[0].sources) == {"ESPN", "NFL"}
    assert set(result[0].source_item_ids) == {"one", "two"}


def test_audit_accounts_for_noisy_and_unresolved_stories() -> None:
    player = Player("1", "Puka Nacua", "WR", "LAR")
    resolved = resolved_story("Puka Nacua is out", player, item_id="one")
    noise = resolved_story("Puka Nacua discusses breakfast", player, item_id="two")
    unknown = story("Power rankings for every team", item_id="three")
    facts = extract_facts([resolved, noise, unknown], now=NOW)
    audit = audit_news([resolved, noise, unknown], facts)
    assert audit.fetched == 3
    assert audit.player_resolved == 2
    assert audit.actionable_facts == 1
    assert audit.rejected == 2
