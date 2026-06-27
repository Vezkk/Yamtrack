"""Jellyfin API client for outbound requests."""

import logging

import requests

logger = logging.getLogger(__name__)

JELLYFIN_API_TIMEOUT = 5


def _get_headers(api_key):
    """Return headers for Jellyfin API requests."""
    return {
        "X-Emby-Authorization": (
            'MediaBrowser Client="Yamtrack", Device="Yamtrack", '
            'DeviceId="yamtrack-server", Version="1.0"'
        ),
        "X-Emby-Token": api_key,
    }


def search_item_by_provider_ids(user, imdb_id=None, tmdb_id=None):
    """Search for an item in Jellyfin by provider IDs.

    Queries all Movies/Series and checks ProviderIds for an exact match.
    Returns the Jellyfin item ID if found, None otherwise.
    """
    if not user.jellyfin_url or not user.jellyfin_api_key:
        return None

    headers = _get_headers(user.jellyfin_api_key)
    base_url = user.jellyfin_url.rstrip("/")

    url = f"{base_url}/Items"
    params = {
        "IncludeItemTypes": "Movie,Series",
        "Fields": "ProviderIds",
        "Recursive": "true",
        "Limit": "300",
    }

    try:
        response = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=JELLYFIN_API_TIMEOUT,
        )
        response.raise_for_status()
        items = response.json().get("Items", [])

        for item in items:
            provider_ids = item.get("ProviderIds", {})
            if imdb_id and provider_ids.get("Imdb") == imdb_id:
                logger.info("Jellyfin match found via IMDB: %s", item.get("Id"))
                return item.get("Id")
            if tmdb_id and provider_ids.get("Tmdb") == str(tmdb_id):
                logger.info("Jellyfin match found via TMDB: %s", item.get("Id"))
                return item.get("Id")

    except requests.RequestException:
        logger.debug("Jellyfin search failed", exc_info=True)

    return None


def get_users(server_url, api_key):
    """Fetch the list of users from a Jellyfin server.

    Returns a list of dicts with 'id' and 'name' keys, or an empty list on error.
    """
    url = f"{server_url.rstrip('/')}/Users/Public"
    try:
        response = requests.get(
            url,
            headers=_get_headers(api_key),
            timeout=JELLYFIN_API_TIMEOUT,
        )
        response.raise_for_status()
        return [{"id": u["Id"], "name": u["Name"]} for u in response.json()]
    except requests.RequestException:
        logger.debug("Failed to fetch Jellyfin users", exc_info=True)
        return []


def get_jellyfin_web_url(user, jellyfin_item_id):
    """Construct the Jellyfin web player URL for an item."""
    base_url = user.jellyfin_url.rstrip("/")
    return f"{base_url}/web/#/details?id={jellyfin_item_id}"
