"""
Binary KV3 (version 5, Zstd) parser for Source 2 compiled physics blocks.

Ported from ValveResourceFormat's BinaryKV3 reader (MIT license):
https://github.com/ValveResourceFormat/ValveResourceFormat
"""
import struct

try:
    import zstandard
except ImportError:  # pragma: no cover
    zstandard = None


# KV3 binary node types
_NULL = 1
_BOOLEAN = 2
_INT64 = 3
_UINT64 = 4
_DOUBLE = 5
_STRING = 6
_BINARY_BLOB = 7
_ARRAY = 8
_OBJECT = 9
_ARRAY_TYPED = 10
_INT32 = 11
_UINT32 = 12
_BOOLEAN_TRUE = 13
_BOOLEAN_FALSE = 14
_INT64_ZERO = 15
_INT64_ONE = 16
_DOUBLE_ZERO = 17
_DOUBLE_ONE = 18
_FLOAT = 19
_INT16 = 20
_UINT16 = 21
_INT32_AS_BYTE = 23
_ARRAY_TYPE_BYTE_LENGTH = 24
_ARRAY_TYPE_AUXILIARY_BUFFER = 25

_MAGIC = 0x4B563300


class _Buf:
    """A cursor over a bytes buffer, with lane sub-cursors b1/b2/b4/b8."""
    __slots__ = ("data", "pos", "b1", "b2", "b4", "b8")

    def __init__(self, data):
        self.data = data
        self.pos = 0
        self.b1 = None
        self.b2 = None
        self.b4 = None
        self.b8 = None

    def read(self, n):
        b = self.data[self.pos:self.pos + n]
        self.pos += n
        return b


