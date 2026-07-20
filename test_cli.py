#!/usr/bin/env python3
"""Unit tests for cli.py — pure helpers + fallback UI + integration flow.

Run outside Kodi:
    python3 -m unittest test_cli
"""
import json
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

    def test_prefers_higher_tier_on_distance_tie(self):
        """When two tiers are equidistant from requested, higher tier wins
        regardless of seeder count."""
        sources = [
            self._src('480p', '400 MB', seeders=100),
            self._src('1080p', '2 GB', seeders=5),
        ]
        best = cli.pick_best_source(sources, quality='720p', max_gb=10)
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

    def test_strips_apostrophes(self):
        self.assertEqual(cli.build_query("It's Always Sunny", 1, 1),
                         "Its Always Sunny S01E01")

    def test_strips_smart_quotes(self):
        self.assertEqual(cli.build_query("It\u2019s Always Sunny", 1, 1),
                         "Its Always Sunny S01E01")


class BuildMovieQueryTests(unittest.TestCase):
    def test_includes_year_when_present(self):
        self.assertEqual(cli.build_movie_query("Inception", "2010"),
                         "Inception 2010")

    def test_omits_year_when_empty(self):
        self.assertEqual(cli.build_movie_query("Inception", ""),
                         "Inception")

    def test_omits_year_when_none(self):
        self.assertEqual(cli.build_movie_query("Inception", None),
                         "Inception")

    def test_strips_apostrophes(self):
        self.assertEqual(cli.build_movie_query("The Boss's Movie", "2020"),
                         "The Bosss Movie 2020")

    def test_strips_smart_quotes(self):
        self.assertEqual(cli.build_movie_query("It\u2019s a Movie", "2021"),
                         "Its a Movie 2021")


class SearchWithRetryTests(unittest.TestCase):
    def test_returns_first_results_without_retry(self):
        calls = []
        def fake_search(query, content_type='shows'):
            calls.append(query)
            return [{'show_title': 'Test', 'url': 'magnet:...', 'title': 'T',
                     'quality': '720p', 'size': '1 GB', 'seeders': 5}]
        orig = cli.scraper_runner.search_all
        cli.scraper_runner.search_all = fake_search
        try:
            result = cli._search_with_retry("Breaking Bad S01E01")
            self.assertEqual(len(result), 1)
            self.assertEqual(len(calls), 1)
        finally:
            cli.scraper_runner.search_all = orig

    def test_retries_shorter_query_on_zero_results(self):
        calls = []
        def fake_search(query, content_type='shows'):
            calls.append(query)
            if query == "Always Sunny in Philadelphia S01E01":
                return [{'show_title': 'Test', 'url': 'magnet:...', 'title': 'T',
                         'quality': '720p', 'size': '1 GB', 'seeders': 5}]
            return []
        orig = cli.scraper_runner.search_all
        cli.scraper_runner.search_all = fake_search
        try:
            result = cli._search_with_retry("Its Always Sunny in Philadelphia S01E01")
            self.assertEqual(len(result), 1)
            self.assertGreater(len(calls), 1)
            self.assertIn("Always Sunny in Philadelphia S01E01", calls)
        finally:
            cli.scraper_runner.search_all = orig

    def test_returns_empty_when_all_retries_fail(self):
        def fake_search(query, content_type='shows'):
            return []
        orig = cli.scraper_runner.search_all
        cli.scraper_runner.search_all = fake_search
        try:
            result = cli._search_with_retry("Some Show S01E01")
            self.assertEqual(result, [])
        finally:
            cli.scraper_runner.search_all = orig

    def test_no_retry_for_single_word_title(self):
        calls = []
        def fake_search(query, content_type='shows'):
            calls.append(query)
            return []
        orig = cli.scraper_runner.search_all
        cli.scraper_runner.search_all = fake_search
        try:
            result = cli._search_with_retry("Show S01E01")
            self.assertEqual(result, [])
            self.assertEqual(len(calls), 1)
        finally:
            cli.scraper_runner.search_all = orig


