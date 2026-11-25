"""Snapping cua Blender cho che do dat marker.

Marker dat bang modal rieng nen transform cua Blender khong chay. Module nay doc
dung cai dat snapping cua scene (nut nam cham, menu Snap To tren header) va lam
lai tren hinh hoc cac mesh dang hien:

  Increment, Grid, Vertex, Edge, Face (Project), Volume, Edge Center,
  Edge Perpendicular, Face Center, Face Nearest
  + Absolute Grid Snap, Backface Culling, Include Non-Selectable, Snap Peel Object

Trong luc keo, giu Ctrl dao trang thai bat / tat snapping nhu khi G trong Blender,
Shift lam buoc Increment min hon 10 lan.
"""

import math

import numpy as np
from bpy_extras import view3d_utils
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import intersect_line_line

SNAP_PX = 30            # ban kinh bat diem / canh (px, nhan ui_scale), nhu transform
GRID_PX = 20            # o luoi nho nhat tren man hinh khi tinh buoc Increment (ortho)
PRECISION = 0.1         # Shift: buoc nho di 10 lan
POINT_KINDS = (('VERTEX', 'co'), ('EDGE_MIDPOINT', 'mid'), ('FACE_MIDPOINT', 'centers'))


class _Geometry:
    """Hinh hoc toa do the gioi cua moi mesh dang hien, ghep chung mot BVH."""

    def __init__(self, context, selectable_only):
        depsgraph = context.evaluated_depsgraph_get()
        cos, edges, tris, centers, owner = [], [], [], [], []
        base = 0
        for index, obj in enumerate(o for o in context.view_layer.objects
                                    if o.type == 'MESH' and o.visible_get()):
            if selectable_only and obj.hide_select:
                continue
            ev = obj.evaluated_get(depsgraph)
            data = ev.to_mesh()
            try:
                M = np.array(ev.matrix_world, dtype=np.float64)
                n = len(data.vertices)
                if n == 0:
                    continue
                co = np.empty(n * 3, np.float32)
                data.vertices.foreach_get("co", co)
                co = co.reshape(-1, 3).astype(np.float64) @ M[:3, :3].T + M[:3, 3]
                e = np.empty(len(data.edges) * 2, np.int32)
                data.edges.foreach_get("vertices", e)
                data.calc_loop_triangles()
                t = np.empty(len(data.loop_triangles) * 3, np.int32)
                data.loop_triangles.foreach_get("vertices", t)
                c = np.empty(len(data.polygons) * 3, np.float32)
                data.polygons.foreach_get("center", c)
                c = c.reshape(-1, 3).astype(np.float64) @ M[:3, :3].T + M[:3, 3]
            finally:
                ev.to_mesh_clear()
            cos.append(co)
            edges.append(e.reshape(-1, 2) + base)
            tris.append(t.reshape(-1, 3) + base)
            centers.append(c)
            owner.append(np.full(len(t) // 3, index, np.int32))
            base += n
        self.empty = base == 0
        if self.empty:
            return
        self.co = np.concatenate(cos)
        self.edges = np.concatenate(edges)
        self.mid = (self.co[self.edges[:, 0]] + self.co[self.edges[:, 1]]) * 0.5
        self.centers = np.concatenate(centers)
        self.owner = np.concatenate(owner)
        tri = np.concatenate(tris)
        self.tree = BVHTree.FromPolygons(self.co.tolist(), tri.tolist()) if len(tri) else None


def _project(P, M, width, height):
    """Diem the gioi (N,3) -> toa do region (N,2) va mat na diem nam truoc camera."""
    h = P @ M[:3, :3].T + M[:3, 3]
    w = P @ M[3, :3] + M[3, 3]
    ok = w > 1e-6
    w = np.where(ok, w, 1.0)
    xy = (h[:, :2] / w[:, None] * 0.5 + 0.5) * (width, height)
    return xy, ok


def _order(d, depth, idx):
    """Gan chuot truoc; trung nhau tren man hinh (duoi nua px, vd dinh truoc / sau
    khi nhin thang) thi diem gan nguoi nhin truoc."""
    return idx[np.lexsort((depth[idx], np.floor(d[idx] * 2.0)))]


def _depth(P, rv3d):
    V = np.array(rv3d.view_matrix, dtype=np.float64)
    return -(P @ V[2, :3] + V[2, 3])


def _ui(context):
    """ui_scale; chay nen (khong co cua so) Blender tra 0."""
    return context.preferences.system.ui_scale or 1.0


class Snapper:
    def __init__(self):
        self._geo = None
        self._key = None

    def geometry(self, context):
        key = bool(context.scene.tool_settings.use_snap_selectable)
        if self._geo is None or key != self._key:
            self._geo, self._key = _Geometry(context, key), key
        return None if self._geo.empty else self._geo

    # ------------------------------------------------------------ tia

    @staticmethod
    def _cast(tree, origin, direction, limit, cull):
        """Diem cham dau tien; bo mat sau khi bat Backface Culling."""
        at, left = Vector(origin), limit
        for _i in range(64):
            hit = tree.ray_cast(at, direction, left) if left is not None \
                else tree.ray_cast(at, direction)
            if hit[0] is None:
                return None
            if not cull or hit[1].dot(direction) < 0.0:
                return hit
            step = (hit[0] - at).length + 1e-5
            at = hit[0] + direction * 1e-5
            if left is not None:
                left -= step
                if left <= 0.0:
                    return None
        return None

    def _visible(self, geo, region, rv3d, point, xray, cull):
        """Diem khong bi mat khac che (che do Solid), giong snapping cua Blender."""
        if xray or geo.tree is None:
            return True
        c = view3d_utils.location_3d_to_region_2d(region, rv3d, point)
        if c is None:
            return False
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, c)
        direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, c)
        dist = (point - origin).dot(direction)
        if dist <= 0.0:
            return False
        tol = max(1e-5, dist * 1e-3)
        return self._cast(geo.tree, origin, direction, dist - tol, cull) is None

    def _volume(self, geo, origin, direction, peel, cull):
        """Giua lop thit dau tien duoi chuot (Volume); Peel Object: ca object."""
        first = self._cast(geo.tree, origin, direction, None, cull)
        if first is None:
            return None
        entry, body = first[0], geo.owner[first[2]]
        exit_point, at = None, entry + direction * 1e-5
        for _i in range(256):
            hit = geo.tree.ray_cast(at, direction)
            if hit[0] is None:
                break
            if geo.owner[hit[2]] == body:
                exit_point = hit[0]
                if not peel:
                    break
            at = hit[0] + direction * 1e-5
        return entry if exit_point is None else (entry + exit_point) * 0.5

    # ------------------------------------------------------------ buoc luoi

    @staticmethod
    def grid_step(context, space, region, rv3d, point, precise=False):
        overlay = space.overlay
        step = max(overlay.grid_scale, 1e-6)
        sub = max(int(overlay.grid_subdivisions), 2)
        if not rv3d.is_perspective:     # ortho: luoi doi theo zoom nhu viewport
            c = view3d_utils.location_3d_to_region_2d(region, rv3d, point) \
                or Vector((region.width / 2, region.height / 2))
            a = view3d_utils.region_2d_to_location_3d(region, rv3d, c, point)
            b = view3d_utils.region_2d_to_location_3d(region, rv3d, c + Vector((1, 0)), point)
            pixel = max((b - a).length, 1e-9)
            least = GRID_PX * _ui(context) * pixel
            for _i in range(40):
                if step >= least:
                    break
                step *= sub
            for _i in range(40):
                if step / sub < least:
                    break
                step /= sub
        return step * (PRECISION if precise else 1.0)

    # ------------------------------------------------------------ chinh

    def snap(self, context, space, region, xy, base=None, free=None,
             invert=False, precise=False):
        """(diem, kieu) theo cai dat snapping cua scene, hoac (None, None).

        base: diem goc cua thao tac (Increment tuong doi, Edge Perpendicular).
        free: diem chua snap (dung cho Increment / Grid / Face Nearest).
        """
        ts = context.scene.tool_settings
        if ts.use_snap == bool(invert):
            return None, None
        elements = set(ts.snap_elements)
        rv3d = space.region_3d
        mouse = np.array(xy, dtype=np.float64)
        reach = SNAP_PX * _ui(context)
        shading = space.shading
        xray = shading.show_xray if shading.type != 'WIREFRAME' else shading.show_xray_wireframe
        cull = ts.use_snap_backface_culling
        geo = self.geometry(context) if elements - {'INCREMENT', 'GRID'} else None
        if geo is not None:
            M = np.array(rv3d.perspective_matrix, dtype=np.float64)
            # 1. Diem: dinh, giua canh, tam mat. Gan chuot nhat thang.
            best = None
            for kind, attr in POINT_KINDS:
                if kind not in elements:
                    continue
                P = getattr(geo, attr)
                s, ok = _project(P, M, region.width, region.height)
                d = np.linalg.norm(s - mouse, axis=1)
                near = np.nonzero(ok & (d < reach))[0]
                for i in _order(d, _depth(P, rv3d), near)[:12]:
                    if best is not None and d[i] >= best[0]:
                        break
                    p = Vector(P[i])
                    if self._visible(geo, region, rv3d, p, xray, cull):
                        best = (d[i], p, kind)
                        break
            if best is not None:
                return best[1], best[2]
            # 2. Canh: diem tren canh gan tia chuot, hoac chan duong vuong goc tu goc.
            if elements & {'EDGE', 'EDGE_PERPENDICULAR'} and len(geo.edges):
                hit = self._edge(geo, M, region, rv3d, mouse, reach, elements, base, xray, cull)
                if hit is not None:
                    return hit
            origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, xy)
            direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, xy)
            # 3. Mat: diem cham duoi chuot.
            if elements & {'FACE', 'FACE_PROJECT'} and geo.tree is not None:
                hit = self._cast(geo.tree, origin, direction, None, cull)
                if hit is not None:
                    return hit[0], 'FACE'
            # 4. Volume: giua khoi thit duoi chuot.
            if 'VOLUME' in elements and geo.tree is not None:
                p = self._volume(geo, origin, direction, ts.use_snap_peel_object, cull)
                if p is not None:
                    return p, 'VOLUME'
            # 5. Face Nearest: keo diem tu do ve mat gan nhat.
            if 'FACE_NEAREST' in elements and free is not None and geo.tree is not None:
                steps = max(1, ts.snap_face_nearest_steps)
                start = Vector(base) if base is not None else Vector(free)
                p = Vector(free)
                for k in range(1, steps + 1):
                    q = geo.tree.find_nearest(start.lerp(Vector(free), k / steps))[0]
                    if q is not None:
                        p = q
                return p, 'FACE_NEAREST'
        # 6. Increment / Grid: chi khi khong bat duoc hinh hoc nao.
        if elements & {'INCREMENT', 'GRID'} and free is not None:
            free = Vector(free)
            step = self.grid_step(context, space, region, rv3d, free, precise)
            if 'GRID' in elements or ts.use_snap_grid_absolute or base is None:
                return Vector(round(v / step) * step for v in free), 'GRID'
            base = Vector(base)
            return base + Vector(round(v / step) * step for v in free - base), 'INCREMENT'
        return None, None

    def _edge(self, geo, M, region, rv3d, mouse, reach, elements, base, xray, cull):
        a, ok_a = _project(geo.co[geo.edges[:, 0]], M, region.width, region.height)
        b, ok_b = _project(geo.co[geo.edges[:, 1]], M, region.width, region.height)
        ab = b - a
        length = np.maximum((ab * ab).sum(axis=1), 1e-12)
        t = np.clip(((mouse - a) * ab).sum(axis=1) / length, 0.0, 1.0)
        d = np.linalg.norm(a + ab * t[:, None] - mouse, axis=1)
        near = np.nonzero(ok_a & ok_b & (d < reach))[0]
        xy = Vector(mouse.tolist())
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, xy)
        far = origin + view3d_utils.region_2d_to_vector_3d(region, rv3d, xy)
        e0, e1 = geo.co[geo.edges[near, 0]], geo.co[geo.edges[near, 1]]
        depth = np.zeros(len(d))
        depth[near] = _depth(e0 + (e1 - e0) * t[near, None], rv3d)
        for i in _order(d, depth, near)[:12]:
            p0, p1 = Vector(geo.co[geo.edges[i, 0]]), Vector(geo.co[geo.edges[i, 1]])
            seg = p1 - p0
            if seg.length_squared < 1e-14:
                continue
            if 'EDGE_PERPENDICULAR' in elements and base is not None:
                u = (Vector(base) - p0).dot(seg) / seg.length_squared
                foot = p0 + seg * u
                c = view3d_utils.location_3d_to_region_2d(region, rv3d, foot)
                if 0.0 <= u <= 1.0 and c is not None \
                        and math.hypot(c.x - mouse[0], c.y - mouse[1]) < reach \
                        and self._visible(geo, region, rv3d, foot, xray, cull):
                    return foot, 'EDGE_PERPENDICULAR'
            if 'EDGE' not in elements:
                continue
            pair = intersect_line_line(p0, p1, origin, far)
            if pair is None:
                point = p0 + seg * float(t[i])
            else:
                u = max(0.0, min(1.0, (pair[0] - p0).dot(seg) / seg.length_squared))
                point = p0 + seg * u
            if self._visible(geo, region, rv3d, point, xray, cull):
                return point, 'EDGE'
        return None
