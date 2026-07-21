#!/usr/bin/env python3
"""Unit tests for alldebrid.py — episode-aware file selection from multi-file magnets.

Run outside Kodi:
    python3 -m unittest test_alldebrid
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# alldebrid.py imports xbmc lazily inside _log, so importing the module is safe
# even when Kodi is not running.
from resources.lib.alldebrid import _find_file_link


class FindFileLinkTests(unittest.TestCase):
    def _mkv(self, name, size, link=None):
        return {"n": name, "s": size, "l": link or "https://debrid.it/dl/" + name}

    def test_skips_non_video_files_in_season_pack(self):
        """Reproduces the kodi.log bug: RARBG.txt listed first must be skipped."""
        files = [
            {"n": "RARBG.txt", "s": 50, "l": "https://debrid.it/dl/rarbg-txt"},
            {"n": "The.Walking.Dead.S01E01.Days.Gone.Bye.1080p.BluRay.mkv",
             "s": 4_000_000_000, "l": "https://debrid.it/dl/s01e01"},
            {"n": "The.Walking.Dead.S01E02.1080p.BluRay.mkv",
             "s": 3_900_000_000, "l": "https://debrid.it/dl/s01e02"},
        ]
        result = _find_file_link(files, season=1, episode=1)
        self.assertEqual(result, "https://debrid.it/dl/s01e01")

    def test_prefers_matching_episode_in_multi_episode_pack(self):
        files = [
            self._mkv("Show.S01E01.mkv", 1_000_000),
            self._mkv("Show.S01E02.mkv", 1_000_000),
            self._mkv("Show.S01E03.mkv", 1_000_000),
        ]
        self.assertEqual(_find_file_link(files, season=1, episode=2),
                         "https://debrid.it/dl/Show.S01E02.mkv")

    def test_episode_match_zero_padded_and_unpadded(self):
        files = [
            self._mkv("Show.S01E01.mkv", 1_000_000),
            self._mkv("Show.S1E1.mkv", 1_000_000, "https://debrid.it/dl/alt"),
        ]
        # Should match either S01E01 or S1E1 form
        self.assertEqual(_find_file_link(files, season=1, episode=1),
                         "https://debrid.it/dl/Show.S01E01.mkv")

    def test_no_episode_info_picks_largest_video_file(self):
        """Movie magnets often contain multiple video files (sample + main)."""
        files = [
            self._mkv("Sample.Movie.mkv", 50_000_000, "https://debrid.it/dl/sample"),
            self._mkv("Movie.2024.1080p.mkv", 8_000_000_000,
                      "https://debrid.it/dl/main"),
            {"n": "Movie.nfo", "s": 5_000, "l": "https://debrid.it/dl/nfo"},
        ]
        self.assertEqual(_find_file_link(files),
                         "https://debrid.it/dl/main")

    def test_no_video_files_returns_none(self):
        files = [
            {"n": "README.txt", "s": 100, "l": "https://debrid.it/dl/readme"},
            {"n": "cover.jpg", "s": 200_000, "l": "https://debrid.it/dl/cover"},
        ]
        self.assertIsNone(_find_file_link(files, season=1, episode=1))

    def test_episode_not_found_falls_back_to_largest_video(self):
        """If no file matches SxxExx, return largest video rather than failing."""
        files = [
            self._mkv("Special.Extra.1080p.mkv", 500_000_000,
                      "https://debrid.it/dl/extra"),
            self._mkv("Main.Feature.1080p.mkv", 8_000_000_000,
                      "https://debrid.it/dl/main"),
        ]
        self.assertEqual(_find_file_link(files, season=1, episode=5),
                         "https://debrid.it/dl/main")

    def test_walks_nested_folder_tree(self):
        """AllDebrid v4.1 sometimes nests files under folder nodes (e/files keys)."""
        files = [
            {"n": "Season.1", "e": [
                {"n": "RARBG.txt", "s": 50, "l": "https://debrid.it/dl/txt"},
                self._mkv("Show.S01E01.mkv", 4_000_000_000,
                          "https://debrid.it/dl/e01"),
            ]},
        ]
        self.assertEqual(_find_file_link(files, season=1, episode=1),
                         "https://debrid.it/dl/e01")

    def test_legacy_no_args_still_works(self):
        """Existing call sites without season/episode must still get a video file."""
        files = [
            {"n": "ignore.txt", "s": 10, "l": "https://debrid.it/dl/ignore"},
            self._mkv("Movie.mkv", 1_000_000, "https://debrid.it/dl/movie"),
        ]
        self.assertEqual(_find_file_link(files), "https://debrid.it/dl/movie")


class _FakeResponse:
    """Minimal mock of requests.Response for AllDebrid API calls."""
    def __init__(self, data):
        self._data = data
    def raise_for_status(self):
        pass
    def json(self):
        return self._data


class StallDetectionTests(unittest.TestCase):
    """Test that resolve() detects dead magnets by tracking download progress."""

    def _upload_response(self, magnet_id=123):
        return _FakeResponse({
            "status": "success",
            "data": {"magnets": [{"id": magnet_id}]},
        })

    def _status_response(self, magnet_id=123, status="Downloading",
                         status_code=1, downloaded=0, size=1000000):
        return _FakeResponse({
            "status": "success",
            "data": {"magnets": [{"id": magnet_id, "status": status,
                                  "statusCode": status_code,
                                  "downloaded": downloaded, "size": size}]},
        })

    @patch('resources.lib.alldebrid.requests')
    def test_raises_on_stalled_download(self, mock_requests):
        """Magnet stuck in Downloading with no progress for 10s -> AllDebridError."""
        from resources.lib import alldebrid

        mock_requests.post.return_value = self._upload_response()
        mock_requests.get.return_value = self._status_response(downloaded=0)

        current_time = [0.0]
        def mock_time():
            return current_time[0]
        def mock_sleep(seconds):
            current_time[0] += seconds

        with patch.object(alldebrid.time, 'time', mock_time), \
             patch.object(alldebrid.time, 'sleep', mock_sleep):
            with self.assertRaises(alldebrid.AllDebridError) as ctx:
                alldebrid.resolve('magnet:?fake', 'fake_api_key', timeout=0)
            self.assertIn('stalled', str(ctx.exception).lower())

    @patch('resources.lib.alldebrid.requests')
    def test_progress_resets_stall_timer(self, mock_requests):
        """If downloaded increases, stall timer resets - no false positive.
        Progress keeps resetting the 10s stall window, so the function
        eventually times out (not stalls) when the timeout is shorter
        than 10s after the last progress."""
        from resources.lib import alldebrid

        # Alternating: no progress, then progress, then no progress
        responses = [
            self._status_response(downloaded=0),      # poll 1: init
            self._status_response(downloaded=0),      # poll 2: no progress
            self._status_response(downloaded=500000), # poll 3: progress! reset
            self._status_response(downloaded=500000), # poll 4: no progress
            self._status_response(downloaded=500000), # poll 5: no progress
            self._status_response(downloaded=900000), # poll 6: progress! reset
            self._status_response(downloaded=900000), # poll 7: no progress
            self._status_response(downloaded=900000), # poll 8: no progress
        ]
        mock_requests.post.return_value = self._upload_response()
        mock_requests.get.side_effect = responses

        current_time = [0.0]
        def mock_time():
            return current_time[0]
        def mock_sleep(seconds):
            current_time[0] += seconds

        with patch.object(alldebrid.time, 'time', mock_time), \
             patch.object(alldebrid.time, 'sleep', mock_sleep):
            with self.assertRaises(alldebrid.AllDebridError) as ctx:
                alldebrid.resolve('magnet:?fake', 'fake_api_key', timeout=8)
            # Should time out, NOT stall -- progress kept resetting the timer
            self.assertIn('timed out', str(ctx.exception).lower())
            self.assertNotIn('stalled', str(ctx.exception).lower())

    @patch('resources.lib.alldebrid.requests')
    def test_no_stall_during_processing_status(self, mock_requests):
        """Processing status (code 0) should not trigger stall detection."""
        from resources.lib import alldebrid

        # All responses are Processing -- should NOT raise stall error
        # (will eventually time out instead, but we use a short timeout)
        mock_requests.post.return_value = self._upload_response()
        mock_requests.get.return_value = self._status_response(
            status="Processing", status_code=0, downloaded=0)

        current_time = [0.0]
        def mock_time():
            return current_time[0]
        def mock_sleep(seconds):
            current_time[0] += seconds

        with patch.object(alldebrid.time, 'time', mock_time), \
             patch.object(alldebrid.time, 'sleep', mock_sleep):
            with self.assertRaises(alldebrid.AllDebridError) as ctx:
                alldebrid.resolve('magnet:?fake', 'fake_api_key', timeout=5)
            # Should be a timeout error, not a stall error
            self.assertIn('timed out', str(ctx.exception).lower())
            self.assertNotIn('stalled', str(ctx.exception).lower())

    @patch('resources.lib.alldebrid.requests')
    def test_missing_downloaded_field_no_false_positive(self, mock_requests):
        """If API response lacks 'downloaded' field, no stall false positive."""
        from resources.lib import alldebrid

        mock_requests.post.return_value = self._upload_response()
        # Status response without 'downloaded' key
        mock_requests.get.return_value = _FakeResponse({
            "status": "success",
            "data": {"magnets": [{"id": 123, "status": "Downloading",
                                  "statusCode": 1}]},
        })

        current_time = [0.0]
        def mock_time():
            return current_time[0]
        def mock_sleep(seconds):
            current_time[0] += seconds

        with patch.object(alldebrid.time, 'time', mock_time), \
             patch.object(alldebrid.time, 'sleep', mock_sleep):
            with self.assertRaises(alldebrid.AllDebridError) as ctx:
                alldebrid.resolve('magnet:?fake', 'fake_api_key', timeout=5)
            # Should time out, not stall
            self.assertIn('timed out', str(ctx.exception).lower())
            self.assertNotIn('stalled', str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
