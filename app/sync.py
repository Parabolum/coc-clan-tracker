"""Periodic, idempotent imports from the official Clash of Clans API."""
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from . import coc_api, database
from .scoring import points_for_war, points_for_raid, SCORING_RULES

log = logging.getLogger(__name__)


def clean_tag(tag):
    return (tag or "").replace("#", "").upper()


def parse_api_time(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%S.%fZ").replace(tzinfo=timezone.utc)
    except ValueError:
        try:
            return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
            except (ValueError, AttributeError):
                return None


def month_key(value):
    return value.strftime("%Y-%m")


def previous_month(value):
    year, month = value.year, value.month
    if month == 1:
        return f"{year - 1:04d}-12"
    return f"{year:04d}-{month - 1:02d}"


def achievement_clan_games_score(player):
    for achievement in player.get("achievements", []):
        if (achievement.get("name") or "").strip().casefold() == "games champion":
            return max(0, int(achievement.get("value", 0) or 0))
    raise ValueError("Games-Champion-Erfolg fehlt im Spielerprofil")


async def player_clan_games_score(tag):
    profile = await coc_api.get_player(tag)
    return achievement_clan_games_score(profile)


def book_war(event_key, members, category="Krieg", attacks_per_member=2, start_time=None, end_time=None):
    start_at = parse_api_time(start_time)
    end_at = parse_api_time(end_time) or start_at
    period_start = start_at.date().isoformat() if start_at else None
    period_end = end_at.date().isoformat() if end_at else None
    entries = []
    for member in members:
        tag = member.get("tag")
        if not tag:
            continue
        database.upsert_member(tag, member.get("name", tag), town_hall_level=member.get("townhallLevel"))
        attacks = member.get("attacks") or []
        used = len(attacks)
        usage = points_for_war(used)
        if usage < 0 and database.member_absent_during(tag, period_start, period_end):
            continue
        entries.append((tag, f"{used}/{attacks_per_member} Angriffe", usage))
    database.replace_event_points(event_key, category, entries)


async def sync_members():
    payload = await coc_api.get_members()
    members = payload.get("items", [])
    for member in members:
        tag = member.get("tag")
        if not tag:
            continue
        database.upsert_member(tag, member.get("name", tag), member.get("role"), member.get("townHallLevel"), is_current_clan=True)
        donated = int(member.get("donations", 0) or 0)
        month_key = datetime.now(timezone.utc).strftime('%Y-%m')
        state_key = f"donations:{month_key}:{tag}"
        previous = int(database.get_state(state_key) or donated)
        delta = max(0, donated - previous)
        remainder_key = f"donation_remainder:{month_key}:{tag}"
        remainder = int(database.get_state(remainder_key) or 0)
        per_thousand = SCORING_RULES["donations"]["per_1000_donated"]
        total_for_points = remainder + delta * per_thousand
        points = total_for_points // 1000
        database.set_state(remainder_key, total_for_points % 1000)
        if points:
            database.book_points(tag, f"donations:{month_key}:{tag}:{donated // 1000}", "Spenden", f"Spendenstand {donated}", points)
        database.set_state(state_key, donated)
    database.set_current_clan_members([member.get("tag") for member in members if member.get("tag")])
    return len(members)


async def sync_regular_war():
    war = await coc_api.get_current_war()
    state = (war.get("state") or "").lower()
    clan = war.get("clan") or {}
    opponent = war.get("opponent") or {}
    if state in {"notinwar", "not_in_war", "clannotfound", "clan_not_found"}:
        previous = database.latest_event("Krieg", {"war", "inwar", "preparation", "ended", "warended"})
        if previous and previous["event_key"] != database.get_state("last_regular_war_booked"):
            if previous["state"] in {"ended", "warended"}:
                old_war = previous["payload"]
                old_clan = old_war.get("clan") or {}
                book_war(previous["event_key"], old_clan.get("members", []), "Krieg", int(old_war.get("attacksPerMember", 2) or 2), old_war.get("startTime"), old_war.get("endTime"))
                database.set_state("last_regular_war_booked", previous["event_key"])
            elif previous["event_key"] != database.get_state("last_regular_war_unavailable"):
                log.warning("Krieg %s nicht bewertet: finales API-Ergebnis wurde verpasst", previous["event_key"])
                database.set_state("last_regular_war_unavailable", previous["event_key"])
        return
    if not war.get("startTime") or not clan.get("tag"):
        return
    event_key = f"war:{war['startTime']}:{clean_tag(opponent.get('tag'))}"
    database.save_event(event_key, "Krieg", state, war)
    # Speichere den letzten vollständigen Stand auch während des Krieges.
    terminal = state in {"warended", "ended", "notinwar", "not_in_war"}
    if terminal and event_key != database.get_state("last_regular_war_booked"):
        book_war(event_key, clan.get("members", []), "Krieg", int(war.get("attacksPerMember", 2) or 2), war.get("startTime"), war.get("endTime"))
        database.set_state("last_regular_war_booked", event_key)


async def sync_cwl():
    try:
        group = await coc_api.get_cwl_group()
    except Exception as exc:
        log.info("CWL derzeit nicht abrufbar: %s", exc)
        return 0
    clan_tag = clean_tag(os.getenv("CLAN_TAG"))
    rounds = group.get("rounds", [])
    season = group.get("season", "unknown")
    completed_rounds = 0
    all_rounds_completed = bool(rounds)
    season_totals = {}
    for round_data in rounds:
        own_war_found = False
        own_war_completed = False
        war_entries = []
        for war_tag in round_data.get("warTags", []):
            if not war_tag or war_tag == "#0":
                continue
            try:
                war = await coc_api.get_cwl_war(war_tag)
            except Exception as exc:
                log.warning("CWL-Krieg %s nicht abrufbar: %s", war_tag, exc)
                continue
            state = (war.get("state") or "").lower()
            event_key = f"cwl:{season}:{war_tag}"
            database.save_event(event_key, "CWL", state, war)
            clan = next((c for c in war.get("clans", []) if clean_tag(c.get("tag")) == clan_tag), None)
            if not clan:
                continue
            own_war_found = True
            if state not in {"warended", "ended"}:
                continue
            own_war_completed = True
            for member in clan.get("members", []):
                tag = member.get("tag")
                if not tag:
                    continue
                database.upsert_member(tag, member.get("name", tag), town_hall_level=member.get("townhallLevel"))
                attacks = member.get("attacks") or []
                stars = sum(int(a.get("stars", 0) or 0) for a in attacks)
                expected = int(war.get("attacksPerMember", SCORING_RULES["cwl"]["expected_attacks_per_round"]) or 1)
                missed = max(0, expected - len(attacks))
                war_start = parse_api_time(war.get("startTime"))
                war_end = parse_api_time(war.get("endTime")) or war_start
                absent = database.member_absent_during(
                    tag,
                    war_start.date().isoformat() if war_start else None,
                    war_end.date().isoformat() if war_end else None,
                )
                if not absent:
                    for miss_index in range(missed):
                        war_entries.append((tag, f"Angriff vergessen {miss_index + 1}", SCORING_RULES["cwl"]["missed_attack"]))
                total = season_totals.setdefault(tag, {"name": member.get("name", tag), "stars": 0})
                total["stars"] += stars
            if own_war_completed:
                database.replace_event_points(event_key, "CWL", war_entries)
        if own_war_found and own_war_completed:
            completed_rounds += 1
        else:
            all_rounds_completed = False

    expected_rounds = len(rounds)
    if all_rounds_completed and completed_rounds >= expected_rounds:
        season_bonus_key = f"cwl:{season}:season-bonus"
        bonus_entries = []
        for tag, total in season_totals.items():
            stars = total["stars"]
            if stars >= 21:
                bonus = SCORING_RULES["cwl"]["stars_21"]
            elif stars >= 18:
                bonus = SCORING_RULES["cwl"]["stars_18_20"]
            elif stars >= 14:
                bonus = SCORING_RULES["cwl"]["stars_14_17"]
            else:
                bonus = 0
            if bonus:
                bonus_entries.append((tag, f"Sterne-Bonus ({stars})", bonus))
        database.replace_event_points(season_bonus_key, "CWL", bonus_entries)
    return completed_rounds


async def sync_raids():
    payload = await coc_api.get_raid_seasons()
    seasons = payload.get("items", [])
    if not seasons:
        return 0
    season = seasons[0]
    key = f"raid:{season.get('startTime','') }:{season.get('endTime','')}"
    database.save_event(key, "Überfall-Wochenende", season.get("state", "unknown"), season)
    if (season.get("state") or "").lower() not in {"ended", "raidended"}:
        return len(season.get("members", []))
    raid_members = {clean_tag(member.get("tag")): member for member in season.get("members", []) if member.get("tag")}
    raid_started_at = parse_api_time(season.get("startTime"))
    raid_ended_at = parse_api_time(season.get("endTime")) or raid_started_at
    raid_period_start = raid_started_at.date().isoformat() if raid_started_at else None
    raid_period_end = raid_ended_at.date().isoformat() if raid_ended_at else None
    raid_entries = []
    for member in season.get("members", []):
        tag = member.get("tag")
        if not tag:
            continue
        database.upsert_member(tag, member.get("name", tag))
        attacks = int(member.get("attacks", 0) or 0)
        joined_at = parse_api_time(database.member_joined_at(tag))
        if attacks == 0 and joined_at and raid_started_at and joined_at > raid_started_at:
            # A new member may be present in the API season list with zero attacks.
            continue
        points = points_for_raid(attacks, int(member.get("attackLimit", 0) or 0), int(member.get("bonusAttackLimit", 0) or 0))
        if points < 0 and database.member_absent_during(tag, raid_period_start, raid_period_end):
            continue
        raid_entries.append((tag, f"{attacks} Raid-Angriffe", points))
    for tag in database.current_member_tags():
        if clean_tag(tag) not in raid_members:
            joined_at = parse_api_time(database.member_joined_at(tag))
            if joined_at and raid_started_at and joined_at > raid_started_at:
                # This player joined after the raid weekend started and was not present in its results.
                continue
            if not database.member_absent_during(tag, raid_period_start, raid_period_end):
                raid_entries.append((tag, "Keine Raid-Angriffe", SCORING_RULES["raid_weekend"]["no_attacks"]))
    event_created_at = raid_ended_at.strftime("%Y-%m-%d %H:%M:%S") if raid_ended_at else None
    database.replace_event_points(key, "Überfall-Wochenende", raid_entries, created_at=event_created_at)
    return len(season.get("members", []))


async def sync_clan_games():
    """Measure monthly Clan Games from each active member's cumulative achievement."""
    now = datetime.now(timezone.utc)
    season = month_key(now)
    season_start = datetime.strptime(season, "%Y-%m").replace(tzinfo=timezone.utc)
    active_tags = database.current_member_tags()
    baselines_saved = 0
    baseline_failures = 0

    # The monthly snapshot is taken before Clan Games normally begin. New joiners
    # receive their own baseline so points earned before joining are not attributed.
    for tag in active_tags:
        if database.clan_games_baseline(season, tag):
            continue
        baseline_attempt_key = f"clan_games:baseline_attempt:{season}:{tag}"
        attempt_day = now.date().isoformat()
        if database.get_state(baseline_attempt_key) == attempt_day:
            continue
        database.set_state(baseline_attempt_key, attempt_day)
        joined_at = parse_api_time(database.member_joined_at(tag))
        joined_this_month = bool(joined_at and joined_at >= season_start)
        baseline_is_timely = now.day <= 15 or joined_this_month
        try:
            score = await player_clan_games_score(tag)
        except Exception as exc:
            baseline_failures += 1
            log.warning("Clan-Spiele-Ausgangswert für %s nicht abrufbar: %s", tag, exc)
            continue
        database.save_clan_games_baseline(season, tag, score, baseline_is_timely)
        baselines_saved += 1
        if not baseline_is_timely:
            log.warning("Clan-Spiele für %s/%s nicht bewertet: Ausgangswert wurde erst nach Monatsmitte erfasst", season, tag)

    # Wait two days after the month changes to give the API time to publish final
    # achievement values. Retries happen once per day if a player profile fails.
    if now.day < 3:
        return {"season": season, "baselines_saved": baselines_saved, "baseline_failures": baseline_failures, "finalized": False}

    completed_season = previous_month(now)
    if database.get_state(f"clan_games:finalized:{completed_season}"):
        return {"season": season, "baselines_saved": baselines_saved, "baseline_failures": baseline_failures, "finalized": True}

    attempt_day = now.date().isoformat()
    attempt_key = f"clan_games:attempt:{completed_season}"
    if database.get_state(attempt_key) == attempt_day:
        return {"season": season, "baselines_saved": baselines_saved, "baseline_failures": baseline_failures, "finalized": False}
    database.set_state(attempt_key, attempt_day)

    results = []
    final_failures = 0
    current_month_start = datetime.strptime(season, "%Y-%m").replace(tzinfo=timezone.utc)
    completed_month_start = datetime.strptime(completed_season, "%Y-%m").replace(tzinfo=timezone.utc)
    for tag in active_tags:
        baseline = database.clan_games_baseline(completed_season, tag)
        if not baseline or not baseline["eligible"]:
            continue
        joined_at = parse_api_time(database.member_joined_at(tag))
        if joined_at and joined_at >= current_month_start:
            # A member who joined/rejoined after the scored month did not belong
            # to the clan during that month's participation window.
            continue
        try:
            score = await player_clan_games_score(tag)
        except Exception as exc:
            final_failures += 1
            log.warning("Clan-Spiele-Endstand für %s/%s nicht abrufbar: %s", completed_season, tag, exc)
            continue
        earned = max(0, score - int(baseline["score"]))
        joined_during_season = bool(joined_at and completed_month_start <= joined_at < current_month_start)
        points = 0 if earned == 0 and joined_during_season else points_for_clan_games(earned)
        season_end = (current_month_start.date() - timedelta(days=1)).isoformat()
        if points < 0 and database.member_absent_during(tag, completed_month_start.date().isoformat(), season_end):
            points = 0
        results.append((tag, earned, points))

    # Replacing the season entry makes retries safe and applies only to active
    # members. Former members retain their history but are never newly scored.
    for tag, earned, points in results:
        database.replace_points(
            tag,
            f"clangames:{completed_season}:{tag}",
            "Clan-Spiele",
            f"Automatisch erfasst: {earned} Punkte",
            points,
        )

    # Try again tomorrow if the API missed any active player's final profile.
    if final_failures == 0 or now.day >= 7:
        database.set_state(f"clan_games:finalized:{completed_season}", "1")
    return {
        "season": season,
        "baselines_saved": baselines_saved,
        "baseline_failures": baseline_failures,
        "scored_members": len(results),
        "finalization_failures": final_failures,
        "finalized": final_failures == 0 or now.day >= 7,
    }


async def sync_once():
    if not (os.getenv("CLAN_TAG") and os.getenv("COC_API_TOKEN")):
        return {"status": "demo", "message": "CLAN_TAG oder COC_API_TOKEN fehlt"}
    result = {}
    for name, fn in (("members", sync_members), ("war", sync_regular_war), ("cwl", sync_cwl), ("raids", sync_raids), ("clan_games", sync_clan_games)):
        if name == "clan_games" and isinstance(result.get("members"), dict):
            result[name] = {"skipped": "Mitglieder-Synchronisierung fehlgeschlagen; aktueller Clanstatus ist nicht bestätigt"}
            continue
        try:
            result[name] = await fn()
        except Exception as exc:
            log.exception("Synchronisierung %s fehlgeschlagen", name)
            result[name] = {"error": str(exc)}
    database.set_state("last_sync", datetime.now(timezone.utc).isoformat())
    return result


async def run_periodically():
    interval = max(60, int(os.getenv("SYNC_INTERVAL_SECONDS", "300")))
    while True:
        await sync_once()
        await asyncio.sleep(interval)
