#!/usr/bin/env python3
"""Standalone terminal CLI for downloading shows via the bald_man addon's
scrape/resolve/download pipeline. Run outside Kodi.

Usage:
    python3 cli.py [--segments N] [--max-size-gb N] [--dry-run]

Fully interactive: arrow-key menus for show lookup, season, episode, quality.
"""
import os
import sys
import xml.etree.ElementTree as ET


KODI_SETTINGS_PATH = os.path.expanduser(
    '~/.kodi/userdata/addon_data/plugin.video.baldest_man/settings.xml')

# Local copy of main.py's _QUALITY_RANK — not imported from main.py because
# main.py imports xbmc at module top level and is unsafe to import outside Kodi.
QUALITY_RANK = {'4k': 4, '2160p': 4, '1080p': 3, '720p': 2, '480p': 1}

QUALITY_OPTIONS = ['4K', '1080p', '720p', '480p']


def read_kodi_settings(path):
    """Parse Kodi's addon settings.xml into a dict of {id: value}.

    Returns {} on missing or unparseable file. Missing settings are absent
    from the returned dict (caller checks presence and exits 4 if required
    keys like alldebridtoken or tmdb_api_key are missing).
    """
    if not os.path.exists(path):
        return {}
    try:
        tree = ET.parse(path)
    except (ET.ParseError, OSError):
        return {}
    root = tree.getroot()
    settings = {}
    for el in root.findall('setting'):
        sid = el.get('id')
        if not sid:
            continue
        # Kodi writes the value as element text; empty settings have no text.
        settings[sid] = (el.text or '').strip()
    return settings


def _rank_quality(q_str):
    """Map a quality string to its numeric rank (0 = unknown/unranked)."""
    return QUALITY_RANK.get((q_str or '').lower(), 0)


def _parse_size_bytes(size_str):
    """Parse human-readable size string to bytes. Returns int or 0.

    Duplicated from main.py because main.py imports xbmc at module top level.
    """
    import re
    m = re.match(r'([\d.]+)\s*(GB|MB|GiB|MiB|KB|B)', str(size_str), re.IGNORECASE)
    if not m:
        return 0
    val = float(m.group(1))
    unit = m.group(2).upper()
    if unit in ('GB', 'GIB'):
        return int(val * 1073741824)
    if unit in ('MB', 'MIB'):
        return int(val * 1048576)
    if unit == 'KB':
        return int(val * 1024)
    return int(val)


def pick_best_source(sources, quality, max_gb):
    """Pick the best source dict from scraper results, or None if none pass.

    Filter: drop sources whose parsed size exceeds max_gb gigabytes.
    Sort: (1) distance from requested quality rank descending — exact match
    first, then next-best tier — (2) seeders descending, (3) size descending.
    """
    if not sources:
        return None
    max_bytes = max_gb * 1073741824
    want_rank = _rank_quality(quality)

    candidates = []
    for r in sources:
        sz = _parse_size_bytes(r.get('size', ''))
        if sz and sz > max_bytes:
            continue
        candidates.append(r)

    if not candidates:
        return None

    def sort_key(r):
        q_rank = _rank_quality(r.get('quality', ''))
        quality_distance = abs(q_rank - want_rank)
        seeders = r.get('seeders') or 0
        size_bytes = _parse_size_bytes(r.get('size', '')) or 0
        return (quality_distance, -seeders, -size_bytes)

    candidates.sort(key=sort_key)
    return candidates[0]


def main():
    """Entry point — implemented in Task 9."""
    pass


if __name__ == '__main__':
    main()
