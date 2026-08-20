"""TLG image decoder for KiriKiri engine (TLG5/TLG6, incl. TLG0.0 wrapper).

Pure-Python port of the decoder logic from GARbro's ImageTLG.cs
(which itself is a C# port of W.Dee's original TLG5/6 decoder).

Supports:
  - TLG0.0 wrapper ("TLG0.0\\x00sds\\x1a" prefix) around TLG5.0/TLG6.0
  - TLG5.0 (LZSS + color composition, 3/4 colors)
  - TLG6.0 (Golomb entropy coding + LZSS-compressed filter types + 32 filters)
  - tag-at-end ("tags" base image blending) via load_base callback

Output: RGBA bytes (width * height * 4).
"""

import struct

MASK32 = 0xFFFFFFFF


class TlgError(Exception):
    pass


def _le_u32(buf, off):
    return struct.unpack_from("<I", buf, off)[0]


def _le_i32(buf, off):
    return struct.unpack_from("<i", buf, off)[0]


def parse_header(data):
    """Return (version, width, height, colors, data_offset)."""
    if len(data) < 64:
        raise TlgError("file too small")
    if data[:11] == b"TLG0.0\x00sds\x1a":
        offset = 0xF
    else:
        offset = 0
    if data[offset + 6:offset + 11] != b"\x00raw\x1a":
        raise TlgError("missing 'raw' marker at offset %d" % offset)
    h = bytearray(data[offset:offset + 32])
    if h[:6] == b"TLG6.0":
        version = 6
    elif h[:6] == b"TLG5.0":
        version = 5
    elif h[:6] == b"XXXYYY":
        version = 5
        h[0x0C] ^= 0xAB
        h[0x10] ^= 0xAC
    elif h[:6] == b"XXXZZZ":
        version = 6
        h[0x0F] ^= 0xAB
        h[0x13] ^= 0xAC
    elif h[:6] == b"JKMXE8":
        version = 5
        h[0x0C] ^= 0x1A
        h[0x10] ^= 0x1C
    else:
        raise TlgError("unknown TLG magic %r" % bytes(h[:8]))
    colors = h[11]
    if version == 6:
        if colors not in (1, 3, 4):
            raise TlgError("invalid TLG6 color count %d" % colors)
        if h[12] or h[13] or h[14]:
            raise TlgError("invalid TLG6 reserved bytes")
        hdr_len = 15
    else:
        if colors not in (3, 4):
            raise TlgError("invalid TLG5 color count %d" % colors)
        hdr_len = 12
    width = _le_u32(h, hdr_len)
    height = _le_u32(h, hdr_len + 4)
    return version, width, height, colors, offset + hdr_len + 8


# ---------------------------------------------------------------------------
# TLG5
# ---------------------------------------------------------------------------

def _lzss_decompress_slide(outbuf, inbuf, text, initialr):
    """Modified LZSS (TVPTLG5DecompressSlide). Returns (outbuf, next_r)."""
    r = initialr
    flags = 0
    o = 0
    i = 0
    n = len(inbuf)
    while i < n:
        flags >>= 1
        if (flags & 0x100) == 0:
            flags = inbuf[i] | 0xFF00
            i += 1
        if flags & 1:
            mpos = inbuf[i] | ((inbuf[i + 1] & 0xF) << 8)
            mlen = (inbuf[i + 1] & 0xF0) >> 4
            i += 2
            mlen += 3
            if mlen == 18:
                mlen += inbuf[i]
                i += 1
            while mlen:
                c = text[mpos & 4095]
                outbuf[o] = c
                o += 1
                text[r] = c
                r += 1
                mpos += 1
                r &= 4095
                mlen -= 1
        else:
            c = inbuf[i]
            i += 1
            outbuf[o] = c
            o += 1
            text[r] = c
            r += 1
            r &= 4095
    return outbuf, r


def _compose_3to4(outp, outp_index, upper, bufs, bufpos, width):
    pc0 = pc1 = pc2 = 0
    for x in range(width):
        c0 = bufs[0][bufpos + x]
        c1 = bufs[1][bufpos + x]
        c2 = bufs[2][bufpos + x]
        c0 += c1
        c2 += c1
        pc0 = (pc0 + c0) & 0xFF
        pc1 = (pc1 + c1) & 0xFF
        pc2 = (pc2 + c2) & 0xFF
        outp[outp_index] = (pc0 + outp[upper + 0]) & 0xFF
        outp[outp_index + 1] = (pc1 + outp[upper + 1]) & 0xFF
        outp[outp_index + 2] = (pc2 + outp[upper + 2]) & 0xFF
        outp[outp_index + 3] = 0xFF
        outp_index += 4
        upper += 4


def _compose_4to4(outp, outp_index, upper, bufs, bufpos, width):
    pc0 = pc1 = pc2 = pc3 = 0
    for x in range(width):
        c0 = bufs[0][bufpos + x]
        c1 = bufs[1][bufpos + x]
        c2 = bufs[2][bufpos + x]
        c3 = bufs[3][bufpos + x]
        c0 += c1
        c2 += c1
        pc0 = (pc0 + c0) & 0xFF
        pc1 = (pc1 + c1) & 0xFF
        pc2 = (pc2 + c2) & 0xFF
        pc3 = (pc3 + c3) & 0xFF
        outp[outp_index] = (pc0 + outp[upper + 0]) & 0xFF
        outp[outp_index + 1] = (pc1 + outp[upper + 1]) & 0xFF
        outp[outp_index + 2] = (pc2 + outp[upper + 2]) & 0xFF
        outp[outp_index + 3] = (pc3 + outp[upper + 3]) & 0xFF
        outp_index += 4
        upper += 4


