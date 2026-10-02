"""Transactional, fail-closed collection setup. Proofs never contain configured URLs.

Checks catalog identity, declared filters and sampled metadata identity. A passed
sample is not a claim that every title in an unbounded remote catalog will work.
"""
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor

VERSION = 1


def sources(groups):
    """Every source switched ON in the collection editor."""
    for group in groups:
        for folder in group.get('folders') or []:
            for source in folder.get('sources') or []:
                if source.get('enabled') is not False:
                    yield folder, source


def extra_for(source):
    extra = dict(source.get('extra') or {})
    if source.get('genre') and source['genre'] != 'None':
        extra['genre'] = source['genre']
    return extra


def fingerprint(groups, providers=None):
    from .metadata_providers import signature
    from .nuviohub import store
    providers = store.list_providers() if providers is None else providers
    bindings = [source for _, source in sources(groups)]
    used = {s.get('addonId') for s in bindings}
    config = [(p.get('id'), p.get('manifest_url'), p.get('base_url'), p.get('manifest'))
              for p in providers if (p.get('manifest') or {}).get('id') in used]
    value = [VERSION, bindings, signature(providers), config]
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode('utf-8')).hexdigest()


def accepts(groups, proof, providers=None):
    return (isinstance(proof, dict) and proof.get('ok') is True and
            proof.get('version') == VERSION and
            proof.get('fingerprint') == fingerprint(groups, providers))


def stored_proof(groups):
    from .collection_profile import profile_file
    try:
        proof = json.loads(profile_file().with_suffix('.verified.json').read_text(encoding='utf-8'))
        return proof if accepts(groups, proof) else None
    except (OSError, ValueError):
        return None


def filter_error(catalog, extra):
    declared = {r.get('name'): r for r in catalog.get('extra') or [] if isinstance(r, dict) and r.get('name')}
    for entry in catalog.get('extra') or []:
        if isinstance(entry, str):declared.setdefault(entry, {'name':entry})
    # Legacy manifest format is still supported by the SDK.
    for key in catalog.get('extraSupported') or []:
        declared.setdefault(key, {'name': key})
    required = set(catalog.get('extraRequired') or []) | {k for k, v in declared.items() if v.get('isRequired')}
    if any(k not in extra or extra[k] in ('', None) for k in required):
        return 'A required catalog filter is missing.'
    for name, value in extra.items():
        if name not in declared:
            return 'A collection filter is not advertised by this catalog.'
        options = declared[name].get('options')
        if options is not None and str(value) not in [str(x) for x in options]:
            return 'A collection filter value is not offered by this catalog.'
    return ''


MAX_METADATA_SAMPLES = 16


def _label(folder, source):
    kind = 'Series' if source.get('type') == 'series' else 'Movies'
    return '%s (%s)' % (folder.get('title') or 'Collection', kind)


