#!/usr/bin/env python3
"""Nuvio Hub 6.0.8 rebrand + Kodi 22/Piers static compatibility guard."""
from pathlib import Path
import ast
import json
import py_compile
import re
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
RETIRED = bytes((100, 101, 120)).decode('ascii')  # retired brand prefix, never spelled out
RETIRED_RE = re.compile(r'(?<![nN])' + RETIRED, re.I)
EXPECTED = sys.argv[1] if len(sys.argv)>1 else '6.0.8'
COMPONENTS = ('plugin.video.nuviohub', 'script.nuvio', 'skin.nuvio', 'screensaver.nuvio')

errors = []
checks = []

def ok(name, cond, detail=''):
    if cond:
        checks.append(name)
    else:
        errors.append(f'{name}: {detail or "failed"}')

# Unified component versions and Kodi ABI declarations.
for aid in COMPONENTS:
    root = ET.parse(ROOT / aid / 'addon.xml').getroot()
    ok(f'{aid} version', root.get('version') == EXPECTED, root.get('version') or '<missing>')

backend = ET.parse(ROOT / 'plugin.video.nuviohub/addon.xml').getroot()
req = {x.get('addon'): x.get('version') for x in backend.findall('./requires/import')}
ok('backend id', backend.get('id') == 'plugin.video.nuviohub', backend.get('id') or '')
ok('xbmc.python ABI', req.get('xbmc.python') == '3.0.0', str(req.get('xbmc.python')))
ok('xbmc.gui Omega/Piers compatible ABI', req.get('xbmc.gui') == '5.17.0', str(req.get('xbmc.gui')))
skin = ET.parse(ROOT / 'skin.nuvio/addon.xml').getroot()
skin_req = {x.get('addon'): x.get('version') for x in skin.findall('./requires/import')}
ok('skin xbmc.gui ABI', skin_req.get('xbmc.gui') == '5.17.0', str(skin_req.get('xbmc.gui')))

# English-only UI.
lang_root = ROOT / 'plugin.video.nuviohub/resources/language'
ok('Arabic locale removed', not any(lang_root.glob('resource.language.ar_*')))
settings_text = (ROOT / 'plugin.video.nuviohub/resources/settings.xml').read_text(encoding='utf-8')
ok('UI language English only', 'values="English"' in settings_text and 'values="Arabic' not in settings_text and '|Arabic' not in settings_text)
i18n = (ROOT / 'plugin.video.nuviohub/resources/lib/i18n.py').read_text(encoding='utf-8')
ok('runtime Arabic translation table removed', 'STRINGS = {}' in i18n and "return \"en\"" in i18n)
po = (ROOT / 'plugin.video.nuviohub/resources/language/resource.language.en_gb/strings.po').read_text(encoding='utf-8')
ok('English locale has no Arabic UI option', 'msgid "Arabic"' not in po)

# Nuvio Hub runtime namespace / assets.
paths = [str(p.relative_to(ROOT)).lower() for p in (ROOT / 'plugin.video.nuviohub').rglob('*')]
ok('no retired-brand runtime paths', not any(RETIRED_RE.search(p) for p in paths), ', '.join(p for p in paths if RETIRED_RE.search(p))[:500])
ok('Nuvio Hub runtime package exists', (ROOT / 'plugin.video.nuviohub/resources/lib/nuviohub').is_dir())
ok('Nuvio Hub TMDb player exists', (ROOT / 'plugin.video.nuviohub/resources/players/nuviohub.json').is_file())
player = json.loads((ROOT / 'plugin.video.nuviohub/resources/players/nuviohub.json').read_text(encoding='utf-8'))
ok('TMDb player name', player.get('name') == 'Nuvio Hub', str(player.get('name')))
ok('TMDb player language English', player.get('language') == 'en', str(player.get('language')))
player_blob = json.dumps(player, ensure_ascii=False)
ok('new TMDb routes have no Arabic-title parameters', 'ar_title' not in player_blob and 'ar_showname' not in player_blob)

# Disallow active old imports/window-property namespace. Explicit upgrade/legal aliases are handled separately.
disallowed = []
for base in ('plugin.video.nuviohub', 'script.nuvio', 'skin.nuvio', 'screensaver.nuvio'):
    for p in (ROOT / base).rglob('*'):
        if not p.is_file() or 'tests' in p.parts or p.name == 'LICENSE.txt' or 'licenses' in p.parts:
            continue
        if p.suffix.lower() not in {'.py', '.xml', '.json', '.txt', '.po'}:
            continue
        try:
            text = p.read_text(encoding='utf-8')
        except Exception:
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            if RETIRED_RE.search(line):
                disallowed.append(f'{p.relative_to(ROOT)}:{line_no}')
