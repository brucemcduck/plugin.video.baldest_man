"""Offline download manager — saves videos to disk for no-network playback."""
import json
import os
import re
import shutil

import requests

try:
    import xbmcaddon
except ImportError:
    xbmcaddon = None

CHUNK_SIZE = 1024 * 1024  # 1 MB
MANIFEST_NAME = "downloads.json"
ART_SUBDIR = "art"


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
    items = load_manifest()
    items.append(entry)
    save_manifest(items)


def remove_from_manifest(item_id):
    items = load_manifest()
    kept = []
    for it in items:
        if it.get('id') == item_id:
            for key in ('file_path', 'poster_path', 'thumb_path'):
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
    try:
        usage = shutil.disk_usage(os.path.dirname(path) or '.')
        return usage.free >= required_bytes * 1.05
    except OSError:
        return True


def download_video(direct_url, dest_path, cancel_check=None, progress_callback=None):
    """Stream direct_url to dest_path in 1MB chunks.
    Supports resume via HTTP Range if a .part file exists.
    Returns True on completion, False if cancelled.
    Raises DownloadError on network failure.
    """
    part_path = dest_path + '.part'
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
