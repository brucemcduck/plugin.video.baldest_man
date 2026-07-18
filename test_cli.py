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


class BuildQueryTests(unittest.TestCase):
    def test_zero_pads_season_and_episode(self):
        self.assertEqual(cli.build_query("Breaking Bad", 1, 3),
                         "Breaking Bad S01E03")

    def test_double_digits(self):
        self.assertEqual(cli.build_query("Show", 10, 12),
                         "Show S10E12")


class EpisodeAlreadyDownloadedTests(unittest.TestCase):
    def test_true_when_file_exists_with_matching_size(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b'x' * 1024)
            path = f.name
        try:
            self.assertTrue(cli.episode_already_downloaded(path, 1024))
        finally:
            os.unlink(path)

    def test_false_when_size_mismatches(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b'x' * 1024)
            path = f.name
        try:
            self.assertFalse(cli.episode_already_downloaded(path, 2048))
        finally:
            os.unlink(path)

    def test_false_when_file_missing(self):
        self.assertFalse(cli.episode_already_downloaded('/nonexistent.mkv', 1024))


class OptionBuilderTests(unittest.TestCase):
    def test_build_season_options_renders_count(self):
        seasons = [
            {'season_number': 1, 'episode_count': 7, 'name': 'Season 1'},
            {'season_number': 2, 'episode_count': 13, 'name': 'Season 2'},
        ]
        opts = cli.build_season_options(seasons)
        self.assertEqual(opts, [(1, 'Season 1 (7 episodes)'),
                                (2, 'Season 2 (13 episodes)')])

    def test_build_season_options_uses_name_when_present(self):
        seasons = [{'season_number': 1, 'episode_count': 7, 'name': 'Breaking Bad'}]
        opts = cli.build_season_options(seasons)
        self.assertEqual(opts[0], (1, 'Breaking Bad (7 episodes)'))

    def test_build_season_options_empty_list(self):
        self.assertEqual(cli.build_season_options([]), [])

    def test_build_episode_options_prepends_whole_season(self):
        episodes = [
            {'episode_number': 1, 'name': 'Seven Thirty-Seven'},
            {'episode_number': 2, 'name': 'Grilled'},
        ]
        opts = cli.build_episode_options(episodes)
        self.assertEqual(opts[0], ('all', 'Whole season'))
        self.assertEqual(opts[1], (1, 'E1 — Seven Thirty-Seven'))
        self.assertEqual(opts[2], (2, 'E2 — Grilled'))

    def test_build_episode_options_handles_missing_name(self):
        episodes = [{'episode_number': 3, 'name': ''}]
        opts = cli.build_episode_options(episodes)
        self.assertEqual(opts[1], (3, 'E3'))

    def test_build_quality_options_returns_four_tiers(self):
        opts, default_idx = cli.build_quality_options(default='720p')
        self.assertEqual([v for v, _ in opts], ['4K', '1080p', '720p', '480p'])
        self.assertEqual(default_idx, 2)  # 720p is 3rd (0-indexed 2)

    def test_build_quality_options_unknown_default_uses_first(self):
        opts, default_idx = cli.build_quality_options(default='unknown')
        self.assertEqual(default_idx, 0)


class ArrowSelectFallbackTests(unittest.TestCase):
    def test_returns_selected_value(self):
        opts = [(1, 'one'), (2, 'two'), (3, 'three')]
        inputs = iter(['2'])
        result = cli.arrow_select_fallback(opts, 'Pick: ', input_fn=lambda _: next(inputs))
        self.assertEqual(result, 2)

    def test_first_option_is_index_one(self):
        opts = [('a', 'A'), ('b', 'B')]
        inputs = iter(['1'])
        result = cli.arrow_select_fallback(opts, 'Pick: ', input_fn=lambda _: next(inputs))
        self.assertEqual(result, 'a')

    def test_re_prompts_on_out_of_range(self):
        opts = [(1, 'one'), (2, 'two')]
        inputs = iter(['0', '5', '2'])
        result = cli.arrow_select_fallback(opts, 'Pick: ', input_fn=lambda _: next(inputs))
        self.assertEqual(result, 2)

    def test_re_prompts_on_non_integer(self):
        opts = [(1, 'one'), (2, 'two')]
        inputs = iter(['x', '1'])
        result = cli.arrow_select_fallback(opts, 'Pick: ', input_fn=lambda _: next(inputs))
        self.assertEqual(result, 1)

    def test_q_raises_keyboard_interrupt(self):
        opts = [(1, 'one')]
        with self.assertRaises(KeyboardInterrupt):
            cli.arrow_select_fallback(opts, 'Pick: ', input_fn=lambda _: 'q')


class SearchAndPickFallbackTests(unittest.TestCase):
    def test_returns_chosen_match(self):
        matches = [
            {'id': 1, 'title': 'Breaking Bad', 'year': '2008'},
            {'id': 2, 'title': 'Better Call Saul', 'year': '2015'},
        ]
        def fake_search(query):
            return matches
        inputs = iter(['breaking bad', '1'])
        result = cli.search_and_pick_fallback(fake_search, input_fn=lambda _: next(inputs))
        self.assertEqual(result['id'], 1)

    def test_re_prompts_on_empty_query(self):
        matches = [{'id': 1, 'title': 'Show', 'year': '2000'}]
        def fake_search(query):
            return matches
        inputs = iter(['', 'show', '1'])
        result = cli.search_and_pick_fallback(fake_search, input_fn=lambda _: next(inputs))
        self.assertEqual(result['id'], 1)

    def test_returns_none_on_zero_tmdb_matches(self):
        def fake_search(query):
            return []
        inputs = iter(['unknown show'])
        result = cli.search_and_pick_fallback(fake_search, input_fn=lambda _: next(inputs))
        self.assertIsNone(result)

    def test_q_during_pick_raises_keyboard_interrupt(self):
        matches = [{'id': 1, 'title': 'Show', 'year': '2000'}]
        def fake_search(query):
            return matches
        inputs = iter(['show', 'q'])
        with self.assertRaises(KeyboardInterrupt):
            cli.search_and_pick_fallback(fake_search, input_fn=lambda _: next(inputs))


if __name__ == '__main__':
    unittest.main()