def _decode_tlg5(data, width, height, colors, data_offset, load_base=None):
    src = data[data_offset:]
    pos = 0
    blockheight = _le_i32(src, pos)
    pos += 4
    blockcount = (height - 1) // blockheight + 1
    pos += blockcount * 4

    stride = width * 4
    image = bytearray(height * stride)
    text = bytearray(4096)
    outbufs = [bytearray(blockheight * width + 10) for _ in range(colors)]
    z = 0
    prevline = -1
    for y_blk in range(0, height, blockheight):
        for c in range(colors):
            mark = src[pos]
            size = _le_i32(src, pos + 1)
            pos += 5
            if mark == 0:
                inbuf = src[pos:pos + size]
                pos += size
                outbufs[c], z = _lzss_decompress_slide(outbufs[c], inbuf, text, z)
            else:
                outbufs[c][:size] = src[pos:pos + size]
                pos += size
        y_lim = min(y_blk + blockheight, height)
        outbuf_pos = 0
        for y in range(y_blk, y_lim):
            current = y * stride
            if prevline >= 0:
                if colors == 3:
                    _compose_3to4(image, current, prevline, outbufs, outbuf_pos, width)
                else:
                    _compose_4to4(image, current, prevline, outbufs, outbuf_pos, width)
            else:
                if colors == 3:
                    pr = pg = pb = 0
                    idx = current
                    for x in range(width):
                        b = outbufs[0][outbuf_pos + x]
                        g = outbufs[1][outbuf_pos + x]
                        r = outbufs[2][outbuf_pos + x]
                        b += g
                        r += g
                        pb = (pb + b) & 0xFF
                        pg = (pg + g) & 0xFF
                        pr = (pr + r) & 0xFF
                        image[idx] = pb
                        image[idx + 1] = pg
                        image[idx + 2] = pr
                        image[idx + 3] = 0xFF
                        idx += 4
                else:
                    pr = pg = pb = pa = 0
                    idx = current
                    for x in range(width):
                        b = outbufs[0][outbuf_pos + x]
                        g = outbufs[1][outbuf_pos + x]
                        r = outbufs[2][outbuf_pos + x]
                        a = outbufs[3][outbuf_pos + x]
                        b += g
                        r += g
                        pb = (pb + b) & 0xFF
                        pg = (pg + g) & 0xFF
                        pr = (pr + r) & 0xFF
                        pa = (pa + a) & 0xFF
                        image[idx] = pb
                        image[idx + 1] = pg
                        image[idx + 2] = pr
                        image[idx + 3] = pa
                        idx += 4
            outbuf_pos += width
            prevline = current
    return bytes(image)


# ---------------------------------------------------------------------------
# TLG6
# ---------------------------------------------------------------------------

H_BLOCK = 8
W_BLOCK = 8
GOLOMB_N = 4
LZ_TABLE_BITS = 12
LZ_TABLE_SIZE = 1 << LZ_TABLE_BITS

GOLOMB_COMPRESSED = [
    (3, 7, 15, 27, 63, 108, 223, 448, 130),
    (3, 5, 13, 24, 51, 95, 192, 384, 257),
    (2, 5, 12, 21, 39, 86, 155, 320, 384),
    (2, 3, 9, 18, 33, 61, 129, 258, 511),
]

_leading_zero = bytearray(LZ_TABLE_SIZE)
for i in range(LZ_TABLE_SIZE):
    cnt = 0
    j = 1
    while j != LZ_TABLE_SIZE and not (i & j):
        j <<= 1
        cnt += 1
    cnt += 1
    if j == LZ_TABLE_SIZE:
        cnt = 0
    _leading_zero[i] = cnt

_golomb_table = bytearray(GOLOMB_N * GOLOMB_N * 2 * 128)
for n in range(GOLOMB_N):
    a = 0
    for i in range(9):
        for _ in range(GOLOMB_COMPRESSED[n][i]):
            _golomb_table[a * GOLOMB_N + n] = i
            a += 1
    assert a == GOLOMB_N * 2 * 128


def _make_gt_mask(a, b):
    tmp2 = (~b) & MASK32
    tmp = ((a & tmp2) + (((a ^ tmp2) >> 1) & 0x7F7F7F7F)) & 0x80808080
    tmp = ((tmp >> 7) + 0x7F7F7F7F) ^ 0x7F7F7F7F
    return tmp


def _packed_add(a, b):
    tmp = (((a & b) << 1) + ((a ^ b) & 0xFEFEFEFE)) & 0x01010100
    return (a + b - tmp) & MASK32


def _med2(a, b, c):
    aa_gt_bb = _make_gt_mask(a, b)
    a_xor_b_and_aa_gt_bb = (a ^ b) & aa_gt_bb
    aa = a_xor_b_and_aa_gt_bb ^ a
    bb = a_xor_b_and_aa_gt_bb ^ b
    n = _make_gt_mask(c, bb)
    nn = _make_gt_mask(aa, c)
    m = (~(n | nn)) & MASK32
    return (n & aa) | (nn & bb) | ((bb & m) - (c & m) + (aa & m)) & MASK32


def _med(a, b, c, v):
    return _packed_add(_med2(a, b, c), v)