class CleanupPartFilesTests(unittest.TestCase):
    def test_removes_unsuffixed_part_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, 'video.mp4')
            for i in range(4):
                with open('{}.part.{}'.format(dest, i), 'wb') as f:
                    f.write(b'x' * 100)
            cli._cleanup_part_files(dest)
            for i in range(4):
                self.assertFalse(os.path.exists('{}.part.{}'.format(dest, i)))

    def test_removes_source_suffixed_part_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, 'video.mp4')
            for i in range(4):
                with open('{}.abc12345.part.{}'.format(dest, i), 'wb') as f:
                    f.write(b'x' * 100)
            cli._cleanup_part_files(dest)
            for i in range(4):
                self.assertFalse(os.path.exists('{}.abc12345.part.{}'.format(dest, i)))

    def test_removes_concat_temp(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, 'video.mp4')
            with open(dest + '.concat', 'wb') as f:
                f.write(b'partial')
            cli._cleanup_part_files(dest)
            self.assertFalse(os.path.exists(dest + '.concat'))

    def test_preserves_final_completed_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, 'video.mp4')
            with open(dest, 'wb') as f:
                f.write(b'complete')
            cli._cleanup_part_files(dest)
            self.assertTrue(os.path.exists(dest))

    def test_preserves_unrelated_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, 'video.mp4')
            other = os.path.join(tmp, 'other.mp4')
            with open(other + '.part.0', 'wb') as f:
                f.write(b'unrelated')
            cli._cleanup_part_files(dest)
            self.assertTrue(os.path.exists(other + '.part.0'))

    def test_no_error_when_nothing_to_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, 'video.mp4')
            # Should not raise even though no .part files exist
            cli._cleanup_part_files(dest)


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


class SearchAndPickLabelTests(unittest.TestCase):
    def test_fallback_uses_label_media_for_display(self):
        matches = [
            {'id': 1, 'title': 'Breaking Bad', 'year': '2008', 'type': 'show'},
            {'id': 2, 'title': 'Inception', 'year': '2010', 'type': 'movie'},
        ]
        def fake_search(query):
            return matches
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        inputs = iter(['test', '1'])
        with redirect_stdout(buf):
            result = cli.search_and_pick_fallback(
                fake_search, input_fn=lambda _: next(inputs))
        output = buf.getvalue()
        self.assertIn('[Show]', output)
        self.assertIn('[Movie]', output)
        self.assertEqual(result['id'], 1)


class SearchAllTypesTests(unittest.TestCase):
    def test_merges_shows_and_movies_with_type_tag(self):
        shows = [{'id': 1, 'title': 'Breaking Bad', 'year': '2008'}]
        movies = [{'id': 2, 'title': 'Inception', 'year': '2010'}]
        orig_shows = cli.tmdb.search_shows
        orig_movies = cli.tmdb.search_movies
        cli.tmdb.search_shows = lambda q, k, l: shows
        cli.tmdb.search_movies = lambda q, k, l: movies
        try:
            results = cli._search_all_types('test', {'tmdb_api_key': 'x'})
        finally:
            cli.tmdb.search_shows = orig_shows
            cli.tmdb.search_movies = orig_movies
        self.assertEqual(len(results), 2)
        types = {r.get('type') for r in results}
        self.assertEqual(types, {'show', 'movie'})
        show_item = [r for r in results if r['type'] == 'show'][0]
        self.assertEqual(show_item['title'], 'Breaking Bad')
        movie_item = [r for r in results if r['type'] == 'movie'][0]
        self.assertEqual(movie_item['title'], 'Inception')

    def test_empty_results_when_both_empty(self):
        orig_shows = cli.tmdb.search_shows
        orig_movies = cli.tmdb.search_movies
        cli.tmdb.search_shows = lambda q, k, l: []
        cli.tmdb.search_movies = lambda q, k, l: []
        try:
            results = cli._search_all_types('test', {'tmdb_api_key': 'x'})
        finally:
            cli.tmdb.search_shows = orig_shows
            cli.tmdb.search_movies = orig_movies
        self.assertEqual(results, [])

    def test_calls_both_apis_with_same_query(self):
        calls = {'shows': [], 'movies': []}
        orig_shows = cli.tmdb.search_shows
        orig_movies = cli.tmdb.search_movies
        cli.tmdb.search_shows = lambda q, k, l: calls['shows'].append(q) or []
        cli.tmdb.search_movies = lambda q, k, l: calls['movies'].append(q) or []
        try:
            cli._search_all_types('inception', {'tmdb_api_key': 'x', 'tmdb_language': 'en'})
        finally:
            cli.tmdb.search_shows = orig_shows
            cli.tmdb.search_movies = orig_movies
        self.assertEqual(calls['shows'], ['inception'])
        self.assertEqual(calls['movies'], ['inception'])


