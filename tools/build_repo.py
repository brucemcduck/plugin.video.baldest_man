#!/usr/bin/env python3
"""Build Kodi repository zips and generate addons.xml for GitHub hosting.

Usage (from repo root):
    python tools/build_repo.py

Outputs:
    repo/zips/addons.xml
    repo/zips/addons.xml.md5
    repo/zips/plugin.video.baldest_man/plugin.video.baldest_man-VERSION.zip
    repo/zips/repository.baldest_man/repository.baldest_man-VERSION.zip
    repo/repository.baldest_man-VERSION.zip  (easy TV install copy)
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
REPO_DIR = os.path.join(ROOT, 'repo')
ZIPS_DIR = os.path.join(REPO_DIR, 'zips')

# Addon folders to package (id -> source path relative to ROOT).
ADDONS = {
    'plugin.video.baldest_man': ROOT,
    'repository.baldest_man': os.path.join(REPO_DIR, 'repository.baldest_man'),
}

# Paths excluded from the video plugin zip (repo/hosting/dev files).
PLUGIN_SKIP = {
    '.git', '.github', 'repo', 'tools', 'docs', 'ideas.txt', 'README.md',
    'requirements.txt', 'cli.py', 'check_scrapers.py', '.gitignore',
    '.DS_Store', 'Thumbs.db',
}
PLUGIN_SKIP_PREFIXES = ('test_',)
PLUGIN_SKIP_SUFFIXES = ('.pyc', '.pyo')


def _read_version(addon_dir):
    tree = ET.parse(os.path.join(addon_dir, 'addon.xml'))
    root = tree.getroot()
    return root.get('version', '0.0.0')


def _addon_xml_body(addon_dir):
    """Return the <addon>...</addon> element as a string for addons.xml."""
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
    """Create addon zip with top-level folder matching addon_id."""
    os.makedirs(os.path.dirname(dest_zip), exist_ok=True)
    with tempfile.TemporaryDirectory() as staging:
        dest_root = os.path.join(staging, addon_id)
        if addon_id == 'plugin.video.baldest_man':
            for dirpath, dirnames, filenames in os.walk(source_dir):
                rel = os.path.relpath(dirpath, source_dir)
                if rel == '.':
                    rel_parts = []
                else:
                    rel_parts = rel.split(os.sep)
                dirnames[:] = [
                    d for d in dirnames
                    if not _should_skip_plugin(d, os.path.join(rel, d))
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
                    arc = os.path.relpath(full, staging)
                    zf.write(full, arc)


def _write_addons_xml(entries):
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<addons>']
    for body in entries:
        lines.append(body)
    lines.append('</addons>')
    return '\n'.join(lines) + '\n'


def main():
    addon_bodies = []
    for addon_id, source_dir in ADDONS.items():
        version = _read_version(source_dir)
        zip_name = '{}-{}.zip'.format(addon_id, version)
        zip_path = os.path.join(ZIPS_DIR, addon_id, zip_name)
        print('Building {} -> {}'.format(addon_id, zip_path))
        _zip_addon(addon_id, source_dir, zip_path)
        addon_bodies.append(_addon_xml_body(source_dir))

    addons_xml = _write_addons_xml(addon_bodies)
    os.makedirs(ZIPS_DIR, exist_ok=True)
    xml_path = os.path.join(ZIPS_DIR, 'addons.xml')
    with open(xml_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(addons_xml)

    digest = hashlib.md5(addons_xml.encode('utf-8')).hexdigest()
    md5_path = os.path.join(ZIPS_DIR, 'addons.xml.md5')
    with open(md5_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(digest)

    repo_version = _read_version(ADDONS['repository.baldest_man'])
    repo_zip = os.path.join(
        ZIPS_DIR, 'repository.baldest_man',
        'repository.baldest_man-{}.zip'.format(repo_version))
    easy_zip = os.path.join(
        REPO_DIR, 'repository.baldest_man-{}.zip'.format(repo_version))
    shutil.copy2(repo_zip, easy_zip)
    print('Wrote {} and {}'.format(xml_path, md5_path))
    print('TV install zip: {}'.format(easy_zip))
    return 0


if __name__ == '__main__':
    sys.exit(main())