def _avg(a, b, c, v):
    return _packed_add(((a & b) + (((a ^ b) & 0xFEFEFEFE) >> 1)) + ((a ^ b) & 0x01010101), v)


def _filter_value(ftype, v):
    """Apply the per-channel rearrange for filter types 2..31.

    All expressions read the ORIGINAL channel values of v (GARbro/krkrz
    compute each output channel from the untouched input; sequential
    updates corrupt filters 6/7, 18/19, 24/25, 26/27, 28/29).
    """
    r0 = (v >> 16) & 0xFF
    g0 = (v >> 8) & 0xFF
    b0 = v & 0xFF
    a = v & 0xFF000000
    if ftype in (2, 3):
        r, g, b = (r0 + g0) & 0xFF, g0, (b0 + g0) & 0xFF
    elif ftype in (4, 5):
        r, g, b = (r0 + b0 + g0) & 0xFF, (g0 + b0) & 0xFF, b0
    elif ftype in (6, 7):
        r, g, b = r0, (g0 + r0) & 0xFF, (b0 + r0 + g0) & 0xFF
    elif ftype in (8, 9):
        r, g, b = (r0 + b0 + r0 + g0) & 0xFF, (g0 + b0 + r0) & 0xFF, (b0 + r0) & 0xFF
    elif ftype in (10, 11):
        r, g, b = r0, (g0 + b0 + r0) & 0xFF, (b0 + r0) & 0xFF
    elif ftype in (12, 13):
        r, g, b = r0, g0, (b0 + g0) & 0xFF
    elif ftype in (14, 15):
        r, g, b = r0, (g0 + b0) & 0xFF, b0
    elif ftype in (16, 17):
        r, g, b = (r0 + g0) & 0xFF, g0, b0
    elif ftype in (18, 19):
        r, g, b = (r0 + b0) & 0xFF, (g0 + r0 + b0) & 0xFF, (b0 + g0 + r0 + b0) & 0xFF
    elif ftype in (20, 21):
        r, g, b = r0, (g0 + r0) & 0xFF, (b0 + r0) & 0xFF
    elif ftype in (22, 23):
        r, g, b = (r0 + b0) & 0xFF, (g0 + b0) & 0xFF, b0
    elif ftype in (24, 25):
        r, g, b = (r0 + b0) & 0xFF, (g0 + r0 + b0) & 0xFF, b0
    elif ftype in (26, 27):
        r, g, b = (r0 + b0 + g0) & 0xFF, (g0 + r0 + b0 + g0) & 0xFF, (b0 + g0) & 0xFF
    elif ftype in (28, 29):
        r, g, b = (r0 + b0 + g0 + r0) & 0xFF, (g0 + r0) & 0xFF, (b0 + g0 + r0) & 0xFF
    else:  # 30, 31
        r, g, b = (r0 + b0 * 2) & 0xFF, (g0 + b0 * 2) & 0xFF, b0
    return (r << 16) | (g << 8) | b | a


def _decode_golomb(bit_pool, pixel_count, offset=None):
    """Golomb decode (TVPTLG6DecodeGolombValues / ...ForFirst)."""
    idx = 0
    n = GOLOMB_N - 1
    a = 0
    bit_pos = 1
    zero = not (bit_pool[0] & 1)
    out = [0] * pixel_count
    pixel = 0
    while pixel < pixel_count:
        t = (_le_u32(bit_pool, idx) >> bit_pos) & MASK32
        b = _leading_zero[t & (LZ_TABLE_SIZE - 1)]
        bit_count = b
        while b == 0:
            bit_count += LZ_TABLE_BITS
            bit_pos += LZ_TABLE_BITS
            idx += bit_pos >> 3
            bit_pos &= 7
            t = (_le_u32(bit_pool, idx) >> bit_pos) & MASK32
            b = _leading_zero[t & (LZ_TABLE_SIZE - 1)]
            bit_count += b
        bit_pos += b
        idx += bit_pos >> 3
        bit_pos &= 7
        bit_count -= 1
        count = 1 << bit_count
        count += ((_le_i32(bit_pool, idx) >> bit_pos) & (count - 1))
        bit_pos += bit_count
        idx += bit_pos >> 3
        bit_pos &= 7
        if zero:
            pixel += count
            zero = False
        else:
            while count:
                k = _golomb_table[a * GOLOMB_N + n]
                t = (_le_u32(bit_pool, idx) >> bit_pos) & MASK32
                if t != 0:
                    b = _leading_zero[t & (LZ_TABLE_SIZE - 1)]
                    bit_count = b
                    while b == 0:
                        bit_count += LZ_TABLE_BITS
                        bit_pos += LZ_TABLE_BITS
                        idx += bit_pos >> 3
                        bit_pos &= 7
                        t = (_le_u32(bit_pool, idx) >> bit_pos) & MASK32
                        b = _leading_zero[t & (LZ_TABLE_SIZE - 1)]
                        bit_count += b
                    bit_count -= 1
                else:
                    idx += 5
                    bit_count = bit_pool[idx - 1]
                    bit_pos = 0
                    t = _le_u32(bit_pool, idx)
                    b = 0
                v = (bit_count << k) + ((t >> b) & ((1 << k) - 1))
                sign = (v & 1) - 1
                v >>= 1
                a += v
                # GARbro/krkrz store the value byte-truncated per channel
                # ((byte)val << offset): high bits must never bleed across
                # channels (missing this corrupts images with values > 255)
                val = (v ^ sign) + sign + 1
                out[pixel] = (val & 0xFF) if offset is None else ((val & 0xFF) << offset)
                pixel += 1
                bit_pos += b
                bit_pos += k
                idx += bit_pos >> 3
                bit_pos &= 7
                n -= 1
                if n < 0:
                    a >>= 1
                    n = GOLOMB_N - 1
                count -= 1
            zero = True
    return out