class DownloadEpisodeTests(unittest.TestCase):
    """Integration test for download_episode with mocked TMDB/AllDebrid
    and a local throttled Range-supporting HTTP server (same pattern as
    test_download_manager.py's ParallelDownloadIntegrationTests).
    """
    def setUp(self):
        import http.server
        import socketserver
        import threading
        import time
        self.tmp = tempfile.mkdtemp()
        # 4 MB payload — small enough for fast tests, large enough that the
        # parallel downloader is exercised when MIN_PARALLEL_SIZE is lowered.
        self.payload = bytes((i * 7 + 13) & 0xFF for i in range(4 * 1024 * 1024))
        self.served_path = os.path.join(self.tmp, 'source.bin')
        with open(self.served_path, 'wb') as f:
            f.write(self.payload)

        # Lower the parallel threshold so the 4 MB payload uses parallel mode
        from resources.lib import download_manager as dm
        self._orig_min_parallel = dm.MIN_PARALLEL_SIZE
        dm.MIN_PARALLEL_SIZE = 1024 * 1024  # 1 MB

        # Patch get_download_dir so tests write into the temp dir instead of
        # the user's real ~/.bald_man/downloads/ folder.
        self._orig_get_download_dir = dm.get_download_dir
        _downloads_dir = os.path.join(self.tmp, 'downloads')
        os.makedirs(_downloads_dir, exist_ok=True)
        dm.get_download_dir = lambda: _downloads_dir

        class RangeThrottledHandler(http.server.SimpleHTTPRequestHandler):
            CHUNK_DELAY_S = 0.002
            protocol_version = 'HTTP/1.1'

            def do_GET(self):
                path = self.translate_path(self.path)
                try:
                    f = open(path, 'rb')
                except OSError:
                    self.send_error(404)
                    return
                try:
                    fs = os.fstat(f.fileno())
                    total = fs.st_size
                    range_header = self.headers.get('Range')
                    if range_header and range_header.startswith('bytes='):
                        spec = range_header[6:]
                        parts = spec.split('-', 1)
                        start = int(parts[0]) if parts[0] else 0
                        end = int(parts[1]) if parts[1] else total - 1
                        end = min(end, total - 1)
                        length = end - start + 1
                        self.send_response(206)
                        self.send_header('Content-Type', 'application/octet-stream')
                        self.send_header('Content-Length', str(length))
                        self.send_header('Content-Range',
                                         'bytes {}-{}/{}'.format(start, end, total))
                        self.send_header('Accept-Ranges', 'bytes')
                        self.end_headers()
                        f.seek(start)
                        remaining = length
                        while remaining > 0:
                            buf = f.read(min(65536, remaining))
                            if not buf:
                                break
                            self.wfile.write(buf)
                            self.wfile.flush()
                            time.sleep(self.CHUNK_DELAY_S)
                            remaining -= len(buf)
                    else:
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/octet-stream')
                        self.send_header('Content-Length', str(total))
                        self.send_header('Accept-Ranges', 'bytes')
                        self.end_headers()
                        while True:
                            buf = f.read(65536)
                            if not buf:
                                break
                            self.wfile.write(buf)
                            self.wfile.flush()
                            time.sleep(self.CHUNK_DELAY_S)
                finally:
                    f.close()

            def log_message(self, *a, **kw):
                pass

        socketserver.TCPServer.allow_reuse_address = True
        self.httpd = socketserver.ThreadingTCPServer(
            ('127.0.0.1', 0), RangeThrottledHandler)
        self.port = self.httpd.server_address[1]
        self.server_thread = threading.Thread(target=self.httpd.serve_forever,
                                              daemon=True)
        self.server_thread.start()
        self.file_url = 'http://127.0.0.1:{}/source.bin'.format(self.port)
        self._orig_cwd = os.getcwd()
        os.chdir(self.tmp)

    def tearDown(self):
        import shutil
        os.chdir(self._orig_cwd)
        from resources.lib import download_manager as dm
        dm.MIN_PARALLEL_SIZE = self._orig_min_parallel
        dm.get_download_dir = self._orig_get_download_dir
        self.httpd.shutdown()
        self.httpd.server_close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_downloads_episode_and_adds_to_manifest(self):
        """End-to-end: mocked scrape returns one source, mocked resolve
        returns the local file URL, download_video fetches it, manifest
        gets a new entry with the expected shape."""
        from resources.lib import download_manager as dm

        show = {'id': 1396, 'title': 'Breaking Bad', 'year': '2008',
                'poster_url': None}
        fake_source = {
            'show_title': 'Breaking Bad',
            'url': 'magnet:fake',
            'title': 'Breaking.Bad.S01E03.720p.mkv',
            'quality': '720p',
            'size': '4 MB',
            'seeders': 50,
        }

        # Patch scraper_runner.search_all to return our fake source
        orig_search_all = cli.scraper_runner.search_all
        cli.scraper_runner.search_all = lambda q, content_type='all': [fake_source]

        # Patch alldebrid.resolve to return the local file URL
        orig_resolve = cli.alldebrid.resolve
        cli.alldebrid.resolve = lambda url, api_key, **kw: self.file_url

        # Patch tmdb.get_imdb_id to return a fake imdb id
        orig_get_imdb = cli.tmdb.get_imdb_id
        cli.tmdb.get_imdb_id = lambda show_id, api_key, is_movie=False: 'tt0903747'

        # Point manifest at a temp file so we don't clobber the real one
        orig_manifest_path = dm.manifest_path
        self.manifest_path = os.path.join(self.tmp, 'downloads.json')
        dm.manifest_path = lambda: self.manifest_path

        settings = {
            'alldebridtoken': 'FAKE',
            'tmdb_api_key': 'FAKE',
            'offline_quality': '720p',
            'download_segments': '4',
            'max_download_size_gb': '10',
        }

        try:
            ok = cli.download_episode(
                show, season=1, episode=3, quality='720p',
                settings=settings, dry_run=False)
            self.assertTrue(ok)

            # File landed on disk with the right content
            dest = os.path.join(dm.get_download_dir(),
                                'Breaking.Bad.S01E03.mp4')
            self.assertTrue(os.path.exists(dest))
            with open(dest, 'rb') as f:
                self.assertEqual(f.read(), self.payload)

            # Manifest has one entry with the expected shape
            import json
            with open(self.manifest_path) as f:
                manifest = json.load(f)
            self.assertEqual(len(manifest), 1)
            entry = manifest[0]
            self.assertEqual(entry['show_title'], 'Breaking Bad')
            self.assertEqual(entry['season'], 1)
            self.assertEqual(entry['episode'], 3)
            self.assertEqual(entry['mediatype'], 'episode')
            self.assertIn('file_path', entry)
            self.assertIn('date_added', entry)
        finally:
            cli.scraper_runner.search_all = orig_search_all
            cli.alldebrid.resolve = orig_resolve
            cli.tmdb.get_imdb_id = orig_get_imdb
            dm.manifest_path = orig_manifest_path

    def test_cancelled_download_cleans_up_part_files(self):
        """When download_video returns False (cancelled), partial files
        are removed so the download dir isn't littered with .part.N files."""
        from resources.lib import download_manager as dm

        show = {'id': 1396, 'title': 'Breaking Bad', 'year': '2008',
                'poster_url': None}
        settings = {
            'alldebridtoken': 'x',
            'tmdb_api_key': 'x',
            'tmdb_language': 'en',
            'offline_quality': '720p',
            'download_segments': '4',
            'max_download_size_gb': '2',
            'magnet_timeout': '120',
        }

        fake_source = {
            'show_title': 'Breaking Bad',
            'url': 'magnet:?fake',
            'title': 'Breaking.Bad.S01E01.720p',
            'quality': '720p',
            'size': '800 MB',
            'seeders': 10,
        }
        orig_search_all = cli.scraper_runner.search_all
        orig_resolve = cli.alldebrid.resolve
        orig_download_video = cli.download_manager.download_video
        orig_manifest_path = dm.manifest_path
        cli.scraper_runner.search_all = lambda q, content_type='all': [fake_source]
        cli.alldebrid.resolve = lambda url, api_key, **kw: 'http://example.com/x'
        dm.manifest_path = os.path.join(self.tmp, 'manifest.json')

        # Pre-create some .part files to simulate a partial download
        dest_dir = dm.get_download_dir()
        dest = os.path.join(dest_dir, 'Breaking.Bad.S01E01.mp4')
        for i in range(4):
            with open('{}.part.{}'.format(dest, i), 'wb') as f:
                f.write(b'partial')

        # Patch download_video to return False (cancelled)
        def fake_download(direct_url, dest_path, **kw):
            return False
        cli.download_manager.download_video = fake_download

        try:
            result = cli.download_episode(show, 1, 1, '720p', settings)
            self.assertFalse(result)
            # All .part files should be gone
            for i in range(4):
                self.assertFalse(
                    os.path.exists('{}.part.{}'.format(dest, i)),
                    'part file {} was not cleaned up'.format(i))
        finally:
            cli.scraper_runner.search_all = orig_search_all
            cli.alldebrid.resolve = orig_resolve
            cli.download_manager.download_video = orig_download_video
            dm.manifest_path = orig_manifest_path

    def test_keyboard_interrupt_during_download_cleans_up_part_files(self):
        """When user hits Ctrl-C during download_video, partial files
        are removed before KeyboardInterrupt propagates."""
        from resources.lib import download_manager as dm

        show = {'id': 1396, 'title': 'Breaking Bad', 'year': '2008',
                'poster_url': None}
        settings = {
            'alldebridtoken': 'x',
            'tmdb_api_key': 'x',
            'tmdb_language': 'en',
            'offline_quality': '720p',
            'download_segments': '4',
            'max_download_size_gb': '2',
            'magnet_timeout': '120',
        }

        fake_source = {
            'show_title': 'Breaking Bad',
            'url': 'magnet:?fake',
            'title': 'Breaking.Bad.S01E01.720p',
            'quality': '720p',
            'size': '800 MB',
            'seeders': 10,
        }
        orig_search_all = cli.scraper_runner.search_all
        orig_resolve = cli.alldebrid.resolve
        orig_download_video = cli.download_manager.download_video
        orig_manifest_path = dm.manifest_path
        cli.scraper_runner.search_all = lambda q, content_type='all': [fake_source]
        cli.alldebrid.resolve = lambda url, api_key, **kw: 'http://example.com/x'
        dm.manifest_path = os.path.join(self.tmp, 'manifest.json')

        dest_dir = dm.get_download_dir()
        dest = os.path.join(dest_dir, 'Breaking.Bad.S01E01.mp4')
        for i in range(4):
            with open('{}.part.{}'.format(dest, i), 'wb') as f:
                f.write(b'partial')

        def raise_kbi(*a, **kw):
            raise KeyboardInterrupt
        cli.download_manager.download_video = raise_kbi

        try:
            with self.assertRaises(KeyboardInterrupt):
                cli.download_episode(show, 1, 1, '720p', settings)
            for i in range(4):
                self.assertFalse(
                    os.path.exists('{}.part.{}'.format(dest, i)),
                    'part file {} was not cleaned up on Ctrl-C'.format(i))
        finally:
            cli.scraper_runner.search_all = orig_search_all
            cli.alldebrid.resolve = orig_resolve
            cli.download_manager.download_video = orig_download_video
            dm.manifest_path = orig_manifest_path


