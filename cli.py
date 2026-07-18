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

from resources.lib import scraper_runner, alldebrid, download_manager, tmdb
from resources.lib.alldebrid import AllDebridError
from resources.lib.download_manager import DownloadError


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
        return (quality_distance, -q_rank, -seeders, -size_bytes)

    candidates.sort(key=sort_key)
    return candidates[0]


def build_query(title, season, episode):
    """Build the scraper query string: 'Title S01E03' (zero-padded).

    Strips apostrophes from the title — some scraper APIs (e.g. PirateBay)
    return zero results for queries containing apostrophes.
    """
    clean_title = title.replace("'", '').replace('\u2019', '')
    return "{} S{:02d}E{:02d}".format(clean_title, int(season), int(episode))


def episode_already_downloaded(dest_path, expected_size):
    """True if dest_path exists with exactly expected_size bytes."""
    try:
        return os.path.getsize(dest_path) == expected_size
    except OSError:
        return False


def build_season_options(seasons):
    """Convert tmdb.get_seasons() result into arrow_select options.

    Returns list of (season_number, 'Name (N episodes)').
    """
    opts = []
    for s in seasons:
        sn = s.get('season_number')
        if sn is None:
            continue
        name = s.get('name') or 'Season {}'.format(sn)
        count = s.get('episode_count', 0)
        opts.append((sn, '{} ({} episodes)'.format(name, count)))
    return opts


def build_episode_options(episodes):
    """Convert tmdb.get_episodes() result into arrow_select options.

    First option is always ('all', 'Whole season'). Remaining options are
    (episode_number, 'E{n} — {name}') or 'E{n}' if name is empty.
    """
    opts = [('all', 'Whole season')]
    for ep in episodes:
        en = ep.get('episode_number')
        if en is None:
            continue
        name = (ep.get('name') or '').strip()
        label = 'E{} — {}'.format(en, name) if name else 'E{}'.format(en)
        opts.append((en, label))
    return opts


def build_quality_options(default='720p'):
    """Return (options, default_index) for the quality arrow_select menu.

    options is a list of (value, label) tuples. default_index points at the
    option matching the addon's offline_quality setting, or 0 if unknown.
    """
    opts = [(q, q) for q in QUALITY_OPTIONS]
    default_norm = (default or '').lower()
    if default_norm == '4k':
        default_norm = '4K'
    for i, (val, _) in enumerate(opts):
        if val.lower() == default_norm.lower():
            return opts, i
    return opts, 0


def arrow_select_fallback(options, label, input_fn=input):
    """Non-curses fallback: numbered list prompt.

    Used when stdin is not a TTY or curses is unavailable. Reads a 1-based
    index from input_fn, returns the value at that index. Re-prompts on
    out-of-range or non-integer input. 'q' raises KeyboardInterrupt.
    """
    while True:
        print(label)
        for i, (_, display) in enumerate(options, start=1):
            print('  {}. {}'.format(i, display))
        choice = input_fn('> ').strip()
        if choice.lower() == 'q':
            raise KeyboardInterrupt
        try:
            idx = int(choice)
        except ValueError:
            print('  invalid: enter a number 1-{} or q to cancel'.format(len(options)))
            continue
        if idx < 1 or idx > len(options):
            print('  out of range: enter 1-{}'.format(len(options)))
            continue
        return options[idx - 1][0]


def search_and_pick_fallback(search_fn, input_fn=input):
    """Non-curses fallback for show lookup: type query, pick from results.

    Prompts for a search query, calls search_fn(query), prints numbered
    matches, returns the chosen match dict. Re-prompts on empty query or
    invalid pick. Returns None if search_fn returns []. 'q' raises
    KeyboardInterrupt.
    """
    while True:
        query = input_fn('Search: ').strip()
        if query.lower() == 'q':
            raise KeyboardInterrupt
        if not query:
            print('  enter a show name to search')
            continue
        matches = search_fn(query)
        if not matches:
            return None
        print('  TMDB matches:')
        for i, m in enumerate(matches, start=1):
            print('  {}. {} ({})'.format(i, m.get('title', '?'), m.get('year', '')))
        choice = input_fn('Pick [1-{}]: '.format(len(matches))).strip()
        if choice.lower() == 'q':
            raise KeyboardInterrupt
        try:
            idx = int(choice)
        except ValueError:
            print('  invalid: enter a number')
            continue
        if idx < 1 or idx > len(matches):
            print('  out of range: enter 1-{}'.format(len(matches)))
            continue
        return matches[idx - 1]


