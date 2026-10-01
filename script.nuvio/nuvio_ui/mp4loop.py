"""Seamless, silent loop copy of a screensaver clip (6.0.32).

Kodi's player cannot loop a file without a visible stall: a seek flushes the
decoder (about a second on Android boxes) and reopening the file shows black.
This module writes a copy of an MP4/MOV clip whose sample tables list the
video samples many times in a row (one hour by default). The player then sees
one long, continuous video: the end of the clip is followed directly by its
first frame, with no seek and no reopen. Only the video track is kept, so the
copy has no sound and Kodi never has to be muted.

The media bytes are copied once, unchanged; only the small index (moov) grows.
Fragmented MP4 and other containers raise ``Unsupported`` and the screensaver
keeps its seek-based loop for them.

Pure Python (no Kodi imports); ``source`` is any object with ``seek(pos)`` and
``read(n)``.
"""
import struct

TARGET_SECONDS = 3600          # length of the generated loop
MAX_SAMPLES = 400000           # bound for the index size (~5 MB)
COPY_BLOCK = 1024 * 1024
KEEP_STBL = ('stsd', 'stts', 'ctts', 'stss', 'stsc', 'stsz', 'stco', 'co64', 'sdtp')


class Unsupported(ValueError):
    pass


def _boxes(data, start=0, end=None):
    """(kind, box_start, payload_start, box_end) for each box in data[start:end]."""
    end = len(data) if end is None else end
    pos = start
    while pos + 8 <= end:
        size, kind = struct.unpack_from('>I4s', data, pos)
        head = 8
        if size == 1:
            size = struct.unpack_from('>Q', data, pos + 8)[0]
            head = 16
        elif size == 0:
            size = end - pos
        if size < head or pos + size > end:
            raise Unsupported('Damaged MP4 box.')
        yield kind.decode('latin-1'), pos, pos + head, pos + size
        pos += size


def _box(kind, payload):
    return struct.pack('>I4s', 8 + len(payload), kind.encode('latin-1')) + payload


def _full(kind, version, flags, payload):
    return _box(kind, struct.pack('>I', (version << 24) | flags) + payload)


def _child(data, start, end, kind):
    for item in _boxes(data, start, end):
        if item[0] == kind:
            return item
    return None


def _top_level(source, size):
    """Top-level boxes of the file without reading the media data."""
    found, pos = [], 0
    while pos + 8 <= size:
        source.seek(pos)
        head = source.read(16)
        if len(head) < 8:
            break
        length, kind = struct.unpack_from('>I4s', head, 0)
        header = 8
        if length == 1:
            if len(head) < 16:
                raise Unsupported('Damaged MP4 box.')
            length = struct.unpack_from('>Q', head, 8)[0]
            header = 16
        elif length == 0:
            length = size - pos
        if length < header or pos + length > size:
            raise Unsupported('Damaged MP4 box.')
        found.append((kind.decode('latin-1'), pos, pos + header, pos + length))
        pos += length
    return found


def _read(source, start, end):
    source.seek(start)
    data = source.read(end - start)
    if len(data) != end - start:
        raise Unsupported('Short read.')
    return data


