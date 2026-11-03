import os
from urllib.parse import quote

import httpx

BASE_URL = "https://api.clashofclans.com/v1"


async def get_clan_endpoint(endpoint: str):
    token = os.getenv("COC_API_TOKEN")
    clan_tag = os.getenv("CLAN_TAG")
    if not token or not clan_tag:
        raise RuntimeError("CLAN_TAG und COC_API_TOKEN müssen in .env gesetzt sein.")
    encoded_tag = quote(clan_tag, safe="")
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            f"{BASE_URL}/clans/{encoded_tag}/{endpoint}",
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        return response.json()


async def get_endpoint(path: str):
    """Fetch a documented API path using the server-side token."""
    token = os.getenv("COC_API_TOKEN")
    if not token:
        raise RuntimeError("COC_API_TOKEN muss in .env gesetzt sein.")
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(f"{BASE_URL}/{path.lstrip('/')}", headers={"Authorization": f"Bearer {token}"})
        response.raise_for_status()
        return response.json()


async def get_members():
    return await get_clan_endpoint("members")


async def get_current_war():
    return await get_clan_endpoint("currentwar")


async def get_cwl_group():
    return await get_clan_endpoint("currentwar/leaguegroup")


async def get_raid_seasons():
    return await get_clan_endpoint("capitalraidseasons")


async def get_cwl_war(war_tag: str):
    return await get_endpoint(f"clanwarleagues/wars/{quote(war_tag, safe='')}")


async def get_player(player_tag: str):
    """Fetch a player profile, including achievement progress."""
    return await get_endpoint(f"players/{quote(player_tag, safe='')}")