class DownloadMovieTests(unittest.TestCase):
    """Integration test for download_movie with mocked scrape/resolve
    and a local throttled Range-supporting HTTP server. Same setUp/tearDown
    pattern as DownloadEpisodeTests."""
    def setUp(self):
        # Reuse the same HTTP server setup as DownloadEpisodeTests.
        # Inline copy because DownloadEpisodeTests.setUp isn't inherited.
        import http.server
        import socketserver
        import threading
        import time
        self.tmp = tempfile.mkdtemp()
        self.payload = b'X' * (4 * 1024 * 1024)
        src = os.path.join(self.tmp, 'source.bin')
        with open(src, 'wb') as f:
            f.write(self.payload)

        outer = self
        class RangeThrottledHandler(http.server.BaseHTTPRequestHandler):
            CHUNK_DELAY_S = 0.005
            def do_GET(self):
                with open(src, 'rb') as f:
                    fs = os.fstat(f.fileno())
                    total = fs.st_size
                    range_header = self.headers.get('Range')
                    if range_header and range_header.startswith('bytes='):
                        spec = range_header[6:]
                        parts = spec.split('-', 1)
                        start = int(parts[0]) if parts[0] else 0
                        end = int(parts[1]) if parts[1] else total - 1
                        end = min(end, total - 1)
                        length = end - start + 1
                        self.send_response(206)
                        self.send_header('Content-Type', 'application/octet-stream')
                        self.send_header('Content-Length', str(length))
                        self.send_header('Content-Range',
                                         'bytes {}-{}/{}'.format(start, end, total))
                        self.send_header('Accept-Ranges', 'bytes')
                        self.end_headers()
                        f.seek(start)
                        remaining = length
                        while remaining > 0:
                            buf = f.read(min(65536, remaining))
                            if not buf:
                                break
                            self.wfile.write(buf)
                            self.wfile.flush()
                            time.sleep(self.CHUNK_DELAY_S)
                            remaining -= len(buf)
                    else:
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/octet-stream')
                        self.send_header('Content-Length', str(total))
                        self.send_header('Accept-Ranges', 'bytes')
                        self.end_headers()
                        while True:
                            buf = f.read(65536)
                            if not buf:
                                break
                            self.wfile.write(buf)
                            self.wfile.flush()
                            time.sleep(self.CHUNK_DELAY_S)
            def log_message(self, *a, **kw):
                pass

        socketserver.TCPServer.allow_reuse_address = True
        self.httpd = socketserver.ThreadingTCPServer(
            ('127.0.0.1', 0), RangeThrottledHandler)
        self.port = self.httpd.server_address[1]
        self.server_thread = threading.Thread(target=self.httpd.serve_forever,
                                              daemon=True)
        self.server_thread.start()
        self.file_url = 'http://127.0.0.1:{}/source.bin'.format(self.port)
        self._orig_cwd = os.getcwd()
        os.chdir(self.tmp)
        from resources.lib import download_manager as dm
        self._orig_min_parallel = dm.MIN_PARALLEL_SIZE
        dm.MIN_PARALLEL_SIZE = 0
        self._orig_get_download_dir = dm.get_download_dir
        dm.get_download_dir = lambda: self.tmp
        self._orig_art_dir = dm.art_dir
        dm.art_dir = lambda: self.tmp

    def tearDown(self):
        import shutil
        os.chdir(self._orig_cwd)
        from resources.lib import download_manager as dm
        dm.MIN_PARALLEL_SIZE = self._orig_min_parallel
        dm.get_download_dir = self._orig_get_download_dir
        dm.art_dir = self._orig_art_dir
        self.httpd.shutdown()
        self.httpd.server_close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_downloads_movie_and_adds_to_manifest(self):
        from resources.lib import download_manager as dm
        movie = {'id': 27205, 'title': 'Inception', 'year': '2010',
                 'poster_url': None, 'type': 'movie'}
        settings = {
            'alldebridtoken': 'x',
            'tmdb_api_key': 'x',
            'tmdb_language': 'en',
            'offline_quality': '720p',
            'download_segments': '4',
            'max_download_size_gb': '2',
            'magnet_timeout': '120',
        }
        fake_source = {
            'show_title': 'Inception',
            'url': 'magnet:?fake',
            'title': 'Inception.2010.1080p',
            'quality': '1080p',
            'size': '800 MB',
            'seeders': 10,
        }
        orig_search_all = cli.scraper_runner.search_all
        orig_resolve = cli.alldebrid.resolve
        orig_manifest_path = dm.manifest_path
        cli.scraper_runner.search_all = lambda q, content_type='all': [fake_source]
        cli.alldebrid.resolve = lambda url, api_key, **kw: self.file_url
        # add_to_manifest calls manifest_path() as a function, so we must
        # patch with a callable (matching DownloadEpisodeTests pattern).
        self.manifest_path = os.path.join(self.tmp, 'manifest.json')
        dm.manifest_path = lambda: self.manifest_path
        try:
            result = cli.download_movie(movie, '720p', settings)
            self.assertTrue(result)
            manifest = json.loads(open(self.manifest_path).read())
            self.assertEqual(len(manifest), 1)
            entry = manifest[0]
            self.assertEqual(entry['mediatype'], 'movie')
            self.assertEqual(entry['title'], 'Inception')
            self.assertNotIn('season', entry)
            self.assertNotIn('episode', entry)
            self.assertTrue(os.path.exists(entry['file_path']))
            self.assertEqual(os.path.getsize(entry['file_path']), len(self.payload))
            # filename has no SxxExx
            self.assertNotIn('S0', entry['id'])
            self.assertNotIn('E0', entry['id'])
        finally:
            cli.scraper_runner.search_all = orig_search_all
            cli.alldebrid.resolve = orig_resolve
            dm.manifest_path = orig_manifest_path

    def test_no_sources_returns_false(self):
        movie = {'id': 1, 'title': 'Unknown', 'year': '2020', 'type': 'movie'}
        settings = {
            'alldebridtoken': 'x', 'tmdb_api_key': 'x', 'tmdb_language': 'en',
            'offline_quality': '720p', 'download_segments': '4',
            'max_download_size_gb': '2', 'magnet_timeout': '120',
        }
        orig_search_all = cli.scraper_runner.search_all
        cli.scraper_runner.search_all = lambda q, content_type='all': []
        try:
            result = cli.download_movie(movie, '720p', settings)
            self.assertFalse(result)
        finally:
            cli.scraper_runner.search_all = orig_search_all

    def test_dry_run_does_not_download(self):
        from resources.lib import download_manager as dm
        movie = {'id': 27205, 'title': 'Inception', 'year': '2010', 'type': 'movie'}
        settings = {
            'alldebridtoken': 'x', 'tmdb_api_key': 'x', 'tmdb_language': 'en',
            'offline_quality': '720p', 'download_segments': '4',
            'max_download_size_gb': '2', 'magnet_timeout': '120',
        }
        fake_source = {
            'show_title': 'Inception', 'url': 'magnet:?fake',
            'title': 'Inception.2010.1080p', 'quality': '1080p',
            'size': '800 MB', 'seeders': 10,
        }
        orig_search_all = cli.scraper_runner.search_all
        orig_resolve = cli.alldebrid.resolve
        orig_manifest_path = dm.manifest_path
        cli.scraper_runner.search_all = lambda q, content_type='all': [fake_source]
        cli.alldebrid.resolve = lambda url, api_key, **kw: self.file_url
        self.manifest_path = os.path.join(self.tmp, 'manifest.json')
        dm.manifest_path = lambda: self.manifest_path
        try:
            result = cli.download_movie(movie, '720p', settings, dry_run=True)
            self.assertTrue(result)
            self.assertFalse(os.path.exists(self.manifest_path))
        finally:
            cli.scraper_runner.search_all = orig_search_all
            cli.alldebrid.resolve = orig_resolve
            dm.manifest_path = orig_manifest_path

    def test_uses_movies_content_type_for_scrape(self):
        movie = {'id': 27205, 'title': 'Inception', 'year': '2010', 'type': 'movie'}
        settings = {
            'alldebridtoken': 'x', 'tmdb_api_key': 'x', 'tmdb_language': 'en',
            'offline_quality': '720p', 'download_segments': '4',
            'max_download_size_gb': '2', 'magnet_timeout': '120',
        }
        fake_source = {
            'show_title': 'Inception', 'url': 'magnet:?fake',
            'title': 'Inception.2010.1080p', 'quality': '1080p',
            'size': '800 MB', 'seeders': 10,
        }
        captured = {}
        def fake_search_all(query, content_type='all'):
            captured['content_type'] = content_type
            return [fake_source]
        orig_search_all = cli.scraper_runner.search_all
        orig_resolve = cli.alldebrid.resolve
        from resources.lib import download_manager as dm
        orig_manifest_path = dm.manifest_path
        cli.scraper_runner.search_all = fake_search_all
        cli.alldebrid.resolve = lambda url, api_key, **kw: self.file_url
        self.manifest_path = os.path.join(self.tmp, 'manifest.json')
        dm.manifest_path = lambda: self.manifest_path
        try:
            cli.download_movie(movie, '720p', settings, dry_run=True)
            self.assertEqual(captured.get('content_type'), 'movies')
        finally:
            cli.scraper_runner.search_all = orig_search_all
            cli.alldebrid.resolve = orig_resolve
            dm.manifest_path = orig_manifest_path


