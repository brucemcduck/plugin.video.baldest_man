#!/usr/bin/env python3
"""Build Kodi repository zips and generate addons.xml for GitHub Pages hosting.

Usage (from repo root):
    python tools/build_repo.py

Outputs under docs/repo/ (served by GitHub Pages):
    docs/repo/index.html
    docs/repo/repository.baldest_man-VERSION.zip
    docs/repo/zips/addons.xml
    docs/repo/zips/addons.xml.md5
    docs/repo/zips/<addon_id>/<addon_id>-VERSION.zip
"""
import hashlib
import os
import re
import shutil
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_TEMPLATE = os.path.join(ROOT, 'repo', 'repository.baldest_man')
HOST_ROOT = os.path.join(ROOT, 'docs', 'repo')
ZIPS_DIR = os.path.join(HOST_ROOT, 'zips')

# Public URL where docs/repo/ is served (GitHub Pages).
PAGES_BASE = 'https://brucemcduck.github.io/plugin.video.baldest_man/repo'

ADDONS = {
    'plugin.video.baldest_man': ROOT,
    'repository.baldest_man': REPO_TEMPLATE,
}

PLUGIN_SKIP = {
    '.git', '.github', 'repo', 'tools', 'docs', 'ideas.txt', 'README.md',
    'requirements.txt', 'cli.py', 'check_scrapers.py', '.gitignore',
    '.DS_Store', 'Thumbs.db',
}
PLUGIN_SKIP_PREFIXES = ('test_',)
PLUGIN_SKIP_SUFFIXES = ('.pyc', '.pyo')


def _read_version(addon_dir):
    tree = ET.parse(os.path.join(addon_dir, 'addon.xml'))
    return tree.getroot().get('version', '0.0.0')


def _addon_xml_body(addon_dir):
    with open(os.path.join(addon_dir, 'addon.xml'), encoding='utf-8') as f:
        text = f.read()
    m = re.search(r'(<addon[\s\S]*?</addon>)', text)
    if not m:
        raise ValueError('No <addon> block in {}'.format(addon_dir))
    return m.group(1).strip()


def _should_skip_plugin(name, path):
    if name in PLUGIN_SKIP:
        return True
    if name.startswith(PLUGIN_SKIP_PREFIXES):
        return True
    if name.endswith(PLUGIN_SKIP_SUFFIXES):
        return True
    if name == '__pycache__':
        return True
    if 'superpowers' in path.replace('\\', '/'):
        return True
    return False


