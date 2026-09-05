"""
Collision world for grenade trajectory bounce detection.

Builds a median-split BVH over the map's collision triangles and provides
two-sided ray casting (Moeller-Trumbore). The BVH is cached to disk keyed by
map name so the (one-time, expensive) build only happens once per map.
"""
import os
import struct

from ext import paths
from ext.physics import extract_triangles

_LEAF_SIZE = 8
_CACHE_DIR = os.path.join(paths.writable_dir(), "collision_cache")
_CACHE_MAGIC = b"CS2COL1"
_CACHE_MAGIC = b"CS2COL1"


def _triangle_normal(ax, ay, az, bx, by, bz, cx, cy, cz):
    e1x, e1y, e1z = bx - ax, by - ay, bz - az
    e2x, e2y, e2z = cx - ax, cy - ay, cz - az
    nx = e1y * e2z - e1z * e2y
    ny = e1z * e2x - e1x * e2z
    nz = e1x * e2y - e1y * e2x
    length = (nx * nx + ny * ny + nz * nz) ** 0.5
    if length < 1e-12:
        return 0.0, 0.0, 1.0
    return nx / length, ny / length, nz / length


class CollisionWorld:
    __slots__ = ("tris", "mats", "nodes", "tri_idx")

    def __init__(self):
        # tris: flat list of 9 floats per triangle (ax..cz)
        self.tris = []
        # mats: surface property index per triangle
        self.mats = []
        # nodes: flat list of [minx,miny,minz,maxx,maxy,maxz,left,right,tri_start,tri_count]
        self.nodes = []
        # tri_idx: triangle index per BVH leaf slot
        self.tri_idx = []

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------
    @classmethod
    def build(cls, triangles):
        """triangles: iterable of (ax,ay,az,bx,by,bz,cx,cy,cz,mat)."""
        w = cls()
        n = len(triangles)
        tris = [0.0] * (n * 9)
        mats = [0] * n
        tminx = [0.0] * n
        tminy = [0.0] * n
        tminz = [0.0] * n
        tmaxx = [0.0] * n
        tmaxy = [0.0] * n
        tmaxz = [0.0] * n
        cx = [0.0] * n
        cy = [0.0] * n
        cz = [0.0] * n
        for i, t in enumerate(triangles):
            ax, ay, az, bx, by, bz, cx_, cy_, cz_, mat = t
            o = i * 9
            tris[o:o + 9] = [ax, ay, az, bx, by, bz, cx_, cy_, cz_]
            mats[i] = mat
            tminx[i] = min(ax, bx, cx_); tmaxx[i] = max(ax, bx, cx_)
            tminy[i] = min(ay, by, cy_); tmaxy[i] = max(ay, by, cy_)
            tminz[i] = min(az, bz, cz_); tmaxz[i] = max(az, bz, cz_)
            cx[i] = (ax + bx + cx_) / 3.0
            cy[i] = (ay + by + cy_) / 3.0
            cz[i] = (az + bz + cz_) / 3.0
        w.tris = tris
        w.mats = mats
        tri_idx = list(range(n))
        cents = (cx, cy, cz)
        bounds = (tminx, tminy, tminz, tmaxx, tmaxy, tmaxz)
        cls._build_recursive(w, tri_idx, cents, bounds, 0, n)
        w.tri_idx = tri_idx
        return w

    @staticmethod
    def _build_recursive(w, tri_idx, cents, bounds, start, end):
        cx, cy, cz = cents
        tminx, tminy, tminz, tmaxx, tmaxy, tmaxz = bounds
        # AABB over [start, end)
        mnx = min(tminx[i] for i in tri_idx[start:end])
        mny = min(tminy[i] for i in tri_idx[start:end])
        mnz = min(tminz[i] for i in tri_idx[start:end])
        mxx = max(tmaxx[i] for i in tri_idx[start:end])
        mxy = max(tmaxy[i] for i in tri_idx[start:end])
        mxz = max(tmaxz[i] for i in tri_idx[start:end])
        if end - start <= _LEAF_SIZE:
            w.nodes.append([mnx, mny, mnz, mxx, mxy, mxz, -1, -1, start, end - start])
            return
        # longest axis
        dx = mxx - mnx
        dy = mxy - mny
        dz = mxz - mnz
        if dx >= dy and dx >= dz:
            axis = 0
            arr = cx
        elif dy >= dz:
            axis = 1
            arr = cy
        else:
            axis = 2
            arr = cz
        seg = tri_idx[start:end]
        seg.sort(key=lambda i: arr[i])
        tri_idx[start:end] = seg
        mid = (start + end) // 2
        # append placeholder internal node, fill after children built
        idx = len(w.nodes)
        w.nodes.append([mnx, mny, mnz, mxx, mxy, mxz, -1, -1, -1, 0])
        CollisionWorld._build_recursive(w, tri_idx, cents, bounds, start, mid)
        left = idx + 1
        right = len(w.nodes)  # right subtree root is the next node appended
        CollisionWorld._build_recursive(w, tri_idx, cents, bounds, mid, end)
        w.nodes[idx][6] = left
        w.nodes[idx][7] = right

    # ------------------------------------------------------------------
    # Ray cast (two-sided, nearest hit)
    # ------------------------------------------------------------------
    def raycast(self, ox, oy, oz, dx, dy, dz, max_dist):
        """Return (t, nx, ny, nz, mat) for nearest hit within max_dist, else None."""
        best = max_dist
        hit = None
        invx = 1.0 / dx if dx != 0.0 else float("inf")
        invy = 1.0 / dy if dy != 0.0 else float("inf")
        invz = 1.0 / dz if dz != 0.0 else float("inf")
        stack = [0]
        tris = self.tris
        nodes = self.nodes
        tri_idx = self.tri_idx
        mats = self.mats
        while stack:
            ni = stack.pop()
            nd = nodes[ni]
            # AABB slab test
            if invx >= 0.0:
                t0 = (nd[0] - ox) * invx
                t1 = (nd[3] - ox) * invx
            else:
                t0 = (nd[3] - ox) * invx
                t1 = (nd[0] - ox) * invx
            if invy >= 0.0:
                ty0 = (nd[1] - oy) * invy
                ty1 = (nd[4] - oy) * invy
            else:
                ty0 = (nd[4] - oy) * invy
                ty1 = (nd[1] - oy) * invy
            if t0 > ty1 or ty0 > t1:
                continue
            if ty0 > t0:
                t0 = ty0
            if ty1 < t1:
                t1 = ty1
            if invz >= 0.0:
                tz0 = (nd[2] - oz) * invz
                tz1 = (nd[5] - oz) * invz
            else:
                tz0 = (nd[5] - oz) * invz
                tz1 = (nd[2] - oz) * invz
            if t0 > tz1 or tz0 > t1:
                continue
            if tz0 > t0:
                t0 = tz0
            if tz1 < t1:
                t1 = tz1
            if t0 > best or t1 < 0.0:
                continue

            if nd[6] == -1:  # leaf
                ts = nd[8]
                tc = nd[9]
                for k in range(ts, ts + tc):
                    ti = tri_idx[k]
                    o = ti * 9
                    ax, ay, az = tris[o], tris[o + 1], tris[o + 2]
                    bx, by, bz = tris[o + 3], tris[o + 4], tris[o + 5]
                    cx, cy, cz = tris[o + 6], tris[o + 7], tris[o + 8]
                    t = _ray_tri(ox, oy, oz, dx, dy, dz, ax, ay, az, bx, by, bz, cx, cy, cz)
                    if t is not None and t > 1e-6 and t < best:
                        best = t
                        nx, ny, nz = _triangle_normal(ax, ay, az, bx, by, bz, cx, cy, cz)
                        # orient normal toward ray origin
                        if nx * dx + ny * dy + nz * dz > 0.0:
                            nx, ny, nz = -nx, -ny, -nz
                        hit = (t, nx, ny, nz, mats[ti])
            else:
                if t1 >= 0.0:
                    stack.append(nd[6])
                    stack.append(nd[7])
        return hit

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------
    @staticmethod
    def cache_path(map_name):
        os.makedirs(_CACHE_DIR, exist_ok=True)
        return os.path.join(_CACHE_DIR, f"{map_name}.col")

    def save(self, map_name):
        path = CollisionWorld.cache_path(map_name)
        n = len(self.mats)
        nn = len(self.nodes)
        with open(path, "wb") as f:
            f.write(_CACHE_MAGIC)
            f.write(struct.pack("<II", n, nn))
            f.write(struct.pack(f"<{n * 9}f", *self.tris))
            f.write(struct.pack(f"<{n}i", *self.mats))
            f.write(struct.pack(f"<{n}i", *self.tri_idx))
            for nd in self.nodes:
                f.write(struct.pack("<6f4i", *nd))
        return path

    @classmethod
    def load(cls, map_name):
        path = CollisionWorld.cache_path(map_name)
        if not os.path.exists(path):
            return None
        w = cls()
        with open(path, "rb") as f:
            if f.read(7) != _CACHE_MAGIC:
                return None
            n, nn = struct.unpack("<II", f.read(8))
            w.tris = list(struct.unpack(f"<{n * 9}f", f.read(n * 36)))
            w.mats = list(struct.unpack(f"<{n}i", f.read(n * 4)))
            w.tri_idx = list(struct.unpack(f"<{n}i", f.read(n * 4)))
            w.nodes = [list(struct.unpack("<6f4i", f.read(40))) for _ in range(nn)]
        return w


