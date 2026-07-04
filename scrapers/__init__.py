"""Scraper auto-discovery. Drop a .py file here with SITE_NAME and search()."""
import os
import importlib

_scrapers = []

def _discover():
    scraper_dir = os.path.dirname(__file__)
    for f in sorted(os.listdir(scraper_dir)):
        if f.startswith('_') or not f.endswith('.py'):
            continue
        name = f[:-3]
        mod = importlib.import_module('.' + name, __package__)
        if hasattr(mod, 'SITE_NAME') and hasattr(mod, 'search'):
            _scrapers.append(mod)

_discover()

def get_scrapers():
    return _scrapers