class BinaryKV3:
    def __init__(self, data):
        self.data = data
        self.version = 0
        self.strings = []
        self.types = _Buf(b"")
        self.object_lengths = _Buf(b"")
        self.blob_lengths = _Buf(b"")
        self.blobs = _Buf(b"")
        # main buffer (buffer2 for v5), auxiliary buffer (buffer1 for v5)
        self.buf = None
        self.aux = None

    # ---- header ----
    def _read_header(self):
        d = self.data
        r = 0
        magic = struct.unpack_from("<I", d, r)[0]; r += 4
        self.version = magic & 0xFF
        if (magic & 0xFFFFFF00) != _MAGIC:
            raise ValueError(f"bad kv3 magic {magic:#x}")
        guid = d[r:r + 16]; r += 16
        self.guid = guid
        compression = struct.unpack_from("<I", d, r)[0]; r += 4
        dict_id = struct.unpack_from("<H", d, r)[0]; r += 2
        frame_size = struct.unpack_from("<H", d, r)[0]; r += 2
        cb1 = struct.unpack_from("<i", d, r)[0]; r += 4
        cb4 = struct.unpack_from("<i", d, r)[0]; r += 4
        cb8 = struct.unpack_from("<i", d, r)[0]; r += 4
        count_types = struct.unpack_from("<i", d, r)[0]; r += 4
        count_objects = struct.unpack_from("<H", d, r)[0]; r += 2
        count_arrays = struct.unpack_from("<H", d, r)[0]; r += 2
        size_unc_total = struct.unpack_from("<i", d, r)[0]; r += 4
        size_comp_total = struct.unpack_from("<i", d, r)[0]; r += 4
        count_blocks = struct.unpack_from("<i", d, r)[0]; r += 4
        size_blob_bytes = struct.unpack_from("<i", d, r)[0]; r += 4
        cb2 = struct.unpack_from("<i", d, r)[0]; r += 4
        size_blockcomp = struct.unpack_from("<i", d, r)[0]; r += 4
        # v5 fields
        size_unc_b1 = struct.unpack_from("<i", d, r)[0]; r += 4
        size_comp_b1 = struct.unpack_from("<i", d, r)[0]; r += 4
        size_unc_b2 = struct.unpack_from("<i", d, r)[0]; r += 4
        size_comp_b2 = struct.unpack_from("<i", d, r)[0]; r += 4
        cb1_b2 = struct.unpack_from("<i", d, r)[0]; r += 4
        cb2_b2 = struct.unpack_from("<i", d, r)[0]; r += 4
        cb4_b2 = struct.unpack_from("<i", d, r)[0]; r += 4
        cb8_b2 = struct.unpack_from("<i", d, r)[0]; r += 4
        r += 4  # unk13
        count_objects_b2 = struct.unpack_from("<i", d, r)[0]; r += 4
        count_arrays_b2 = struct.unpack_from("<i", d, r)[0]; r += 4
        r += 4  # unk16
        self._hdr_end = r

        self._meta = dict(
            compression=compression, cb1=cb1, cb4=cb4, cb8=cb8, cb2=cb2,
            count_types=count_types, count_blocks=count_blocks,
            size_blob_bytes=size_blob_bytes, size_unc_b1=size_unc_b1,
            size_comp_b1=size_comp_b1, size_unc_b2=size_unc_b2,
            size_comp_b2=size_comp_b2, cb1_b2=cb1_b2, cb2_b2=cb2_b2,
            cb4_b2=cb4_b2, cb8_b2=cb8_b2, count_objects_b2=count_objects_b2,
        )

    # ---- decompress ----
    @staticmethod
    def _zstd(data, out_size):
        if zstandard is None:
            raise RuntimeError("zstandard not installed")
        dctx = zstandard.ZstdDecompressor()
        return dctx.decompress(data, max_output_size=out_size)

    def parse(self):
        self._read_header()
        m = self._meta
        d = self.data
        r = self._hdr_end

        if m["compression"] != 2:
            raise ValueError(f"only zstd supported, got {m['compression']}")

        # buffer1
        b1_raw = self._zstd(d[r:r + m["size_comp_b1"]], m["size_unc_b1"])
        r += m["size_comp_b1"]
        # buffer2
        b2_raw = self._zstd(d[r:r + m["size_comp_b2"]], m["size_unc_b2"])
        r += m["size_comp_b2"]
        # binary blobs
        blob_comp = m["size_comp_b1"] + m["size_comp_b2"]
        blob_comp_total = None
        # size_comp_total not stored; derive from remaining bytes minus trailer(4)
        blob_compressed_size = len(d) - r - 4
        blobs_raw = self._zstd(d[r:r + blob_compressed_size], m["size_blob_bytes"])
        r += blob_compressed_size

        # ---- buffer1 (aux) ----
        aux = _Buf(b1_raw)
        off = 0
        aux.b1 = _Buf(b1_raw[off:off + m["cb1"]]) if m["cb1"] else _Buf(b"")
        off += m["cb1"]
        if m["cb2"]:
            off = (off + 1) & ~1
            aux.b2 = _Buf(b1_raw[off:off + m["cb2"] * 2])
            off += m["cb2"] * 2
        else:
            aux.b2 = _Buf(b"")
        if m["cb4"]:
            off = (off + 3) & ~3
            aux.b4 = _Buf(b1_raw[off:off + m["cb4"] * 4])
            off += m["cb4"] * 4
        else:
            aux.b4 = _Buf(b"")
        if m["cb8"]:
            off = (off + 7) & ~7
            aux.b8 = _Buf(b1_raw[off:off + m["cb8"] * 8])
            off += m["cb8"] * 8
        else:
            aux.b8 = _Buf(b"")
        self.aux = aux

        # string count = first int of aux.b4
        count_strings = struct.unpack_from("<i", aux.b4.data, 0)[0]
        aux.b4.pos = 4
        self.strings = []
        s = aux.b1
        for _ in range(count_strings):
            end = s.data.find(b"\x00", s.pos)
            self.strings.append(s.data[s.pos:end].decode("utf-8", "replace"))
            s.pos = end + 1

        # ---- buffer2 (main) ----
        buf = _Buf(b2_raw)
        off = 0
        # object lengths
        obj_len_bytes = m["count_objects_b2"] * 4
        self.object_lengths = _Buf(b2_raw[off:off + obj_len_bytes])
        off += obj_len_bytes
        if m["cb1_b2"]:
            buf.b1 = _Buf(b2_raw[off:off + m["cb1_b2"]]); off += m["cb1_b2"]
        else:
            buf.b1 = _Buf(b"")
        if m["cb2_b2"]:
            off = (off + 1) & ~1
            buf.b2 = _Buf(b2_raw[off:off + m["cb2_b2"] * 2]); off += m["cb2_b2"] * 2
        else:
            buf.b2 = _Buf(b"")
        if m["cb4_b2"]:
            off = (off + 3) & ~3
            buf.b4 = _Buf(b2_raw[off:off + m["cb4_b2"] * 4]); off += m["cb4_b2"] * 4
        else:
            buf.b4 = _Buf(b"")
        if m["cb8_b2"]:
            off = (off + 7) & ~7
            buf.b8 = _Buf(b2_raw[off:off + m["cb8_b2"] * 8]); off += m["cb8_b2"] * 8
        else:
            buf.b8 = _Buf(b"")
        self.types = _Buf(b2_raw[off:off + m["count_types"]])
        off += m["count_types"]
        # binary blob lengths
        if m["count_blocks"]:
            self.blob_lengths = _Buf(b2_raw[off:off + m["count_blocks"] * 4])
            off += m["count_blocks"] * 4
        else:
            self.blob_lengths = _Buf(b"")
        self.buf = buf
        self.blobs = _Buf(blobs_raw)

        # ---- read tree ----
        root_type, _ = self._read_type()
        root = self._read_value(root_type)
        return root

    # ---- types ----
    def _read_type(self):
        b = self.types.data[self.types.pos]
        self.types.pos += 1
        flag = 0
        if self.version >= 3:
            if b & 0x80:
                b &= 0x3F
                flag = self.types.data[self.types.pos]
                self.types.pos += 1
        else:
            if b & 0x80:
                b &= 0x7F
                flag = self.types.data[self.types.pos]
                self.types.pos += 1
        return b, flag

    # ---- values ----
    def _read_value(self, typ):
        buf = self.buf
        if typ == _NULL:
            return None
        if typ == _BOOLEAN_TRUE:
            return True
        if typ == _BOOLEAN_FALSE:
            return False
        if typ == _INT64_ZERO:
            return 0
        if typ == _INT64_ONE:
            return 1
        if typ == _DOUBLE_ZERO:
            return 0.0
        if typ == _DOUBLE_ONE:
            return 1.0
        if typ == _BOOLEAN:
            v = buf.b1.data[buf.b1.pos]; buf.b1.pos += 1
            return v == 1
        if typ == _INT32_AS_BYTE:
            v = buf.b1.data[buf.b1.pos]; buf.b1.pos += 1
            return v
        if typ == _INT16:
            v = struct.unpack_from("<h", buf.b2.data, buf.b2.pos)[0]; buf.b2.pos += 2
            return v
        if typ == _UINT16:
            v = struct.unpack_from("<H", buf.b2.data, buf.b2.pos)[0]; buf.b2.pos += 2
            return v
        if typ == _INT32:
            v = struct.unpack_from("<i", buf.b4.data, buf.b4.pos)[0]; buf.b4.pos += 4
            return v
        if typ == _UINT32:
            v = struct.unpack_from("<I", buf.b4.data, buf.b4.pos)[0]; buf.b4.pos += 4
            return v
        if typ == _FLOAT:
            v = struct.unpack_from("<f", buf.b4.data, buf.b4.pos)[0]; buf.b4.pos += 4
            return v
        if typ == _INT64:
            v = struct.unpack_from("<q", buf.b8.data, buf.b8.pos)[0]; buf.b8.pos += 8
            return v
        if typ == _UINT64:
            v = struct.unpack_from("<Q", buf.b8.data, buf.b8.pos)[0]; buf.b8.pos += 8
            return v
        if typ == _DOUBLE:
            v = struct.unpack_from("<d", buf.b8.data, buf.b8.pos)[0]; buf.b8.pos += 8
            return v
        if typ == _STRING:
            sid = struct.unpack_from("<i", buf.b4.data, buf.b4.pos)[0]; buf.b4.pos += 4
            return "" if sid == -1 else self.strings[sid]
        if typ == _BINARY_BLOB:
            n = struct.unpack_from("<i", self.blob_lengths.data, self.blob_lengths.pos)[0]
            self.blob_lengths.pos += 4
            if n > 0:
                out = self.blobs.data[self.blobs.pos:self.blobs.pos + n]
                self.blobs.pos += n
            else:
                out = b""
            return out
        if typ == _ARRAY:
            n = struct.unpack_from("<i", buf.b4.data, buf.b4.pos)[0]; buf.b4.pos += 4
            out = []
            for _ in range(n):
                out.append(self._read_array_item())
            return out
        if typ in (_ARRAY_TYPED, _ARRAY_TYPE_BYTE_LENGTH):
            if typ == _ARRAY_TYPE_BYTE_LENGTH:
                n = buf.b1.data[buf.b1.pos]; buf.b1.pos += 1
            else:
                n = struct.unpack_from("<i", buf.b4.data, buf.b4.pos)[0]; buf.b4.pos += 4
            sub, _ = self._read_type()
            out = []
            for _ in range(n):
                out.append(self._read_value(sub))
            return out
        if typ == _ARRAY_TYPE_AUXILIARY_BUFFER:
            n = buf.b1.data[buf.b1.pos]; buf.b1.pos += 1
            sub, _ = self._read_type()
            self.buf, self.aux = self.aux, self.buf
            out = []
            for _ in range(n):
                out.append(self._read_value(sub))
            self.buf, self.aux = self.aux, self.buf
            return out
        if typ == _OBJECT:
            if self.version >= 5:
                n = struct.unpack_from("<i", self.object_lengths.data, self.object_lengths.pos)[0]
                self.object_lengths.pos += 4
            else:
                n = struct.unpack_from("<i", buf.b4.data, buf.b4.pos)[0]; buf.b4.pos += 4
            out = {}
            for _ in range(n):
                k, v = self._read_member()
                out[k] = v
            return out
        raise ValueError(f"unknown type {typ}")

    def _read_array_item(self):
        typ, _ = self._read_type()
        return self._read_value(typ)

    def _read_member(self):
        typ, _ = self._read_type()
        sid = struct.unpack_from("<i", self.buf.b4.data, self.buf.b4.pos)[0]
        self.buf.b4.pos += 4
        name = "" if sid == -1 else self.strings[sid]
        return name, self._read_value(typ)
