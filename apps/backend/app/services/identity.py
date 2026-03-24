from __future__ import annotations

import re
import unicodedata

_RAW_NHL_TEAM_ALIASES = (
    ("Anaheim Ducks", "Anaheim", "Ducks", "ANA"),
    ("Boston Bruins", "Boston", "Bruins", "BOS"),
    ("Buffalo Sabres", "Buffalo", "Sabres", "BUF"),
    ("Calgary Flames", "Calgary", "Flames", "CGY"),
    ("Carolina Hurricanes", "Carolina", "Hurricanes", "Canes", "CAR"),
    ("Chicago Blackhawks", "Chicago", "Blackhawks", "Hawks", "CHI"),
    ("Colorado Avalanche", "Colorado", "Avalanche", "Avs", "COL"),
    ("Columbus Blue Jackets", "Columbus", "Blue Jackets", "Jackets", "CBJ"),
    ("Dallas Stars", "Dallas", "Stars", "DAL"),
    ("Detroit Red Wings", "Detroit", "Red Wings", "Wings", "DET"),
    ("Edmonton Oilers", "Edmonton", "Oilers", "EDM"),
    ("Florida Panthers", "Florida", "Panthers", "FLA"),
    ("Los Angeles Kings", "Los Angeles", "LA Kings", "Kings", "LAK"),
    ("Minnesota Wild", "Minnesota", "Wild", "MIN"),
    ("Montreal Canadiens", "Montreal", "Canadiens", "Habs", "MTL"),
    ("Nashville Predators", "Nashville", "Predators", "Preds", "NSH"),
    ("New Jersey Devils", "New Jersey", "NJ Devils", "Devils", "NJD"),
    ("New York Islanders", "NY Islanders", "New York Islanders", "Islanders", "NYI"),
    ("New York Rangers", "NY Rangers", "New York Rangers", "Rangers", "NYR"),
    ("Ottawa Senators", "Ottawa", "Senators", "Sens", "OTT"),
    ("Philadelphia Flyers", "Philadelphia", "Flyers", "PHI"),
    ("Pittsburgh Penguins", "Pittsburgh", "Penguins", "Pens", "PIT"),
    ("San Jose Sharks", "San Jose", "Sharks", "SJS"),
    ("Seattle Kraken", "Seattle", "Kraken", "SEA"),
    ("St. Louis Blues", "St Louis", "St. Louis", "Blues", "STL"),
    ("Tampa Bay Lightning", "Tampa Bay", "Lightning", "Bolts", "TBL"),
    ("Toronto Maple Leafs", "Toronto", "Maple Leafs", "Leafs", "TOR"),
    ("Utah Hockey Club", "Utah Mammoth", "Mammoth", "Utah", "UTAH", "UTA"),
    ("Vancouver Canucks", "Vancouver", "Canucks", "VAN"),
    ("Vegas Golden Knights", "Vegas", "Golden Knights", "Knights", "VGK"),
    ("Washington Capitals", "Washington", "Capitals", "Caps", "WSH"),
    ("Winnipeg Jets", "Winnipeg", "Jets", "WPG"),
)


def _normalize_ascii(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in folded if not unicodedata.combining(ch))


def normalize_team_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _normalize_ascii(value).strip().lower())


def normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _normalize_ascii(value).strip().lower()).strip()


def name_aliases(value: str) -> set[str]:
    prepared = _prepare_player_name_for_aliasing(value)
    normalized = normalize_name(prepared)
    if not normalized:
        return set()

    aliases = {normalized, normalized.replace(" ", "")}
    parts = [part for part in normalized.split(" ") if part]
    if len(parts) >= 3 and len(parts[-1]) <= 3:
        parts = parts[:-1]
    if len(parts) >= 2:
        first, last = parts[0], parts[-1]
        aliases.add(f"{first} {last}")
        aliases.add(f"{first}{last}")
        aliases.add(f"{first[0]} {last}")
        aliases.add(f"{first[0]}{last}")
        aliases.add(last)
    return aliases


def _prepare_player_name_for_aliasing(value: str) -> str:
    normalized = _normalize_ascii(value).strip().lower()
    if not normalized:
        return ""

    # Strip contextual suffixes often present in sportsbook outcome labels.
    normalized = re.sub(r"\([^)]*\)", " ", normalized)
    normalized = re.sub(r"\[[^\]]*\]", " ", normalized)
    normalized = re.sub(r"\s+-\s+[a-z]{2,4}$", " ", normalized)

    # Convert "Last, First" into "First Last".
    if "," in normalized:
        last_name, first_name = normalized.split(",", maxsplit=1)
        normalized = f"{first_name.strip()} {last_name.strip()}".strip()

    normalized = _strip_bookmaker_market_suffix(normalized)

    return normalized


def _strip_bookmaker_market_suffix(normalized: str) -> str:
    separators = (" - ", " – ", " — ", "|")
    for separator in separators:
        if separator not in normalized:
            continue
        head, tail = normalized.split(separator, maxsplit=1)
        head = head.strip()
        tail = tail.strip()
        if not head:
            continue
        if not tail:
            return head
        if _looks_like_market_or_team_metadata(tail):
            return head
    return normalized


def _looks_like_market_or_team_metadata(value: str) -> bool:
    compact = normalize_name(value)
    if not compact:
        return False
    tokens = [token for token in compact.split(" ") if token]
    if not tokens:
        return False

    metadata_tokens = {
        "to",
        "score",
        "first",
        "goal",
        "goalscorer",
        "goalcorer",
        "anytime",
        "player",
        "other",
        "team",
        "for",
        "the",
    }
    if set(tokens).issubset(metadata_tokens):
        return True

    team_tokens = team_alias_tokens(compact)
    if team_tokens:
        return True

    if len(tokens) >= 2 and tokens[0] in {"any", "first", "to"}:
        return True

    return False


TEAM_TOKEN_ALIASES: dict[str, set[str]] = {}
for alias_group in _RAW_NHL_TEAM_ALIASES:
    tokens = {normalize_team_token(alias) for alias in alias_group if alias.strip()}
    for token in tokens:
        TEAM_TOKEN_ALIASES.setdefault(token, set()).update(tokens)


def team_alias_tokens(team_name: str) -> set[str]:
    normalized = normalize_team_token(team_name)
    if not normalized:
        return set()
    return {normalized} | TEAM_TOKEN_ALIASES.get(normalized, set())
