"""Jellyfin API client for outbound requests."""

import logging

import requests
from django.core.cache import cache

logger = logging.getLogger(__name__)

JELLYFIN_API_TIMEOUT = 5
JELLYFIN_LIBRARY_CACHE_TTL = 3600  # 1 hour
JELLYFIN_PAGE_SIZE = 300


def _get_headers(api_key):
    """Return headers for Jellyfin API requests."""
    return {
        "X-Emby-Authorization": (
            'MediaBrowser Client="Yamtrack", Device="Yamtrack", '
            'DeviceId="yamtrack-server", Version="1.0"'
        ),
        "X-Emby-Token": api_key,
    }


def _fetch_library_items(base_url, api_key):
    """Fetch all Movies/Series from Jellyfin with pagination.

    Returns a list of dicts with 'id' and 'provider_ids' keys.
    Results are cached for 1 hour to avoid repeated full library scans.
    """
    cache_key = f"jellyfin_library:{base_url}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    headers = _get_headers(api_key)
    all_items = []
    start_index = 0

    while True:
        params = {
            "IncludeItemTypes": "Movie,Series",
            "Fields": "ProviderIds",
            "Recursive": "true",
            "Limit": str(JELLYFIN_PAGE_SIZE),
            "StartIndex": str(start_index),
        }

        try:
            response = requests.get(
                f"{base_url}/Items",
                params=params,
                headers=headers,
                timeout=JELLYFIN_API_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()
            items = data.get("Items", [])
            total_count = data.get("TotalRecordCount", 0)

            for item in items:
                all_items.append(
                    {
                        "id": item.get("Id"),
                        "provider_ids": item.get("ProviderIds", {}),
                    }
                )

            start_index += len(items)
            if start_index >= total_count or not items:
                break

        except requests.RequestException:
            logger.debug("Jellyfin library fetch failed at offset %d", start_index, exc_info=True)
            break

    cache.set(cache_key, all_items, JELLYFIN_LIBRARY_CACHE_TTL)
    return all_items


def search_item_by_provider_ids(user, imdb_id=None, tmdb_id=None, tvdb_id=None):
    """Search for an item in Jellyfin by provider IDs.

    Checks the local cache of Jellyfin library items for an exact match.
    Returns the Jellyfin item ID if found, None otherwise.
    """
    if not user.jellyfin_url or not user.jellyfin_api_key:
        return None

    base_url = user.jellyfin_url.rstrip("/")
    items = _fetch_library_items(base_url, user.jellyfin_api_key)

    for item in items:
        provider_ids = item["provider_ids"]
        if imdb_id and provider_ids.get("Imdb") == imdb_id:
            logger.info("Jellyfin match found via IMDB: %s", item["id"])
            return item["id"]
        if tmdb_id and provider_ids.get("Tmdb") == str(tmdb_id):
            logger.info("Jellyfin match found via TMDB: %s", item["id"])
            return item["id"]
        if tvdb_id and provider_ids.get("Tvdb") == str(tvdb_id):
            logger.info("Jellyfin match found via TVDB: %s", item["id"])
            return item["id"]

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
