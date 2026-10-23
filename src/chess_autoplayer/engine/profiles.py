"""Strength profiles and engine configuration table."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Profile:
    """Settings controlling Stockfish strength and evaluation parameters."""

    name: str
    limit_strength: bool
    elo: int | None
    time_limit: float
    multipv: int
    temperature: float  # in centipawns
    max_cp_loss: int  # in centipawns
    blunder_chance: float  # probability 0.0 to 1.0


PROFILES: dict[str, Profile] = {
    "beginner": Profile(
        name="beginner",
        limit_strength=True,
        elo=1350,
        time_limit=0.10,
        multipv=5,
        temperature=120.0,
        max_cp_loss=400,
        blunder_chance=0.06,
    ),
    "casual": Profile(
        name="casual",
        limit_strength=True,
        elo=1600,
        time_limit=0.15,
        multipv=5,
        temperature=80.0,
        max_cp_loss=250,
        blunder_chance=0.03,
    ),
    "club": Profile(
        name="club",
        limit_strength=True,
        elo=1900,
        time_limit=0.25,
        multipv=4,
        temperature=45.0,
        max_cp_loss=150,
        blunder_chance=0.015,
    ),
    "strong": Profile(
        name="strong",
        limit_strength=True,
        elo=2300,
        time_limit=0.40,
        multipv=3,
        temperature=20.0,
        max_cp_loss=80,
        blunder_chance=0.005,
    ),
    "master": Profile(
        name="master",
        limit_strength=False,
        elo=None,
        time_limit=0.80,
        multipv=3,
        temperature=10.0,
        max_cp_loss=40,
        blunder_chance=0.0,
    ),
    "max": Profile(
        name="max",
        limit_strength=False,
        elo=None,
        time_limit=1.50,
        multipv=1,
        temperature=0.0,
        max_cp_loss=0,
        blunder_chance=0.0,
    ),
}


def get_profile(name: str) -> Profile:
    """Retrieve strength profile by name. Raises KeyError if profile name is invalid."""
    clean = name.strip().lower()
    if clean not in PROFILES:
        valid = ", ".join(sorted(PROFILES.keys()))
        raise KeyError(f"Unknown strength profile: {name!r}. Must be one of: {valid}")
    return PROFILES[clean]
