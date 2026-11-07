"""Central place for editable point rules. Confirm values against the clan sheet."""

SCORING_RULES = {
    "war": {
        "two_attacks": 1,
        "one_attack": 0,
        "zero_attacks": -2,
        "no_participation": 0,
    },
    "cwl": {
        "missed_attack": -4,
        "expected_attacks_per_round": 1,
        "stars_14_17": 1,
        "stars_18_20": 2,
        "stars_21": 4,
    },
    "donations": {"per_1000_donated": 1},
    "clan_games": {"at_least_10000": 3, "4000_to_9999": 1, "1_to_3999": 0, "zero": -3},
    "raid_weekend": {"no_attacks": -1, "all_attacks": 1, "partial_attacks": 0},
    "inactivity": {"threshold_days": 7, "penalty_per_day": -1},
}


def points_for_war(attacks_used: int) -> int:
    if attacks_used >= 2:
        return SCORING_RULES["war"]["two_attacks"]
    if attacks_used == 1:
        return SCORING_RULES["war"]["one_attack"]
    return SCORING_RULES["war"]["zero_attacks"]


def points_for_clan_games(score: int) -> int:
    if score >= 10000:
        return SCORING_RULES["clan_games"]["at_least_10000"]
    if score >= 4000:
        return SCORING_RULES["clan_games"]["4000_to_9999"]
    if score >= 1:
        return SCORING_RULES["clan_games"]["1_to_3999"]
    return SCORING_RULES["clan_games"]["zero"]


def points_for_raid(attacks: int, attack_limit: int, bonus_attack_limit: int = 0) -> int:
    maximum = attack_limit + bonus_attack_limit
    if attacks == 0:
        return SCORING_RULES["raid_weekend"]["no_attacks"]
    if maximum > 0 and attacks >= maximum:
        return SCORING_RULES["raid_weekend"]["all_attacks"]
    return SCORING_RULES["raid_weekend"]["partial_attacks"]
