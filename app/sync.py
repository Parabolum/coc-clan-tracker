"""Periodic, idempotent imports from the official Clash of Clans API."""
import asyncio
import logging
import os
from datetime import datetime, timezone

from . import coc_api, database
from .scoring import points_for_war, points_for_raid, SCORING_RULES

log = logging.getLogger(__name__)


def clean_tag(tag):
    return (tag or "").replace("#", "").upper()


def book_war(event_key, members, category="Krieg", attacks_per_member=2):
    for member in members:
        tag = member.get("tag")
        if not tag:
            continue
        database.upsert_member(tag, member.get("name", tag), town_hall_level=member.get("townhallLevel"))
        attacks = member.get("attacks") or []
        used = len(attacks)
        usage = points_for_war(used)
        database.book_points(tag, event_key, category, f"{used}/{attacks_per_member} Angriffe", usage)


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
        previous = database.latest_event("Krieg", {"war", "inwar", "preparation", "ended"})
        if previous and previous["event_key"] != database.get_state("last_regular_war_booked"):
            old_war = previous["payload"]
            old_clan = old_war.get("clan") or {}
            book_war(previous["event_key"], old_clan.get("members", []), "Krieg", int(old_war.get("attacksPerMember", 2) or 2))
            database.set_state("last_regular_war_booked", previous["event_key"])
        return
    if not war.get("startTime") or not clan.get("tag"):
        return
    event_key = f"war:{war['startTime']}:{clean_tag(opponent.get('tag'))}"
    database.save_event(event_key, "Krieg", state, war)
    # Speichere den letzten vollständigen Stand auch während des Krieges.
    terminal = state in {"warended", "ended", "notinwar", "not_in_war"}
    if terminal and event_key != database.get_state("last_regular_war_booked"):
        book_war(event_key, clan.get("members", []), "Krieg", int(war.get("attacksPerMember", 2) or 2))
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
                for miss_index in range(missed):
                    database.book_points(tag, event_key, "CWL", f"Angriff vergessen {miss_index + 1}", SCORING_RULES["cwl"]["missed_attack"])
                total = season_totals.setdefault(tag, {"name": member.get("name", tag), "stars": 0})
                total["stars"] += stars
        if own_war_found and own_war_completed:
            completed_rounds += 1
        else:
            all_rounds_completed = False

    expected_rounds = len(rounds)
    if all_rounds_completed and completed_rounds >= expected_rounds:
        season_bonus_key = f"cwl:{season}:season-bonus"
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
                database.book_points(tag, season_bonus_key, "CWL", f"Sterne-Bonus ({stars})", bonus)
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
    for member in season.get("members", []):
        tag = member.get("tag")
        if not tag:
            continue
        database.upsert_member(tag, member.get("name", tag))
        attacks = int(member.get("attacks", 0) or 0)
        points = points_for_raid(attacks, int(member.get("attackLimit", 0) or 0), int(member.get("bonusAttackLimit", 0) or 0))
        database.book_points(tag, key, "Überfall-Wochenende", f"{attacks} Raid-Angriffe", points)
    for tag in database.current_member_tags():
        if clean_tag(tag) not in raid_members:
            database.book_points(tag, key, "Überfall-Wochenende", "Keine Raid-Angriffe", SCORING_RULES["raid_weekend"]["no_attacks"])
    return len(season.get("members", []))


async def sync_once():
    if not (os.getenv("CLAN_TAG") and os.getenv("COC_API_TOKEN")):
        return {"status": "demo", "message": "CLAN_TAG oder COC_API_TOKEN fehlt"}
    result = {}
    for name, fn in (("members", sync_members), ("war", sync_regular_war), ("cwl", sync_cwl), ("raids", sync_raids)):
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
