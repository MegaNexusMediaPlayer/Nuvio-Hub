# -*- coding: utf-8 -*-
"""v5.4.4 — three guards against the fault that cost this project the most.

Every one of these was found the hard way, more than once:

  * search_style, clean_catalog_view and the quality badges each had a code
    fallback that disagreed with settings.xml, so the settings screen said
    one thing and the addon did another. The user changed a setting and
    nothing happened — three separate sessions, same root cause.
  * the 5.4.0 build hid 102 settings and force-wrote two of them through a
    migration, silently reversing choices the user had made.

Guards, not fixes: a fix closes one instance, a guard closes the class.
Anything intentional is listed with the reason it is intentional, so the
next person adding an exception has to state their case in code.
"""
import glob
import io
import os
import re
import unittest
import xml.etree.ElementTree as ET

import kodi_stub

ROOT = kodi_stub.ADDON_ROOT
SETTINGS = os.path.join(ROOT, 'resources', 'settings.xml')

# ── deliberate divergences, each with its reason ────────────────────────
ALLOWED_FALLBACK_DIVERGENCE = {
    # network clients keep a longer safety timeout than the UI default:
    # the setting tunes the SEARCH budget, these guard a single request
    'timeout': 'network clients use a longer per-request safety timeout',
    # '0' means "auto / follow the skin"; the xml default names a preset
    'theme_preset': "'0' means auto-detect, a valid distinct state",
    # the enum accepts both the index and the legacy word
    'continue_art_style': 'enum accepts both the index and the legacy name',
    # writer-side sentinel, not a user default
    'nuviohub_defaults_rev': 'migration sentinel, not a user-facing default',
    # service picks its own routing when the user has expressed no opinion
    'catalog_click_mode': 'service-side routing default, user value wins',
    # perf lane sizes itself from the device, the setting caps it
    'parallel_workers': 'runtime sizes the pool; the setting is a cap',
}

# a hidden setting must look like machine state, never like a user choice
INTERNAL = re.compile(r'_json$|_map$|_at$|_action$|_rev$|_applied$|_cache$'
                      r'|_state$|_token$|_secret$|_uuid$|providers|autodetected'
                      r'|_status$|_force_|_seen$|_shown$'
                      r'|_client_id$|_client_identifier$|_device_id$|_keymap_data$'
                      r'|^poster_source_mode$|^source_sort_mode$'
                      r'|^source_priority_order$')

FALLBACK_RE = re.compile(
    r"""getSetting\(\s*['"](\w+)['"]\s*\)\s*or\s*['"]([^'"]*)['"]"""
    r"""|_setting\(\s*['"](\w+)['"]\s*,\s*['"]([^'"]*)['"]""")


def _declared_defaults():
    return {s.get('id'): (s.get('default') or '').strip()
            for s in ET.parse(SETTINGS).getroot().iter('setting') if s.get('id')}


def _source_files():
    files = glob.glob(os.path.join(ROOT, 'resources', 'lib', '**', '*.py'),
                      recursive=True)
    files.append(os.path.join(ROOT, 'service.py'))
    return [f for f in files if os.path.isfile(f)]


