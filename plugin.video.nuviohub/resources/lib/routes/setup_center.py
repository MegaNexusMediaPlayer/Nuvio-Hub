# -*- coding: utf-8 -*-
"""Small, task-oriented setup front door for Nuvio Hub.

Kodi's native settings window remains available for advanced users, but it is
not a friendly first stop on a television.  This module groups the handful of
choices that materially change day-to-day use into short remote-friendly
dialogs.  It deliberately never enables automatic source playback without a
separate confirmation.
"""


def _setting(addon, key, default=''):
    try:
        value = addon.getSetting(key)
    except Exception:
        value = ''
    return str(value if value not in (None, '') else default)


def _set_many(addon, values):
    for key, value in values.items():
        addon.setSetting(str(key), str(value))


def _provider_count(api):
    try:
        return len(api.store.list_providers() or [])
    except Exception:
        return 0


def _manual_source_mode(addon):
    return _setting(
        addon, 'playback_open_mode', 'Choose from sources'
    ).strip().lower() != 'best quality automatically'


def status_text(api):
    """Return a compact, privacy-safe configuration summary."""
    addon = api.ADDON
    source_mode = (
        api.tr('اختيار المصدر يدوياً') if _manual_source_mode(addon)
        else api.tr('تشغيل أفضل جودة تلقائياً')
    )
    subtitle_mode = _setting(addon, 'subtitle_search_mode', 'Play only')
    subtitle_label = (
        api.tr('عند الطلب') if subtitle_mode.strip().lower() == 'play only'
        else api.tr('مع التشغيل')
    )
    try:
        timeout = max(10, min(20, int(float(
            _setting(addon, 'subtitle_timeout', '15')))))
    except Exception:
        timeout = 15
    return api.tr('%d مصدر • %s • الترجمة %s (%d ثانية)') % (
        _provider_count(api), source_mode, subtitle_label, timeout)


def render(api):
    """Render the simple setup centre as a normal Kodi directory."""
    add = api.add_item
    url = api.build_url
    art = api.root_art

    add(api.tr('الحالة • %s') % status_text(api),
        url(action='setup_diagnostics'), is_folder=False,
        art=art('settings'),
        info={'title': api.tr('حالة الإعداد'),
              'plot': api.tr('ملخص سريع دون عرض مفاتيح أو بيانات خاصة.')})
    add(api.tr('البداية السريعة'), url(action='first_run_wizard'),
        art=art('add'),
        info={'title': api.tr('البداية السريعة'),
              'plot': api.tr('اختر Nuvio أو Stremio أو الإعداد اليدوي فقط.')})
    add(api.tr('المصادر'), url(action='providers'), art=art('providers'),
        info={'title': api.tr('المصادر'),
              'plot': api.tr('إضافة المصادر وترتيبها وإدارة الحسابات المرتبطة.')})
    add(api.tr('طريقة التشغيل'), url(action='setup_playback'),
        is_folder=False, art=art('play'),
        info={'title': api.tr('طريقة التشغيل'),
              'plot': api.tr('الاختيار اليدوي هو الوضع الموصى به. التشغيل التلقائي يحتاج تأكيداً مستقلاً.')})
    add(api.tr('الترجمة'), url(action='setup_subtitles'),
        is_folder=False, art=art('subtitles'),
        info={'title': api.tr('الترجمة'),
              'plot': api.tr('وضع الترجمة ومدة البحث المشتركة من 10 إلى 20 ثانية.')})
    add(api.tr('الجودة'), url(action='setup_quality'),
        is_folder=False, art=art('catalogs'),
        info={'title': api.tr('الجودة'),
              'plot': api.tr('ملفات جاهزة: متوازن، أفضل جودة، أو توفير البيانات.')})
    add(api.tr('المظهر'), url(action='theme_select'),
        is_folder=False, art=art('settings'),
        info={'title': api.tr('المظهر'),
              'plot': api.tr('اختر ثيماً هادئاً مع معاينة الألوان.')})
    add(api.tr('الحسابات والمكتبات'), url(action='integrations_menu'),
        art=art('sync'),
        info={'title': api.tr('الحسابات والمكتبات'),
              'plot': api.tr('Nuvio وStremio وTrakt وPlex وEmby والتكاملات الأخرى.')})
    add(api.tr('ثبات الأجهزة الضعيفة'), url(action='setup_stability'),
        is_folder=False, art=art('settings'),
        info={'title': api.tr('ثبات الأجهزة الضعيفة'),
              'plot': api.tr('يوقف العمل الخلفي الثقيل والنوافذ الاختيارية من دون حذف أي مصدر.')})
    add(api.tr('إعدادات متقدمة'), url(action='open_settings'),
        is_folder=False, art=art('settings'),
        info={'title': api.tr('إعدادات متقدمة'),
              'plot': api.tr('كل الخيارات التفصيلية في نافذة إعدادات Kodi.')})
    return api.end_dir(content='files', cache=False)


