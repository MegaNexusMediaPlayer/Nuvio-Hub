# -*- coding: utf-8 -*-
"""Pure, self-contained routing helpers for plugin.video.nuviohub.

First module of the "safe helpers" tier from the v3.9.145 refactor map:
functions whose entire dependency closure is ``context.build_url`` plus each
other.  Moved verbatim from ``plugin.py`` (v3.9.147); behaviour is verified
identical via a 1700+-case before/after output snapshot.

Rules for adding functions here:
  * no Kodi UI calls (dialogs, ListItems, window properties),
  * no module-level state beyond what ``context`` provides,
  * no imports from ``plugin`` (would create a cycle).
"""

from .context import build_url


def _is_series_media(media_type=''):
    return str(media_type or '').strip().lower() in ('series', 'anime', 'show', 'tv')


def _source_picker_url(media_type='movie', canonical_id='', title='', season='', episode='', video_id='', resume_seconds='', preferred_provider_name='', source_provider_id='', source_mode='', resume_percent=''):
    media_type = str(media_type or 'movie').strip().lower()
    if season not in (None, '', 0, '0') and episode not in (None, '', 0, '0'):
        args = {
            'action': 'episode_streams',
            'canonical_id': canonical_id,
            'video_id': video_id or canonical_id,
            'season': str(season),
            'episode': str(episode),
            'title': title or canonical_id,
            'media_type': 'series' if _is_series_media(media_type) else media_type,
        }
        if resume_seconds not in (None, '', 0, '0'):
            args['resume_seconds'] = str(resume_seconds)
        if resume_percent not in (None, '', 0, '0'):
            args['resume_percent'] = str(resume_percent)
        if preferred_provider_name:
            args['preferred_provider_name'] = preferred_provider_name
        if source_provider_id:
            args['source_provider_id'] = source_provider_id
        if source_mode:
            args['source_mode'] = source_mode
        return build_url(**args)
    if _is_series_media(media_type):
        return build_url(action='series_meta', media_type='series', canonical_id=canonical_id, title=title or canonical_id, source_provider_id=source_provider_id or '')
    args = {'action': 'streams', 'media_type': media_type or 'movie', 'canonical_id': canonical_id, 'title': title or canonical_id}
    if resume_seconds not in (None, '', 0, '0'):
        args['resume_seconds'] = str(resume_seconds)
    if resume_percent not in (None, '', 0, '0'):
        args['resume_percent'] = str(resume_percent)
    if preferred_provider_name:
        args['preferred_provider_name'] = preferred_provider_name
    if source_provider_id:
        args['source_provider_id'] = source_provider_id
    if source_mode:
        args['source_mode'] = source_mode
    return build_url(**args)


def _source_picker_url_from_ctx(ctx, resume_seconds='', resume_percent=''):
    ctx = ctx or {}
    try:
        rs = resume_seconds if resume_seconds not in (None, '') else ctx.get('resume_seconds', '')
        rp = resume_percent if resume_percent not in (None, '') else ctx.get('resume_percent', '')
        return _source_picker_url(
            media_type=ctx.get('media_type') or 'movie',
            canonical_id=ctx.get('canonical_id') or '',
            title=ctx.get('title') or ctx.get('show_title') or ctx.get('canonical_id') or '',
            season=ctx.get('season') or '',
            episode=ctx.get('episode') or '',
            video_id=ctx.get('video_id') or ctx.get('canonical_id') or '',
            resume_seconds=rs,
            resume_percent=rp,
            preferred_provider_name=ctx.get('provider_name') or '',
            source_provider_id=ctx.get('source_provider_id') or ctx.get('meta_target_key') or '',
            source_mode=ctx.get('source_mode') or '',
        )
    except Exception:
        return ''