class DownloadSeasonTests(unittest.TestCase):
    """Season-batch flow with mocked scrape/resolve. Three episodes: two
    succeed, one has no sources and is skipped without aborting the batch.
    """
    def setUp(self):
        # Reuse the HTTP server setup from DownloadEpisodeTests
        self._http_setup = DownloadEpisodeTests.setUp(self)
        # Override scrape to return sources for episodes 1 and 3, none for 2
        self._ep_sources = {
            1: [{'show_title': 'Show', 'url': 'magnet:e1',
                 'title': 'Show.S01E01.720p.mkv', 'quality': '720p',
                 'size': '4 MB', 'seeders': 50}],
            3: [{'show_title': 'Show', 'url': 'magnet:e3',
                 'title': 'Show.S01E03.720p.mkv', 'quality': '720p',
                 'size': '4 MB', 'seeders': 50}],
        }

    def tearDown(self):
        DownloadEpisodeTests.tearDown(self)

    def test_batch_downloads_available_episodes_and_skips_missing(self):
        from resources.lib import download_manager as dm

        show = {'id': 1396, 'title': 'Show', 'year': '2008', 'poster_url': None}
        episodes = [
            {'episode_number': 1, 'name': 'Ep1'},
            {'episode_number': 2, 'name': 'Ep2'},
            {'episode_number': 3, 'name': 'Ep3'},
        ]

        # Patch scraper_runner.search_all to return per-episode sources
        orig_search_all = cli.scraper_runner.search_all
        def fake_search(query, content_type='all'):
            # query is 'Show S01E{N}'; extract episode number
            import re
            m = re.search(r'E(\d+)', query)
            if not m:
                return []
            ep = int(m.group(1))
            return self._ep_sources.get(ep, [])
        cli.scraper_runner.search_all = fake_search

        # Patch alldebrid.resolve to return the local file URL
        orig_resolve = cli.alldebrid.resolve
        cli.alldebrid.resolve = lambda url, api_key, **kw: self.file_url

        # Patch tmdb.get_imdb_id
        orig_get_imdb = cli.tmdb.get_imdb_id
        cli.tmdb.get_imdb_id = lambda show_id, api_key, is_movie=False: 'tt0000000'

        # Temp manifest
        orig_manifest_path = dm.manifest_path
        self.manifest_path = os.path.join(self.tmp, 'season_manifest.json')
        dm.manifest_path = lambda: self.manifest_path

        settings = {
            'alldebridtoken': 'FAKE',
            'tmdb_api_key': 'FAKE',
            'offline_quality': '720p',
            'download_segments': '2',
            'max_download_size_gb': '10',
        }

        try:
            downloaded, skipped = cli.download_season(
                show, season=1, episodes=episodes, quality='720p',
                settings=settings, dry_run=False)
            self.assertEqual(downloaded, 2)
            self.assertEqual(skipped, 1)

            # Manifest has two entries (episodes 1 and 3)
            import json
            with open(self.manifest_path) as f:
                manifest = json.load(f)
            ep_nums = sorted(e['episode'] for e in manifest)
            self.assertEqual(ep_nums, [1, 3])
        finally:
            cli.scraper_runner.search_all = orig_search_all
            cli.alldebrid.resolve = orig_resolve
            cli.tmdb.get_imdb_id = orig_get_imdb
            dm.manifest_path = orig_manifest_path