class _Track:
    """The parsed index of the first video track."""

    def __init__(self, moov):
        self.moov = moov
        boxes = list(_boxes(moov))
        if any(kind == 'mvex' for kind, *_ in boxes):
            raise Unsupported('Fragmented MP4.')
        mvhd = next((b for b in boxes if b[0] == 'mvhd'), None)
        if not mvhd:
            raise Unsupported('No movie header.')
        self.mvhd = moov[mvhd[2]:mvhd[3]]
        self.movie_scale = struct.unpack_from('>I', self.mvhd, 20 if self.mvhd[0] == 1 else 12)[0]
        for kind, start, payload, end in boxes:
            if kind == 'trak' and self._handler(payload, end) == b'vide':
                self._parse_trak(payload, end)
                break
        else:
            raise Unsupported('No video track.')

    def _handler(self, start, end):
        mdia = _child(self.moov, start, end, 'mdia')
        hdlr = mdia and _child(self.moov, mdia[2], mdia[3], 'hdlr')
        return self.moov[hdlr[2] + 8:hdlr[2] + 12] if hdlr else b''

    def _parse_trak(self, start, end):
        m = self.moov
        tkhd = _child(m, start, end, 'tkhd')
        mdia = _child(m, start, end, 'mdia')
        if not (tkhd and mdia):
            raise Unsupported('Incomplete video track.')
        self.tkhd = m[tkhd[2]:tkhd[3]]
        mdhd = _child(m, mdia[2], mdia[3], 'mdhd')
        hdlr = _child(m, mdia[2], mdia[3], 'hdlr')
        minf = _child(m, mdia[2], mdia[3], 'minf')
        if not (mdhd and hdlr and minf):
            raise Unsupported('Incomplete video track.')
        self.mdhd = m[mdhd[2]:mdhd[3]]
        self.media_scale = struct.unpack_from('>I', self.mdhd, 20 if self.mdhd[0] == 1 else 12)[0]
        self.hdlr = m[hdlr[1]:hdlr[3]]
        edts = _child(m, start, end, 'edts')
        elst = edts and _child(m, edts[2], edts[3], 'elst')
        self.edits = self._edits(m[elst[2]:elst[3]]) if elst else None
        self.minf_other = []
        stbl = None
        for kind, b_start, b_payload, b_end in _boxes(m, minf[2], minf[3]):
            if kind == 'stbl':
                stbl = (b_payload, b_end)
            elif kind == 'dinf':
                self._check_self_contained(b_payload, b_end)
                self.minf_other.append(m[b_start:b_end])
            else:
                self.minf_other.append(m[b_start:b_end])
        if not stbl:
            raise Unsupported('No sample table.')
        self.tables = {}
        for kind, b_start, b_payload, b_end in _boxes(m, *stbl):
            if kind == 'stz2':
                raise Unsupported('Compact sample sizes.')
            if kind in KEEP_STBL:
                self.tables[kind] = (m[b_start:b_end], m[b_payload:b_end])
        for need in ('stsd', 'stts', 'stsc', 'stsz'):
            if need not in self.tables:
                raise Unsupported('Incomplete sample table.')
        if 'stco' not in self.tables and 'co64' not in self.tables:
            raise Unsupported('No chunk offsets.')
        self._parse_tables()

    def _check_self_contained(self, start, end):
        dref = _child(self.moov, start, end, 'dref')
        if not dref:
            return
        for kind, b_start, b_payload, b_end in _boxes(self.moov, dref[2] + 8, dref[3]):
            flags = struct.unpack_from('>I', self.moov, b_payload)[0] & 0xFFFFFF
            if not flags & 1:
                raise Unsupported('Media data in another file.')

    @staticmethod
    def _edits(payload):
        version = payload[0]
        count = struct.unpack_from('>I', payload, 4)[0]
        fmt, width = ('>QqhH', 20) if version == 1 else ('>IihH', 12)
        return [struct.unpack_from(fmt, payload, 8 + i * width)[:3] for i in range(count)]

    def _parse_tables(self):
        t = {k: v[1] for k, v in self.tables.items()}
        count = struct.unpack_from('>I', t['stts'], 4)[0]
        self.stts = [struct.unpack_from('>II', t['stts'], 8 + i * 8) for i in range(count)]
        self.ctts = None
        if 'ctts' in t:
            count = struct.unpack_from('>I', t['ctts'], 4)[0]
            self.ctts = (t['ctts'][0], t['ctts'][8:8 + count * 8], count)
        self.stss = None
        if 'stss' in t:
            count = struct.unpack_from('>I', t['stss'], 4)[0]
            self.stss = list(struct.unpack_from('>%dI' % count, t['stss'], 8))
        count = struct.unpack_from('>I', t['stsc'], 4)[0]
        self.stsc = [struct.unpack_from('>III', t['stsc'], 8 + i * 12) for i in range(count)]
        self.sample_size, self.samples = struct.unpack_from('>II', t['stsz'], 4)
        self.sizes = list(struct.unpack_from('>%dI' % self.samples, t['stsz'], 12)) if self.sample_size == 0 else None
        if 'co64' in t:
            count = struct.unpack_from('>I', t['co64'], 4)[0]
            self.offsets = list(struct.unpack_from('>%dQ' % count, t['co64'], 8))
        else:
            count = struct.unpack_from('>I', t['stco'], 4)[0]
            self.offsets = list(struct.unpack_from('>%dI' % count, t['stco'], 8))
        self.sdtp = t['sdtp'][4:] if 'sdtp' in t else None
        if self.sdtp is not None and len(self.sdtp) != self.samples:
            self.sdtp = None
        if not self.samples or not self.offsets or sum(c for c, _ in self.stts) != self.samples:
            raise Unsupported('Inconsistent sample table.')
        self.media_duration = sum(c * d for c, d in self.stts)
        if self.media_duration <= 0 or not self.media_scale or not self.movie_scale:
            raise Unsupported('No duration.')

    def chunk_spans(self):
        """(offset, length) of every chunk of the video track."""
        spans, sample = [], 0
        chunks = len(self.offsets)
        for index, (first, per_chunk, _) in enumerate(self.stsc):
            last = self.stsc[index + 1][0] - 1 if index + 1 < len(self.stsc) else chunks
            for chunk in range(first, last + 1):
                if chunk > chunks:
                    break
                if self.sizes is None:
                    length = per_chunk * self.sample_size
                else:
                    length = sum(self.sizes[sample:sample + per_chunk])
                spans.append((self.offsets[chunk - 1], length))
                sample += per_chunk
        if len(spans) != chunks or sample != self.samples:
            raise Unsupported('Inconsistent chunk table.')
        return spans


