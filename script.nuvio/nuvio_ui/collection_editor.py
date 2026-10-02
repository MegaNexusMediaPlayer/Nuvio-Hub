"""Explicit layout edits; provider sync never owns the Home design."""
import json
import xbmcgui
import xbmcvfs
from resources.lib import collection_profile, backend_api


def _image(title):
    dialog=xbmcgui.Dialog()
    choice=dialog.select(title,['Choose local image / GIF','Enter image URL'])
    if choice==0:return dialog.browseSingle(1,title,'files','.png|.jpg|.jpeg|.webp|.gif')
    if choice==1:
        value=dialog.input('Image URL').strip()
        if value and not value.startswith(('https://','http://')):raise ValueError('Use an HTTP or HTTPS image URL.')
        return value
    return ''


def _catalogs(folder):
    from resources.lib import metadata_providers
    from resources.lib.nuviohub import store
    switches = {p['id']: on for p, on in metadata_providers.entries()}
    options = [(p, c) for p in store.list_providers()
               if switches.get(p['id'], True)
               for c in (p.get('manifest') or {}).get('catalogs') or []
               if c.get('id') and c.get('type') in ('movie', 'series')]
    if not options:
        raise ValueError('Add a manifest with movie or series catalogs first.')
    old = {(s.get('addonId'), s.get('providerId'), s['catalogId'], s['type']): s
           for s in folder.get('sources') or []}
    def identity(p, c):
        return ((p.get('manifest') or {}).get('id'), p['id'], c['id'], c['type'])
    selected = xbmcgui.Dialog().multiselect('Catalogs for ' + folder['title'],
        ['%s · %s (%s)' % (p.get('name') or p['id'], c.get('name') or c['id'], c['type']) for p, c in options],
        preselect=[i for i, (p, c) in enumerate(options) if identity(p, c) in old])
    if selected is None:
        return False
    if not selected:
        raise ValueError('Choose at least one catalog. Use Hide to remove a card from Home.')
    folder['sources'] = [dict(old.get(identity(*options[i]), {}),
        addonId=(options[i][0].get('manifest') or {}).get('id', ''), providerId=options[i][0]['id'],
        catalogId=options[i][1]['id'], type=options[i][1]['type']) for i in selected]
    for source, index in zip(folder['sources'], selected):
        catalog = options[index][1]
        specs = {item['name']: item for item in catalog.get('extra') or [] if isinstance(item, dict) and item.get('name')}
        required = set(catalog.get('extraRequired') or []) | {name for name, spec in specs.items() if spec.get('isRequired')}
        extra = dict(source.get('extra') or {})
        if source.get('genre') and source['genre'] != 'None':extra['genre'] = source['genre']
        for name in sorted(required):
            if extra.get(name) not in (None, ''):continue
            values = specs.get(name, {}).get('options') or []
            if values:
                pick = xbmcgui.Dialog().select(source['catalogId'] + ' · ' + name, [str(v) for v in values])
                if pick < 0:return False
                extra[name] = str(values[pick])
            else:
                value = xbmcgui.Dialog().input(source['catalogId'] + ' · required ' + name).strip()
                if not value:return False
                extra[name] = value
        source['extra'] = extra
    return True


def _source_label(source, providers):
    from resources.lib.collections_home import matching_catalog
    kind = 'Series' if source.get('type') == 'series' else 'Movies'
    match = matching_catalog(source, providers)
    if not match:
        return '%s (%s)' % (source.get('catalogId'), kind), False
    provider, catalog = match
    name = catalog.get('name') or catalog.get('id')
    genre = source.get('genre') if source.get('genre') not in (None, '', 'None') else ''
    return '%s · %s (%s%s)' % (provider.get('name') or provider['id'], name, kind,
                               ', ' + genre if genre else ''), True


