import logging

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from downloads.clients.torrentclaw import TorrentClawClient

logger = logging.getLogger(__name__)


def _info_hash_to_magnet(info_hash):
    """Build a magnet link from an info hash (standard BTIH format)."""
    return f"magnet:?xt=urn:btih:{info_hash}"


def _get_torrentclaw_client(user):
    api_key = user.torrentclaw_api_key if user.torrentclaw_api_key else None
    return TorrentClawClient(api_key=api_key)


def _is_verified(torrent):
    """Check if a torrent is considered verified."""
    if torrent.get("verified"):
        return True
    if torrent.get("threatLevel") == "clean":
        return True
    if torrent.get("scanStatus") == "success":
        return True
    return False


def _pick_best_result(torrents, user):
    """Pick the best torrent result based on user preferences."""
    if not torrents:
        return None

    filtered = [t for t in torrents if t.get("seeders", 0) >= user.download_min_seeders]
    if not filtered:
        filtered = torrents

    if user.download_prefer_verified:
        verified = [t for t in filtered if _is_verified(t)]
        if verified:
            filtered = verified

    if user.download_prefer_best_quality:
        filtered.sort(key=lambda t: t.get("qualityScore", 0), reverse=True)
    else:
        filtered.sort(key=lambda t: t.get("seeders", 0), reverse=True)

    return filtered[0] if filtered else None


@require_GET
@login_required
def download_search(request):
    """HTMX endpoint: search for torrents via TorrentClaw."""
    media_id = request.GET.get("media_id", "")
    media_type = request.GET.get("media_type", "")
    source = request.GET.get("source", "tmdb")
    title = request.GET.get("title", "")
    mode = request.GET.get("mode", "instant")

    quality = request.GET.get("quality", "")
    codec = request.GET.get("codec", "")
    audio = request.GET.get("audio", "")
    hdr = request.GET.get("hdr", "")
    verified = request.GET.get("verified") == "on"
    sort_by = request.GET.get("sort", "")
    release_group = request.GET.get("release_group", "")

    query = title
    client = _get_torrentclaw_client(request.user)
    torrents = client.search(query, limit=30)

    if not torrents:
        return render(request, "downloads/search_results.html", {
            "torrents": [],
            "query": query,
            "media_id": media_id,
            "media_type": media_type,
            "source": source,
            "title": title,
        })

    # Apply client-side filters (API doesn't support all of these)
    if quality:
        torrents = [t for t in torrents if quality.lower() in str(t.get("quality", "")).lower()]
    if codec:
        torrents = [t for t in torrents if codec.lower() in str(t.get("codec", "")).lower()]
    if audio:
        torrents = [t for t in torrents if audio.lower() in str(t.get("audioCodec", "")).lower()]
    if hdr:
        torrents = [t for t in torrents if hdr.lower() in str(t.get("hdrType", "")).lower()]
    if verified:
        torrents = [t for t in torrents if _is_verified(t)]
    if release_group:
        torrents = [t for t in torrents if release_group.lower() in str(t.get("releaseGroup", t.get("rawTitle", ""))).lower()]

    # Sort
    if sort_by == "seeders":
        torrents.sort(key=lambda t: t.get("seeders", 0), reverse=True)
    elif sort_by == "size":
        torrents.sort(key=lambda t: t.get("sizeBytes", 0), reverse=True)
    else:
        torrents.sort(key=lambda t: t.get("qualityScore", 0), reverse=True)

    if mode == "instant":
        best = _pick_best_result(torrents, request.user)
        if best:
            return _add_to_transmission(request, best)
        return render(request, "downloads/download_status.html", {
            "success": False,
            "message": "No suitable torrent found matching your preferences. Try adjusting your download settings.",
        })

    return render(request, "downloads/search_results.html", {
        "torrents": torrents[:20],
        "query": query,
        "media_id": media_id,
        "media_type": media_type,
        "source": source,
        "title": title,
    })


@require_POST
@login_required
def download_add(request):
    """HTMX endpoint: add a specific torrent to Transmission."""
    info_hash = request.POST.get("info_hash", "")
    title = request.POST.get("title", "")

    if not info_hash:
        return render(request, "downloads/download_status.html", {
            "success": False,
            "message": "No torrent selected. Please try again.",
        })

    # Build magnet directly from info_hash — works without API key
    magnet = _info_hash_to_magnet(info_hash)
    return _add_to_transmission_with_magnet(request, magnet, title)


def _add_to_transmission(request, torrent):
    """Add a torrent result directly to Transmission."""
    info_hash = torrent.get("infoHash", "")
    title = torrent.get("rawTitle", torrent.get("content_title", "Unknown"))
    magnet = torrent.get("magnetUrl") or torrent.get("magnet", "")

    if not magnet and info_hash:
        magnet = _info_hash_to_magnet(info_hash)

    if not magnet:
        return render(request, "downloads/download_status.html", {
            "success": False,
            "message": f"Could not get magnet link for: {title[:60]}",
        })

    return _add_to_transmission_with_magnet(request, magnet, title)


def _add_to_transmission_with_magnet(request, magnet, title):
    """Add a magnet link to Transmission and return status HTML."""
    user = request.user

    if not user.download_client_url:
        return render(request, "downloads/download_status.html", {
            "success": False,
            "message": "Download client not configured. Go to Settings > Integrations.",
        })

    if user.download_client == "transmission":
        from downloads.clients.transmission import TransmissionClient

        tc = TransmissionClient(
            user.download_client_url,
            user.download_client_user,
            user.download_client_pass,
        )
        try:
            download_dir = user.download_default_path or None
            tc.add_torrent(magnet=magnet, download_dir=download_dir)
            return render(request, "downloads/download_status.html", {
                "success": True,
                "message": f"Added to Transmission: {title[:60]}",
            })
        except ConnectionError:
            logger.exception("Transmission connection failed")
            return render(request, "downloads/download_status.html", {
                "success": False,
                "message": "Cannot connect to Transmission. Check the client URL and ensure it is running.",
            })
        except Exception as exc:
            logger.exception("Failed to add torrent to Transmission")
            msg = str(exc) if str(exc) else "Check client settings and ensure Transmission is accessible."
            return render(request, "downloads/download_status.html", {
                "success": False,
                "message": f"Transmission error: {msg}",
            })

    return render(request, "downloads/download_status.html", {
        "success": False,
        "message": f"Unsupported download client: {user.download_client}",
    })
