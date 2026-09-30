"""Provider display text; stream URLs and raw provider rows remain untouched."""
import unicodedata
import re

# Character coverage of the bundled NotoSans-Regular.ttf (font13/font_flag).
# Keeping Unicode letters alone is insufficient: some have no glyph in the font.
_COVERAGE = '20-7e a0-377 37a-37f 384-38a 38c 38e-3a1 3a3-52f 531-556 559-55f 561-587 589-58a 58d-58f 591-5c7 5d0-5ea 5f0-5f4 1ab0-1abe 1c80-1c88 1d00-1df5 1dfb-1f15 1f18-1f1d 1f20-1f45 1f48-1f4d 1f50-1f57 1f59 1f5b 1f5d 1f5f-1f7d 1f80-1fb4 1fb6-1fc4 1fc6-1fd3 1fd6-1fdb 1fdd-1fef 1ff2-1ff4 1ff6-1ffe 2000-2064 2066-2071 2074-208e 2090-209c 20a0-20bf 20f0 2100-215f 2184 2189 2190-2195 21a8 2202 2206 220f 2211-2212 2215 2219-221a 221e-221f 2229 222b 2248 2260-2261 2264-2265 2302 2310 2320-2321 2500 2502 250c 2510 2514 2518 251c 2524 252c 2534 253c 2550-256c 2580 2584 2588 258c 2590-2593 25a0-25a1 25aa-25ac 25b2 25ba 25bc 25c4 25ca-25cc 25cf 25d8-25d9 25e6 2605-2606 263a-263c 2640 2642 2660 2663 2665-2666 266a-266b 266f 29f5 2c60-2c7f 2de0-2e44 a640-a69f a700-a7ae a7b0-a7b7 a7f7-a7ff a92e ab30-ab65 fb00-fb06 fb13-fb17 fb1d-fb36 fb38-fb3c fb3e fb40-fb41 fb43-fb44 fb46-fb4f fe00 fe20-fe2f feff fffc-fffd'
_SUPPORTED = frozenset(n for span in _COVERAGE.split()
    for bounds in [span.split('-')]
    for n in range(int(bounds[0],16),int(bounds[-1],16)+1))
_SMALL_CAPS = str.maketrans(dict(zip('ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡʏᴢ', 'ABCDEFGHIJKLMNOPQRSTUVWYZ')))


def normalized(value):
    text=unicodedata.normalize('NFKC',str(value or '')).translate(_SMALL_CAPS)
    # Enclosed/negative letters used as provider codec and resolution badges.
    return ''.join(chr(ord('A')+ord(c)-base) if base else c for c in text
                   for base in [0x1f170 if 0x1f170<=ord(c)<=0x1f189 else 0x1f150 if 0x1f150<=ord(c)<=0x1f169 else 0])


def plain(value):
    text=normalized(value)
    text=re.sub(r'\[(?:/?COLOR[^\]]*|/?B|/?I)\]','',text,flags=re.I)
    def supported(c):
        return c in '\t +=%' or (ord(c) in _SUPPORTED and unicodedata.category(c)[0] in 'LNPM' and c not in '\ufffc\ufffd')
    return '\n'.join(' '.join(''.join(c if supported(c) else ' ' for c in line).split()) for line in text.splitlines()).strip()