def linked_catalogs(groups, folder):
    """Each linked catalog by name with its own On/Off switch."""
    from . import settings_page as page
    from .settings import commit_collections
    from resources.lib.nuviohub import store

    def rows():
        providers = store.list_providers()
        result = []
        for source in folder['sources']:
            label, installed = _source_label(source, providers)
            if installed:
                result.append(page.item(label, enabled=source.get('enabled') is not False))
            else:
                result.append(page.item(label, 'Not installed'))
        return result + [page.item('Add or change catalogs…'), page.item('Back')]

    def choose(pick):
        sources = folder['sources']
        if pick == len(sources) + 1:
            return page.DONE
        from copy import deepcopy
        before = deepcopy(sources)
        if pick == len(sources):
            if not _catalogs(folder):
                return None
        else:
            source = sources[pick]
            turning_off = source.get('enabled') is not False
            if turning_off and sum(1 for s in sources if s.get('enabled') is not False) <= 1:
                raise ValueError('Keep at least one catalog ON. Use "Show on Home" to hide the whole card.')
            source['enabled'] = not turning_off
        if not commit_collections(groups):
            folder['sources'][:] = before
        return None

    return page.show(lambda: 'Catalogs · ' + folder['title'], rows, choose)


def _linked_summary(folder):
    from resources.lib.nuviohub import store
    providers = store.list_providers()
    sources = folder.get('sources') or []
    on = [s for s in sources if s.get('enabled') is not False]
    names = [_source_label(s, providers)[0].split(' · ')[-1] for s in on[:2]]
    text = ', '.join(names) + (' …' if len(on) > 2 else '')
    return '%d of %d ON · %s' % (len(on), len(sources), text) if sources else 'None'


def edit_items():
    dialog=xbmcgui.Dialog()
    previous=0
    while True:
        groups=collection_profile.load()
        rows=[(g,i,f) for g in groups for i,f in enumerate(g['folders'])]
        pick=dialog.select('Home collection cards',[g['title']+' / '+f['title']+(' [Hidden]' if f.get('hidden') else '') for g,i,f in rows],preselect=min(previous,max(0,len(rows)-1)))
        if pick<0:return
        previous=pick
        group,index,folder=rows[pick]
        edit_card(groups,group,folder)


def edit_card(groups,group,folder):
    from . import settings_page as page
    dialog=xbmcgui.Dialog()
    def rows():return [page.item('Name',folder['title']),page.item('Cover image','Configured' if folder.get('cover') else 'Default'),
        page.item('Hero background','Configured' if folder.get('backdrop') else 'Default'),
        page.item('Focused animation / GIF','Configured' if folder.get('animation') else 'Default'),
        page.item('Show on Home',enabled=not folder.get('hidden')),page.item('Move left'),page.item('Move right'),
        page.item('Linked metadata catalogs',_linked_summary(folder)),page.item('Genre filter'),
        page.item('Show card title',enabled=not folder.get('hideTitle')),page.item('Back')]
    def choose(choice):
        if choice==10:return page.DONE
        from copy import deepcopy
        original_folder = deepcopy(folder)
        original_order = list(group['folders'])
        changed=True
        if choice==0:
            value=dialog.input('Collection title',defaultt=folder['title']).strip()
            if value:folder['title']=value
            else:changed=False
        elif choice in (1,2,3):
            value=_image(('Cover image','Hero background','Focused animation / GIF')[choice-1])
            if value:
                folder[{1:'cover',2:'backdrop',3:'animation'}[choice]]=value
                if choice==3:
                    from . import settings
                    try:overrides=json.loads(settings.ADDON.getSetting('nuvio_animation_map') or '{}')
                    except ValueError:overrides={}
                    overrides.pop(folder['id'],None)
                    settings.ADDON.setSetting('nuvio_animation_map',json.dumps(overrides))
            else:changed=False
        elif choice==4:folder['hidden']=not folder.get('hidden')
        elif choice in (5,6):
            index=next(i for i,f in enumerate(group['folders']) if f['id']==folder['id'])
            dest=max(0,min(len(group['folders'])-1,index+(-1 if choice==5 else 1)))
            group['folders'].insert(dest,group['folders'].pop(index))
        elif choice==7:
            linked_catalogs(groups,folder)
            changed=False  # Each switch in that page is saved and validated on its own.
        elif choice==8:
            from resources.lib.nuviohub import store
            providers=store.list_providers()
            selected=dialog.select('Catalog genre filter',[_source_label(s,providers)[0] for s in folder['sources']])
            if selected>=0:
                source=folder['sources'][selected]
                source['genre']=dialog.input('Genre (empty means all)',defaultt=source.get('genre') or '').strip()
                extra=dict(source.get('extra') or {});extra.pop('genre',None);source['extra']=extra
            else:changed=False
        elif choice==9:folder['hideTitle']=not folder.get('hideTitle')
        if changed:
            from .settings import commit_collections
            if not commit_collections(groups):
                folder.clear();folder.update(original_folder)
                group['folders'][:]=original_order
    return page.show(lambda:folder['title'],rows,choose)


