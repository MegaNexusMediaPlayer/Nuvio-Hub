# -*- coding: utf-8 -*-
"""QR sign-in, now part of "Set up on phone" (6.0.22).

The 6.0.7 pairing page only linked an account, and its server code was lost in
the 6.0.10 import. The backend route ``nuvio_qr_login`` keeps working: it opens
the phone setup service of the interface (resources.lib.phone_setup), whose
Account tab signs in to Nuvio.
"""
import xbmc


def qr_pair(service):
    """Open phone setup. Only Nuvio accounts are supported there."""
    if service != 'nuvio':
        return False
    xbmc.executebuiltin('RunScript(script.nuvio,phone)')
    return True
