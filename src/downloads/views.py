import logging

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from downloads.clients.torrentclaw import TorrentClawClient
from downloads.models import DownloadTask

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
    """Pick the best torrent result based on user preferences with scoring."""
    if not torrents:
        return None

    # Hard filter: minimum seeders
    filtered = [t for t in torrents if t.get("seeders", 0) >= user.download_min_seeders]
    if not filtered:
        filtered = torrents

    # Hard filter: verified only (if enabled)
    if user.download_prefer_verified:
        verified = [t for t in filtered if _is_verified(t)]
        if verified:
            filtered = verified

    # Score each torrent by preference matches
    def _score(t):
        score = 0
        pref_quality = (user.download_preferred_quality or "").lower()
        pref_codec = (user.download_preferred_codec or "").lower()
        pref_audio = (user.download_preferred_audio or "").lower()
        pref_hdr = (user.download_preferred_hdr or "").lower()

        if pref_quality and pref_quality in str(t.get("quality", "")).lower():
            score += 4
        if pref_codec and pref_codec in str(t.get("codec", "")).lower():
            score += 2
        if pref_audio and pref_audio in str(t.get("audioCodec", "")).lower():
            score += 2
        if pref_hdr and pref_hdr in str(t.get("hdrType", "")).lower():
            score += 2
        if _is_verified(t):
            score += 1

        # Secondary sort key
        sort_key = t.get("qualityScore", 0) if user.download_prefer_best_quality else t.get("seeders", 0)
        return (score, sort_key)

    filtered.sort(key=_score, reverse=True)
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
            return _add_to_transmission(request, best, media_id, media_type)
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
    media_id = request.POST.get("media_id", "")
    media_type = request.POST.get("media_type", "")

    if not info_hash:
        return render(request, "downloads/download_status.html", {
            "success": False,
            "message": "No torrent selected. Please try again.",
        })

    # Build magnet directly from info_hash — works without API key
    magnet = _info_hash_to_magnet(info_hash)
    return _add_to_transmission_with_magnet(request, magnet, title, info_hash, media_id, media_type)


def _add_to_transmission(request, torrent, media_id="", media_type=""):
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

    return _add_to_transmission_with_magnet(request, magnet, title, info_hash, media_id, media_type)


def _add_to_transmission_with_magnet(request, magnet, title, info_hash="", media_id="", media_type=""):
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
            t = tc.add_torrent(magnet=magnet, download_dir=download_dir)

            # Track the download
            DownloadTask.objects.create(
                user=user,
                media_id=media_id,
                media_type=media_type,
                title=title[:500],
                info_hash=info_hash or getattr(t, "info_hash", "")[:40],
                transmission_id=getattr(t, "id", None),
            )

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


@require_GET
@login_required
def download_progress(request):
    """HTMX endpoint: return progress for active downloads on a media item."""
    media_id = request.GET.get("media_id", "")
    media_type = request.GET.get("media_type", "")

    tasks = DownloadTask.objects.filter(
        user=request.user,
        media_id=media_id,
        media_type=media_type,
        is_active=True,
    )

    from downloads.clients.transmission import TransmissionClient

    tc = None
    progress_data = []

    for task in tasks:
        if task.transmission_id is None:
            continue

        try:
            if tc is None:
                tc = TransmissionClient(
                    request.user.download_client_url,
                    request.user.download_client_user,
                    request.user.download_client_pass,
                )
            t = tc.get_torrent(task.transmission_id)

            percent = getattr(t, "percent_done", 0) * 100
            status = getattr(t, "status", "unknown")
            rate = getattr(t, "rate_download", 0)
            total = getattr(t, "total_size", 0)
            left = getattr(t, "left_until_done", 0)
            eta_seconds = getattr(t, "eta", -1)
            error_string = getattr(t, "error_string", "")

            # Format speed
            if rate > 1073741824:
                speed = f"{rate / 1073741824:.1f} GB/s"
            elif rate > 1048576:
                speed = f"{rate / 1048576:.1f} MB/s"
            elif rate > 1024:
                speed = f"{rate / 1024:.1f} KB/s"
            else:
                speed = f"{rate} B/s"

            # Format size
            if total > 1073741824:
                total_str = f"{total / 1073741824:.1f} GB"
            elif total > 1048576:
                total_str = f"{total / 1048576:.1f} MB"
            else:
                total_str = f"{total / 1024:.1f} KB"

            downloaded = total - left
            if downloaded > 1073741824:
                downloaded_str = f"{downloaded / 1073741824:.1f} GB"
            elif downloaded > 1048576:
                downloaded_str = f"{downloaded / 1048576:.1f} MB"
            else:
                downloaded_str = f"{downloaded / 1024:.1f} KB"

            # Format ETA
            import datetime as _dt
            if isinstance(eta_seconds, _dt.timedelta) and eta_seconds.total_seconds() > 0:
                total_secs = int(eta_seconds.total_seconds())
                hours, remainder = divmod(total_secs, 3600)
                minutes, seconds = divmod(remainder, 60)
                if hours > 0:
                    eta = f"{hours}h {minutes}m"
                else:
                    eta = f"{minutes}m {seconds}s"
            elif isinstance(eta_seconds, int) and eta_seconds > 0:
                hours, remainder = divmod(eta_seconds, 3600)
                minutes, seconds = divmod(remainder, 60)
                if hours > 0:
                    eta = f"{hours}h {minutes}m"
                else:
                    eta = f"{minutes}m {seconds}s"
            else:
                eta = ""

            # Mark completed
            if percent >= 100 or status == "seeding":
                task.is_active = False
                task.completed_at = timezone.now()
                task.save(update_fields=["is_active", "completed_at"])

            progress_data.append({
                "task_id": task.id,
                "title": task.title[:80],
                "percent": round(percent, 1),
                "status": status,
                "speed": speed,
                "total": total_str,
                "downloaded": downloaded_str,
                "eta": eta,
                "error": error_string,
            })

        except Exception:
            logger.exception("Failed to get progress for task %s", task.id)
            # Don't mark inactive — just skip this poll cycle. It may be a transient error.

    return render(request, "downloads/download_progress.html", {
        "tasks": progress_data,
    })
