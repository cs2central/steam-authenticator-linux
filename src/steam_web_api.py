"""
Steam Web API Service
Fetches player data, game info, and ban status from Steam's public API
"""
import aiohttp
import asyncio
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime


STEAM_API_BASE = "https://api.steampowered.com"


class SteamWebAPI:
    """Service for fetching profile data from Steam Web API"""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    def is_configured(self) -> bool:
        """Check if API key is set"""
        return bool(self.api_key)

    def set_api_key(self, api_key: str):
        """Set the Steam Web API key"""
        self.api_key = api_key

    async def _make_request(self, endpoint: str, params: Dict[str, Any] = None) -> Optional[Dict]:
        """Make a request to the Steam Web API"""
        if not self.api_key:
            logging.warning("Steam Web API key not configured")
            return None

        if not self.session:
            self.session = aiohttp.ClientSession()

        url = f"{STEAM_API_BASE}{endpoint}"
        request_params = {"key": self.api_key}
        if params:
            request_params.update(params)

        try:
            async with self.session.get(url, params=request_params) as response:
                if response.status == 403:
                    logging.error("Invalid Steam API key")
                    return None
                elif response.status != 200:
                    logging.error(f"Steam API error: {response.status}")
                    return None

                return await response.json()
        except Exception as e:
            logging.error(f"Steam API request failed: {e}")
            return None

    async def get_player_summary(self, steam_id: str) -> Optional[Dict[str, Any]]:
        """
        Get player summary information

        Returns:
            dict with: steam_id, display_name, avatar_url, profile_url,
                      visibility, persona_state, country_code, time_created
        """
        if not steam_id:
            return None

        data = await self._make_request(
            "/ISteamUser/GetPlayerSummaries/v2/",
            {"steamids": steam_id}
        )

        if not data:
            return None

        players = data.get("response", {}).get("players", [])
        if not players:
            return None

        player = players[0]

        return {
            "steam_id": player.get("steamid"),
            "display_name": player.get("personaname"),
            "avatar_url": player.get("avatarfull") or player.get("avatar"),
            "avatar_medium": player.get("avatarmedium"),
            "profile_url": player.get("profileurl"),
            "visibility": player.get("communityvisibilitystate"),  # 1=private, 3=public
            "persona_state": player.get("personastate"),  # 0=offline, 1=online, etc
            "country_code": player.get("loccountrycode"),
            "time_created": datetime.fromtimestamp(player["timecreated"]) if player.get("timecreated") else None,
            "last_logoff": datetime.fromtimestamp(player["lastlogoff"]) if player.get("lastlogoff") else None,
        }

    async def get_owned_games(self, steam_id: str) -> List[Dict[str, Any]]:
        """
        Get player's owned games with playtime

        Returns:
            List of dicts with: app_id, name, playtime_forever, playtime_2weeks, icon_url
        """
        if not steam_id:
            return []

        data = await self._make_request(
            "/IPlayerService/GetOwnedGames/v1/",
            {
                "steamid": steam_id,
                "include_appinfo": 1,
                "include_played_free_games": 1
            }
        )

        if not data:
            return []

        games = data.get("response", {}).get("games", [])

        return [
            {
                "app_id": game.get("appid"),
                "name": game.get("name"),
                "playtime_forever": game.get("playtime_forever", 0),  # minutes
                "playtime_2weeks": game.get("playtime_2weeks", 0),  # minutes
                "icon_url": f"https://media.steampowered.com/steamcommunity/public/images/apps/{game['appid']}/{game['img_icon_url']}.jpg"
                           if game.get("img_icon_url") else None,
                "last_played": datetime.fromtimestamp(game["rtime_last_played"])
                              if game.get("rtime_last_played") else None
            }
            for game in games
        ]

    async def get_player_bans(self, steam_id: str) -> Optional[Dict[str, Any]]:
        """
        Get player ban status

        Returns:
            dict with: vac_banned, vac_bans, game_bans, community_banned,
                      economy_ban, days_since_last_ban
        """
        if not steam_id:
            return None

        data = await self._make_request(
            "/ISteamUser/GetPlayerBans/v1/",
            {"steamids": steam_id}
        )

        if not data:
            return None

        players = data.get("players", [])
        if not players:
            return None

        player = players[0]

        return {
            "steam_id": player.get("SteamId"),
            "vac_banned": player.get("VACBanned", False),
            "vac_bans": player.get("NumberOfVACBans", 0),
            "game_bans": player.get("NumberOfGameBans", 0),
            "community_banned": player.get("CommunityBanned", False),
            "economy_ban": player.get("EconomyBan", "none"),  # 'none', 'probation', 'banned'
            "days_since_last_ban": player.get("DaysSinceLastBan", 0),
            "trade_banned": player.get("EconomyBan") == "banned"
        }

    async def fetch_all_player_data(self, steam_id: str) -> Dict[str, Any]:
        """
        Fetch all available data for a player in parallel

        Returns:
            dict with: summary, games, bans
        """
        if not steam_id:
            return {"summary": None, "games": [], "bans": None}

        # Fetch all data in parallel
        summary, games, bans = await asyncio.gather(
            self.get_player_summary(steam_id),
            self.get_owned_games(steam_id),
            self.get_player_bans(steam_id),
            return_exceptions=True
        )

        # Handle exceptions
        if isinstance(summary, Exception):
            logging.error(f"Failed to get player summary: {summary}")
            summary = None
        if isinstance(games, Exception):
            logging.error(f"Failed to get owned games: {games}")
            games = []
        if isinstance(bans, Exception):
            logging.error(f"Failed to get player bans: {bans}")
            bans = None

        return {
            "summary": summary,
            "games": games,
            "bans": bans
        }

    async def validate_api_key(self) -> bool:
        """Test if the API key is valid by making a simple request"""
        if not self.api_key:
            return False

        # Try to get player summary for a known Steam ID (Valve's ID)
        try:
            data = await self._make_request(
                "/ISteamUser/GetPlayerSummaries/v2/",
                {"steamids": "76561197960265728"}  # Valve's Steam ID
            )
            return data is not None
        except:
            return False


# Singleton-style convenience functions
_api_instance: Optional[SteamWebAPI] = None


def get_steam_web_api(api_key: Optional[str] = None) -> SteamWebAPI:
    """Get or create the Steam Web API instance"""
    global _api_instance
    if _api_instance is None:
        _api_instance = SteamWebAPI(api_key)
    elif api_key:
        _api_instance.set_api_key(api_key)
    return _api_instance


async def refresh_account_profile(account, api_key: str) -> bool:
    """
    Convenience function to refresh an account's profile data

    Args:
        account: SteamGuardAccount instance
        api_key: Steam Web API key

    Returns:
        True if successful, False otherwise
    """
    if not account.steamid or not api_key:
        return False

    async with SteamWebAPI(api_key) as api:
        data = await api.fetch_all_player_data(account.steamid)

        if data["summary"]:
            account.display_name = data["summary"].get("display_name", "")
            account.avatar_url = data["summary"].get("avatar_url", "")
            account.profile_visibility = data["summary"].get("visibility", 0)

        if data["games"]:
            account.total_games = len(data["games"])

        if data["bans"]:
            account.vac_banned = data["bans"].get("vac_banned", False)
            account.trade_banned = data["bans"].get("trade_banned", False)
            account.game_bans = data["bans"].get("game_bans", 0)

        return data["summary"] is not None
