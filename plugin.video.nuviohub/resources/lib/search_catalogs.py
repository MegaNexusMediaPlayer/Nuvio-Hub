"""Search only capabilities actually advertised by the selected metadata add-on."""

def extras(catalog):
    result={}
    for value in catalog.get('extra') or []:
        spec=value if isinstance(value,dict) else {'name':value}
        if spec.get('name'):result[str(spec['name'])]=spec
    for name in catalog.get('extraSupported') or []:
        result.setdefault(str(name),{'name':str(name)})
    for name in catalog.get('extraRequired') or []:
        result.setdefault(str(name),{'name':str(name)})['isRequired']=True
    return result


def is_people(catalog):
    text=(str(catalog.get('id') or '')+' '+str(catalog.get('name') or '')).casefold()
    return (catalog.get('type') in ('person','people','actor') or
            any(word in text for word in ('people','person','actor','cast','crew')))


def entries(source):
    for catalog in ((source or {}).get('manifest') or {}).get('catalogs') or []:
        if not isinstance(catalog,dict) or not catalog.get('id') or not catalog.get('type'):continue
        specs=extras(catalog)
        if 'search' not in specs:continue
        # A catalog requiring an unrelated genre/filter needs its own browser.
        if any(spec.get('isRequired') and name!='search' for name,spec in specs.items()):continue
        yield catalog


def title(catalog):
    mt=catalog.get('type') or ''
    kind={'movie':'Movies','series':'Series','tv':'Series','person':'Actors & crew',
          'people':'Actors & crew','actor':'Actors & crew'}.get(mt,mt.replace('.',' ').title())
    name=str(catalog.get('name') or catalog.get('id') or '')
    prefix=('Actors · '+kind) if is_people(catalog) and mt not in ('person','people','actor') else kind
    return prefix+' — '+name if name else prefix


def person_id(person):
    """Never mistake an IMDb/TVDB person ID for a TMDb numeric ID."""
    value=str(person.get('tmdbId') or person.get('tmdb_id') or '')
    if value.startswith('tmdb:'):value=value.rsplit(':',1)[-1]
    if value.isdigit():return value
    raw=str(person.get('id') or '')
    if raw.startswith('tmdb:') and raw.rsplit(':',1)[-1].isdigit():return raw.rsplit(':',1)[-1]
    return ''


def person_card(person,source=None):
    name=str(person.get('name') or person.get('title') or 'Unknown person')
    pid=person_id(person)
    photo=person.get('photo') or person.get('poster') or person.get('image') or person.get('thumbnail') or ''
    if not photo and person.get('profile_path'):
        photo='https://image.tmdb.org/t/p/w185'+str(person['profile_path'])
    credit=dict(person,name=name,tmdb_id=pid,photo=photo)
    return {'title':name,'poster':photo,'fanart':'','clearlogo':'','subtitle':'Actor / crew',
            'meta_line':'Filmography · Movies & series','plot':'Open movies and series featuring '+name,
            'person':credit,'target':{'media_type':'person','canonical_id':str(person.get('id') or pid or name),
            'title':name,'source_provider_id':(source or {}).get('id') or ''},'is_folder':True}


def search_people(query):
    from . import tmdb_direct
    if not tmdb_direct._api_key():return []
    data=tmdb_direct._request('/search/person',{'query':query},timeout=10)
    return [person_card(dict(row,tmdb_id=row['id'])) for row in data.get('results') or []
            if isinstance(row,dict) and row.get('id') and row.get('name')]
