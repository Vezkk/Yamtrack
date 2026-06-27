import logging

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://torrentclaw.com/api/v1"
USER_AGENT = "Yamtrack/0.25.3"


class TorrentClawClient:
    """Client for TorrentClaw torrent search API."""

    def __init__(self, api_key=None):
        self.api_key = api_key

    def _headers(self):
        headers = {
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def search(self, query, media_type=None, quality=None, verified=None, limit=50):
        """Search for content and return flat list of torrents.

        The API returns content items (movies/shows) each with a nested
        torrents[] array. This method flattens them into a single list
        of torrent dicts, enriched with the parent content metadata.
        """
        params = {"q": query, "limit": min(limit, 50)}
        if media_type:
            params["type"] = media_type
        if quality:
            params["quality"] = quality
        if verified:
            params["verified"] = "true"
        try:
            response = requests.get(
                f"{BASE_URL}/search",
                params=params,
                headers=self._headers(),
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException:
            logger.exception("TorrentClaw search failed")
            return []

        # Flatten: extract torrents from each content result
        flat_torrents = []
        for content in data.get("results", []):
            content_title = content.get("title", "")
            content_year = content.get("year", "")
            for t in content.get("torrents", []):
                # Enrich torrent with parent content info
                t["content_title"] = content_title
                t["content_year"] = content_year
                t["content_type"] = content.get("contentType", "")
                t["poster_url"] = content.get("posterUrl", "")
                flat_torrents.append(t)

        return flat_torrents

    def get_magnet(self, info_hash):
        """Get torrent file/magnet info by info hash."""
        try:
            response = requests.get(
                f"{BASE_URL}/torrent/{info_hash}",
                headers=self._headers(),
                timeout=30,
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException:
            logger.exception("TorrentClaw torrent fetch failed for %s", info_hash)
            return None
