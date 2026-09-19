from player_identity import PlayerIdentityResolver, normalize_name


ROWS = [
    {"gsis_id": "g1", "espn_id": "101", "display_name": "A.J. Brown", "position": "WR", "latest_team": "PHI"},
    {"gsis_id": "g2", "espn_id": "102", "display_name": "Marvin Jones Jr.", "position": "WR", "latest_team": "DET"},
    {"gsis_id": "g3", "espn_id": "103", "display_name": "Trade Player", "position": "RB", "latest_team": "NYJ"},
    {"gsis_id": "g4", "display_name": "Chris Smith", "position": "WR", "latest_team": "DAL"},
    {"gsis_id": "g5", "display_name": "Chris Smith", "position": "WR", "latest_team": "MIA"},
    {"gsis_id": "g6", "display_name": "Justin Tucker", "position": "K", "latest_team": "BAL"},
]


def test_normalizes_punctuation_suffixes_and_initials():
    assert normalize_name("A.J. Brown") == normalize_name("AJ Brown")
    assert normalize_name("Marvin Jones Jr.") == normalize_name("Marvin Jones")


def test_exact_provider_id_wins():
    identity = PlayerIdentityResolver(ROWS).resolve("s1", {"full_name": "Wrong Name", "position": "WR", "team": "XXX", "gsis_id": "g1"})
    assert identity.gsis_id == "g1"
    assert identity.resolution == "gsis_id"


def test_normalized_mapping_and_team_mismatch():
    resolver = PlayerIdentityResolver(ROWS)
    assert resolver.resolve("s2", {"full_name": "Marvin Jones", "position": "WR", "team": "DET"}).gsis_id == "g2"
    traded = resolver.resolve("s3", {"full_name": "Trade Player", "position": "RB", "team": "SF"})
    assert traded.gsis_id == "g3"
    assert traded.resolution == "name_position"


def test_ambiguous_and_unresolved_stay_unresolved():
    resolver = PlayerIdentityResolver(ROWS)
    ambiguous = resolver.resolve("s4", {"full_name": "Chris Smith", "position": "WR", "team": "FA"})
    missing = resolver.resolve("s5", {"full_name": "Nobody Here", "position": "QB", "team": "SEA"})
    assert ambiguous.gsis_id is None and ambiguous.resolution == "unresolved"
    assert missing.gsis_id is None


def test_defense_and_kicker_handling():
    resolver = PlayerIdentityResolver(ROWS)
    defense = resolver.resolve("BUF", {"full_name": "Buffalo Bills", "position": "DEF", "team": "BUF"})
    kicker = resolver.resolve("s6", {"full_name": "Justin Tucker", "position": "K", "team": "BAL"})
    assert defense.resolution == "team_defense" and defense.gsis_id is None
    assert kicker.gsis_id == "g6"
