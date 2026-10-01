# -*- coding: utf-8 -*-
"""First-run setup chooser kept outside the large plugin router."""

def choose_setup_path(dialog, tr=lambda x: x):
    labels = [
        tr('Nuvio — link Continue Watching'),
        tr('Stremio — import addons + Continue Watching'),
        tr('Manual setup — Stremio / Plex / Emby myself'),
    ]
    idx = dialog.select(tr('Quick Start • choose a setup method'), labels)
    if idx < 0:
        return None
    return ('nuvio', 'stremio', 'manual')[idx]