def _zip_addon(addon_id, source_dir, dest_zip):
    os.makedirs(os.path.dirname(dest_zip), exist_ok=True)
    with tempfile.TemporaryDirectory() as staging:
        dest_root = os.path.join(staging, addon_id)
        if addon_id == 'plugin.video.baldest_man':
            for dirpath, dirnames, filenames in os.walk(source_dir):
                rel = os.path.relpath(dirpath, source_dir)
                dirnames[:] = [
                    d for d in dirnames
                    if not _should_skip_plugin(d, os.path.join(rel, d) if rel != '.' else d)
                ]
                for fname in filenames:
                    rel_path = os.path.join(rel, fname) if rel != '.' else fname
                    if _should_skip_plugin(fname, rel_path):
                        continue
                    src = os.path.join(dirpath, fname)
                    out = os.path.join(dest_root, rel_path)
                    os.makedirs(os.path.dirname(out), exist_ok=True)
                    shutil.copy2(src, out)
        else:
            shutil.copytree(source_dir, dest_root)

        with zipfile.ZipFile(dest_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
            for dirpath, _, filenames in os.walk(dest_root):
                for fname in filenames:
                    full = os.path.join(dirpath, fname)
                    zf.write(full, os.path.relpath(full, staging))


def _write_dir_index(entries, title='Index of /'):
    """Apache-style listing. Kodi's Install-from-zip browser parses
    <a href="name.zip">name.zip</a> — link text must be the filename."""
    lines = [
        '<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 3.2 Final//EN">',
        '<html><head><title>{}</title></head><body>'.format(title),
        '<h1>{}</h1><hr><pre>'.format(title),
    ]
    for name, href in entries:
        lines.append('<a href="{}">{}</a>'.format(href, name))
    lines.append('</pre><hr></body></html>')
    return '\n'.join(lines) + '\n'


def main():
    if os.path.isdir(HOST_ROOT):
        shutil.rmtree(HOST_ROOT)
    os.makedirs(ZIPS_DIR)

    addon_bodies = []
    plugin_zip_rel = ''
    for addon_id, source_dir in ADDONS.items():
        version = _read_version(source_dir)
        zip_name = '{}-{}.zip'.format(addon_id, version)
        zip_path = os.path.join(ZIPS_DIR, addon_id, zip_name)
        print('Building {} -> {}'.format(addon_id, zip_path))
        _zip_addon(addon_id, source_dir, zip_path)
        addon_bodies.append(_addon_xml_body(source_dir))
        if addon_id == 'plugin.video.baldest_man':
            plugin_zip_rel = 'zips/{}/{}'.format(addon_id, zip_name)

    addons_xml = '\n'.join(
        ['<?xml version="1.0" encoding="UTF-8"?>', '<addons>']
        + addon_bodies + ['</addons>']) + '\n'

    xml_path = os.path.join(ZIPS_DIR, 'addons.xml')
    with open(xml_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(addons_xml)

    digest = hashlib.md5(addons_xml.encode('utf-8')).hexdigest()
    md5_path = os.path.join(ZIPS_DIR, 'addons.xml.md5')
    with open(md5_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(digest)

    repo_version = _read_version(REPO_TEMPLATE)
    repo_zip_name = 'repository.baldest_man-{}.zip'.format(repo_version)
    repo_zip = os.path.join(ZIPS_DIR, 'repository.baldest_man', repo_zip_name)
    easy_repo = os.path.join(HOST_ROOT, repo_zip_name)
    shutil.copy2(repo_zip, easy_repo)

    # Flat copies at repo root so Install-from-zip shows both zips immediately
    # (no folder navigation). Link text == filename for Kodi's HTML parser.
    plugin_zip_name = os.path.basename(plugin_zip_rel)
    easy_plugin = os.path.join(HOST_ROOT, plugin_zip_name)
    shutil.copy2(os.path.join(HOST_ROOT, plugin_zip_rel), easy_plugin)

    root_entries = [
        (repo_zip_name, repo_zip_name),
        (plugin_zip_name, plugin_zip_name),
        ('zips/', 'zips/'),
    ]
    with open(os.path.join(HOST_ROOT, 'index.html'), 'w',
              encoding='utf-8', newline='\n') as f:
        f.write(_write_dir_index(root_entries, 'Index of /repo/'))

    # Subfolder indexes so browsing still works
    zips_entries = []
    for addon_id in ADDONS:
        zips_entries.append(('{}/'.format(addon_id), '{}/'.format(addon_id)))
        sub_entries = []
        sub_dir = os.path.join(ZIPS_DIR, addon_id)
        for fname in sorted(os.listdir(sub_dir)):
            if fname.endswith('.zip'):
                sub_entries.append((fname, fname))
        with open(os.path.join(sub_dir, 'index.html'), 'w',
                  encoding='utf-8', newline='\n') as f:
            f.write(_write_dir_index(
                sub_entries, 'Index of /repo/zips/{}/'.format(addon_id)))
    zips_entries.append(('addons.xml', 'addons.xml'))
    zips_entries.append(('addons.xml.md5', 'addons.xml.md5'))
    with open(os.path.join(ZIPS_DIR, 'index.html'), 'w',
              encoding='utf-8', newline='\n') as f:
        f.write(_write_dir_index(zips_entries, 'Index of /repo/zips/'))

    print('Wrote {}'.format(xml_path))
    print('Pages root: {}/'.format(PAGES_BASE))
    print('TV source URL: {}/'.format(PAGES_BASE))
    return 0


if __name__ == '__main__':
    sys.exit(main())
