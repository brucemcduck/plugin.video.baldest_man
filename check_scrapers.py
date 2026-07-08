#!/usr/bin/env python3
"""Test each scraper: reachability first, then search results. Run outside Kodi."""
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, ".")
import scrapers

QUERIES = ["the", "2024"]  # common words that should match something in any batch


def test_one(mod):
    """Returns (name, reachable_bool, result_count_or_None, elapsed, error_string_or_None)"""
    start = time.time()
    best = 0
    try:
        for q in QUERIES:
            try:
                raw = mod.search(q)
                if isinstance(raw, list):
                    best = max(best, len(raw))
            except Exception:
                pass
        elapsed = time.time() - start
    except Exception:
        return mod.SITE_NAME, False, None, time.time() - start, traceback.format_exc()

    if best > 0:
        return mod.SITE_NAME, True, best, elapsed, None

    # No results from any query — try one more raw call to check reachability
    try:
        raw = mod.search(QUERIES[0])
        elapsed = time.time() - start
        if isinstance(raw, list) and len(raw) == 0:
            return mod.SITE_NAME, True, 0, elapsed, "site reachable, 0 matching results"
        return mod.SITE_NAME, False, 0, elapsed, "returned nothing for all queries"
    except Exception:
        return mod.SITE_NAME, False, None, elapsed, traceback.format_exc()


def main():
    scraper_list = scrapers.get_scrapers()
    print(f"Testing {len(scraper_list)} scrapers (queries={QUERIES}, timeout={TIMEOUT}s)\n")

    results = []
    with ThreadPoolExecutor(max_workers=len(scraper_list)) as pool:
        futures = {pool.submit(test_one, m): m for m in scraper_list}
        for future in as_completed(futures):
            results.append(future.result())

    results.sort(key=lambda r: (not r[1], -(r[2] or 0)))

    alive = 0
    dead = 0
    for name, reachable, count, elapsed, error in results:
        if error and "traceback" in str(error).lower()[:20]:
            print(f"  \033[31m✗ DEAD\033[0m  {name:20s} {elapsed:5.1f}s  crashed")
            dead += 1
        elif error:
            print(f"  \033[33m~ NOISE\033[0m {name:20s} {elapsed:5.1f}s  {error}")
        elif reachable and count == 0:
            print(f"  \033[33m~ EMPTY\033[0m {name:20s} {elapsed:5.1f}s  alive, no matches for {QUERIES}")
            alive += 1
        elif reachable:
            print(f"  \033[32m✓ OK\033[0m    {name:20s} {elapsed:5.1f}s  {count} results")
            alive += 1
        else:
            print(f"  \033[31m✗ DEAD\033[0m  {name:20s} {elapsed:5.1f}s  unreachable")
            dead += 1

    print(f"\n{alive} alive  {dead} dead  ({len(scraper_list)} total)")


if __name__ == "__main__":
    main()
