"""Unicode preservation, not translation or heuristic transliteration."""
import unicodedata


def clean(value):
    text = unicodedata.normalize('NFC', str(value or ''))
    # Keep CJK, combining marks, emoji selectors and ZWJ sequences intact.
    # Strip only non-printing control bytes; retain line breaks for descriptions.
    return ''.join(c for c in text if c in '\n\t' or unicodedata.category(c) not in ('Cc', 'Cs'))


def episode_line(episode, season=None):
    from datetime import date
    try:
        season = int(episode.get('season') if episode.get('season') is not None else season if season is not None else 1)
        number = int(episode.get('episode') or 0)
    except (TypeError, ValueError):
        return ''
    label = ('Specials' if season == 0 else 'Season %d' % season) + ' · Episode %d' % number
    raw = str(episode.get('released') or episode.get('first_aired') or episode.get('air_date') or '')[:10]
    try:
        released = date.fromisoformat(raw)
    except (TypeError, ValueError):
        return label
    return label + ' · ' + ('Airs ' if released > date.today() else 'Released ') + released.isoformat()