class LabelMediaTests(unittest.TestCase):
    def test_show_with_year(self):
        item = {'title': 'Breaking Bad', 'year': '2008', 'type': 'show'}
        self.assertEqual(cli._label_media(item), 'Breaking Bad (2008) [Show]')

    def test_movie_with_year(self):
        item = {'title': 'Inception', 'year': '2010', 'type': 'movie'}
        self.assertEqual(cli._label_media(item), 'Inception (2010) [Movie]')

    def test_show_without_year(self):
        item = {'title': 'Some Show', 'year': '', 'type': 'show'}
        self.assertEqual(cli._label_media(item), 'Some Show [Show]')

    def test_movie_without_year(self):
        item = {'title': 'Some Movie', 'year': None, 'type': 'movie'}
        self.assertEqual(cli._label_media(item), 'Some Movie [Movie]')

    def test_missing_type_defaults_to_show(self):
        item = {'title': 'Untitled', 'year': '2020'}
        self.assertEqual(cli._label_media(item), 'Untitled (2020) [Show]')


class MainArgsTests(unittest.TestCase):
    """Test argument parsing in isolation. The interactive flow is mocked."""

    def test_invalid_segments_flag_exits_5(self):
        # --segments must be a positive integer
        with self.assertRaises(SystemExit) as cm:
            cli.main(['--segments', '0'])
        self.assertEqual(cm.exception.code, 5)

    def test_invalid_max_size_flag_exits_5(self):
        with self.assertRaises(SystemExit) as cm:
            cli.main(['--max-size-gb', 'abc'])
        self.assertEqual(cm.exception.code, 5)

    def test_help_flag_exits_0(self):
        with self.assertRaises(SystemExit) as cm:
            cli.main(['--help'])
        self.assertEqual(cm.exception.code, 0)

    def test_no_magnet_timeout_flag_is_parsed(self):
        """--no-magnet-timeout sets args.no_magnet_timeout to True."""
        args = cli._parse_args(['--no-magnet-timeout'])
        self.assertTrue(args.no_magnet_timeout)

    def test_no_magnet_timeout_defaults_false(self):
        """Without the flag, no_magnet_timeout is False."""
        args = cli._parse_args([])
        self.assertFalse(args.no_magnet_timeout)


if __name__ == '__main__':
    unittest.main()
