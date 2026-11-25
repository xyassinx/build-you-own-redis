"""A small parser for Redis RDB (dump) files.

Only the parts needed to load keys are implemented: the file header, metadata
opcodes, expiry timestamps and the common value types (string, list, set, hash,
sorted set). Strings may be length-prefixed, integer-encoded or LZF-compressed.
"""

import struct


def lzf_decompress(data, expected_length):
    """Decompress an LZF block (used for string values in RDB files)."""
    out = bytearray()
    i = 0
    n = len(data)
    while i < n:
        ctrl = data[i]
        i += 1
        if ctrl < 32:
            # Literal run: the next (ctrl + 1) bytes are copied as-is.
            length = ctrl + 1
            out += data[i:i + length]
            i += length
        else:
            # Back reference into the already-decoded output.
            length = ctrl >> 5
            ref = i - ((ctrl & 0x1F) << 8) - 1
            if length == 7:
                length += data[i]
                i += 1
            ref -= data[i]
            i += 1
            for _ in range(length + 2):
                out.append(out[ref])
                ref += 1
    return bytes(out[:expected_length])


class RDB:
    def __init__(self, data):
        self.data = data
        self.entries = {}  # key -> value
        self.expires = {}  # key -> absolute epoch seconds

    @classmethod
    def load(cls, path):
        """Read and parse ``path``. A missing or malformed file yields an
        empty result so the server can still start."""
        try:
            with open(path, "rb") as handle:
                data = handle.read()
        except OSError:
            return cls(b"")

        rdb = cls(data)
        try:
            rdb.parse()
        except (IndexError, struct.error, ValueError):
            # Ignore the remainder of a file we do not fully understand.
            pass
        return rdb

    def parse(self):
        buf = self.data
        if buf[:5] != b"REDIS":
            return
        pos = 9  # skip "REDIS0011" and friends
        expires_at = None

        while pos < len(buf):
            opcode = buf[pos]
            pos += 1

            if opcode == 0xFF:          # end of file
                break
            if opcode == 0xFA:          # auxiliary metadata
                _, pos = self._read_string(buf, pos)
                _, pos = self._read_string(buf, pos)
                continue
            if opcode == 0xFE:          # database selector
                _, pos, _ = self._read_length(buf, pos)
                continue
            if opcode == 0xFB:          # hash table sizes
                _, pos, _ = self._read_length(buf, pos)
                _, pos, _ = self._read_length(buf, pos)
                continue
            if opcode == 0xFC:          # expiry in milliseconds
                expires_at = struct.unpack_from("<Q", buf, pos)[0] / 1000.0
                pos += 8
                continue
            if opcode == 0xFD:          # expiry in seconds
                expires_at = float(struct.unpack_from("<I", buf, pos)[0])
                pos += 4
                continue

            # Anything else is a key/value pair, preceded by its value type.
            key, pos = self._read_string(buf, pos)
            value, pos = self._read_value(opcode, buf, pos)
            self.entries[key] = value
            if expires_at is not None:
                self.expires[key] = expires_at
                expires_at = None

    # ------------------------------------------------------------------
    # Low level readers
    # ------------------------------------------------------------------
    def _read_length(self, buf, pos):
        """Return (length, new_pos, is_special_encoding)."""
        first = buf[pos]
        pos += 1
        kind = first >> 6
        if kind == 0:  # 6 bit length
            return first & 0x3F, pos, False
        if kind == 1:  # 14 bit length
            second = buf[pos]
            pos += 1
            return ((first & 0x3F) << 8) | second, pos, False
        if kind == 2:  # special encoding
            return first & 0x3F, pos, True
        raise ValueError("invalid length encoding")

    def _read_string(self, buf, pos):
        length, pos, special = self._read_length(buf, pos)
        if not special:
            value = bytes(buf[pos:pos + length])
            return value, pos + length

        if length == 0:  # 8 bit integer
            value, = struct.unpack_from("b", buf, pos)
            return str(value).encode(), pos + 1
        if length == 1:  # 16 bit integer
            value, = struct.unpack_from("<h", buf, pos)
            return str(value).encode(), pos + 2
        if length == 2:  # 32 bit integer
            value, = struct.unpack_from("<i", buf, pos)
            return str(value).encode(), pos + 4
        if length == 3:  # LZF compressed string
            compressed_len, pos, _ = self._read_length(buf, pos)
            uncompressed_len, pos, _ = self._read_length(buf, pos)
            raw = buf[pos:pos + compressed_len]
            return lzf_decompress(bytes(raw), uncompressed_len), pos + compressed_len
        raise ValueError("unknown string encoding")

    def _read_value(self, kind, buf, pos):
        if kind == 0x00:  # string
            return self._read_string(buf, pos)
        if kind == 0x01:  # list
            count, pos, _ = self._read_length(buf, pos)
            items = []
            for _ in range(count):
                item, pos = self._read_string(buf, pos)
                items.append(item)
            return items, pos
        if kind == 0x02:  # set
            count, pos, _ = self._read_length(buf, pos)
            items = set()
            for _ in range(count):
                item, pos = self._read_string(buf, pos)
                items.add(item)
            return items, pos
        if kind == 0x03:  # sorted set (score is a length-prefixed string)
            count, pos, _ = self._read_length(buf, pos)
            items = {}
            for _ in range(count):
                member, pos = self._read_string(buf, pos)
                score, pos = self._read_string(buf, pos)
                items[member] = float(score)
            return items, pos
        if kind == 0x04:  # hash
            count, pos, _ = self._read_length(buf, pos)
            items = {}
            for _ in range(count):
                field, pos = self._read_string(buf, pos)
                value, pos = self._read_string(buf, pos)
                items[field] = value
            return items, pos
        if kind == 0x05:  # sorted set v2 (score is an 8 byte double)
            count, pos, _ = self._read_length(buf, pos)
            items = {}
            for _ in range(count):
                member, pos = self._read_string(buf, pos)
                score, = struct.unpack_from("<d", buf, pos)
                pos += 8
                items[member] = score
            return items, pos
        raise ValueError("unsupported RDB value type 0x%02x" % kind)
