"""Memory profile by device (6.0.39).

The default "auto" picks the poster / catalog / details budgets from the
device's total RAM, so a 1-2 GB stick (Fire TV, Mi Box) is not pushed into
Android's low-memory killer while a 4 GB+ box keeps the full 6.0.27 budgets.
A preset chosen in HUB Settings > Performance is used as it is.
"""
import re

AUTO = 'auto'
SETTING = 'nuvio_art_cache'
# preset -> (posters, catalog pages, details) in bytes
MIB = 1024 * 1024
BUDGETS = {'ram96': (96 * MIB, 32 * MIB, 12 * MIB),
           'ram160': (160 * MIB, 64 * MIB, 24 * MIB),
           'ram256': (256 * MIB, 96 * MIB, 32 * MIB)}
LABELS = {'ram96': 'RAM · 96 MiB', 'ram160': 'RAM · 160 MiB', 'ram256': 'RAM · 256 MiB'}
_DEVICE = []


def device_mb():
    """Total RAM in MB from Kodi (System.Memory(total)), 0 when unknown."""
    if _DEVICE:
        return _DEVICE[0]
    value = 0
    try:
        import xbmc
        text = str(xbmc.getInfoLabel('System.Memory(total)') or '').replace(',', '.')
        match = re.search(r'([0-9.]+)\s*([KMGT]?B)', text, re.I)
        if match:
            number, unit = float(match.group(1)), match.group(2).upper()
            value = int(number * {'KB': 1 / 1024.0, 'MB': 1, 'GB': 1024, 'TB': 1024 * 1024}.get(unit, 1))
    except Exception:
        value = 0
    if value:
        _DEVICE.append(value)
    return value


def for_device(mb=None):
    mb = device_mb() if mb is None else mb
    if not mb:
        return 'ram160'          # unknown: the middle, safe on small boxes
    if mb <= 2560:
        return 'ram96'
    if mb <= 4608:
        return 'ram160'
    return 'ram256'


def chosen(addon):
    """The stored choice ('auto' or a preset)."""
    try:
        return addon.getSetting(SETTING) or AUTO
    except Exception:
        return AUTO


def effective(mode):
    """'auto' -> the preset for this device; other presets unchanged."""
    if mode in ('', AUTO):
        return for_device()
    if mode in ('ram150', 'ram200'):
        return 'ram256'
    return mode


def pages(mode, fallback):
    return BUDGETS.get(effective(mode), (0, fallback, 0))[1]


def details(mode, fallback):
    return BUDGETS.get(effective(mode), (0, 0, fallback))[2]
