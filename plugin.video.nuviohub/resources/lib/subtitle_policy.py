# -*- coding: utf-8 -*-
"""Subtitle automation policy.

AI rows remain discoverable for manual selection, but are never downloaded,
prepared, attached or activated automatically. This prevents DexWorld AI token
usage unless the user explicitly chooses that row.
"""
from __future__ import absolute_import


def _text(row):
    row = row or {}
    keys = ('sourceName','providerName','provider','addonName','addon','sourceAddon',
            'source','sourceType','origin','title','displayName','name','url','key',
            'id','type','category','model')
    return ' '.join(str(row.get(k) or '') for k in keys).lower()


def is_ai_subtitle(row):
    row = row or {}
    if any(row.get(k) is True for k in ('is_ai','ai','generated','ai_generated')):
        return True
    text = _text(row)
    explicit = ('ai_public','ai-generated','ai_generated','/ai/',' ai ',
                'artificial intelligence','ترجمة ai','ذكاء اصطناعي')
    if any(x in text for x in explicit):
        return True
    # DexWorld exposes both normal/provider subtitles and AI. Only classify it
    # as AI when the row itself also says AI/translation/generated.
    if 'dexworld' in text and any(x in text for x in ('ai','generated','translate','translation','مترجم')):
        return True
    return False


def is_manual_choice(row):
    row = row or {}
    return bool(row.get('user_selected') or row.get('manual_selected') or
                str(row.get('sourceType') or '').lower() == 'manual')


def allow_automatic(row):
    return bool(row) and (not is_ai_subtitle(row) or is_manual_choice(row))


def automatic_rows(rows):
    return [r for r in (rows or []) if allow_automatic(r)]