def plan(source, size):
    """Parse the clip; returns (ftyp bytes, track, data start, data end)."""
    top = _top_level(source, size)
    kinds = [kind for kind, *_ in top]
    if 'moof' in kinds:
        raise Unsupported('Fragmented MP4.')
    moov = next((b for b in top if b[0] == 'moov'), None)
    if not moov or moov[3] - moov[2] > 64 * 1024 * 1024:
        raise Unsupported('No usable movie index.')
    ftyp = next((b for b in top if b[0] == 'ftyp'), None)
    ftyp = _read(source, ftyp[1], ftyp[3]) if ftyp else _box('ftyp', b'isom\x00\x00\x02\x00isomiso2avc1mp41')
    track = _Track(_read(source, moov[2], moov[3]))
    spans = track.chunk_spans()
    low = min(o for o, _ in spans)
    high = max(o + n for o, n in spans)
    if low < 0 or high > size:
        raise Unsupported('Chunks outside the file.')
    return ftyp, track, low, high


def repeats(track, target=TARGET_SECONDS):
    seconds = track.media_duration / float(track.media_scale)
    count = max(1, int(target / max(seconds, .1)))
    return max(1, min(count, MAX_SAMPLES // max(1, track.samples)))


def build_moov(track, copies, base, low, wide):
    """Index for ``copies`` back-to-back copies of the clip; chunk data at base."""
    samples, chunks = track.samples, len(track.offsets)
    stts = struct.pack('>I', len(track.stts) * copies) + b''.join(struct.pack('>II', c, d) for c, d in track.stts) * copies
    tables = [track.tables['stsd'][0], _full('stts', 0, 0, stts)]
    if track.ctts:
        version, entries, count = track.ctts
        tables.append(_full('ctts', version, 0, struct.pack('>I', count * copies) + entries * copies))
    if track.stss is not None:
        sync = [s + k * samples for k in range(copies) for s in track.stss]
        tables.append(_full('stss', 0, 0, struct.pack('>I%dI' % len(sync), len(sync), *sync)))
    stsc = [(first + k * chunks, per, desc) for k in range(copies) for first, per, desc in track.stsc]
    tables.append(_full('stsc', 0, 0, struct.pack('>I', len(stsc)) + b''.join(struct.pack('>III', *e) for e in stsc)))
    if track.sizes is None:
        tables.append(_full('stsz', 0, 0, struct.pack('>II', track.sample_size, samples * copies)))
    else:
        one = struct.pack('>%dI' % samples, *track.sizes)
        tables.append(_full('stsz', 0, 0, struct.pack('>II', 0, samples * copies) + one * copies))
    moved = [o - low + base for o in track.offsets]
    if wide:
        one = struct.pack('>%dQ' % chunks, *moved)
        tables.append(_full('co64', 0, 0, struct.pack('>I', chunks * copies) + one * copies))
    else:
        one = struct.pack('>%dI' % chunks, *moved)
        tables.append(_full('stco', 0, 0, struct.pack('>I', chunks * copies) + one * copies))
    if track.sdtp is not None:
        tables.append(_full('sdtp', 0, 0, track.sdtp * copies))
    stbl = _box('stbl', b''.join(tables))
    minf = _box('minf', b''.join(track.minf_other) + stbl)

    media_total = track.media_duration * copies
    clip_movie = int(round(track.media_duration * track.movie_scale / float(track.media_scale)))
    movie_total = clip_movie * copies
    mdhd = track.mdhd
    created, modified = _times(mdhd)
    language = mdhd[-4:]
    mdhd = _full('mdhd', 1, 0, struct.pack('>QQIQ', created, modified, track.media_scale, media_total) + language)
    mdia = _box('mdia', mdhd + track.hdlr + minf)

    edts = b''
    if track.edits:
        normal = [i for i, e in enumerate(track.edits) if e[1] != -1]
        if len(normal) == 1:
            edits = [list(e) for e in track.edits]
            edits[normal[0]][0] += clip_movie * (copies - 1)
            movie_total = sum(e[0] for e in edits)
            body = struct.pack('>I', len(edits)) + b''.join(struct.pack('>QqhH', d, t, r, 0) for d, t, r in edits)
            edts = _box('edts', _full('elst', 1, 0, body))
    tkhd = track.tkhd
    created, modified = _times(tkhd)
    flags = struct.unpack_from('>I', tkhd, 0)[0] & 0xFFFFFF
    rest = tkhd[24:] if tkhd[0] == 0 else tkhd[36:]          # after duration
    track_id = struct.unpack_from('>I', tkhd, 12 if tkhd[0] == 0 else 20)[0]
    tkhd = _full('tkhd', 1, flags, struct.pack('>QQIIQ', created, modified, track_id, 0, movie_total) + rest)
    trak = _box('trak', tkhd + edts + mdia)

    mvhd = track.mvhd
    created, modified = _times(mvhd)
    rest = mvhd[20:] if mvhd[0] == 0 else mvhd[32:]          # after duration
    mvhd = _full('mvhd', 1, 0, struct.pack('>QQIQ', created, modified, track.movie_scale, movie_total) + rest)
    return _box('moov', mvhd + trak)


def _times(full_box):
    if full_box[0] == 1:
        return struct.unpack_from('>QQ', full_box, 4)
    return struct.unpack_from('>II', full_box, 4)


def write_loop(source, size, out, target=TARGET_SECONDS, stopped=None, progress=None):
    """Write the loop copy to the open binary file ``out``; returns the copies made."""
    ftyp, track, low, high = plan(source, size)
    copies = repeats(track, target)
    data = high - low
    wide = data > 0xF0000000
    mdat_head = 16 if data + 16 > 0xFFFFFFFF else 8
    moov = build_moov(track, copies, 0, low, wide)
    base = len(ftyp) + len(moov) + mdat_head
    moov = build_moov(track, copies, base, low, wide)
    out.write(ftyp)
    out.write(moov)
    if mdat_head == 16:
        out.write(struct.pack('>I4sQ', 1, b'mdat', data + 16))
    else:
        out.write(struct.pack('>I4s', data + 8, b'mdat'))
    source.seek(low)
    left = data
    while left > 0:
        if stopped and stopped():
            raise InterruptedError('Stopped.')
        block = source.read(min(COPY_BLOCK, left))
        if not block:
            raise Unsupported('Short read.')
        out.write(block)
        left -= len(block)
        if progress:
            progress(1.0 - left / float(data or 1))
    return copies
