#!/usr/bin/env python3
"""Unit tests for cli.py — pure helpers + fallback UI + integration flow.

Run outside Kodi:
    python3 -m unittest test_cli
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cli


SETTINGS_FIXTURE = """<settings version="2">
    <setting id="alldebridtoken">FAKE_TOKEN_123</setting>
    <setting id="tmdb_api_key">FAKE_TMDB_KEY</setting>
    <setting id="tmdb_language">en</setting>
    <setting id="offline_quality">720p</setting>
    <setting id="download_segments">4</setting>
    <setting id="max_download_size_gb">2</setting>
    <setting id="download_path"></setting>
</settings>
"""


class ReadKodiSettingsTests(unittest.TestCase):
    def test_parses_all_expected_keys(self):
        with tempfile.NamedTemporaryFile('w', suffix='.xml', delete=False) as f:
            f.write(SETTINGS_FIXTURE)
            path = f.name
        try:
            s = cli.read_kodi_settings(path)
            self.assertEqual(s['alldebridtoken'], 'FAKE_TOKEN_123')
            self.assertEqual(s['tmdb_api_key'], 'FAKE_TMDB_KEY')
            self.assertEqual(s['tmdb_language'], 'en')
            self.assertEqual(s['offline_quality'], '720p')
            self.assertEqual(s['download_segments'], '4')
            self.assertEqual(s['max_download_size_gb'], '2')
            self.assertEqual(s['download_path'], '')
        finally:
            os.unlink(path)

    def test_missing_file_returns_empty_dict(self):
        self.assertEqual(cli.read_kodi_settings('/nonexistent/path.xml'), {})

    def test_missing_key_is_absent_from_dict(self):
        fixture = """<settings><setting id="tmdb_api_key">only_key</setting></settings>"""
        with tempfile.NamedTemporaryFile('w', suffix='.xml', delete=False) as f:
            f.write(fixture)
            path = f.name
        try:
            s = cli.read_kodi_settings(path)
            self.assertEqual(s['tmdb_api_key'], 'only_key')
            self.assertNotIn('alldebridtoken', s)
        finally:
            os.unlink(path)


class PickBestSourceTests(unittest.TestCase):
    def _src(self, quality, size, seeders=10, url='magnet:fake'):
        return {
            'show_title': 'Show',
            'url': url,
            'title': 'Show.S01E01.{}.mkv'.format(quality),
            'quality': quality,
            'size': size,
            'seeders': seeders,
        }

    def test_prefers_requested_quality(self):
        sources = [
            self._src('1080p', '1.5 GB', seeders=100),
            self._src('720p', '800 MB', seeders=50),
            self._src('4k', '5 GB', seeders=5),
        ]
        best = cli.pick_best_source(sources, quality='720p', max_gb=10)
        self.assertEqual(best['quality'], '720p')

    def test_4k_matches_2160p_alias(self):
        sources = [
            self._src('2160p', '5 GB', seeders=20),
            self._src('1080p', '2 GB', seeders=100),
        ]
        best = cli.pick_best_source(sources, quality='4K', max_gb=10)
        self.assertEqual(best['quality'], '2160p')

    def test_falls_back_to_next_tier_when_no_exact_match(self):
        sources = [
            self._src('1080p', '2 GB', seeders=100),
            self._src('480p', '400 MB', seeders=10),
        ]
        best = cli.pick_best_source(sources, quality='720p', max_gb=10)
        # No 720p source — should fall back to highest available tier (1080p)
        self.assertEqual(best['quality'], '1080p')

    def test_drops_oversized_sources(self):
        sources = [
            self._src('720p', '3 GB', seeders=50),   # over 2 GB cap
            self._src('480p', '400 MB', seeders=10),  # under cap
        ]
        best = cli.pick_best_source(sources, quality='720p', max_gb=2)
        # 720p source dropped by size; falls back to 480p
        self.assertEqual(best['quality'], '480p')

    def test_breaks_ties_by_seeders_then_size(self):
        sources = [
            self._src('720p', '800 MB', seeders=30),
            self._src('720p', '900 MB', seeders=50),
        ]
        best = cli.pick_best_source(sources, quality='720p', max_gb=10)
        self.assertEqual(best['seeders'], 50)

    def test_returns_none_when_all_filtered_out(self):
        sources = [self._src('720p', '3 GB', seeders=50)]
        self.assertIsNone(cli.pick_best_source(sources, quality='720p', max_gb=1))

    def test_returns_none_on_empty_list(self):
        self.assertIsNone(cli.pick_best_source([], quality='720p', max_gb=10))

    def test_unknown_quality_falls_to_rank_0(self):
        # Sources with no quality string still get considered, ranked last
        sources = [
            self._src('', '500 MB', seeders=5),
            self._src('720p', '800 MB', seeders=10),
        ]
        best = cli.pick_best_source(sources, quality='720p', max_gb=10)
        self.assertEqual(best['quality'], '720p')


if __name__ == '__main__':
    unittest.main()