def playback(api):
    labels = [
        api.tr('اختيار المصدر في كل مرة (موصى به)'),
        api.tr('استخدام نفس المصدر فقط'),
        api.tr('الاختيار عبر TMDb Helper'),
        api.tr('تشغيل أفضل جودة تلقائياً'),
    ]
    idx = api.xbmcgui.Dialog().select(api.tr('طريقة التشغيل'), labels)
    if idx < 0:
        return False
    if idx == 3:
        confirmed = api.xbmcgui.Dialog().yesno(
            api.tr('تأكيد التشغيل التلقائي'),
            api.tr('سيبدأ أفضل مصدر مباشرةً من دون نافذة اختيار. هل تريد تفعيله؟'),
        )
        if not confirmed:
            return False
        _set_many(api.ADDON, {
            'source_resolution_mode': 'NuvioHub picker',
            'playback_open_mode': 'Best quality automatically',
            'remember_last_source': 'false',
        })
    else:
        resolution = ('NuvioHub picker', 'Same source', 'TMDb Helper')[idx]
        _set_many(api.ADDON, {
            'source_resolution_mode': resolution,
            'playback_open_mode': 'Choose from sources',
            'remember_last_source': 'false',
        })
    api.notify(api.tr('تم حفظ طريقة التشغيل'))
    return True


def subtitles(api):
    mode_labels = [
        api.tr('تشغيل فقط؛ الترجمة عند الطلب'),
        api.tr('تشغيل مع ترجمة'),
    ]
    mode_idx = api.xbmcgui.Dialog().select(api.tr('وضع الترجمة'), mode_labels)
    if mode_idx < 0:
        return False
    timeout_labels = [
        api.tr('10 ثوانٍ'), api.tr('15 ثانية (موصى به)'), api.tr('20 ثانية')
    ]
    timeout_idx = api.xbmcgui.Dialog().select(
        api.tr('مدة البحث المشتركة'), timeout_labels)
    if timeout_idx < 0:
        return False
    _set_many(api.ADDON, {
        'subtitle_search_mode': (
            'Play only' if mode_idx == 0 else 'Play with subtitles'),
        'subtitle_timeout': ('10', '15', '20')[timeout_idx],
    })
    api.notify(api.tr('تم حفظ إعداد الترجمة'))
    return True


def quality(api):
    values = (
        'Balanced (recommended)', 'Best', 'Data saver', 'Custom'
    )
    labels = [
        api.tr('متوازن (موصى به)'), api.tr('أفضل جودة'),
        api.tr('توفير البيانات'), api.tr('مخصص'),
    ]
    idx = api.xbmcgui.Dialog().select(api.tr('ملف الجودة'), labels)
    if idx < 0:
        return False
    api.ADDON.setSetting('quality_profile', values[idx])
    api.notify(api.tr('تم حفظ ملف الجودة'))
    if idx == 3:
        api.open_settings_action()
    return True


def stability(api):
    confirmed = api.xbmcgui.Dialog().yesno(
        api.tr('ثبات الأجهزة الضعيفة'),
        api.tr('تفعيل الوضع الخفيف وإيقاف نافذة الانتظار والكاش المسبق للحلقة التالية والعمل المتوازي الثقيل؟'),
    )
    if not confirmed:
        return False
    _set_many(api.ADDON, {
        'lightweight_mode': 'true',
        'show_playback_waiter': 'false',
        'pre_cache_next_episode': 'false',
        'streams_full_parallel_scan': 'false',
        'elite_badges_enabled': 'false',
        'verbose_logging': 'false',
    })
    api.notify(api.tr('تم تفعيل إعداد الثبات'))
    return True


def diagnostics(api):
    try:
        from ..runtime_tasks import active_count
        optional_jobs = active_count()
    except Exception:
        optional_jobs = 0
    details = [
        api.tr('الإصدار: %s') % api.ADDON.getAddonInfo('version'),
        api.tr('المصادر: %d') % _provider_count(api),
        api.tr('المهام الخلفية الاختيارية: %d') % int(optional_jobs),
        api.tr('الوضع: اختيار يدوي') if _manual_source_mode(api.ADDON)
        else api.tr('الوضع: تشغيل تلقائي'),
        api.tr('الكاش المسبق للحلقة التالية: متوقف')
        if _setting(api.ADDON, 'pre_cache_next_episode', 'false').lower() != 'true'
        else api.tr('الكاش المسبق للحلقة التالية: مفعّل'),
    ]
    api.xbmcgui.Dialog().ok(api.tr('حالة Nuvio Hub'), '\n'.join(details))
    return True
