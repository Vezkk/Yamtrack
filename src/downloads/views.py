import logging

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from downloads.clients.torrentclaw import TorrentClawClient

logger = logging.getLogger(__name__)


def _get_torrentclaw_client(user):
    api_key = user.torrentclaw_api_key if user.torrentclaw_api_key else None
    return TorrentClawClient(api_key=api_key)


def _pick_best_result(results, user):
    """Pick the best torrent result based on user preferences."""
    if not results:
        return None

    filtered = [r for r in results if r.get("seeders", 0) >= user.download_min_seeders]
    if not filtered:
        filtered = results

    if user.download_prefer_verified:
        verified = [r for r in filtered if r.get("verified")]
        if verified:
            filtered = verified

    if user.download_prefer_best_quality:
        filtered.sort(key=lambda r: r.get("qualityScore", 0), reverse=True)
    else:
        filtered.sort(key=lambda r: r.get("seeders", 0), reverse=True)

    return filtered[0] if filtered else None


def _format_size(size_bytes):
    if not size_bytes:
        return "Unknown"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size_bytes) < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


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
    result = client.search(query, limit=30)

    torrents = result.get("results", [])
    if not torrents:
        return render(request, "downloads/search_results.html", {
            "torrents": [],
            "query": query,
            "media_id": media_id,
            "media_type": media_type,
            "source": source,
            "title": title,
        })

    if quality:
        torrents = [t for t in torrents if quality.lower() in str(t.get("quality", "")).lower()]
    if codec:
        torrents = [t for t in torrents if codec.lower() in str(t.get("codec", "")).lower()]
    if audio:
        torrents = [t for t in torrents if audio.lower() in str(t.get("audio", "")).lower()]
    if hdr:
        torrents = [t for t in torrents if hdr.lower() in str(t.get("hdr", "")).lower()]
    if verified:
        torrents = [t for t in torrents if t.get("verified")]
    if release_group:
        torrents = [t for t in torrents if release_group.lower() in str(t.get("releaseGroup", t.get("title", ""))).lower()]

    if sort_by == "seeders":
        torrents.sort(key=lambda t: t.get("seeders", 0), reverse=True)
    elif sort_by == "size":
        torrents.sort(key=lambda t: t.get("size", 0), reverse=True)
    else:
        torrents.sort(key=lambda t: t.get("qualityScore", 0), reverse=True)

    if mode == "instant":
        best = _pick_best_result(torrents, request.user)
        if best:
            return _add_to_transmission(request, best)
        return render(request, "downloads/download_status.html", {
            "success": False,
            "message": "No suitable torrent found matching your preferences.",
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
            "message": "No torrent selected.",
        })

    client = _get_torrentclaw_client(request.user)
    torrent_data = client.get_magnet(info_hash)

    if not torrent_data:
        return render(request, "downloads/download_status.html", {
            "success": False,
            "message": "Could not fetch torrent data from TorrentClaw.",
        })

    magnet = torrent_data.get("magnet") or torrent_data.get("magnetLink", "")
    if not magnet:
        return render(request, "downloads/download_status.html", {
            "success": False,
            "message": "No magnet link available for this torrent.",
        })

    return _add_to_transmission_with_magnet(request, magnet, title)


def _add_to_transmission(request, torrent):
    """Add a torrent result directly to Transmission."""
    info_hash = torrent.get("infoHash", "")
    title = torrent.get("title", "Unknown")
    magnet = torrent.get("magnet") or torrent.get("magnetLink", "")

    if not magnet:
        magnet_data = _get_torrentclaw_client(request.user).get_magnet(info_hash)
        if magnet_data:
            magnet = magnet_data.get("magnet") or magnet_data.get("magnetLink", "")

    if not magnet:
        return render(request, "downloads/download_status.html", {
            "success": False,
            "message": f"Could not get magnet link for: {title}",
        })

    return _add_to_transmission_with_magnet(request, magnet, title)


def _add_to_transmission_with_magnet(request, magnet, title):
    """Add a magnet link to Transmission and return status HTML."""
    user = request.user

    if not user.download_client or not user.download_client_url:
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
                "message": f"Added to Transmission: {title}",
            })
        except Exception:
            logger.exception("Failed to add torrent to Transmission")
            return render(request, "downloads/download_status.html", {
                "success": False,
                "message": f"Failed to add torrent to Transmission. Check client settings.",
            })

    return render(request, "downloads/download_status.html", {
        "success": False,
        "message": f"Unsupported download client: {user.download_client}",
    })