def _is_tty():
    """True if stdin is a TTY (interactive terminal)."""
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def arrow_select(options, label, default=0):
    """Arrow-key vertical menu. Falls back to numbered prompt when curses
    is unavailable or stdin is not a TTY.

    options: list of (value, display_text) tuples.
    Returns the selected value. Raises KeyboardInterrupt on q/Esc/Ctrl-C.
    """
    if not _is_tty():
        return arrow_select_fallback(options, label)
    try:
        import curses
    except ImportError:
        return arrow_select_fallback(options, label)

    idx = default
    if idx < 0 or idx >= len(options):
        idx = 0

    def _draw(stdscr, current):
        stdscr.clear()
        stdscr.addstr(0, 0, label, curses.A_BOLD)
        for i, (_, display) in enumerate(options):
            marker = '> ' if i == current else '  '
            line = '{}{}'.format(marker, display)
            attr = curses.A_REVERSE if i == current else curses.A_NORMAL
            stdscr.addstr(i + 2, 0, line, attr)
        stdscr.addstr(len(options) + 3, 0,
                      '(Up/Down move, Enter select, q cancel)', curses.A_DIM)
        stdscr.refresh()

    def _loop(stdscr):
        nonlocal idx
        curses.curs_set(0)
        _draw(stdscr, idx)
        while True:
            ch = stdscr.getch()
            if ch in (curses.KEY_UP, ord('k')):
                idx = max(0, idx - 1)
            elif ch in (curses.KEY_DOWN, ord('j')):
                idx = min(len(options) - 1, idx + 1)
            elif ch in (curses.KEY_ENTER, 10, 13):
                return options[idx][0]
            elif ch in (ord('q'), 27):
                raise KeyboardInterrupt
            _draw(stdscr, idx)

    try:
        return curses.wrapper(_loop)
    except KeyboardInterrupt:
        raise


def search_and_pick(search_fn):
    """Split-pane search UI with arrow-key result picking.

    Type a query on the top line, press Enter to fetch TMDB matches, arrow
    keys to highlight, Enter to select. Falls back to the numbered prompt
    when curses is unavailable or stdin is not a TTY.

    Returns the chosen match dict, or None if the search returns no matches.
    Raises KeyboardInterrupt on q/Esc/Ctrl-C.
    """
    if not _is_tty():
        return search_and_pick_fallback(search_fn)
    try:
        import curses
    except ImportError:
        return search_and_pick_fallback(search_fn)

    # curses implementation: use the fallback for the text-input phase
    # (curses text input is fiddly and not worth the complexity here), then
    # switch to arrow_select for picking from the fetched results.
    # This keeps the curses path simple while still giving arrow-key picking.
    query = ''
    while True:
        try:
            query = input('Search: ').strip()
        except EOFError:
            raise KeyboardInterrupt
        if query.lower() == 'q':
            raise KeyboardInterrupt
        if not query:
            print('  enter a show name to search')
            continue
        matches = search_fn(query)
        if not matches:
            return None
        opts = [(m, '{} ({})'.format(m.get('title', '?'), m.get('year', '')))
                for m in matches]
        return arrow_select(opts, 'Pick a show:')


def select_quality(default='720p'):
    """Arrow-key quality menu (4K / 1080p / 720p / 480p)."""
    opts, default_idx = build_quality_options(default)
    return arrow_select(opts, 'Select preferred quality:', default=default_idx)


def select_season(seasons):
    """Arrow-key season menu over tmdb.get_seasons() results."""
    opts = build_season_options(seasons)
    if not opts:
        raise ValueError("No seasons available")
    return arrow_select(opts, 'Seasons:', default=0)


def select_episode(episodes):
    """Arrow-key episode menu. First option is always 'Whole season'."""
    opts = build_episode_options(episodes)
    if not opts:
        raise ValueError("No episodes available")
    return arrow_select(opts, 'Episodes:', default=0)


