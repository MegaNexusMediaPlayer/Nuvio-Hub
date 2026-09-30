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
    provider=backend_api.provider('metadata')
    if not provider:raise ValueError('Choose metadata for all collections first.')
    manifest=provider.get('manifest') or {}
    catalogs=[c for c in manifest.get('catalogs') or [] if c.get('type') in ('movie','series') and c.get('id')]
    if not catalogs:raise ValueError('The metadata provider has no movie or series catalogs.')
    old={(s['catalogId'],s['type']):s for s in folder['sources']}
    selected=xbmcgui.Dialog().multiselect('Catalogs for '+folder['title'],
        [(c.get('name') or c['id'])+' ('+c['type']+')' for c in catalogs],
        preselect=[i for i,c in enumerate(catalogs) if (c['id'],c['type']) in old])
    if selected is None:return False
    if not selected:raise ValueError('Choose at least one catalog. Use Hide to remove the card from Home.')
    folder['sources']=[dict(old.get((catalogs[i]['id'],catalogs[i]['type']),{}),
        addonId=manifest.get('id',''),catalogId=catalogs[i]['id'],type=catalogs[i]['type']) for i in selected]
    return True


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
        page.item('Linked metadata catalogs',str(len(folder['sources']))+' catalogs'),page.item('Genre filter'),
        page.item('Show card title',enabled=not folder.get('hideTitle')),page.item('Back')]
    def choose(choice):
        if choice==10:return page.DONE
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
        elif choice==7:changed=_catalogs(folder)
        elif choice==8:
            selected=dialog.select('Catalog genre filter',[s['catalogId']+' ('+s['type']+')' for s in folder['sources']])
            if selected>=0:
                source=folder['sources'][selected]
                source['genre']=dialog.input('Genre (empty means all)',defaultt=source.get('genre') or '').strip()
                extra=dict(source.get('extra') or {});extra.pop('genre',None);source['extra']=extra
            else:changed=False
        elif choice==9:folder['hideTitle']=not folder.get('hideTitle')
        if changed:collection_profile.save(groups)
    return page.show(lambda:folder['title'],rows,choose)


def run():
    from . import settings
    dialog=xbmcgui.Dialog()
    previous=0
    while True:
        meta=backend_api.provider('metadata')
        name=(meta.get('name') or meta.get('id')) if meta else 'Not connected'
        choice=dialog.select('Skin configuration - Collections',[
            'Metadata for ALL collections: '+name,'Edit each collection card',
            'Optional: import layout from Nuvio account','Optional: import collections JSON',
            'Restore original Nuvio Home layout','Check catalog mapping','Back'],preselect=previous)
        if choice<0 or choice==6:return
        previous=choice
        if choice==0:settings.select_provider('metadata')
        elif choice==1:edit_items()
        elif choice==2:settings.import_nuvio_collections()
        elif choice==3:
            path=dialog.browseSingle(1,'Nuvio collections export','files','.json')
            if path and dialog.yesno('Import collection layout','Replace the Home layout with this collection file? Sports and World stay excluded.'):
                stream=xbmcvfs.File(path)
                try:count=collection_profile.save(json.loads(stream.read()))
                finally:stream.close()
                dialog.ok('Collections','%d collections saved.'%count)
        elif choice==4:
            if dialog.yesno('Original Home layout','Restore the supplied collection titles, images and order? Metadata provider selection is kept.'):
                collection_profile.save(collection_profile.defaults())
        elif choice==5:
            matched,missing=collection_profile.mapping_report()
            dialog.ok('Catalog mapping','%d catalog sources matched; %d missing. Choose the metadata provider and edit unmatched cards.'%(matched,missing))
