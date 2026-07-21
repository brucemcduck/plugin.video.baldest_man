#!/usr/bin/env python3
"""Unit tests for download_manager.py — multi-segment parallel download planning.

Run outside Kodi:
    python3 -m unittest test_download_manager
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from resources.lib import download_manager as dm


class PlanSegmentsTests(unittest.TestCase):
    def test_even_split_when_size_divisible(self):
        segs = dm._plan_segments(total_size=100_000_000, num_segments=4,
                                 min_segment_size=1)
        self.assertEqual(len(segs), 4)
        # Segments are (start, end_inclusive)
        self.assertEqual(segs[0], (0, 24_999_999))
        self.assertEqual(segs[1], (25_000_000, 49_999_999))
        self.assertEqual(segs[2], (50_000_000, 74_999_999))
        self.assertEqual(segs[3], (75_000_000, 99_999_999))
        # Cover the full range with no gaps or overlaps
        self.assertEqual(segs[0][0], 0)
        self.assertEqual(segs[-1][1], 99_999_999)

    def test_uneven_split_last_segment_absorbs_remainder(self):
        segs = dm._plan_segments(total_size=100_000_003, num_segments=4,
                                 min_segment_size=1)
        self.assertEqual(len(segs), 4)
        self.assertEqual(segs[-1][1], 100_000_002)
        # No gaps
        for i in range(3):
            self.assertEqual(segs[i][1] + 1, segs[i + 1][0])

    def test_single_segment(self):
        segs = dm._plan_segments(total_size=1_000, num_segments=1,
                                 min_segment_size=1)
        self.assertEqual(segs, [(0, 999)])

    def test_zero_size_returns_empty(self):
        segs = dm._plan_segments(total_size=0, num_segments=4,
                                 min_segment_size=1)
        self.assertEqual(segs, [])

    def test_fewer_segments_when_below_min_size(self):
        # 10 MB total, min 4 MB per segment, ask for 4 -> only 2 fit
        segs = dm._plan_segments(total_size=10_000_000, num_segments=4,
                                 min_segment_size=4_000_000)
        # Should reduce to 2 segments (each ~5MB) rather than 4 tiny ones
        self.assertEqual(len(segs), 2)
        self.assertEqual(segs[0][0], 0)
        self.assertEqual(segs[-1][1], 9_999_999)

    def test_at_least_one_segment_when_size_positive(self):
        # Even tiny file gets one segment
        segs = dm._plan_segments(total_size=500, num_segments=4,
                                 min_segment_size=1_000_000)
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0], (0, 499))


class DecideModeTests(unittest.TestCase):
    def test_parallel_when_large_and_range_supported(self):
        mode = dm._decide_mode(total_size=500_000_000,
                               supports_range=True,
                               num_segments=4,
                               min_parallel_size=20_000_000)
        self.assertEqual(mode, "parallel")

    def test_sequential_when_range_not_supported(self):
        mode = dm._decide_mode(total_size=500_000_000,
                               supports_range=False,
                               num_segments=4,
                               min_parallel_size=20_000_000)
        self.assertEqual(mode, "sequential")

    def test_sequential_when_below_min_parallel_size(self):
        mode = dm._decide_mode(total_size=10_000_000,
                               supports_range=True,
                               num_segments=4,
                               min_parallel_size=20_000_000)
        self.assertEqual(mode, "sequential")

    def test_sequential_when_one_segment(self):
        mode = dm._decide_mode(total_size=500_000_000,
                               supports_range=True,
                               num_segments=1,
                               min_parallel_size=20_000_000)
        self.assertEqual(mode, "sequential")

    def test_sequential_when_size_unknown(self):
        mode = dm._decide_mode(total_size=0,
                               supports_range=True,
                               num_segments=4,
                               min_parallel_size=20_000_000)
        self.assertEqual(mode, "sequential")


class PrepareResumeTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.dest = os.path.join(self.tmp, "movie.mkv")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _part_path(self, source_id, idx):
        import hashlib
        suffix = ''
        if source_id:
            suffix = '.' + hashlib.md5(source_id.encode('utf-8')).hexdigest()[:8]
        return '{}{}.part.{}'.format(self.dest, suffix, idx)

    def test_no_part_files_starts_from_zero(self):
        offsets = dm._prepare_resume(self.dest, num_segments=4, source_id="abc")
        self.assertEqual(offsets, [0, 0, 0, 0])

    def test_resumes_each_segment_from_existing_bytes(self):
        # Pre-write 1MB to segment 0 and 2, leave 1 and 3 empty
        for idx, size in [(0, 1_000_000), (1, 0), (2, 2_000_000), (3, 0)]:
            p = self._part_path("abc", idx)
            with open(p, 'wb') as f:
                f.write(b'x' * size)
        offsets = dm._prepare_resume(self.dest, num_segments=4, source_id="abc")
        self.assertEqual(offsets, [1_000_000, 0, 2_000_000, 0])

    def test_ignores_part_files_from_different_source(self):
        # Write part files with NO source suffix (different source_id)
        for idx in range(4):
            p = '{}.part.{}'.format(self.dest, idx)  # no source suffix
            with open(p, 'wb') as f:
                f.write(b'x' * 5_000_000)
        # With source_id="abc", those files shouldn't match
        offsets = dm._prepare_resume(self.dest, num_segments=4, source_id="abc")
        self.assertEqual(offsets, [0, 0, 0, 0])

    def test_no_source_id_uses_unsuffixed_part_files(self):
        for idx in range(2):
            p = '{}.part.{}'.format(self.dest, idx)
            with open(p, 'wb') as f:
                f.write(b'x' * 3_000_000)
        offsets = dm._prepare_resume(self.dest, num_segments=2, source_id=None)
        self.assertEqual(offsets, [3_000_000, 3_000_000])


class ConcatSegmentsTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.dest = os.path.join(self.tmp, "movie.mkv")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_concatenates_part_files_in_order(self):
        # Write 4 part files with distinct content
        parts = [b'AAAA', b'BBBB', b'CCCC', b'DDDD']
        for i, content in enumerate(parts):
            with open('{}.part.{}'.format(self.dest, i), 'wb') as f:
                f.write(content)
        ok = dm._concat_segments(self.dest, num_segments=4, source_id=None)
        self.assertTrue(ok)
        with open(self.dest, 'rb') as f:
            self.assertEqual(f.read(), b'AAAABBBBCCCCDDDD')
        # Part files removed
        for i in range(4):
            self.assertFalse(os.path.exists('{}.part.{}'.format(self.dest, i)))

    def test_returns_false_if_any_part_missing(self):
        with open('{}.part.0'.format(self.dest), 'wb') as f:
            f.write(b'AAAA')
        # Segment 1 missing
        ok = dm._concat_segments(self.dest, num_segments=2, source_id=None)
        self.assertFalse(ok)
        # Should not have created dest
        self.assertFalse(os.path.exists(self.dest))


class SupportsRangeTests(unittest.TestCase):
    def test_true_when_accept_ranges_header_present(self):
        headers = {'Accept-Ranges': 'bytes', 'Content-Length': '1000'}
        self.assertTrue(dm._supports_range(headers))

    def test_true_when_accept_ranges_none(self):
        headers = {'Accept-Ranges': 'none', 'Content-Length': '1000'}
        self.assertFalse(dm._supports_range(headers))

    def test_false_when_header_missing(self):
        headers = {'Content-Length': '1000'}
        self.assertFalse(dm._supports_range(headers))


class ParseContentRangeTests(unittest.TestCase):
    def test_parses_total_from_valid_header(self):
        self.assertEqual(dm._parse_content_range_total('bytes 0-0/8388608'), 8388608)

    def test_parses_mid_range(self):
        self.assertEqual(dm._parse_content_range_total('bytes 500-999/2000'), 2000)

    def test_returns_zero_on_missing_slash(self):
        self.assertEqual(dm._parse_content_range_total('bytes 0-0'), 0)

    def test_returns_zero_on_garbage(self):
        self.assertEqual(dm._parse_content_range_total(''), 0)
        self.assertEqual(dm._parse_content_range_total('not-a-range'), 0)


class ParallelDownloadIntegrationTests(unittest.TestCase):
    """End-to-end parallel download against a local HTTP server.

    Verifies byte-identical output, progress callbacks fire, cancel works,
    and resume continues from existing .part.N files.
    """
    def setUp(self):
        import http.server
        import socketserver
        import tempfile
        import threading
        self.tmp = tempfile.mkdtemp()
        # 8 MB of pseudo-random but deterministic content
        self.payload = bytes((i * 7 + 13) & 0xFF for i in range(8 * 1024 * 1024))
        self.served_path = os.path.join(self.tmp, 'source.bin')
        with open(self.served_path, 'wb') as f:
            f.write(self.payload)

        # Lower the parallel threshold so 8 MB payloads use the parallel path
        # (production default is 20 MB; lowered here so tests don't need huge
        # payloads and slow runtimes).
        self._orig_min_parallel = dm.MIN_PARALLEL_SIZE
        dm.MIN_PARALLEL_SIZE = 1024 * 1024  # 1 MB

        # Range-supporting, throttled handler. Python's SimpleHTTPRequestHandler
        # doesn't support Range requests out of the box, so we need a custom
        # handler to exercise the parallel download path. Sleeps briefly per
        # chunk so downloads span enough time for the progress poller to fire.
        class RangeThrottledHandler(http.server.SimpleHTTPRequestHandler):
            CHUNK_DELAY_S = 0.005  # 5ms per 64KB write
            protocol_version = 'HTTP/1.1'

            def do_GET(self):
                import time
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

        # ThreadingTCPServer so parallel segment requests are truly concurrent
        socketserver.TCPServer.allow_reuse_address = True
        self.httpd = socketserver.ThreadingTCPServer(
            ('127.0.0.1', 0), RangeThrottledHandler)
        self.port = self.httpd.server_address[1]
        self.server_thread = threading.Thread(target=self.httpd.serve_forever,
                                              daemon=True)
        self.server_thread.start()
        self.url = 'http://127.0.0.1:{}/source.bin'.format(self.port)
        # SimpleHTTPRequestHandler serves from cwd — chdir to tmp for the test
        self._orig_cwd = os.getcwd()
        os.chdir(self.tmp)

    def tearDown(self):
        import shutil
        os.chdir(self._orig_cwd)
        dm.MIN_PARALLEL_SIZE = self._orig_min_parallel
        self.httpd.shutdown()
        self.httpd.server_close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_parallel_download_produces_byte_identical_file(self):
        dest = os.path.join(self.tmp, 'out.mkv')
        progresses = []
        ok = dm.download_video(
            self.url, dest,
            num_segments=4,
            progress_callback=lambda w, t, p: progresses.append((w, t, p)),
        )
        self.assertTrue(ok)
        with open(dest, 'rb') as f:
            self.assertEqual(f.read(), self.payload)
        # Progress should have advanced
        self.assertTrue(progresses)
        self.assertTrue(progresses[-1][2] >= 99)
        # No leftover .part files
        import glob
        self.assertEqual(glob.glob(dest + '*part*'), [])

    def test_sequential_fallback_for_small_file(self):
        # Tiny file under MIN_PARALLEL_SIZE should use sequential path
        tiny = b'hello world'
        tiny_path = os.path.join(self.tmp, 'tiny.bin')
        with open(tiny_path, 'wb') as f:
            f.write(tiny)
        dest = os.path.join(self.tmp, 'out_tiny.mkv')
        ok = dm.download_video(self.url_for(tiny_path), dest, num_segments=4)
        self.assertTrue(ok)
        with open(dest, 'rb') as f:
            self.assertEqual(f.read(), tiny)

    def url_for(self, path):
        return 'http://127.0.0.1:{}/{}'.format(self.port, os.path.basename(path))

    def test_cancel_aborts_parallel_download(self):
        dest = os.path.join(self.tmp, 'out_cancel.mkv')
        cancelled = {'flag': False}
        calls = {'n': 0}

        def cancel_check():
            calls['n'] += 1
            # Cancel after a handful of chunk checks
            if calls['n'] > 3:
                cancelled['flag'] = True
            return cancelled['flag']

        ok = dm.download_video(self.url, dest, num_segments=4,
                               cancel_check=cancel_check)
        self.assertFalse(ok)
        # dest should not exist (concat never ran)
        self.assertFalse(os.path.exists(dest))

    def test_parallel_resume_continues_from_part_files(self):
        dest = os.path.join(self.tmp, 'out_resume.mkv')
        # Manually pre-write the first 1 MB of segment 0
        segs = dm._plan_segments(len(self.payload), 4)
        part0 = '{}.part.0'.format(dest)
        with open(part0, 'wb') as f:
            f.write(self.payload[segs[0][0]:segs[0][0] + 1024 * 1024])
        # Should still complete and produce the full file
        ok = dm.download_video(self.url, dest, num_segments=4)
        self.assertTrue(ok)
        with open(dest, 'rb') as f:
            self.assertEqual(f.read(), self.payload)

    def test_parallel_progress_fires_frequently_not_just_at_segment_ends(self):
        """Regression guard: progress must update within segments, not only
        when a whole segment completes. With 4 segments the buggy version
        fired ~4 times; the fix fires continuously via a poller thread."""
        original_interval = dm.PROGRESS_POLL_INTERVAL_S
        dm.PROGRESS_POLL_INTERVAL_S = 0.025  # 25ms polling for faster test
        try:
            dest = os.path.join(self.tmp, 'out_progress.mkv')
            progresses = []
            ok = dm.download_video(
                self.url, dest, num_segments=4,
                progress_callback=lambda w, t, p: progresses.append(w),
            )
            self.assertTrue(ok)
            # 4-segment download must produce well more than 4 progress updates.
            # The buggy version (report only on segment completion) gave exactly
            # num_segments updates; require at least 3x that to be safe.
            self.assertGreater(len(progresses), 12,
                               "progress callback only fired {} times — "
                               "regression: parallel mode not reporting within "
                               "segments".format(len(progresses)))
        finally:
            dm.PROGRESS_POLL_INTERVAL_S = original_interval


if __name__ == '__main__':
    unittest.main()
