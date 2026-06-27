import logging

logger = logging.getLogger(__name__)


class TransmissionClient:
    """Wrapper around transmission-rpc for Torrent-to-Transmission integration."""

    def __init__(self, url, user="", password=""):
        from urllib.parse import urlparse

        parsed = urlparse(url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 9091
        self.host = host
        self.port = port
        self.user = user
        self.password = password

    def _get_client(self):
        from transmission_rpc import Client

        kwargs = {"host": self.host, "port": self.port}
        if self.user:
            kwargs["username"] = self.user
        if self.password:
            kwargs["password"] = self.password
        return Client(**kwargs)

    def test_connection(self):
        try:
            client = self._get_client()
            client.session_stats()
            return True
        except Exception:
            logger.exception("Transmission connection test failed")
            return False

    def add_torrent(self, torrent_url=None, magnet=None, download_dir=None):
        client = self._get_client()
        kwargs = {}
        if download_dir:
            kwargs["download_dir"] = download_dir
        if magnet:
            return client.add_torrent(magnet, **kwargs)
        if torrent_url:
            return client.add_torrent(torrent_url, **kwargs)
        msg = "Either torrent_url or magnet must be provided"
        raise ValueError(msg)

    def get_torrent(self, torrent_id):
        client = self._get_client()
        return client.get_torrent(torrent_id)

    def get_torrents(self):
        client = self._get_client()
        return client.get_torrents()
