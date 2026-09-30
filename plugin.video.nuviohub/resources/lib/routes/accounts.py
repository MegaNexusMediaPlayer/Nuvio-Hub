# -*- coding: utf-8 -*-
"""Account and cloud-sync routes.

This module owns Nuvio/Stremio login/logout/sync UI so the main plugin router
no longer carries account state and dialog orchestration.
"""
from __future__ import absolute_import


def qr_login(service):
    if service != 'nuvio':return False
    from resources.lib.qr_pair import qr_pair
    return qr_pair(service)


def login(service, addon, tr):
    if service != 'nuvio':return False
    import xbmcgui
    from resources.lib.dexhub import nuvio_stremio_sync as sync
    dlg = xbmcgui.Dialog()
    email = (addon.getSetting('%s_email' % service) or '').strip()
    password = addon.getSetting('%s_password' % service) or ''
    if not email or not password:
        dlg.ok('Nuvio Hub', tr('اكتب البريد وكلمة المرور في الإعدادات أولاً.'))
        return False
    try:
        if service == 'nuvio':
            sync.Nuvio.login(email, password)
        else:
            sync.Stremio.login(email, password)
        try:
            addon.setSetting('%s_password' % service, '')
        except Exception:
            pass
        # v4.0.0: linking implies the user wants sync — enable the master
        # toggle so "Sync now" works right away instead of a dead end.
        try:
            addon.setSetting('%s_sync_enabled' % service, 'true')
        except Exception:
            pass
        dlg.notification('Nuvio Hub', tr('تم تسجيل الدخول ✓'), xbmcgui.NOTIFICATION_INFO, 4000)
        return True
    except Exception as exc:
        dlg.ok('Nuvio Hub', tr('فشل تسجيل الدخول:') + '\n' + str(exc))
        return False


def logout(service, tr):
    import xbmcgui
    from resources.lib.dexhub import nuvio_stremio_sync as sync
    if service == 'nuvio':
        sync.Nuvio.clear()
    else:
        sync.Stremio.clear()
    xbmcgui.Dialog().notification('Nuvio Hub', tr('تم تسجيل الخروج'), xbmcgui.NOTIFICATION_INFO, 3000)
    return True


def direction(addon):
    raw = addon.getSetting('cloud_sync_direction') or 'Two-way'
    if raw in ('Upload only', 'رفع فقط'):
        return 'push'
    if raw in ('Download only', 'سحب فقط'):
        return 'pull'
    return 'both'


def sync_options(addon, tr, setting):
    """Small front door for the adaptive account-sync policy."""
    import xbmcgui
    while True:
        try:
            interval = int(float(setting('cloud_sync_interval_min', '30') or '30'))
        except Exception:
            interval = 30
        continuous = (setting('cloud_sync_continuous', 'true') or 'true'
                      ).strip().lower() in ('true', '1', 'yes', 'on')
        if interval <= 0:
            mode = tr('موقوفة')
        elif continuous:
            mode = tr('مستمرة (فورية)')
        else:
            mode = tr('ذكية وخفيفة')
        rows = [
            '%s:  [B]%s[/B]' % (tr('وضع المزامنة'), mode),
            '%s:  [B]%s[/B]' % (
                tr('فترة السحب'),
                (tr('%d دقيقة') % interval) if interval > 0 else tr('موقوفة')),
            tr('مزامنة الآن'),
        ]
        choice = xbmcgui.Dialog().select(tr('إعدادات المزامنة'), rows)
        if choice < 0:
            return
        if choice == 0:
            # v5.4.1: continuous is selectable again. This dialog wrote
            # cloud_sync_continuous='false' on EVERY pass, so the setting
            # could never be turned on from the one screen built to
            # control it — and the service loop ignored it anyway.
            pick = xbmcgui.Dialog().select(
                tr('وضع المزامنة'),
                [tr('مستمرة (فورية)'), tr('ذكية وخفيفة'), tr('موقوفة')])
            if pick < 0:
                continue
            if pick == 2:
                addon.setSetting('cloud_sync_interval_min', '0')
            else:
                if interval <= 0:
                    addon.setSetting('cloud_sync_interval_min', '30')
                addon.setSetting('cloud_sync_continuous',
                                 'true' if pick == 0 else 'false')
        elif choice == 1:
            options = [5, 15, 30, 60, 120, 240]
            pick = xbmcgui.Dialog().select(
                tr('فترة السحب'), [tr('%d دقيقة') % n for n in options])
            if pick < 0:
                continue
            addon.setSetting('cloud_sync_interval_min', str(options[pick]))
        else:
            return sync_now(addon, tr, only=None)
        try:
            from resources.lib import settings_cache
            settings_cache.invalidate()
        except Exception:
            pass


def sync_now(addon, tr, only=None):
    import xbmcgui
    from resources.lib.dexhub import nuvio_stremio_sync as sync
    dlg = xbmcgui.Dialog()
    targets = sync.enabled_targets()
    if only:
        targets = [t for t in targets if t == only]
        if not targets:
            dlg.ok('Nuvio Hub', tr('لا يوجد حساب مفعّل لهذه الخدمة.'))
            return False
    if not targets:
        dlg.ok('Nuvio Hub', tr('فعّل حساب Nuvio أو Stremio وسجّل الدخول أولاً.'))
        return False
    pd = xbmcgui.DialogProgressBG()
    pd.create('Nuvio Hub', tr('مزامنة الحسابات…'))
    try:
        pd.update(15, tr('تحضير المزامنة…'))
        # v4.0.0: direction and sections resolve per service from settings.
        result = sync.run_sync(targets=targets, force_full=False)
        pd.update(95, tr('حفظ النتائج…'))
    finally:
        pd.close()
    if not result or not result.get('ok'):
        errors = []
        for row in (result or {}).get('report', []):
            for name, section in (row.get('sections') or {}).items():
                if not section.get('ok'):
                    errors.append('%s/%s: %s' % (row.get('service'), name, section.get('error', '')))
        dlg.ok('Nuvio Hub', tr('فشلت المزامنة:') + '\n' + ('\n'.join(errors) or str((result or {}).get('error', ''))))
        return False
    ok_services = [r['service'] for r in result.get('report', []) if r.get('ok')]
    wb = result.get('writeback', {})
    msg = tr('تمت المزامنة')
    if ok_services:
        msg += ' • ' + ', '.join(ok_services)
    msg += ' • ' + tr('+%d إضافة، %d متابعة') % (
        wb.get('providers', 0), wb.get('progress', 0))
    dlg.notification('Nuvio Hub', msg, xbmcgui.NOTIFICATION_INFO, 6000)
    errors = []
    for row in result.get('report', []):
        for name, section in (row.get('sections') or {}).items():
            if not section.get('ok'):
                errors.append('%s/%s: %s' % (row.get('service'), name, section.get('error', '')))
    if errors:
        dlg.ok('Nuvio Hub • Sync details', '\n'.join(errors))
    return True