def _fmt_mb(bytes_val):
    """Format bytes as MB with no decimals."""
    return '{} MB'.format(bytes_val // (1024 * 1024))


def make_progress_callback():
    """Return a progress_callback(written, total, pct) that prints a live
    single-line progress meter to stderr using carriage return.
    """
    def cb(written, total, pct):
        line = '\r[download] {} / {} ({}%)'.format(
            _fmt_mb(written), _fmt_mb(total), pct)
        sys.stderr.write(line)
        sys.stderr.flush()
        # Clear the line when complete
        if total and written >= total:
            sys.stderr.write('\n')
            sys.stderr.flush()
    return cb


def _search_with_retry(query, content_type='shows'):
    """Search scrapers; if no results, retry with progressively shorter queries.

    Drops leading words from the title portion (keeping the S01E01 code) to
    handle shows whose full title doesn't match torrent names well — e.g.
    "It's Always Sunny in Philadelphia" → try "Always Sunny in Philadelphia",
    then "Sunny in Philadelphia", etc.
    """
    sources = scraper_runner.search_all(query, content_type=content_type)
    if sources:
        return sources

    parts = query.rsplit(' S', 1)
    if len(parts) != 2:
        return []
    title_part, ep_part = parts[0], 'S' + parts[1]
    words = title_part.split()

    for n in range(len(words) - 1, 0, -1):
        shorter = ' '.join(words[len(words) - n:]) + ' ' + ep_part
        print('[scrape] retrying with: {}'.format(shorter))
        sources = scraper_runner.search_all(shorter, content_type=content_type)
        if sources:
            return sources

    return []


def download_episode(show, season, episode, quality, settings, dry_run=False):
    """Run the scrape -> resolve -> download -> manifest flow for one episode.

    show: TMDB show dict with at least {id, title, poster_url}.
    settings: dict from read_kodi_settings().
    Returns True on success, False on no sources or download failure.
    Raises AllDebridError if the magnet resolution fails (caller decides
    whether to abort or skip-and-continue).
    """
    title = show.get('title', '')
    show_id = show.get('id')
    poster_url = show.get('poster_url')

    query = build_query(title, season, episode)
    print('[scrape] searching for {}'.format(query))
    sources = _search_with_retry(query, content_type='shows')
    if not sources:
        print('[scrape] no sources found')
        return False
    print('[scrape] {} sources found'.format(len(sources)))

    max_gb = int(settings.get('max_download_size_gb', '2') or '2')
    best = pick_best_source(sources, quality=quality, max_gb=max_gb)
    if not best:
        print('[scrape] no sources passed quality/size filters')
        return False
    print('[scrape] best: {} ({}, {} seeders)'.format(
        best.get('title', ''), best.get('size', '?'), best.get('seeders', 0)))

    if dry_run:
        print('[dry-run] would download from {}'.format(best.get('url', '')))
        return True

    api_key = settings.get('alldebridtoken', '')
    num_segments = int(settings.get('download_segments', '4') or '4')

    # Resolve magnet -> direct URL (episode-aware file picker)
    print('[alldebrid] resolving...')
    direct_url = alldebrid.resolve(
        best['url'], api_key,
        season=season, episode=episode,
        progress_callback=_alldebrid_progress,
    )
    print('[alldebrid] ready')

    # Download
    dest_dir = download_manager.get_download_dir()
    fname = download_manager.safe_filename(title, season, episode)
    dest = os.path.join(dest_dir, fname)

    print('[download] -> {}'.format(dest))
    progress_cb = make_progress_callback()
    try:
        ok = download_manager.download_video(
            direct_url, dest,
            num_segments=num_segments,
            progress_callback=progress_cb,
        )
    except DownloadError as e:
        print('[fail] download error: {}'.format(e))
        return False
    if not ok:
        print('[fail] download cancelled or failed')
        return False

    # Cache artwork
    poster_local = None
    if poster_url:
        poster_local = download_manager.cache_artwork(
            poster_url, os.path.join(download_manager.art_dir(),
                                     fname + '.poster.jpg'))

    # Add to manifest — same shape as main.py:477-489
    entry = {
        'id': fname,
        'title': '{} S{:02d}E{:02d}'.format(title, season, episode),
        'show_title': title,
        'season': season,
        'episode': episode,
        'file_path': dest,
        'size_bytes': os.path.getsize(dest),
        'date_added': int(__import__('time').time()),
        'mediatype': 'episode',
        'plot': '',
        'poster_path': poster_local,
    }
    download_manager.add_to_manifest(entry)
    print('Done: {}'.format(dest))
    return True


def _alldebrid_progress(state, pct, eta):
    """Print AllDebrid magnet-resolution progress to stderr."""
    print('[alldebrid] {}... {}%'.format(state, pct), file=sys.stderr)


def download_season(show, season, episodes, quality, settings, dry_run=False):
    """Download every episode in a season. Skips episodes with no sources
    or download failures; continues the batch. Returns (downloaded, skipped).

    episodes: list of TMDB episode dicts (from tmdb.get_episodes), each with
    at least {episode_number, name}.
    """
    title = show.get('title', '')
    downloaded = 0
    skipped = []

    for ep in episodes:
        ep_num = ep.get('episode_number')
        if ep_num is None:
            continue
        ep_name = ep.get('name', '')
        label = 'S{:02d}E{:02d}'.format(season, ep_num)
        if ep_name:
            label += ' — {}'.format(ep_name)
        print('\n--- {} ---'.format(label))

        try:
            ok = download_episode(show, season, ep_num, quality, settings, dry_run)
        except AllDebridError as e:
            print('[skip] {}: AllDebrid error: {}'.format(label, e))
            skipped.append(label)
            continue
        if ok:
            downloaded += 1
        else:
            skipped.append(label)

    print('\n--- Summary ---')
    print('Downloaded {}/{} episodes.'.format(downloaded, len(episodes)))
    if skipped:
        print('Skipped: {}'.format(', '.join(skipped)))
    return downloaded, len(skipped)


def _parse_args(argv):
    """Parse CLI flags. Returns parsed args or raises SystemExit(exit_code)
    on invalid input (exit 5) or --help (exit 0)."""
    import argparse

    parser = argparse.ArgumentParser(
        prog='cli.py',
        description='Download shows via the bald_man addon pipeline.',
        add_help=True,
    )
    parser.add_argument('--segments', type=int, default=None,
                        help='Parallel download segments (1 = sequential). '
                             'Overrides download_segments setting.')
    parser.add_argument('--max-size-gb', type=int, default=None,
                        help='Max source size in GB. '
                             'Overrides max_download_size_gb setting.')
    parser.add_argument('--dry-run', action='store_true',
                        help='Scrape and pick sources but skip download.')

    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        # argparse exits with 2 on parse error; remap to our code 5.
        # --help exits with 0; pass through.
        if e.code == 0:
            raise
        raise SystemExit(5)

    if args.segments is not None and args.segments < 1:
        print('error: --segments must be >= 1', file=sys.stderr)
        raise SystemExit(5)
    if args.max_size_gb is not None and args.max_size_gb < 1:
        print('error: --max-size-gb must be >= 1', file=sys.stderr)
        raise SystemExit(5)

    return args


def main(argv=None):
    """Entry point. Returns an exit code (0 = success)."""
    if argv is None:
        argv = sys.argv[1:]
    args = _parse_args(argv)

    # Read settings from Kodi's settings.xml
    settings = read_kodi_settings(KODI_SETTINGS_PATH)
    if not settings.get('alldebridtoken') or not settings.get('tmdb_api_key'):
        print('error: AllDebrid token or TMDB API key not set in Kodi settings',
              file=sys.stderr)
        print('  expected at: {}'.format(KODI_SETTINGS_PATH), file=sys.stderr)
        return 4

    # Apply CLI overrides
    if args.segments is not None:
        settings['download_segments'] = str(args.segments)
    if args.max_size_gb is not None:
        settings['max_download_size_gb'] = str(args.max_size_gb)

    try:
        # 1. Show lookup (interactive)
        def search_fn(query):
            return tmdb.search_shows(
                query,
                settings.get('tmdb_api_key', ''),
                settings.get('tmdb_language', 'en'),
            )
        show = search_and_pick(search_fn)
        if show is None:
            print('[tmdb] no matches')
            return 2
        print('[tmdb] {} -> show_id={}'.format(
            show.get('title', '?'), show.get('id')))

        # 2. Season picker
        seasons = tmdb.get_seasons(
            show['id'], settings.get('tmdb_api_key', ''),
            settings.get('tmdb_language', 'en'),
        )
        if not seasons:
            print('[tmdb] no seasons found for this show')
            return 2
        season = select_season(seasons)

        # 3. Episode picker
        episodes = tmdb.get_episodes(
            show['id'], season, settings.get('tmdb_api_key', ''),
            settings.get('tmdb_language', 'en'),
        )
        if not episodes:
            print('[tmdb] no episodes found for season {}'.format(season))
            return 2
        ep_choice = select_episode(episodes)

        # 4. Quality picker
        quality = select_quality(default=settings.get('offline_quality', '720p'))
        print('[quality] {}'.format(quality))

        # 5. Download
        if ep_choice == 'all':
            downloaded, skipped = download_season(
                show, season, episodes, quality, settings,
                dry_run=args.dry_run)
            if downloaded == 0:
                return 1
        else:
            ok = download_episode(show, season, ep_choice, quality, settings,
                                  dry_run=args.dry_run)
            if not ok:
                return 1
        return 0

    except KeyboardInterrupt:
        print('\n[cancelled]')
        return 130
    except AllDebridError as e:
        print('[error] AllDebrid: {}'.format(e), file=sys.stderr)
        return 3


if __name__ == '__main__':
    main()
