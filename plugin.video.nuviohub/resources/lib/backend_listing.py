"""Plain Kodi directory output for long AIOMetadata catalogs; the skin owns rendering."""
from . import backend_api


def render(params):
    from . import plugin as p
    from .nuviohub.client import fetch_catalog
    source=backend_api.provider('metadata')
    if not source:
        p.add_item('Connect AIOMetadata in HUB Settings',p.build_url(action='first_run_wizard'),is_folder=False)
        return p.end_dir(content='files',cache=False)
    mt=params.get('media_type') or 'movie';cid=params.get('catalog_id') or ''
    catalog=next((c for c in (source.get('manifest') or {}).get('catalogs') or [] if c.get('id')==cid and c.get('type')==mt),None)
    if not catalog:
        p.add_item('Enable this catalog in AIOMetadata',p.build_url(action='first_run_wizard'),is_folder=False)
        return p.end_dir(content='files',cache=False)
    try:skip=max(0,int(params.get('page') or 0))
    except ValueError:skip=0
    extra={k:params[k] for k in ('genre','search','year') if params.get(k) and params[k]!='None'}
    if skip:extra['skip']=skip
    data=fetch_catalog(source,mt,cid,extra=extra,timeout_override=12)
    raw=(data or {}).get('metas') or []
    for meta in raw:
        if not isinstance(meta,dict) or not meta.get('id'):continue
        title=meta.get('name') or meta.get('title') or meta['id']
        p.add_item(title,p.build_url(action='play_item',media_type=mt,canonical_id=meta['id'],title=title),
                   is_folder=False,info=p._meta_info(meta),art={'poster':meta.get('poster') or '',
                   'thumb':meta.get('poster') or '', 'fanart':meta.get('background') or ''},properties={'IsPlayable':'false'})
    supports_skip=any((e.get('name') if isinstance(e,dict) else e)=='skip' for e in catalog.get('extra') or [])
    if raw and supports_skip:
        query=dict(params,action='catalog_all',page=str(skip+len(raw)),provider_id=source['id'])
        p.add_item('Next page',p.build_url(**query))
    if not raw:p.add_item('No more titles','',is_folder=False)
    return p.end_dir(content='tvshows' if mt=='series' else 'movies',cache=False)