def import_json():
    from .settings import commit_collections
    path = xbmcgui.Dialog().browseSingle(1, 'Nuvio collections export', 'files', '.json')
    if not path:
        return False
    stream = xbmcvfs.File(path)
    try:
        data = json.loads(stream.read())
    finally:
        stream.close()
    return commit_collections(data)


def create_collection():
    from .settings import commit_collections
    import uuid
    title = xbmcgui.Dialog().input('Collection name').strip()
    if not title:
        return False
    groups = collection_profile.load()
    folder = {'id': 'custom.' + uuid.uuid4().hex, 'title': title, 'sources': []}
    if not _catalogs(folder):
        return False
    custom = next((g for g in groups if g['id'] == 'custom'), None)
    if custom is None:
        custom = {'id': 'custom', 'title': 'My collections', 'folders': []}
        groups.append(custom)
    custom['folders'].append(folder)
    return commit_collections(groups)


def default_collections():
    """Cinemeta (no setup, the default) or the numb3rs set (needs AIOMetadata)."""
    from . import settings
    from resources.lib import default_setup
    from resources.lib.nuviohub import store
    from .playback import job
    dialog = xbmcgui.Dialog()
    pick = dialog.select('Default collections', [
        'Cinemeta · works without any setup (default)',
        'numb3rs collections · needs AIOMetadata from numb3rs.stream'])
    if pick < 0:
        return False
    if pick == 0:
        try:job(default_setup.install_cinemeta, label='Setting up Cinemeta')
        except Exception:dialog.ok('Cinemeta','Cinemeta could not be reached now. The collections are saved and load when it answers.')
        return settings.commit_collections(default_setup.cinemeta_collections())
    saved = settings.commit_collections(collection_profile.defaults())
    ready = default_setup.numb3rs_ready(store.list_providers())
    dialog.textviewer('numb3rs collections' + (' · AIOMetadata found' if ready else ' · setup needed'),
                      ('AIOMetadata is installed. If a collection stays empty, check its catalogs at '
                       + default_setup.NUMB3RS_URL + '.\n\n' if ready else '') + default_setup.NUMB3RS_HELP)
    return saved


def home_rows():
    """Show or hide whole Home rows: Continue Watching and each collection group."""
    from . import settings_page as page
    from . import settings
    def rows():
        groups = collection_profile.load()
        return ([page.item('Continue Watching', enabled=settings.ADDON.getSetting('nuvio_home_continue') != 'false')] +
                [page.item(g['title'], '%d collections' % len(g['folders']) if not g.get('hidden') else '', enabled=not g.get('hidden'))
                 for g in groups] + [page.item('Back')])
    def choose(pick):
        groups = collection_profile.load()
        if pick == 0:
            settings.ADDON.setSetting('nuvio_home_continue', 'true' if settings.ADDON.getSetting('nuvio_home_continue') == 'false' else 'false')
            return None
        if pick > len(groups):
            return page.DONE
        group = groups[pick - 1]
        group['hidden'] = not group.get('hidden')
        collection_profile.save(groups)
        return None
    return page.show('Home rows · show or hide', rows, choose)


def run():
    from . import settings
    dialog = xbmcgui.Dialog()
    previous = 0
    while True:
        choice = dialog.select('Collections', [
            'Default collections · Cinemeta or numb3rs', 'Home rows · show or hide',
            'Edit each collection card', 'Metadata add-ons',
            'Import collections from Nuvio account', 'Import collections JSON (no account needed)',
            'Create a collection from installed catalogs', 'Check collection catalogs (report only)',
            'Back'], preselect=previous)
        if choice < 0 or choice == 8:
            return
        previous = choice
        try:
            if choice == 0:
                default_collections()
            elif choice == 1:
                home_rows()
            elif choice == 2:
                edit_items()
            elif choice == 3:
                settings.metadata_addons()
            elif choice == 4:
                settings.import_nuvio_collections()
            elif choice == 5:
                import_json()
            elif choice == 6:
                create_collection()
            elif choice == 7:
                groups = collection_profile.load()
                if groups:
                    settings.commit_collections(groups, force=True)
                else:
                    dialog.ok('Collection checks', 'Import or create collections first.')
        except (ValueError, OSError):
            dialog.ok('Collections', 'The change was not saved. Check the selected catalogs, filters and file format.')