def _tlg6_lzss_text():
    """The 4096-byte LZSS sliding-dictionary seed: every 2-byte pattern with
    (r,g,b,a) + (r,g,b,a) repeated 32x16 times (the standard TLG6 start)."""
    text = bytearray(4096)
    p = 0
    for i in range(0, 32 * 0x01010101, 0x01010101):
        for j in range(0, 16 * 0x01010101, 0x01010101):
            text[p] = i & 0xFF
            text[p + 1] = (i >> 8) & 0xFF
            text[p + 2] = (i >> 16) & 0xFF
            text[p + 3] = (i >> 24) & 0xFF
            text[p + 4] = j & 0xFF
            text[p + 5] = (j >> 8) & 0xFF
            text[p + 6] = (j >> 16) & 0xFF
            text[p + 7] = (j >> 24) & 0xFF
            p += 8
    return text


def _decode_tlg6_header(src, width, height, colors):
    """Parse the TLG6 block header and set up the decode state: block
    geometry, per-row buffers, the LZSS sliding dictionary and the (LZSS-
    decompressed) filter-type stream.  Returns (state_dict, pos) with pos
    just past the filter stream - the start of the image blocks."""
    pos = 0
    max_bit_length = _le_i32(src, pos)
    pos += 4

    x_block_count = (width - 1) // W_BLOCK + 1
    y_block_count = (height - 1) // H_BLOCK + 1
    main_count = width // W_BLOCK
    fraction = width - main_count * W_BLOCK

    image_bits = [0] * (height * width)
    bit_pool = bytearray(max_bit_length // 8 + 5)
    pixelbuf = [0] * (width * H_BLOCK + 1)
    filter_types = bytearray(x_block_count * y_block_count)
    zeroline = [0] * width
    LZSS_text = _tlg6_lzss_text()

    zerocolor = 0xFF000000 if colors == 3 else 0x00000000
    for i in range(width):
        zeroline[i] = zerocolor

    inbuf_size = _le_i32(src, pos)
    pos += 4
    inbuf = src[pos:pos + inbuf_size]
    pos += inbuf_size
    if len(inbuf) != inbuf_size:
        raise TlgError("filter types truncated")
    filter_types = bytearray(filter_types)
    _lzss_decompress_slide(filter_types, inbuf, LZSS_text, 0)

    state = {
        "x_block_count": x_block_count,
        "y_block_count": y_block_count,
        "main_count": main_count,
        "fraction": fraction,
        "max_bit_length": max_bit_length,
        "image_bits": image_bits,
        "bit_pool": bit_pool,
        "pixelbuf": pixelbuf,
        "filter_types": filter_types,
        "zeroline": zeroline,
        "LZSS_text": LZSS_text,
        "zerocolor": zerocolor,
    }
    return state, pos


def _decode_tlg6_blocks(src, state, width, height, colors, pos):
    """Decode every 8x8 block's entropy-coded pixel data and reconstruct the
    filtered scan lines into image_bits, then pack them as RGBA bytes.
    `pos` is the offset just past the filter stream (start of image blocks)."""
    x_block_count = state["x_block_count"]
    main_count = state["main_count"]
    fraction = state["fraction"]
    image_bits = state["image_bits"]
    bit_pool = state["bit_pool"]
    pixelbuf = state["pixelbuf"]
    filter_types = state["filter_types"]
    zerocolor = state["zerocolor"]

    prevline = state["zeroline"]
    prevline_index = 0

    for y in range(0, height, H_BLOCK):
        ylim = min(y + H_BLOCK, height)
        pixel_count = (ylim - y) * width
        for c in range(colors):
            bit_length = _le_i32(src, pos)
            pos += 4
            method = (bit_length >> 30) & 3
            bit_length &= 0x3FFFFFFF
            byte_length = bit_length // 8
            if bit_length % 8:
                byte_length += 1
            bit_pool[:byte_length] = src[pos:pos + byte_length]
            pos += byte_length
            if method == 0:
                vals = _decode_golomb(bit_pool, pixel_count,
                                      None if (c == 0 and colors != 1) else c * 8)
                if c == 0 and colors != 1:
                    pixelbuf[:pixel_count] = vals
                else:
                    for k in range(pixel_count):
                        pixelbuf[k] = (pixelbuf[k] & ~(0xFF << (c * 8))) | vals[k]
            else:
                raise TlgError("unsupported TLG6 entropy method %d" % method)

        ft = (y // H_BLOCK) * x_block_count
        skipbytes = (ylim - y) * W_BLOCK
        for yy in range(y, ylim):
            curline = yy * width
            dirv = (yy & 1) ^ 1
            oddskip = (ylim - yy - 1) - (yy - y)
            if main_count != 0:
                start = (width if width < W_BLOCK else W_BLOCK) * (yy - y)
                _decode_line_generic(prevline, prevline_index, image_bits, curline,
                                     width, 0, main_count, filter_types, ft, skipbytes,
                                     pixelbuf, start, zerocolor, oddskip, dirv)
            if main_count != x_block_count:
                ww = fraction
                if ww > W_BLOCK:
                    ww = W_BLOCK
                start = ww * (yy - y)
                _decode_line_generic(prevline, prevline_index, image_bits, curline,
                                     width, main_count, x_block_count, filter_types, ft,
                                     skipbytes, pixelbuf, start, zerocolor, oddskip, dirv)
            prevline = image_bits
            prevline_index = curline

    out = bytearray(height * width * 4)
    for i, v in enumerate(image_bits):
        out[i * 4] = v & 0xFF
        out[i * 4 + 1] = (v >> 8) & 0xFF
        out[i * 4 + 2] = (v >> 16) & 0xFF
        out[i * 4 + 3] = (v >> 24) & 0xFF
    return bytes(out)


def _decode_tlg6(data, width, height, colors, data_offset, load_base=None):
    src = data[data_offset:]
    state, pos = _decode_tlg6_header(src, width, height, colors)
    return _decode_tlg6_blocks(src, state, width, height, colors, pos)


def _decode_line_generic(prevline, prevline_index, curline, curline_index, width,
                         start_block, block_limit, filtertypes, filtertypes_index,
                         skipblockbytes, inbuf, inbuf_index, initialp, oddskip, dirv):
    if start_block != 0:
        prevline_index += start_block * W_BLOCK
        curline_index += start_block * W_BLOCK
        p = curline[curline_index - 1]
        up = prevline[prevline_index - 1]
    else:
        p = up = initialp

    inbuf_index += skipblockbytes * start_block
    step = 1 if (dirv & 1) else -1

    for i in range(start_block, block_limit):
        w = width - i * W_BLOCK
        if w > W_BLOCK:
            w = W_BLOCK
        ww = w
        if step == -1:
            inbuf_index += ww - 1
        if i & 1:
            inbuf_index += oddskip * ww
        ftype = filtertypes[filtertypes_index + i]
        if ftype > 31:
            return
        even = ftype in (0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30)
        while w:
            u = prevline[prevline_index]
            if ftype >= 2:
                v = _filter_value(ftype, inbuf[inbuf_index])
            else:
                v = inbuf[inbuf_index]
            if even:
                p = _med(p, u, up, v)
            else:
                p = _avg(p, u, up, v)
            up = u
            curline[curline_index] = p
            curline_index += 1
            prevline_index += 1
            inbuf_index += step
            w -= 1
        if step == 1:
            inbuf_index += skipblockbytes - ww
        else:
            inbuf_index += skipblockbytes + 1
        if i & 1:
            inbuf_index -= oddskip * ww


# ---------------------------------------------------------------------------
# tags-at-end blending (optional, used by some games for base images)
# ---------------------------------------------------------------------------

def _parse_tags(tail):
    """Parse the 'tags' section at end of file. Returns dict key -> (value_bytes)."""
    i = len(tail) - 8
    while i >= 0:
        if tail[i:i + 4] == b"tags":
            break
        i -= 1
    if i < 0:
        return None
    off = i + 4
    length = _le_i32(tail, off)
    off += 4
    if length <= 0 or length > len(tail) - off:
        return None
    end = off + length
    tags = {}
    while off < end:
        colon = tail.find(b":", off, end)
        if colon < 0:
            break
        key_len = int(tail[off:colon])
        off = colon + 1
        key = int.from_bytes(tail[off:off + key_len], "little") if key_len > 0 else 0
        off += key_len + 1
        colon = tail.find(b":", off, end)
        if colon < 0:
            break
        val_len = int(tail[off:colon])
        off = colon + 1
        tags[key] = tail[off:off + val_len]
        off += val_len + 1
    return tags


def _blend_image(base, base_w, base_h, overlay, ov_w, ov_h, off_x, off_y, method):
    """Blend overlay RGBA onto base RGBA (both bytes arrays)."""
    out = bytearray(base)
    dst_stride = base_w * 4
    src_stride = ov_w * 4
    dst = off_y * dst_stride + off_x * 4
    src = 0
    for _y in range(ov_h):
        for _x in range(ov_w):
            src_alpha = overlay[src + 3]
            if method == 2:
                out[dst] ^= overlay[src]
                out[dst + 1] ^= overlay[src + 1]
                out[dst + 2] ^= overlay[src + 2]
                out[dst + 3] ^= src_alpha
            elif src_alpha != 0:
                if src_alpha == 0xFF or out[dst + 3] == 0:
                    out[dst:dst + 4] = overlay[src:src + 4]
                else:
                    out[dst] = (overlay[src] * src_alpha + out[dst] * (0xFF - src_alpha)) // 0xFF
                    out[dst + 1] = (overlay[src + 1] * src_alpha + out[dst + 1] * (0xFF - src_alpha)) // 0xFF
                    out[dst + 2] = (overlay[src + 2] * src_alpha + out[dst + 2] * (0xFF - src_alpha)) // 0xFF
                    out[dst + 3] = max(src_alpha, out[dst + 3])
            dst += 4
            src += 4
        dst += dst_stride - src_stride
    return bytes(out)


def decode(data, load_base=None):
    """Decode TLG data -> RGBA bytes. load_base(name) -> (w, h, rgba) for
    games that reference a base image via trailing tags; optional."""
    version, width, height, colors, data_offset = parse_header(data)
    if version == 6 and _USE_NUMBA:
        try:
            rgba = bytes(_decode_tlg6_fast(data, width, height, colors, data_offset))
        except Exception:
            # Broad catch on purpose: the numba JIT fast path is an optional
            # accelerator. Any JIT/numa error on edge data must fall back to
            # the proven pure-Python decoder (same algorithm).
            rgba = _decode_tlg6(data, width, height, colors, data_offset)
    elif version == 6:
        rgba = _decode_tlg6(data, width, height, colors, data_offset)
    else:
        rgba = _decode_tlg5(data, width, height, colors, data_offset)

    if len(data) > data_offset:
        tail = data[-512:]
        if len(tail) > 8:
            tags = _parse_tags(tail)
            if tags and load_base and 1 in tags:
                base_name = tags[1].decode("cp932", errors="replace")
                base = load_base(base_name)
                if base:
                    bw, bh, brgba = base
                    off_x = tags.get(2)
                    off_y = tags.get(3)
                    method = tags.get(4)
                    ox = int.from_bytes(off_x, "little") & 0xFFFF if off_x else 0
                    oy = int.from_bytes(off_y, "little") & 0xFFFF if off_y else 0
                    m = int.from_bytes(method, "little") if method else 1
                    if brgba and len(brgba) == bw * bh * 4:
                        return _blend_image(brgba, bw, bh, rgba, width, height, ox, oy, m)
    return rgba


def decode_to_png(data, out_path, load_base=None):
    """Decode TLG and write PNG via Pillow."""
    from PIL import Image
    version, width, height, colors, _ = parse_header(data)
    rgba = decode(data, load_base)
    img = Image.frombytes("RGBA", (width, height), rgba)
    img.save(out_path, "PNG")
    return width, height


# ---------------------------------------------------------------------------
# numba JIT acceleration (optional). Falls back to pure Python if numba
# is unavailable. The JIT path keeps the exact same bit-level algorithm.
# ---------------------------------------------------------------------------

try:
    import numpy as _np
    from numba import njit as _njit

    _USE_NUMBA = True
except Exception:
    # Optional-dependency guard: if numpy/numba are missing or fail to
    # initialise for any reason, the pure-Python decoder is used instead.
    # Import-time failures are not enumerable, so the guard stays broad.
    _USE_NUMBA = False


if _USE_NUMBA:
    @_njit(cache=True)
    def _nb_u32(buf, off):
        return (buf[off] | (buf[off + 1] << 8) | (buf[off + 2] << 16)
                | (buf[off + 3] << 24))

    @_njit(cache=True)
    def _nb_i32(buf, off):
        v = _nb_u32(buf, off)
        if v & 0x80000000:
            return _np.int64(v) - 0x100000000
        return _np.int64(v)

    @_njit(cache=True)
    def _nb_golomb(bit_pool, pixel_count, offset, lz, gt):
        out = _np.zeros(pixel_count, dtype=_np.uint32)
        idx = 0
        n = 3
        a = 0
        bit_pos = 1
        zero = (bit_pool[0] & 1) == 0
        pixel = 0
        while pixel < pixel_count:
            t = _nb_u32(bit_pool, idx) >> bit_pos
            b = int(lz[t & 4095])
            bit_count = b
            while b == 0:
                bit_count += 12
                bit_pos += 12
                idx += bit_pos >> 3
                bit_pos &= 7
                t = _nb_u32(bit_pool, idx) >> bit_pos
                b = int(lz[t & 4095])
                bit_count += b
            bit_pos += b
            idx += bit_pos >> 3
            bit_pos &= 7
            bit_count -= 1
            count = 1 << bit_count
            count += (_nb_i32(bit_pool, idx) >> bit_pos) & (count - 1)
            bit_pos += bit_count
            idx += bit_pos >> 3
            bit_pos &= 7
            if zero:
                pixel += count
                zero = False
            else:
                while count:
                    t = _nb_u32(bit_pool, idx) >> bit_pos
                    if t != 0:
                        b = int(lz[t & 4095])
                        bit_count = b
                        while b == 0:
                            bit_count += 12
                            bit_pos += 12
                            idx += bit_pos >> 3
                            bit_pos &= 7
                            t = _nb_u32(bit_pool, idx) >> bit_pos
                            b = int(lz[t & 4095])
                            bit_count += b
                        bit_count -= 1
                    else:
                        idx += 5
                        bit_count = bit_pool[idx - 1]
                        bit_pos = 0
                        t = _nb_u32(bit_pool, idx)
                        b = 0
                    k = gt[a * 4 + n]
                    v = (bit_count << k) + ((t >> b) & ((1 << k) - 1))
                    sign = (v & 1) - 1
                    v >>= 1
                    a += v
                    val = (v ^ sign) + sign + 1
                    if offset < 0:
                        out[pixel] = val & 0xFF
                    else:
                        out[pixel] = (val & 0xFF) << offset
                    pixel += 1
                    bit_pos += b
                    bit_pos += k
                    idx += bit_pos >> 3
                    bit_pos &= 7
                    n -= 1
                    if n < 0:
                        a >>= 1
                        n = 3
                    count -= 1
                zero = True
        return out, idx

    @_njit(cache=True)
    def _nb_gt_mask(a, b):
        tmp2 = (~b) & 0xFFFFFFFF
        tmp = ((a & tmp2) + (((a ^ tmp2) >> 1) & 0x7F7F7F7F)) & 0x80808080
        tmp = ((tmp >> 7) + 0x7F7F7F7F) ^ 0x7F7F7F7F
        return tmp

    @_njit(cache=True)
    def _nb_packed_add(a, b):
        tmp = (((a & b) << 1) + ((a ^ b) & 0xFEFEFEFE)) & 0x01010100
        return (a + b - tmp) & 0xFFFFFFFF

    @_njit(cache=True)
    def _nb_med2(a, b, c):
        aa_gt_bb = _nb_gt_mask(a, b)
        ax = (a ^ b) & aa_gt_bb
        aa = ax ^ a
        bb = ax ^ b
        n = _nb_gt_mask(c, bb)
        nn = _nb_gt_mask(aa, c)
        m = (~(n | nn)) & 0xFFFFFFFF
        return (n & aa) | (nn & bb) | ((bb & m) - (c & m) + (aa & m)) & 0xFFFFFFFF

    @_njit(cache=True)
    def _nb_med(a, b, c, v):
        return _nb_packed_add(_nb_med2(a, b, c), v)

    @_njit(cache=True)
    def _nb_avg(a, b, c, v):
        return _nb_packed_add(((a & b) + (((a ^ b) & 0xFEFEFEFE) >> 1))
                              + ((a ^ b) & 0x01010101), v)

    @_njit(cache=True)
    def _nb_filter(ftype, v):
        r0 = (v >> 16) & 0xFF
        g0 = (v >> 8) & 0xFF
        b0 = v & 0xFF
        a = v & 0xFF000000
        if ftype == 2 or ftype == 3:
            r, g, b = (r0 + g0) & 0xFF, g0, (b0 + g0) & 0xFF
        elif ftype == 4 or ftype == 5:
            r, g, b = (r0 + b0 + g0) & 0xFF, (g0 + b0) & 0xFF, b0
        elif ftype == 6 or ftype == 7:
            r, g, b = r0, (g0 + r0) & 0xFF, (b0 + r0 + g0) & 0xFF
        elif ftype == 8 or ftype == 9:
            r, g, b = (r0 + b0 + r0 + g0) & 0xFF, (g0 + b0 + r0) & 0xFF, (b0 + r0) & 0xFF
        elif ftype == 10 or ftype == 11:
            r, g, b = r0, (g0 + b0 + r0) & 0xFF, (b0 + r0) & 0xFF
        elif ftype == 12 or ftype == 13:
            r, g, b = r0, g0, (b0 + g0) & 0xFF
        elif ftype == 14 or ftype == 15:
            r, g, b = r0, (g0 + b0) & 0xFF, b0
        elif ftype == 16 or ftype == 17:
            r, g, b = (r0 + g0) & 0xFF, g0, b0
        elif ftype == 18 or ftype == 19:
            r, g, b = (r0 + b0) & 0xFF, (g0 + r0 + b0) & 0xFF, (b0 + g0 + r0 + b0) & 0xFF
        elif ftype == 20 or ftype == 21:
            r, g, b = r0, (g0 + r0) & 0xFF, (b0 + r0) & 0xFF
        elif ftype == 22 or ftype == 23:
            r, g, b = (r0 + b0) & 0xFF, (g0 + b0) & 0xFF, b0
        elif ftype == 24 or ftype == 25:
            r, g, b = (r0 + b0) & 0xFF, (g0 + r0 + b0) & 0xFF, b0
        elif ftype == 26 or ftype == 27:
            r, g, b = (r0 + b0 + g0) & 0xFF, (g0 + r0 + b0 + g0) & 0xFF, (b0 + g0) & 0xFF
        elif ftype == 28 or ftype == 29:
            r, g, b = (r0 + b0 + g0 + r0) & 0xFF, (g0 + r0) & 0xFF, (b0 + g0 + r0) & 0xFF
        else:
            r, g, b = (r0 + b0 + b0) & 0xFF, (g0 + b0 + b0) & 0xFF, b0
        return (r << 16) | (g << 8) | b | a

    @_njit(cache=True)
    def _nb_lzss(outbuf, inbuf, text, initialr):
        r = initialr
        flags = 0
        o = 0
        i = 0
        n = len(inbuf)
        while i < n:
            flags >>= 1
            if (flags & 0x100) == 0:
                flags = inbuf[i] | 0xFF00
                i += 1
            if flags & 1:
                mpos = inbuf[i] | ((inbuf[i + 1] & 0xF) << 8)
                mlen = (inbuf[i + 1] & 0xF0) >> 4
                i += 2
                mlen += 3
                if mlen == 18:
                    mlen += inbuf[i]
                    i += 1
                while mlen:
                    c = text[mpos & 4095]
                    outbuf[o] = c
                    o += 1
                    text[r] = c
                    r += 1
                    mpos += 1
                    r &= 4095
                    mlen -= 1
            else:
                c = inbuf[i]
                i += 1
                outbuf[o] = c
                o += 1
                text[r] = c
                r += 1
                r &= 4095
        return r

    @_njit(cache=True)
    def _nb_line(prevline, prevline_index, curline, curline_index, width,
                 start_block, block_limit, filtertypes, filtertypes_index,
                 skipblockbytes, inbuf, inbuf_index, initialp, oddskip, dirv):
        if start_block != 0:
            prevline_index += start_block * 8
            curline_index += start_block * 8
            p = curline[curline_index - 1]
            up = prevline[prevline_index - 1]
        else:
            p = up = initialp
        inbuf_index += skipblockbytes * start_block
        step = 1 if (dirv & 1) else -1
        for i in range(start_block, block_limit):
            w = width - i * 8
            if w > 8:
                w = 8
            ww = w
            if step == -1:
                inbuf_index += ww - 1
            if i & 1:
                inbuf_index += oddskip * ww
            ftype = filtertypes[filtertypes_index + i]
            if ftype > 31:
                return
            even = ftype in (0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30)
            while w:
                u = prevline[prevline_index]
                if ftype >= 2:
                    v = _nb_filter(ftype, inbuf[inbuf_index])
                else:
                    v = inbuf[inbuf_index]
                if even:
                    p = _nb_med(p, u, up, v)
                else:
                    p = _nb_avg(p, u, up, v)
                up = u
                curline[curline_index] = p
                curline_index += 1
                prevline_index += 1
                inbuf_index += step
                w -= 1
            if step == 1:
                inbuf_index += skipblockbytes - ww
            else:
                inbuf_index += skipblockbytes + 1
            if i & 1:
                inbuf_index -= oddskip * ww

    @_njit(cache=True)
    def _nb_decode_tlg6(src, width, height, colors, data_offset, lz, gt):
        x_block_count = (width - 1) // 8 + 1
        y_block_count = (height - 1) // 8 + 1
        main_count = width // 8
        fraction = width - main_count * 8
        image_bits = _np.zeros(height * width, dtype=_np.uint32)
        pixelbuf = _np.zeros(width * 8 + 1, dtype=_np.uint32)
        ft = _np.zeros(int(x_block_count * y_block_count), dtype=_np.uint8)
        zeroline = _np.zeros(int(width), dtype=_np.uint32)
        zerocolor = 0xFF000000 if colors == 3 else 0
        for i in range(width):
            zeroline[i] = zerocolor
        text = _np.zeros(4096, dtype=_np.uint8)
        p = 0
        for i in range(0, 32 * 0x01010101, 0x01010101):
            for j in range(0, 16 * 0x01010101, 0x01010101):
                text[p] = i & 0xFF
                text[p + 1] = (i >> 8) & 0xFF
                text[p + 2] = (i >> 16) & 0xFF
                text[p + 3] = (i >> 24) & 0xFF
                text[p + 4] = j & 0xFF
                text[p + 5] = (j >> 8) & 0xFF
                text[p + 6] = (j >> 16) & 0xFF
                text[p + 7] = (j >> 24) & 0xFF
                p += 8
        pos = data_offset
        max_bit_length = _nb_i32(src, pos)
        pos += 4
        bit_pool = _np.zeros(int(max_bit_length) // 8 + 5, dtype=_np.uint8)
        insz = _nb_i32(src, pos)
        pos += 4
        inbuf = src[pos:pos + insz]
        pos += insz
        _nb_lzss(ft, inbuf, text, 0)
        prevline = zeroline
        prevline_index = 0
        for y in range(0, height, 8):
            ylim = y + 8
            if ylim > height:
                ylim = height
            pixel_count = (ylim - y) * width
            for c in range(colors):
                bl = _nb_i32(src, pos)
                pos += 4
                method = (bl >> 30) & 3
                length = bl & 0x3FFFFFFF
                byte_length = length // 8
                if length % 8:
                    byte_length += 1
                bit_pool[:byte_length] = src[pos:pos + byte_length]
                pos += byte_length
                if method == 0:
                    offarg = -1 if (c == 0 and colors != 1) else c * 8
                    vals, _ = _nb_golomb(bit_pool, pixel_count, offarg, lz, gt)
                    if c == 0 and colors != 1:
                        for k in range(pixel_count):
                            pixelbuf[k] = vals[k]
                    else:
                        for k in range(pixel_count):
                            pixelbuf[k] = (pixelbuf[k] & ~(0xFF << (c * 8))) | vals[k]
                else:
                    raise RuntimeError("unsupported TLG6 entropy method")
            ft_idx = (y // 8) * x_block_count
            skipbytes = (ylim - y) * 8
            for yy in range(y, ylim):
                curline = yy * width
                dirv = (yy & 1) ^ 1
                oddskip = (ylim - yy - 1) - (yy - y)
                if main_count != 0:
                    start = (width if width < 8 else 8) * (yy - y)
                    _nb_line(prevline, prevline_index, image_bits, curline, width,
                             0, main_count, ft, ft_idx, skipbytes, pixelbuf, start,
                             zerocolor, oddskip, dirv)
                if main_count != x_block_count:
                    ww = fraction
                    if ww > 8:
                        ww = 8
                    start = ww * (yy - y)
                    _nb_line(prevline, prevline_index, image_bits, curline, width,
                             main_count, x_block_count, ft, ft_idx, skipbytes,
                             pixelbuf, start, zerocolor, oddskip, dirv)
                prevline = image_bits
                prevline_index = curline
        out = _np.empty(height * width * 4, dtype=_np.uint8)
        k = 0
        for i in range(height * width):
            v = int(image_bits[i])
            out[k] = v & 0xFF
            out[k + 1] = (v >> 8) & 0xFF
            out[k + 2] = (v >> 16) & 0xFF
            out[k + 3] = (v >> 24) & 0xFF
            k += 4
        return out


def _decode_tlg6_fast(data, width, height, colors, data_offset):
    """numba JIT path; falls back to pure python on any error."""
    import numpy as np
    src = np.frombuffer(data, dtype=np.uint8)
    lz = np.frombuffer(bytes(_leading_zero), dtype=np.uint8)
    gt = np.frombuffer(bytes(_golomb_table), dtype=np.uint8)
    return _nb_decode_tlg6(src, width, height, colors, data_offset, lz, gt)
