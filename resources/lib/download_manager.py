"""Offline download manager — saves videos to disk for no-network playback."""
import hashlib
import json
import os
import re
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

try:
    import xbmcaddon
except ImportError:
    xbmcaddon = None

CHUNK_SIZE = 1024 * 1024  # 1 MB
MANIFEST_NAME = "downloads.json"
ART_SUBDIR = "art"

# Multi-segment parallel download defaults
DEFAULT_SEGMENTS = 4
MIN_SEGMENT_SIZE = 4 * 1024 * 1024  # don't split below 4 MB per segment
MIN_PARALLEL_SIZE = 20 * 1024 * 1024  # don't parallelize below 20 MB total
SEGMENT_TIMEOUT = (15, 600)  # (connect, read) seconds per segment
PROGRESS_POLL_INTERVAL_S = 0.1  # how often the parallel poller fires progress


class DownloadError(Exception):
    pass


def _log(msg):
    try:
        import xbmc
        xbmc.log("bald_man download: " + str(msg), level=xbmc.LOGINFO)
    except ImportError:
        import sys
        print("download: " + str(msg), file=sys.stderr)


def _addon():
    return xbmcaddon.Addon() if xbmcaddon else None


def _addon_data_dir():
    """Base dir for manifest + cached art (always writable, always exists)."""
    try:
        import xbmcvfs
        return xbmcvfs.translatePath('special://userdata/addon_data/plugin.video.baldest_man')
    except ImportError:
        return os.path.join(os.path.expanduser('~'), '.bald_man')


def get_download_dir():
    """Resolve download_path setting, fall back to addon data dir,
    ensure the directory exists. Returns absolute path."""
    addon = _addon()
    path = addon.getSetting('download_path') if addon else ''
    if not path:
        path = os.path.join(_addon_data_dir(), 'downloads')
    os.makedirs(path, exist_ok=True)
    return path


def manifest_path():
    base = _addon_data_dir()
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, MANIFEST_NAME)


def art_dir():
    p = os.path.join(_addon_data_dir(), ART_SUBDIR)
    os.makedirs(p, exist_ok=True)
    return p


def load_manifest():
    try:
        with open(manifest_path()) as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return []


def save_manifest(items):
    p = manifest_path()
    tmp = p + '.tmp'
    try:
        with open(tmp, 'w') as f:
            json.dump(items, f, indent=2)
        os.replace(tmp, p)
    except OSError as e:
        raise DownloadError("Failed to save manifest: {}".format(e))


def add_to_manifest(entry):
    """Append entry, replacing any existing entry with the same id (dedup)."""
    items = load_manifest()
    item_id = entry.get('id')
    items = [it for it in items if it.get('id') != item_id]
    items.append(entry)
    save_manifest(items)


def remove_from_manifest(item_id):
    items = load_manifest()
    kept = []
    for it in items:
        if it.get('id') == item_id:
            for key in ('file_path', 'poster_path'):
                p = it.get(key)
                if p and os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
        else:
            kept.append(it)
    save_manifest(kept)


def safe_filename(title, season=None, episode=None):
    """Build a filesystem-safe filename. Shows get SxxExx suffix."""
    name = re.sub(r'[^\w\s.-]', '', title).strip().replace(' ', '.')
    if season and episode:
        name += f".S{int(season):02d}E{int(episode):02d}"
    if len(name) > 180:
        name = name[:180]
    return name + '.mp4'


def has_space(path, required_bytes):
    """Check disk has room for required_bytes (5% headroom).
    Returns True if the check can't run (don't block downloads on unknown fs).
    """
    try:
        usage = shutil.disk_usage(os.path.dirname(path) or '.')
        return usage.free >= required_bytes * 1.05
    except OSError:
        return True


# ---------------------------------------------------------------------------
# Multi-segment parallel download helpers
# ---------------------------------------------------------------------------

def _plan_segments(total_size, num_segments, min_segment_size=MIN_SEGMENT_SIZE):
    """Split [0, total_size) into at most num_segments contiguous byte ranges.

    Returns a list of (start, end_inclusive) tuples. The last segment absorbs
    any remainder so the ranges always exactly cover [0, total_size) with no
    gaps or overlaps.

    If total_size is too small to give each segment at least min_segment_size,
    the segment count is reduced until it fits (minimum 1 segment for any
    positive total_size). Returns [] for total_size == 0.
    """
    if total_size <= 0:
        return []
    if num_segments < 1:
        num_segments = 1
    # Shrink segment count until each segment is at least min_segment_size
    while num_segments > 1 and total_size // num_segments < min_segment_size:
        num_segments -= 1
    base = total_size // num_segments
    segments = []
    for i in range(num_segments):
        start = i * base
        if i == num_segments - 1:
            end = total_size - 1
        else:
            end = start + base - 1
        segments.append((start, end))
    return segments


