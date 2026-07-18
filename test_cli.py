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


if __name__ == '__main__':
    unittest.main()
