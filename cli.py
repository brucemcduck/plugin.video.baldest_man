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


def main():
    """Entry point — implemented in Task 9."""
    pass


if __name__ == '__main__':
    main()