def _decide_mode(total_size, supports_range, num_segments, min_parallel_size=None):
    """Choose 'parallel' or 'sequential' download strategy.

    Parallel is used only when ALL hold:
      - total_size >= min_parallel_size (small files finish fast anyway)
      - num_segments > 1 (no point parallelizing one segment)
      - server advertises Accept-Ranges: bytes
      - total_size is known (> 0)

    min_parallel_size defaults to the module MIN_PARALLEL_SIZE constant,
    read at call time so tests can monkeypatch it.
    """
    if min_parallel_size is None:
        min_parallel_size = MIN_PARALLEL_SIZE
    if num_segments <= 1:
        return "sequential"
    if not supports_range:
        return "sequential"
    if total_size <= 0:
        return "sequential"
    if total_size < min_parallel_size:
        return "sequential"
    return "parallel"


def _supports_range(headers):
    """True if the response headers advertise Accept-Ranges: bytes."""
    val = headers.get('Accept-Ranges', '')
    if not val:
        return False
    return val.lower() == 'bytes'


def _part_suffix(source_id):
    """File suffix folded into .part.N filenames for source isolation."""
    if source_id:
        return '.' + hashlib.md5(source_id.encode('utf-8')).hexdigest()[:8]
    return ''


def _prepare_resume(dest_path, num_segments, source_id):
    """Return per-segment resume offsets by inspecting existing .part.N files.

    Only .part.N files whose suffix matches source_id are counted, so stale
    bytes from a different source don't corrupt the new download.
    """
    suffix = _part_suffix(source_id)
    offsets = []
    for i in range(num_segments):
        part_path = '{}{}.part.{}'.format(dest_path, suffix, i)
        if os.path.exists(part_path):
            offsets.append(os.path.getsize(part_path))
        else:
            offsets.append(0)
    return offsets