class TestFallbacksMatchTheSettingsScreen(unittest.TestCase):
    """GUARD 1 — the code must not contradict what the user is shown."""

    def test_no_undocumented_divergence(self):
        declared = _declared_defaults()
        offenders = []
        for path in _source_files():
            for m in FALLBACK_RE.finditer(io.open(path, encoding='utf-8').read()):
                sid = m.group(1) or m.group(3)
                fallback = (m.group(2) if m.group(1) else m.group(4)).strip()
                real = declared.get(sid)
                if real is None or not fallback:
                    continue                      # not a declared setting
                if real.lower() == fallback.lower():
                    continue                      # agrees
                if sid in ALLOWED_FALLBACK_DIVERGENCE:
                    continue                      # documented above
                offenders.append('%s: %s code=%r xml=%r'
                                 % (os.path.basename(path), sid, fallback, real))
        self.assertEqual(sorted(set(offenders)), [],
                         'code fallback disagrees with settings.xml:\n  '
                         + '\n  '.join(sorted(set(offenders))))

    def test_the_switches_that_broke_before_are_aligned(self):
        """Named regressions: each of these shipped wrong at least once."""
        declared = _declared_defaults()
        blob = '\n'.join(io.open(p, encoding='utf-8').read() for p in _source_files())
        for sid in ('elite_badges_enabled', 'search_style', 'clean_catalog_view',
                    'enable_trakt', 'enable_stremio_subtitle_broker',
                    'cloud_sync_continuous', 'lightweight_mode',
                    'hide_pagination_more', 'catalog_genre_folders'):
            want = declared[sid].lower()
            for m in re.finditer(
                    r"""(?:getSetting\(\s*['"]%s['"]\s*\)\s*or|"""
                    r"""_setting\(\s*['"]%s['"]\s*,)\s*['"]([^'"]*)['"]"""
                    % (sid, sid), blob):
                got = m.group(1).strip().lower()
                if not got:
                    continue        # empty fallback defers to the caller
                self.assertEqual(got, want,
                                 '%s fallback disagrees with its default' % sid)

    def test_the_exception_list_stays_justified(self):
        """Every allowance must name a setting that still exists and give a
        reason — an empty reason is how exception lists rot."""
        declared = _declared_defaults()
        for sid, reason in ALLOWED_FALLBACK_DIVERGENCE.items():
            self.assertIn(sid, declared, '%s no longer exists' % sid)
            self.assertGreater(len(reason), 20, '%s has no real reason' % sid)


class TestSettingsStayReachable(unittest.TestCase):
    """GUARD 2 — a release may not hide a user's controls."""

    def test_only_internal_state_is_hidden(self):
        offenders = [s.get('id') for s in ET.parse(SETTINGS).getroot().iter('setting')
                     if s.get('id') and s.get('visible') == 'false'
                     and not INTERNAL.search(s.get('id'))]
        self.assertEqual(sorted(offenders), [],
                         'user-facing settings hidden from the UI: %s' % offenders)

    def test_group_headers_are_visible(self):
        raw = io.open(SETTINGS, encoding='utf-8').read()
        self.assertEqual(
            re.findall(r'<setting type="(?:sep|lsep)"[^/]*visible="false"', raw), [])

    def test_no_category_is_a_wall(self):
        for cat in ET.parse(SETTINGS).getroot().iter('category'):
            n = len([s for s in cat.iter('setting') if s.get('id')])
            self.assertLessEqual(n, 30, 'category %s has %d settings'
                                 % (cat.get('label'), n))


class TestMigrationsRespectUserChoices(unittest.TestCase):
    """GUARD 3 — a migration may set up a new install, never overrule one."""

    OPT_IN = ('elite_badges_enabled', 'cloud_sync_continuous', 'enable_trakt',
              'enable_simkl', 'nuvio_sync_enabled', 'stremio_sync_enabled',
              'theme_preset', 'search_style', 'home_style',
              'elite_badges_json_url', 'nuvio_sync_library')

    def _migration_bodies(self):
        service = io.open(os.path.join(ROOT, 'service.py'), encoding='utf-8').read()
        context = io.open(os.path.join(ROOT, 'resources', 'lib', 'context.py'),
                          encoding='utf-8').read()
        return service + '\n' + context

    def test_no_migration_force_writes_an_opt_in_feature(self):
        blob = self._migration_bodies()
        # a bulk `values = { ... }` table applied with setSetting is the shape
        # that reversed the user's badges and continuous-sync choices
        for table in re.findall(r'values = \{(.*?)\}', blob, re.S):
            for sid in self.OPT_IN:
                self.assertNotIn("'%s'" % sid, table,
                                 '%s is force-written by a migration' % sid)

    def test_permanent_constraint_still_holds(self):
        ctx = io.open(os.path.join(ROOT, 'resources', 'lib', 'context.py'),
                      encoding='utf-8').read()
        self.assertIn("'clean_catalog_view': 'false',", ctx)

    def test_corrective_migration_checks_before_writing(self):
        ctx = io.open(os.path.join(ROOT, 'resources', 'lib', 'context.py'),
                      encoding='utf-8').read()
        seg = ctx.split("if rev == '139-clean-defaults':", 1)[1][:900]
        self.assertIn("getSetting('clean_catalog_view')", seg)


if __name__ == '__main__':
    unittest.main(verbosity=2)