def validate(groups, providers=None, stopped=None):
    """Check every collection source; problems are reported per source.

    Blocking (``ok`` false): no collections, no enabled metadata add-on, no
    source that resolves to an installed catalog, or cancellation.
    A source is *skipped* when its catalog is not installed, its metadata
    add-on is OFF, a required filter is missing, the catalog returns titles of
    the wrong type, or a sampled title resolves to a different title.
    Network timeouts, temporarily empty catalogs and filter values missing from
    the manifest's option list are *warnings*: the collection is kept and loads
    when the provider answers. Catalog pages fetched here warm the Home cache.
    """
    from .nuviohub import store
    from .nuviohub.client import fetch_meta
    from .collections_home import matching_catalog
    from . import metadata_providers, browse_cache
    from .resource_support import same_identity
    providers = list(store.list_providers() if providers is None else providers)
    config_key = fingerprint(groups, providers)
    errors, warnings, skipped, jobs, seen = [], [], [], [], set()
    switches = {p['id']: on for p, on in metadata_providers.entries(providers)}
    total = 0
    if not groups:
        errors.append('Import collections from Nuvio, import a JSON export, or create a collection.')
    if not metadata_providers.enabled(providers=providers):
        errors.append('Enable at least one metadata add-on (Settings > Add-ons > Metadata add-ons).')
    for folder, source in sources(groups):
        encoded = json.dumps(source, sort_keys=True, ensure_ascii=False)
        if encoded in seen:
            continue
        seen.add(encoded)
        total += 1
        label = _label(folder, source)
        from .collection_sources import is_virtual, usable
        if is_virtual(source):
            if not usable(source):
                skipped.append(label + ': TMDB source - enter your TMDb API key in Settings > Add-ons.')
            continue   # Trakt / TMDB: read from the service, nothing to install
        match = matching_catalog(source, providers)
        if not match:
            skipped.append(label + ': catalog "%s" is not installed from add-on "%s".'
                           % (source.get('catalogId'), source.get('addonId') or '?'))
            continue
        provider, catalog = match
        if provider.get('id') in switches and not switches[provider['id']]:
            skipped.append(label + ': its add-on %s is switched OFF under Metadata add-ons.'
                           % (provider.get('name') or provider['id']))
            continue
        error = filter_error(catalog, extra_for(source))
        if error.startswith('A required'):
            skipped.append(label + ': ' + error)
            continue
        if error:
            warnings.append(label + ': ' + error)
        jobs.append((label, provider, catalog, source))

    samples = {id(job) for job in jobs[:MAX_METADATA_SAMPLES]}

    def probe(job):
        """Return (hard problem, warning)."""
        label, provider, catalog, source = job
        if stopped and stopped():
            return '', ''
        try:
            # Cache-first: rechecking after a small edit stays fast, and pages
            # fetched here are the ones Home shows next.
            data = browse_cache.catalog(provider, catalog, extra_for(source), timeout=6)
        except Exception:
            return '', label + ': the catalog did not answer now; it will load when the provider responds.'
        rows = (data or {}).get('metas') or []
        if not rows:
            return '', label + ': the catalog is empty right now.'
        row = rows[0]
        cid, kind = str(row['id']), catalog['type']
        if row.get('type') and metadata_media(row['type']) != metadata_media(kind):
            return label + ': the catalog returns titles of a different type.', ''
        if id(job) not in samples:
            return '', ''
        candidates = metadata_providers.enabled(kind, cid, preferred=provider['id'], providers=providers)
        if not candidates:
            return '', label + ': no enabled metadata add-on supports IDs like %s.' % cid.split(':')[0]
        reached = False
        for meta_provider in candidates:
            if stopped and stopped():
                return '', ''
            try:
                payload = fetch_meta(meta_provider, kind, cid, timeout_override=5, retry=False, rate_wait=.1)
            except Exception:
                continue
            reached = True
            if same_identity((payload or {}).get('meta'), kind, cid):
                return '', ''
        if reached:
            return label + ': a sampled title resolved to a different title in the metadata add-on.', ''
        return '', label + ': metadata could not be checked now (no answer).'

    passed = 0
    if jobs and not errors:
        with ThreadPoolExecutor(max_workers=min(4, len(jobs))) as pool:
            for hard, warning in pool.map(probe, jobs):
                if hard:
                    skipped.append(hard)
                else:
                    passed += 1
                if warning:
                    warnings.append(warning)
    if stopped and stopped():
        errors.append('Validation cancelled; the previous collections were kept.')
    elif groups and not errors and not passed:
        errors.append('None of the collection catalogs is available from your installed add-ons.')
    if fingerprint(groups, providers) != config_key:
        errors.append('Configuration changed during validation. Retry with the current profile.')
    return {'version': VERSION, 'ok': not errors, 'fingerprint': config_key,
            'checked_at': int(time.time()), 'catalogs': passed, 'total': total,
            'errors': errors, 'skipped': skipped, 'warnings': warnings}


def metadata_media(kind):
    from .resource_support import media_type
    return media_type(kind)


def message(proof):
    """Short, readable result: blocking errors first, then skipped/warned sources."""
    lines = list(proof.get('errors') or [])
    if proof.get('ok') and proof.get('total'):
        lines.append('%d of %d collection catalogs are ready.' % (proof.get('catalogs', 0), proof['total']))
    skipped = proof.get('skipped') or []
    warnings = proof.get('warnings') or []
    if skipped:
        lines.append('Not shown (%d):' % len(skipped))
        lines.extend('• ' + x for x in skipped[:5])
        if len(skipped) > 5:
            lines.append('… and %d more.' % (len(skipped) - 5))
    if warnings:
        lines.append('Will retry later (%d):' % len(warnings))
        lines.extend('• ' + x for x in warnings[:3])
        if len(warnings) > 3:
            lines.append('… and %d more.' % (len(warnings) - 3))
    return '\n'.join(lines) if lines else 'Collection validation did not complete.'