def _concat_segments(dest_path, num_segments, source_id):
    """Concatenate .part.0 .. .part.(N-1) into dest_path, removing the parts.

    Returns True on success, False if any part file is missing (caller should
    retry that segment). Parts are removed only after the final write succeeds.
    """
    suffix = _part_suffix(source_id)
    part_paths = ['{}{}.part.{}'.format(dest_path, suffix, i)
                  for i in range(num_segments)]
    for p in part_paths:
        if not os.path.exists(p):
            return False
    tmp = dest_path + '.concat'
    try:
        with open(tmp, 'wb') as out:
            for p in part_paths:
                with open(p, 'rb') as src:
                    shutil.copyfileobj(src, out, length=CHUNK_SIZE)
        os.replace(tmp, dest_path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False
    for p in part_paths:
        try:
            os.remove(p)
        except OSError:
            pass
    return True


def _download_segment(direct_url, dest_path, seg_index, start, end,
                      resume_at, source_id, cancel_check,
                      progress_state, progress_lock, total_size):
    """Download one byte range [start, end] into dest_path.part.<index>.

    Streams to disk in CHUNK_SIZE chunks. Updates the shared progress_state
    dict (seg_index -> bytes_written_for_this_segment) under progress_lock.
    Returns True on completion, False if cancelled. Raises DownloadError on
    network failure.
    """
    suffix = _part_suffix(source_id)
    part_path = '{}{}.part.{}'.format(dest_path, suffix, seg_index)
    # Range request: start from (segment start + per-segment resume offset)
    # so resume continues within this segment without re-downloading.
    fetch_start = start + resume_at
    headers = {'Range': 'bytes={}-{}'.format(fetch_start, end)}
    try:
        resp = requests.get(direct_url, headers=headers, stream=True,
                            timeout=SEGMENT_TIMEOUT)
        if resume_at and resp.status_code != 206:
            # Server ignored Range — start this segment from scratch
            resume_at = 0
            fetch_start = start
            resp.close()
            headers = {'Range': 'bytes={}-{}'.format(fetch_start, end)}
            resp = requests.get(direct_url, headers=headers, stream=True,
                                timeout=SEGMENT_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise DownloadError("Segment {} request failed: {}".format(seg_index, e))

    mode = 'ab' if resume_at else 'wb'
    written = resume_at
    try:
        with open(part_path, mode) as f:
            for chunk in resp.iter_content(CHUNK_SIZE):
                if cancel_check and cancel_check():
                    _log("segment {} cancelled".format(seg_index))
                    resp.close()
                    return False
                if chunk:
                    f.write(chunk)
                    written += len(chunk)
                    with progress_lock:
                        progress_state[seg_index] = written
        return True
    except OSError as e:
        raise DownloadError("Segment {} write failed: {}".format(seg_index, e))
    except requests.RequestException as e:
        raise DownloadError("Segment {} interrupted: {}".format(seg_index, e))
    finally:
        try:
            resp.close()
        except Exception:
            pass


def _download_parallel(direct_url, dest_path, segments, resume_offsets,
                       source_id, cancel_check, progress_callback):
    """Download all segments concurrently, then concatenate into dest_path.

    Aggregates per-segment progress and fires progress_callback(written, total,
    pct) periodically. Returns True on completion, False if cancelled.
    Raises DownloadError on any segment failure (after cancelling siblings).
    """
    total_size = segments[-1][1] + 1
    num_segments = len(segments)
    progress_state = {i: resume_offsets[i] for i in range(num_segments)}
    progress_lock = threading.Lock()

    def report():
        with progress_lock:
            written = sum(progress_state.values())
        pct = int(written / total_size * 100) if total_size else 0
        if progress_callback:
            progress_callback(written, total_size, pct)

    cancel_flag = {'cancel': False}

    def wrapped_cancel():
        return cancel_flag['cancel'] or (cancel_check and cancel_check())

    # Background thread: poll progress_state and fire progress_callback every
    # ~100ms. Without this, progress only fires when a whole segment completes,
    # which makes the Kodi progress bar appear frozen between segment
    # boundaries (e.g. 0% -> 25% -> 50% -> 75% -> 100% for 4 segments).
    stop_polling = threading.Event()

    def poll_loop():
        while not stop_polling.wait(PROGRESS_POLL_INTERVAL_S):
            report()

    poller = threading.Thread(target=poll_loop, daemon=True)
    poller.start()

    futures = []
    errors = []
    with ThreadPoolExecutor(max_workers=num_segments) as pool:
        for i, (start, end) in enumerate(segments):
            fut = pool.submit(_download_segment, direct_url, dest_path, i,
                              start, end, resume_offsets[i], source_id,
                              wrapped_cancel, progress_state, progress_lock,
                              total_size)
            futures.append(fut)
        try:
            for fut in as_completed(futures):
                try:
                    fut.result()
                except DownloadError as e:
                    errors.append(str(e))
                    cancel_flag['cancel'] = True
                report()
        finally:
            stop_polling.set()
            if errors:
                cancel_flag['cancel'] = True
                for f in futures:
                    f.cancel()

    poller.join(timeout=1.0)
    # Final flush so the callback sees 100%
    if progress_callback:
        with progress_lock:
            written = sum(progress_state.values())
        pct = int(written / total_size * 100) if total_size else 0
        progress_callback(written, total_size, pct)

    if wrapped_cancel() and not errors:
        return False
    if errors:
        raise DownloadError("Parallel download failed: {}".format(
            "; ".join(errors[:3])))

    if not _concat_segments(dest_path, num_segments, source_id):
        raise DownloadError("A segment part file went missing during concat")
    _log("parallel download complete: {}".format(dest_path))
    return True


def _download_sequential(direct_url, dest_path, source_id,
                         cancel_check, progress_callback):
    """Original single-stream download path. Used when parallel mode is not
    applicable (small file, no Range support, single segment requested).

    Returns True on completion, False if cancelled. Raises DownloadError.
    """
    suffix = _part_suffix(source_id)
    part_path = dest_path + suffix + '.part'
    resume_at = 0
    headers = {}
    if os.path.exists(part_path):
        resume_at = os.path.getsize(part_path)
        headers['Range'] = 'bytes={}-'.format(resume_at)
        _log("resuming at {} bytes".format(resume_at))

    try:
        resp = requests.get(direct_url, headers=headers, stream=True, timeout=30)
        if resume_at and resp.status_code != 206:
            resume_at = 0
            resp.close()
            resp = requests.get(direct_url, stream=True, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise DownloadError("Download request failed: {}".format(e))

    total = int(resp.headers.get('Content-Length', 0)) + resume_at
    mode = 'ab' if resume_at else 'wb'
    written = resume_at

    try:
        with open(part_path, mode) as f:
            for chunk in resp.iter_content(CHUNK_SIZE):
                if cancel_check and cancel_check():
                    _log("download cancelled by user")
                    resp.close()
                    return False
                if chunk:
                    f.write(chunk)
                    written += len(chunk)
                    if progress_callback:
                        pct = int(written / total * 100) if total else 0
                        progress_callback(written, total, pct)
        os.replace(part_path, dest_path)
        _log("download complete: {}".format(dest_path))
        return True
    except OSError as e:
        raise DownloadError("File write failed: {}".format(e))
    except requests.RequestException as e:
        raise DownloadError("Download interrupted: {}".format(e))
    finally:
        try:
            resp.close()
        except Exception:
            pass


def _probe_download(direct_url, source_id, dest_path):
    """Probe the URL to learn Content-Length and whether Range is supported.

    Sends a 1-byte Range request (bytes=0-0). A 206 response confirms Range
    support and carries the total size in Content-Range; a 200 response means
    Range is not supported and Content-Length holds the total size.

    Returns (total_size, supports_range). Raises DownloadError on failure.
    """
    try:
        resp = requests.get(direct_url, headers={'Range': 'bytes=0-0'},
                            stream=True, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise DownloadError("Download probe failed: {}".format(e))

    try:
        if resp.status_code == 206:
            # Range supported. Total size is in Content-Range: bytes 0-0/N
            cr = resp.headers.get('Content-Range', '')
            total_size = _parse_content_range_total(cr)
            if total_size <= 0:
                # Fallback: Content-Length on 206 is the range length (1),
                # so we can't get total size this way. Try Accept-Ranges +
                # a HEAD request, or just treat as unknown.
                total_size = int(resp.headers.get('Content-Length', 0))
                if total_size > 0:
                    total_size = 0  # unknown total, can't parallelize safely
            return total_size, True
        # 200 OK — server ignored Range. Total size from Content-Length.
        total_size = int(resp.headers.get('Content-Length', 0))
        # Some servers support Range but don't honor it on small files or
        # don't advertise it. Trust the header if present.
        supports_range = _supports_range(resp.headers)
        return total_size, supports_range
    finally:
        resp.close()


def _parse_content_range_total(content_range):
    """Extract total size from 'bytes 0-0/8388608' style Content-Range header."""
    try:
        slash = content_range.rindex('/')
        return int(content_range[slash + 1:])
    except (ValueError, TypeError):
        return 0


def download_video(direct_url, dest_path, cancel_check=None, progress_callback=None,
                   source_id=None, num_segments=None):
    """Stream direct_url to dest_path.

    For large files from servers that support HTTP Range, downloads N segments
    in parallel for a significant speedup on throttled/high-latency links
    (e.g. hotel WiFi). Falls back to a single sequential stream otherwise.

    Supports resume: if .part files exist for this source_id, the download
    continues from the already-written bytes (per-segment in parallel mode,
    tail-append in sequential mode).

    source_id: optional string (e.g. magnet hash) folded into the .part
    filename so resume only appends to bytes from the same source.
    num_segments: parallel segment count. None = read from addon settings
    (default 4). 1 = force sequential.
    Returns True on completion, False if cancelled.
    Raises DownloadError on network failure.
    """
    if num_segments is None:
        num_segments = _configured_segments()

    # Fast path: single segment or caller forced sequential
    if num_segments <= 1:
        return _download_sequential(direct_url, dest_path, source_id,
                                    cancel_check, progress_callback)

    # Probe the URL to learn size + Range support. The probe uses a 1-byte
    # Range request; parallel segments open their own full connections.
    total_size, supports_range = _probe_download(direct_url, source_id, dest_path)
    mode = _decide_mode(total_size, supports_range, num_segments)
    _log("download_video: mode={} size={} range={} segments={}".format(
        mode, total_size, supports_range, num_segments))

    if mode == "sequential":
        return _download_sequential(direct_url, dest_path, source_id,
                                    cancel_check, progress_callback)

    segments = _plan_segments(total_size, num_segments)
    if len(segments) <= 1:
        return _download_sequential(direct_url, dest_path, source_id,
                                    cancel_check, progress_callback)

    resume_offsets = _prepare_resume(dest_path, len(segments), source_id)
    return _download_parallel(direct_url, dest_path, segments, resume_offsets,
                              source_id, cancel_check, progress_callback)


def _configured_segments():
    """Read the download_segments addon setting, fall back to DEFAULT_SEGMENTS."""
    addon = _addon()
    if addon:
        try:
            val = addon.getSetting('download_segments')
            if val:
                n = int(val)
                if 1 <= n <= 16:
                    return n
        except (ValueError, TypeError):
            pass
    return DEFAULT_SEGMENTS


def cache_artwork(url, dest_path):
    """Download an image to dest_path, return dest_path on success or None."""
    if not url:
        return None
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        with open(dest_path, 'wb') as f:
            f.write(resp.content)
        return dest_path
    except (requests.RequestException, OSError) as e:
        _log("artwork cache failed: {}".format(e))
        return None