def _ray_tri(ox, oy, oz, dx, dy, dz, ax, ay, az, bx, by, bz, cx, cy, cz):
    """Moeller-Trumbore (two-sided). Returns t or None."""
    e1x = bx - ax; e1y = by - ay; e1z = bz - az
    e2x = cx - ax; e2y = cy - ay; e2z = cz - az
    hx = dy * e2z - dz * e2y
    hy = dz * e2x - dx * e2z
    hz = dx * e2y - dy * e2x
    a = e1x * hx + e1y * hy + e1z * hz
    if -1e-9 < a < 1e-9:
        return None
    f = 1.0 / a
    sx = ox - ax; sy = oy - ay; sz = oz - az
    u = f * (sx * hx + sy * hy + sz * hz)
    if u < 0.0 or u > 1.0:
        return None
    qx = sy * e1z - sz * e1y
    qy = sz * e1x - sx * e1z
    qz = sx * e1y - sy * e1x
    v = f * (dx * qx + dy * qy + dz * qz)
    if v < 0.0 or u + v > 1.0:
        return None
    t = f * (e2x * qx + e2y * qy + e2z * qz)
    return t if t > 1e-7 else None


# --------------------------------------------------------------------------
# Lazy world loader
# --------------------------------------------------------------------------
def get_world(map_name, vpk_path=None):
    """Load a cached collision world, or build+save one from the map VPK."""
    w = CollisionWorld.load(map_name)
    if w is not None:
        return w
    if vpk_path and os.path.exists(vpk_path):
        try:
            print(f"[grenade-trajectory] Building collision cache for '{map_name}' (one-time)...")
            triangles, _stats = extract_triangles(vpk_path, map_name)
            if triangles:
                w = CollisionWorld.build(triangles)
                w.save(map_name)
                print(f"[grenade-trajectory] Collision cache ready ({len(triangles)} triangles).")
                return w
        except Exception as e:
            print(f"[grenade-trajectory] Collision build failed: {e}")
            return None
    return None
