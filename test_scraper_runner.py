#!/usr/bin/env python3
"""Unit tests for resources.lib.scraper_runner._relevant filter.

Run outside Kodi:
    python3 -m unittest test_scraper_runner
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from resources.lib import scraper_runner


class RelevantTests(unittest.TestCase):
    def test_short_show_title_matches(self):
        """Query 'Breaking Bad S01E01' matches show_title 'Breaking Bad'."""
        self.assertTrue(scraper_runner._relevant('Breaking Bad S01E01', 'Breaking Bad'))

    def test_long_title_with_apostrophe_matches(self):
        """Query "It's Always Sunny..." matches show_title 'It is Always Sunny...'."""
        self.assertTrue(scraper_runner._relevant(
            "It's Always Sunny in Philadelphia S01E01",
            'It is Always Sunny in Philadelphia'))

    def test_shorter_query_matches_longer_title(self):
        """Query 'Always Sunny S01E01' matches 'It is Always Sunny in Philadelphia'."""
        self.assertTrue(scraper_runner._relevant(
            'Always Sunny S01E01',
            'It is Always Sunny in Philadelphia'))

    def test_rejects_different_show(self):
        """Query 'Breaking Bad S01E01' does not match 'Better Call Saul'."""
        self.assertFalse(scraper_runner._relevant('Breaking Bad S01E01', 'Better Call Saul'))

    def test_rejects_wrong_word_order(self):
        """Query 'Breaking Bad' does not match 'The Bad Guys Breaking In'."""
        self.assertFalse(scraper_runner._relevant(
            'Breaking Bad S01E01', 'The Bad Guys Breaking In'))

    def test_strips_episode_code(self):
        """Episode code S01E05 is stripped from query before matching."""
        self.assertTrue(scraper_runner._relevant('The Office S01E05', 'The Office'))

    def test_empty_query_is_false(self):
        self.assertFalse(scraper_runner._relevant('', 'Anything'))

    def test_empty_show_title_is_false(self):
        self.assertFalse(scraper_runner._relevant('Anything S01E01', ''))


if __name__ == '__main__':
    unittest.main()
