import logging

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://torrentclaw.com/api/v1"


class TorrentClawClient:
    """Client for TorrentClaw torrent search API."""

    def __init__(self, api_key=None):
        self.api_key = api_key

    def _headers(self):
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def search(self, query, media_type=None, quality=None, verified=None, limit=50):
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
            return response.json()
        except requests.RequestException:
            logger.exception("TorrentClaw search failed")
            return {"results": []}

    def get_magnet(self, info_hash):
        try:
            response = requests.get(
                f"{BASE_URL}/torrent/{info_hash}",
                headers=self._headers(),
                timeout=30,
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException:
            logger.exception("TorrentClaw magnet fetch failed for %s", info_hash)
            return None
