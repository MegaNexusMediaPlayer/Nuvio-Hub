#!/usr/bin/env python3
"""Maintained regression suite and source-format checks (not a Kodi runtime)."""
import ast
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ('plugin.video.nuviohub', 'script.nuvio', 'skin.nuvio', 'screensaver.nuvio')
MODULES = ('test_nuvio_601', 'test_nuvio_602', 'test_nuvio_603', 'test_nuvio_604',
           'test_nuvio_605', 'test_nuvio_609', 'test_nuvio_610', 'test_nuvio_611', 'test_nuvio_612', 'test_nuvio_613', 'test_nuvio_home_iptv',
           'test_nuvio_build', 'test_nuvio_extras', 'test_nuvio_reliability',
           'test_nuvio_architecture')


def main():
    counts = {'runtime_python38_grammar': 0, 'component_xml': 0, 'component_json': 0}
    errors = []
    for component in COMPONENTS:
        for path in (ROOT / component).rglob('*'):
            if not path.is_file() or any(part in ('tests', '__pycache__', 'packages', '.test-profile') for part in path.parts):
                continue
            try:
                if path.suffix == '.py':
                    ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path), feature_version=(3, 8))
                    counts['runtime_python38_grammar'] += 1
                elif path.suffix == '.xml':
                    ET.parse(path)
                    counts['component_xml'] += 1
                elif path.suffix == '.json':
                    json.loads(path.read_text(encoding='utf-8-sig'))
                    counts['component_json'] += 1
            except (SyntaxError, ValueError, OSError, ET.ParseError) as exc:
                errors.append('%s: %s' % (path.relative_to(ROOT), exc))
    env = dict(os.environ)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    env['PYTHONPATH'] = str(ROOT / 'plugin.video.nuviohub/tests')
    result = subprocess.run([sys.executable, '-m', 'unittest', *MODULES], cwd=str(ROOT),
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, timeout=180)
    print(result.stdout)
    (ROOT / 'review/unit-tests-6.0.13.txt').write_text(result.stdout, encoding='utf-8')
    match = re.search(r'Ran (\d+) tests? in ([0-9.]+)s', result.stdout)
    report = {'version': '6.0.13', 'base': 'local 6.0.12 candidate',
              'python': sys.version.split()[0], 'checks': counts,
              'unit_tests': int(match.group(1)) if match else None,
              'unit_seconds': float(match.group(2)) if match else None,
              'test_modules': list(MODULES), 'errors': errors,
              'result': 'PASS' if not errors and result.returncode == 0 else 'FAIL',
              'scope': 'HTTP/Kodi stubs, real local SQLite; not Kodi rendering, native playback or live accounts.'}
    (ROOT / 'review/results-6.0.13.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    return 0 if report['result'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