ok('retired brand absent from runtime sources', not disallowed, '; '.join(disallowed[:20]))

# The whole tree (docs, tests, review tools, licenses) must not spell the
# retired brand either. No exceptions.
spelled = []
for p in ROOT.rglob('*'):
    if not p.is_file() or '.git' in p.parts or '__pycache__' in p.parts:
        continue
    if p.suffix.lower() not in {'.py', '.xml', '.json', '.txt', '.po', '.md', '.yml', '.yaml', '.cfg', '.ini'}:
        continue
    try:
        text = p.read_text(encoding='utf-8')
    except Exception:
        continue
    for line_no, line in enumerate(text.splitlines(), 1):
        if RETIRED_RE.search(line):
            spelled.append(f'{p.relative_to(ROOT)}:{line_no}')
ok('retired brand absent from repository text', not spelled, '; '.join(spelled[:20]))

# Intentional compatibility hooks must remain so an in-place update does not strand old profiles.
legacy = (ROOT / 'plugin.video.nuviohub/resources/lib/legacy_names.py').read_text(encoding='utf-8')
fork = (ROOT / 'plugin.video.nuviohub/resources/lib/fork_profile.py').read_text(encoding='utf-8')
bundle = (ROOT / 'plugin.video.nuviohub/resources/lib/bundle_installer.py').read_text(encoding='utf-8')
tmdbh = (ROOT / 'plugin.video.nuviohub/resources/lib/tmdbh_player.py').read_text(encoding='utf-8')
shortcut = (ROOT / 'plugin.video.nuviohub/resources/lib/shortcut_manager.py').read_text(encoding='utf-8')
ok('legacy prefix assembled at runtime', 'bytes((100, 101, 120))' in legacy)
ok('legacy addon migration retained', 'OLD_ADDON_ID as OLD_ID' in fork)
ok('legacy addon disable retained', 'OLD_ADDON_ID' in bundle)
ok('legacy TMDb player cleanup retained', 'OLD_PLAYER_PREFIXES' in tmdbh and 'OLD_PLAYER_NAME' in tmdbh)
ok('legacy keymap cleanup retained', 'OLD_KEYMAP_FILENAMES' in shortcut)
service = (ROOT / 'plugin.video.nuviohub/service.py').read_text(encoding='utf-8')
ok('legacy settings migration retained', 'legacy_names.carry_forward' in service)

# Python 3.14 removed-stdlib audit. Kodi 22 Beta 2 moved to Python 3.14.7.
removed_modules = {
    'aifc','audioop','cgi','cgitb','chunk','crypt','imghdr','imp','mailcap','msilib',
    'nis','nntplib','ossaudiodev','pipes','sndhdr','spwd','sunau','telnetlib','uu','xdrlib',
    'lib2to3','distutils',
}
removed_hits = []
compiled = 0
for p in ROOT.rglob('*.py'):
    if '.git' in p.parts or '__pycache__' in p.parts:
        continue
    try:
        py_compile.compile(str(p), doraise=True)
        compiled += 1
    except Exception as exc:
        errors.append(f'Python compile {p.relative_to(ROOT)}: {exc}')
        continue
    try:
        tree = ast.parse(p.read_text(encoding='utf-8'))
    except Exception:
        continue
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name.split('.')[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module.split('.')[0]]
        for name in names:
            if name in removed_modules:
                removed_hits.append(f'{p.relative_to(ROOT)}:{getattr(node,"lineno",0)}:{name}')
ok('Python 3.14 removed-stdlib audit', not removed_hits, '; '.join(removed_hits[:20]))

# XML / JSON parse guard.
xml_count = 0
json_count = 0
for p in ROOT.rglob('*.xml'):
    if '.git' in p.parts:
        continue
    try:
        ET.parse(p); xml_count += 1
    except Exception as exc:
        errors.append(f'XML parse {p.relative_to(ROOT)}: {exc}')
for p in ROOT.rglob('*.json'):
    if '.git' in p.parts:
        continue
    try:
        json.loads(p.read_text(encoding='utf-8')); json_count += 1
    except Exception as exc:
        errors.append(f'JSON parse {p.relative_to(ROOT)}: {exc}')

result = {
    'result': 'PASS' if not errors else 'FAIL',
    'version': EXPECTED,
    'checks_passed': len(checks),
    'python_files_compiled': compiled,
    'xml_files_parsed': xml_count,
    'json_files_parsed': json_count,
    'errors': errors,
}
print(json.dumps(result, indent=2, ensure_ascii=False))
sys.exit(1 if errors else 0)
