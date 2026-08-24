from dataclasses import dataclass
from enum import StrEnum, auto

class Kind(StrEnum):
    COUNTING = auto()
    RATE = auto()
class Direction(StrEnum): 
    HIGHER_IS_BETTER = auto() 
    LOWER_IS_BETTER = auto()
class Prorate(StrEnum):   
    GAMES = auto() 
    NONE = auto()
class Tier(StrEnum):      
    RECORD = auto() 
    ELITE = auto() 
    GOOD = auto() 
    AVERAGE = auto() 
    BELOW = auto() 
    POOR = auto() 
    WORST = auto()

@dataclass(frozen=True)
class Stat:
    field: str
    display: str
    legacy_key: str | None
    kind: Kind
    direction: Direction
    prorate: Prorate
    era_from: int
    views: frozenset[str]
    milestone_eligible: bool


VIEWS: tuple[str, ...] = ('season_REG', 'week_REG', 'season_POST', 'week_POST')

VIEWS_SET: frozenset[str] = frozenset(VIEWS)

STATS: dict[str, Stat] = {
    "completions": Stat(field="completions", display="CMP", legacy_key="CMP", kind=Kind.COUNTING, direction=Direction.HIGHER_IS_BETTER, prorate=Prorate.GAMES, era_from=1999, views=VIEWS_SET, milestone_eligible=True),
    "attempts": Stat(field="attempts", display="ATT", legacy_key="ATT", kind=Kind.COUNTING, direction=Direction.HIGHER_IS_BETTER, prorate=Prorate.GAMES, era_from=1999, views=VIEWS_SET, milestone_eligible=True),
    "completion_pct": Stat(field="completion_pct", display="CMP%", legacy_key="CMP%", kind=Kind.RATE, direction=Direction.HIGHER_IS_BETTER, prorate=Prorate.NONE, era_from=1999, views=VIEWS_SET, milestone_eligible=True),
    "passing_yards": Stat(field="passing_yards", display="YDS", legacy_key="YDS", kind=Kind.COUNTING, direction=Direction.HIGHER_IS_BETTER, prorate=Prorate.GAMES, era_from=1999, views=VIEWS_SET, milestone_eligible=True),
    "yards_per_completion": Stat(field="yards_per_completion", display="Y/C", legacy_key="Y/C", kind=Kind.RATE, direction=Direction.HIGHER_IS_BETTER, prorate=Prorate.NONE, era_from=1999, views=VIEWS_SET, milestone_eligible=False),
    "yards_per_attempt": Stat(field="yards_per_attempt", display="Y/A", legacy_key="Y/A", kind=Kind.RATE, direction=Direction.HIGHER_IS_BETTER, prorate=Prorate.NONE, era_from=1999, views=VIEWS_SET, milestone_eligible=True),
    "passing_tds": Stat(field="passing_tds", display="PTD", legacy_key="PTD", kind=Kind.COUNTING, direction=Direction.HIGHER_IS_BETTER, prorate=Prorate.GAMES, era_from=1999, views=VIEWS_SET, milestone_eligible=True),
    "td_pct": Stat(field="td_pct", display="TD%", legacy_key="TD%", kind=Kind.RATE, direction=Direction.HIGHER_IS_BETTER, prorate=Prorate.NONE, era_from=1999, views=VIEWS_SET, milestone_eligible=False),
    "passer_rating": Stat(field="passer_rating", display="RTG", legacy_key="RTG", kind=Kind.RATE, direction=Direction.HIGHER_IS_BETTER, prorate=Prorate.NONE, era_from=1999, views=VIEWS_SET, milestone_eligible=True),
    "any_a": Stat(field="any_a", display="ANY/A", legacy_key=None, kind=Kind.RATE, direction=Direction.HIGHER_IS_BETTER, prorate=Prorate.NONE, era_from=1999, views=VIEWS_SET, milestone_eligible=False),
    "qbr": Stat(field="qbr", display="QBR", legacy_key="QBR", kind=Kind.RATE, direction=Direction.HIGHER_IS_BETTER, prorate=Prorate.NONE, era_from=2006, views=VIEWS_SET, milestone_eligible=True),
    "interceptions": Stat(field="interceptions", display="INT", legacy_key="INT", kind=Kind.COUNTING, direction=Direction.LOWER_IS_BETTER, prorate=Prorate.GAMES, era_from=1999, views=VIEWS_SET, milestone_eligible=True),
    "int_pct": Stat(field="int_pct", display="INT%", legacy_key="INT%", kind=Kind.RATE, direction=Direction.LOWER_IS_BETTER, prorate=Prorate.NONE, era_from=1999, views=VIEWS_SET, milestone_eligible=True),
    "td_int_ratio": Stat(field="td_int_ratio", display="TD/INT", legacy_key="TD/INT", kind=Kind.RATE, direction=Direction.HIGHER_IS_BETTER, prorate=Prorate.NONE, era_from=1999, views=VIEWS_SET, milestone_eligible=True),
    "sacks": Stat(field="sacks", display="SCK", legacy_key=None, kind=Kind.COUNTING, direction=Direction.LOWER_IS_BETTER, prorate=Prorate.GAMES, era_from=1999, views=VIEWS_SET, milestone_eligible=True),
    "sack_yards": Stat(field="sack_yards", display="SCK YDS", legacy_key=None, kind=Kind.COUNTING, direction=Direction.LOWER_IS_BETTER, prorate=Prorate.GAMES, era_from=1999, views=VIEWS_SET, milestone_eligible=True),
    "sack_pct": Stat(field="sack_pct", display="SCK%", legacy_key="SCK%", kind=Kind.RATE, direction=Direction.LOWER_IS_BETTER, prorate=Prorate.NONE, era_from=1999, views=VIEWS_SET, milestone_eligible=False),
    "rushing_yards": Stat(field="rushing_yards", display="RYDS", legacy_key="RYDS", kind=Kind.COUNTING, direction=Direction.HIGHER_IS_BETTER, prorate=Prorate.GAMES, era_from=1999, views=VIEWS_SET, milestone_eligible=True),
    "rushing_tds": Stat(field="rushing_tds", display="RTD", legacy_key="RTD", kind=Kind.COUNTING, direction=Direction.HIGHER_IS_BETTER, prorate=Prorate.GAMES, era_from=1999, views=VIEWS_SET, milestone_eligible=True),
    "rushing_attempts": Stat(field="rushing_attempts", display="RATT", legacy_key="RATT", kind=Kind.COUNTING, direction=Direction.HIGHER_IS_BETTER, prorate=Prorate.GAMES, era_from=1999, views=VIEWS_SET, milestone_eligible=True),
    "rush_yards_per_att": Stat(field="rush_yards_per_att", display="RY/RA", legacy_key="RY/RA", kind=Kind.RATE, direction=Direction.HIGHER_IS_BETTER, prorate=Prorate.NONE, era_from=1999, views=VIEWS_SET, milestone_eligible=False),
    "fumbles": Stat(field="fumbles", display="FUM", legacy_key="FUM", kind=Kind.COUNTING, direction=Direction.LOWER_IS_BETTER, prorate=Prorate.GAMES, era_from=1999, views=VIEWS_SET, milestone_eligible=True),
    "total_tds": Stat(field="total_tds", display="TOT TD", legacy_key=None, kind=Kind.COUNTING, direction=Direction.HIGHER_IS_BETTER, prorate=Prorate.GAMES, era_from=1999, views=VIEWS_SET, milestone_eligible=True),
    "total_yards": Stat(field="total_yards", display="TOT YDS", legacy_key=None, kind=Kind.COUNTING, direction=Direction.HIGHER_IS_BETTER, prorate=Prorate.GAMES, era_from=1999, views=VIEWS_SET, milestone_eligible=True),
    "snap_pct": Stat(field="snap_pct", display="SNAP%", legacy_key=None, kind=Kind.RATE, direction=Direction.HIGHER_IS_BETTER, prorate=Prorate.NONE, era_from=2013, views=VIEWS_SET, milestone_eligible=True),
}

def stats_for_view(view: str) -> list[Stat]:
    stats: list[Stat] = []
    for stat in STATS.values():
        if view in stat.views:
            stats.append(stat)
    return stats

def legacy_tier_to_semantic(name: str) -> Tier:
    match name:
        case 'record' : return Tier.RECORD
        case 'dark_green': return Tier.ELITE
        case 'green': return Tier.GOOD
        case 'yellow': return Tier.AVERAGE
        case 'orange': return Tier.BELOW
        case 'red': return Tier.POOR
        case 'dark_red': return Tier.WORST
        case _: raise ValueError(f"{name!r} is not a valid legacy tier name.")