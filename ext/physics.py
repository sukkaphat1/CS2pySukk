"""
Source 2 map collision extraction.

Reads a map VPK's ``maps/<map>world_physics.vmdl_c``, decompiles the binary
KV3 (Zstd) PHYS block via :mod:`ext.vphys`, and flattens the Rubikon physics
shapes (``m_meshes`` triangles + ``m_hulls`` convex faces) into a list of
triangles for BVH / ray-trace bounce detection.
"""
import struct

from ext.vphys import BinaryKV3

# Clip building walls above this height. The physics meshes carry the buildings'
# full (simplified) height, which is far taller than the grenade trajectory sees.
WALL_MAX_Z = 700.0


# --------------------------------------------------------------------------
# VPK (v2) reading
# --------------------------------------------------------------------------
def _parse_vpk_dir(tree):
    pos = 0
    files = {}

    def rs(p):
        e = tree.find(b"\x00", p)
        return tree[p:e].decode("ascii", "replace"), e + 1

    while pos < len(tree):
        ext, pos = rs(pos)
        if ext == "":
            break
        while True:
            path, pos = rs(pos)
            if path == "":
                break
            while True:
                fname, pos = rs(pos)
                if fname == "":
                    break
                crc, preload, aidx, eoff, elen, term = struct.unpack("<IHHIIH", tree[pos:pos + 18])
                pos += 18
                files[path + fname + "." + ext] = (eoff, elen)
    return files


def read_vpk_file(vpk_path, name):
    with open(vpk_path, "rb") as f:
        header = f.read(28)
        magic, ver, dir_size, embed, ch, sh, sg = struct.unpack("<IIIIIII", header)
        tree = f.read(dir_size)
        files = _parse_vpk_dir(tree)
        data_base = 28 + dir_size
        if name not in files:
            return None
        eoff, elen = files[name]
        f.seek(data_base + eoff)
        return f.read(elen)


def get_phys_block(vpk_path, map_name):
    """Return the raw PHYS block bytes of ``maps/<map>world_physics.vmdl_c``."""
    name = f"maps/{map_name}world_physics.vmdl_c"
    vmdl = read_vpk_file(vpk_path, name)
    if vmdl is None:
        return None
    block_count = struct.unpack_from("<I", vmdl, 12)[0]
    pos = 16
    for _ in range(block_count):
        btype = struct.unpack_from("<I", vmdl, pos)[0]
        entrypos = pos + 4
        boff = entrypos + struct.unpack_from("<I", vmdl, entrypos)[0]
        bsize = struct.unpack_from("<I", vmdl, entrypos + 4)[0]
        pos += 12
        if btype == 0x53594850:  # b'PHYS'
            return vmdl[boff:boff + bsize]
    return None


# --------------------------------------------------------------------------
# Shape extraction
# --------------------------------------------------------------------------
def _unpack_vec3(blob, off):
    return struct.unpack_from("<fff", blob, off)


def extract_triangles(vpk_path, map_name="de_dust2"):
    """Return (triangles, stats).

    Each triangle is ``(ax, ay, az, bx, by, bz, cx, cy, cz, surface_prop)``.
    """
    phys = get_phys_block(vpk_path, map_name)
    if phys is None:
        return [], {"error": "PHYS block not found"}

    root = BinaryKV3(phys).parse()
    parts = root.get("m_parts") or []
    if not parts:
        return [], {"error": "no m_parts"}

    shape = parts[0].get("m_rnShape") or {}
    meshes = shape.get("m_meshes") or []
    hulls = shape.get("m_hulls") or []

    # Only the "default" collision group is solid for grenades. "ConditionallySolid"
    # (doors, breakables, etc.) is passable and would otherwise create tall invisible walls.
    solid_attrs = set()
    for i, a in enumerate(root.get("m_collisionAttributes") or []):
        if (a.get("m_CollisionGroupString") or "").lower() == "default":
            solid_attrs.add(i)
    meshes = [m for m in meshes if m.get("m_nCollisionAttributeIndex", -1) in solid_attrs]
    hulls = [h for h in hulls if h.get("m_nCollisionAttributeIndex", -1) in solid_attrs]

    triangles = []
    n_mesh_tris = 0
    n_hull_tris = 0

    for mesh in meshes:
        m = mesh.get("m_Mesh") or {}
        vblob = m.get("m_Vertices") or b""
        tblob = m.get("m_Triangles") or b""
        sp = mesh.get("m_nSurfacePropertyIndex", 0)
        nv = len(vblob) // 12
        nt = len(tblob) // 12
        for i in range(nt):
            a, b, c = struct.unpack_from("<iii", tblob, i * 12)
            if a >= nv or b >= nv or c >= nv:
                continue
            va = _unpack_vec3(vblob, a * 12)
            vb = _unpack_vec3(vblob, b * 12)
            vc = _unpack_vec3(vblob, c * 12)
            e1x = vb[0] - va[0]; e1y = vb[1] - va[1]; e1z = vb[2] - va[2]
            e2x = vc[0] - va[0]; e2y = vc[1] - va[1]; e2z = vc[2] - va[2]
            nx = e1y * e2z - e1z * e2y
            ny = e1z * e2x - e1x * e2z
            nz = e1x * e2y - e1y * e2x
            if abs(nz) > abs(nx) and abs(nz) > abs(ny):
                # horizontal-ish (ground/roof) -> keep as-is
                triangles.append((*va, *vb, *vc, sp))
            else:
                # vertical wall -> clip above WALL_MAX_Z so buildings don't reach the sky
                za = min(va[2], WALL_MAX_Z)
                zb = min(vb[2], WALL_MAX_Z)
                zc = min(vc[2], WALL_MAX_Z)
                if za == zb and zb == zc:
                    continue
                triangles.append((va[0], va[1], za, vb[0], vb[1], zb, vc[0], vc[1], zc, sp))
            n_mesh_tris += 1

    for hull in hulls:
        h = hull.get("m_Hull") or {}
        sp = hull.get("m_nSurfacePropertyIndex", 0)
        pblob = h.get("m_VertexPositions") or b""
        eblob = h.get("m_Edges") or b""
        fblob = h.get("m_Faces") or b""
        nv = len(pblob) // 12
        if nv == 0 or not eblob or not fblob:
            continue
        positions = [_unpack_vec3(pblob, i * 12) for i in range(nv)]
        nh = len(eblob) // 4
        half_edges = [struct.unpack_from("<BBBB", eblob, i * 4) for i in range(nh)]
        faces = list(fblob)
        for face_start in faces:
            loop = []
            cur = face_start
            for _ in range(64):  # convex face <= 255 verts; safety bound
                if cur >= nh:
                    break
                nxt, twin, origin, face = half_edges[cur]
                loop.append(origin)
                cur = nxt
                if cur == face_start:
                    break
            if len(loop) < 3:
                continue
            for i in range(1, len(loop) - 1):
                a = positions[loop[0]]
                b = positions[loop[i]]
                c = positions[loop[i + 1]]
                triangles.append((*a, *b, *c, sp))
                n_hull_tris += 1

    stats = {
        "meshes": len(meshes),
        "hulls": len(hulls),
        "mesh_triangles": n_mesh_tris,
        "hull_triangles": n_hull_tris,
        "total_triangles": len(triangles),
    }
    return triangles, stats
