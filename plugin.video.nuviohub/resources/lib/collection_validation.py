"""Transactional, fail-closed collection setup. Proofs never contain configured URLs.

Checks catalog identity, declared filters and sampled metadata identity. A passed
sample is not a claim that every title in an unbounded remote catalog will work.
"""
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

VERSION = 1


def sources(groups):
    for group in groups:
        for folder in group.get('folders') or []:
            for source in folder.get('sources') or []:
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


def validate(groups, providers=None, stopped=None):
    from .nuviohub import store
    from .nuviohub.client import fetch_catalog, fetch_meta
    from .collections_home import matching_catalog
    from . import metadata_providers
    from .resource_support import same_identity
    providers = list(store.list_providers() if providers is None else providers)
    config_key = fingerprint(groups, providers)
    errors, jobs, seen = [], [], set()
    switches = {p['id']: on for p, on in metadata_providers.entries(providers)}
    if not groups:
        errors.append('Import collections from Nuvio, import a JSON export, or create a validated collection.')
    if not metadata_providers.enabled(providers=providers):
        errors.append('Enable at least one metadata add-on.')
    for folder, source in sources(groups):
        encoded = json.dumps(source, sort_keys=True, ensure_ascii=False)
        if encoded in seen:
            continue
        seen.add(encoded)
        label = str(folder.get('title') or 'Collection')
        match = matching_catalog(source, providers)
        if not match:
            errors.append(label + ': catalog identity does not match, or the configured variant is ambiguous.')
            continue
        provider, catalog = match
        if provider.get('id') in switches and not switches[provider['id']]:
            errors.append(label + ': its metadata add-on is switched off.')
            continue
        error = filter_error(catalog, extra_for(source))
        if error:
            errors.append(label + ': ' + error)
            continue
        jobs.append((label, provider, catalog, source))

    def probe(job):
        label, provider, catalog, source = job
        if stopped and stopped():
            return label + ': validation cancelled.'
        try:
            data = fetch_catalog(provider, catalog['type'], catalog['id'], extra=extra_for(source),
                                 timeout_override=6, retry=False, rate_wait=.1)
            rows = (data or {}).get('metas')
            if not isinstance(rows, list) or not rows:
                return label + ': catalog is empty or unavailable; no metadata sample can be verified.'
            if any(not isinstance(row, dict) or not row.get('id') for row in rows):
                return label + ': catalog returned malformed title IDs.'
            # Probe up to two different IDs; bound work regardless of catalog size.
            for row in rows[:2]:
                if stopped and stopped():
                    return label + ': validation cancelled.'
                cid, kind = str(row['id']), catalog['type']
                if row.get('type') and row['type'] != kind:
                    return label + ': catalog item type does not match its catalog.'
                candidates = metadata_providers.enabled(kind, cid, preferred=provider['id'], providers=providers)
                good = False
                for meta_provider in candidates:
                    try:
                        payload = fetch_meta(meta_provider, kind, cid, timeout_override=5, retry=False, rate_wait=.1)
                        if same_identity((payload or {}).get('meta'), kind, cid):
                            good = True
                            break
                    except Exception:
                        pass
                if not good:
                    return label + ': no enabled metadata add-on resolved the sampled ID correctly.'
            return ''
        except Exception:
            return label + ': request failed; check the provider and connection.'

    if jobs and not errors:
        with ThreadPoolExecutor(max_workers=min(4, len(jobs))) as pool:
            futures = [pool.submit(probe, job) for job in jobs]
            for future in as_completed(futures):
                error = future.result()
                if error:
                    errors.append(error)
    if stopped and stopped():
        errors.append('Validation cancelled; the previous collections were kept.')
    if fingerprint(groups, providers) != config_key:
        errors.append('Configuration changed during validation. Retry with the current profile.')
    return {'version': VERSION, 'ok': not errors, 'fingerprint': config_key,
            'checked_at': int(time.time()), 'catalogs': len(jobs), 'errors': errors}


def message(proof):
    errors = proof.get('errors') or ['Collection validation did not complete.']
    return '\n'.join(errors[:6]) + ('\n… and %d more.' % (len(errors)-6) if len(errors) > 6 else '')
