"""Lật / đối xứng shape key giữa hai bên trái - phải.

Hai việc:
- LẬT SANG BÊN KIA: key một bên (EYE_BlinkL, Pose_Smile.L...) -> key bên kia,
  tên tự đổi L <-> R. Tạo mới hoặc ghi đè key có sẵn.
- ĐỐI XỨNG TRONG KEY: chép nửa này sang nửa kia ngay trong một key, cho key
  làm tay hai bên mà mới nắn một bên.

Mặt phẳng đối xứng lấy theo RIG chứ không theo object: mesh Kid xoay -90° X,
scale 0.01, nên trục X object không chắc là trục trái-phải. Trong không gian
armature thì trục X luôn là trái-phải, tâm đặt ở bone Head.

Cặp vertex đối xứng tìm bằng KDTree trên Basis. Mesh không đối xứng tuyệt đối
thì vẫn lấy vertex gần nhất, nhưng đếm số cặp lệch quá ngưỡng để báo ra.
"""

import re

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy.types import Operator
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree
from mathutils.interpolate import poly_3d_calc
from mathutils.kdtree import KDTree

from . import face, facerig, posekey

PAIR_TOL = 1e-3     # cặp lệch quá ngần này lần kích thước mesh thì coi là lệch
ASYM_WARN = 0.05    # quá ngần này phần vertex lệch thì cảnh báo
ASYM_BASIS = 0.006  # Basis hai bên lệch quá ngần này (m) ở vùng key thì cảnh báo

_SIDE = re.compile(r'(Left|Right|left|right)'
                   r'|(?<=[._\- ])([LRlr])(?=$|[._\- 0-9])'
                   r'|(?<=[a-z0-9])([LR])(?=$|\.\d+$)')
_SWAP = {'Left': 'Right', 'Right': 'Left', 'left': 'right', 'right': 'left',
         'L': 'R', 'R': 'L', 'l': 'r', 'r': 'l'}


def swap_side(name):
    """Đổi dấu bên CUỐI CÙNG trong tên. Không có dấu bên thì None."""
    if name.startswith('VIS_'):
        return None     # VIS_L là âm "L", không phải bên trái
    found = list(_SIDE.finditer(name))
    if not found:
        return None
    m = found[-1]
    return name[:m.start()] + _SWAP[m.group(0)] + name[m.end():]


def mirror_name(name):
    return swap_side(name) or name + "_Mirror"


def rig_centre(arm):
    """(tâm x, dấu bên L) trong không gian armature."""
    head = posekey.head_bone(arm)
    cx = head.head_local.x if head is not None else 0.0
    xs = [b.head_local.x - cx for b in arm.data.bones
          if b.name.endswith(('.L', '_L', '.l', '_l'))]
    sign = 1.0 if not xs or sum(xs) >= 0 else -1.0
    return cx, sign


def topo_twins(obj, near, dists, tol, pts, cx):
    """[vertex đối xứng hoặc None] theo CẤU TRÚC LƯỚI.

    Mồi: cặp trùng chỗ (lệch < tol) và hai chiều. Lan: vertex chưa có cặp mà
    có hàng xóm đã có cặp -> cặp của nó là hàng xóm chung của các cặp kia
    (bỏ phiếu), hoà thì lấy cái gần điểm gương. Cùng ý với Topology Mirror của
    Blender: vertex bị nắn lệch bao xa cũng không sao, miễn lưới hai bên cùng
    cách nối. Đo trên Adult: 124 vertex quanh mắt không có cặp trùng chỗ.
    """
    n = len(pts)
    adj = [[] for _i in range(n)]
    for e in obj.data.edges:
        a, b = e.vertices
        adj[a].append(b)
        adj[b].append(a)
    twin = [None] * n
    for i in range(n):
        j = near[i]
        if dists[i] <= tol and near[j] == i and dists[j] <= tol:
            twin[i] = j
    for _round in range(64):
        changed = False
        for i in range(n):
            if twin[i] is not None:
                continue
            votes = {}
            for u in adj[i]:
                t = twin[u]
                if t is None:
                    continue
                for c in adj[t]:
                    # c == i: vertex nằm trên đường giữa, cặp là chính nó
                    if twin[c] is None:
                        votes[c] = votes.get(c, 0) + 1
            if not votes:
                continue
            best = max(votes.values())
            if best < 2 and sum(1 for u in adj[i] if twin[u] is not None) > 1:
                continue
            q = Vector((2 * cx - pts[i].x, pts[i].y, pts[i].z))
            c = min((c for c, v in votes.items() if v == best), key=lambda c: (pts[c] - q).length)
            twin[i] = c
            twin[c] = i
            changed = True
        if not changed:
            break
    return twin


class Mirror:
    """Bản đồ đối xứng của một mesh: vertex i lấy độ dời từ `src[i]` =
    [(vertex, trọng số)] bên kia, cùng phép lật.

    Bản đầu ghép vertex i với VERTEX gần điểm gương nhất. Lưới đối xứng chuẩn
    (Kid) thì đúng; lưới bị nắn lệch thì sai: quanh mắt Adult 108 vertex không có
    vertex đối xứng trùng chỗ, lệch tới 17.6 mm -- ghép nhầm sang hàng mí khác,
    lật EYE_BlinkL sang R là mí phải rách thành mảng. Nội suy bề mặt tại điểm
    gương cũng không cứu được (mí là mấy lớp da sát nhau, điểm gần nhất rơi
    nhầm lớp). Giờ ghép theo lưới (`topo_twins`); chỉ vertex không lần ra cặp
    mới nội suy bề mặt.
    """

    def __init__(self, obj, arm):
        basis = obj.data.shape_keys.key_blocks['Basis']
        M = arm.matrix_world.inverted() @ obj.matrix_world
        cx, self.sign = rig_centre(arm)
        pts = [M @ d.co for d in basis.data]
        kd = KDTree(len(pts))
        for i, p in enumerate(pts):
            kd.insert(p, i)
        kd.balance()
        obj.data.calc_loop_triangles()
        tris = [tuple(t.vertices) for t in obj.data.loop_triangles]
        bvh = BVHTree.FromPolygons(pts, tris) if tris else None
        lo = Vector(tuple(min(p[k] for p in pts) for k in range(3)))
        hi = Vector(tuple(max(p[k] for p in pts) for k in range(3)))
        self.tol = (hi - lo).length * PAIR_TOL
        n = len(pts)
        near, dists = [], []
        for p in pts:
            _co, j, dist = kd.find(Vector((2 * cx - p.x, p.y, p.z)))
            near.append(j)
            dists.append(dist)
        twin = topo_twins(obj, near, dists, self.tol, pts, cx)
        self.match, self.src, self.off = [], [], 0
        for i, p in enumerate(pts):
            j = twin[i]
            if j is not None:
                self.match.append(j)
                self.src.append(((j, 1.0),))
                continue
            # không lần ra cặp theo lưới: nội suy bề mặt tại điểm gương
            self.off += 1
            q = Vector((2 * cx - p.x, p.y, p.z))
            self.match.append(near[i])
            hit = bvh.find_nearest(q) if bvh is not None else None
            if hit is None or hit[2] is None:
                self.src.append(((near[i], 1.0),))
            else:
                tri = tris[hit[2]]
                self.src.append(tuple(zip(tri, poly_3d_calc([pts[k] for k in tri], hit[0]))))
        # bên của vertex: >0 là bên L, <0 là bên R, 0 là đường giữa
        self.side = [(p.x - cx) * self.sign for p in pts]
        R = M.to_3x3()
        self.flip = R.inverted() @ Matrix.Diagonal((-1.0, 1.0, 1.0)) @ R
        self.n = len(pts)
        self.M, self.Mi, self.cx = M, M.inverted(), cx
        self.basis = [d.co.copy() for d in basis.data]
        self.pts = pts

    def asym(self, delta, thresh=1e-4):
        """Lệch lớn nhất (đơn vị rig) giữa Basis hai bên, chỉ ở vertex key làm động."""
        worst = 0.0
        for j in range(self.n):
            if delta[j].length <= thresh:
                continue
            p = self.pts[j]
            q = Vector()
            for k, w in self.src[j]:
                q += self.pts[k] * w
            worst = max(worst, (q - Vector((2 * self.cx - p.x, p.y, p.z))).length)
        return worst

    def flipped_shape(self, delta):
        """Như `flipped` nhưng lật HÌNH khi bật key chứ không lật độ dời: vertex
        bên này về đúng ảnh gương của điểm tương ứng bên kia (Basis + key).
        Basis hai bên lệch nhau (Adult: sửa key mà lỡ sửa vào Basis, 126 vertex
        quanh mắt trái dời tới 17.6 mm) thì lật độ dời ra hình khác hẳn; lật hình
        thì bật key bên kia trông y hệt.

        Chỉ lật hình ở BÊN ĐÍCH. Bên nguồn và đường giữa vẫn lật độ dời: key L
        của Adult làm động cả 23 vertex bên phải (tới 8 mm); lật hình chúng là
        kéo mắt trái về hình nghỉ của mắt phải -- bật key R thì mắt TRÁI rách."""
        out = []
        cx = self.cx
        # bên nguồn = bên mang phần lớn độ dời
        mass = sum((self.pts[j].x - cx) * delta[j].length for j in range(self.n))
        src_side = 1.0 if mass >= 0 else -1.0
        F = self.flip
        for j in range(self.n):
            moved = any(delta[k].length > 1e-7 for k, _w in self.src[j])
            if not moved:
                out.append(Vector())
                continue
            if (self.pts[j].x - cx) * src_side > -self.tol:
                out.append(F @ self._at(delta, j))
                continue
            p = Vector()
            for k, w in self.src[j]:
                p += (self.M @ (self.basis[k] + delta[k])) * w
            q = Vector((2 * cx - p.x, p.y, p.z))
            out.append(self.Mi @ q - self.basis[j])
        return out

    def _at(self, delta, j):
        """Độ dời tại điểm gương của vertex j (chưa lật)."""
        out = Vector()
        for k, w in self.src[j]:
            out += delta[k] * w
        return out

    def flipped(self, delta):
        """Độ dời của key lật gương sang bên kia."""
        F = self.flip
        return [F @ self._at(delta, j) for j in range(self.n)]

    def symmetrized(self, delta, keep='L'):
        """Giữ nửa `keep`, chép gương sang nửa kia; đường giữa bỏ phần dời ngang."""
        F, t = self.flip, self.tol
        s = 1.0 if keep == 'L' else -1.0
        out = []
        for j in range(self.n):
            x = self.side[j] * s
            if x > t:
                out.append(delta[j].copy())
            elif x < -t:
                out.append(F @ self._at(delta, j))
            else:
                out.append((delta[j] + F @ delta[j]) * 0.5)
        return out


def key_delta(obj, name):
    kbs = obj.data.shape_keys.key_blocks
    basis, kb = kbs['Basis'], kbs[name]
    return [kb.data[i].co - basis.data[i].co for i in range(len(basis.data))]


def mirror_key(arm, mesh, src, dst, action='FLIP', keep='L', shape=True):
    """Lật / đối xứng `src` của mesh mặt và mọi mesh phụ có key cùng tên.
    `shape`: lật theo hình khi bật key (xem Mirror.flipped_shape), không thì
    lật độ dời.

    Trả về (key block trên mesh mặt, [mesh phụ đã ghi], số vertex lệch cặp,
    lệch Basis lớn nhất ở vùng key làm động -- đơn vị armature).
    """
    out_kb, others, off, asym = None, [], 0, 0.0
    srckey = mesh.data.shape_keys
    for o in facerig.targets_for(arm, mesh):
        key = o.data.shape_keys
        if key is None or src not in key.key_blocks:
            continue
        mr = Mirror(o, arm)
        d0 = key_delta(o, src)
        if action == 'FLIP':
            d = mr.flipped_shape(d0) if shape else mr.flipped(d0)
        else:
            d = mr.symmetrized(d0, keep)
        kb, new = posekey.write_key(o, dst, d, create=True)
        if o is mesh:
            out_kb, off, asym = kb, mr.off, mr.asym(d0)
            continue
        others.append(o.name)
        if new:
            face.add_driver(kb, srckey, dst)
    return out_kb, others, off, asym


def _source_changed(self, context):
    dst = mirror_name(self.source)
    self.key_name = dst
    _arm, mesh = posekey.rig_and_mesh(context)
    if mesh.data.shape_keys and dst in mesh.data.shape_keys.key_blocks:
        self.dest = 'OVERWRITE'
        self.target = dst
    else:
        self.dest = 'NEW'


class FACESHAPES_OT_mirror_key(Operator):
    bl_idname = "face_shapes.mirror_key"
    bl_label = "Đối xứng shape key L ↔ R"
    bl_description = ("Lật một shape key sang bên kia (tên tự đổi L/R), hoặc "
                      "chép nửa này sang nửa kia ngay trong key")
    bl_options = {'REGISTER', 'UNDO'}

    source: EnumProperty(name="Key nguồn", items=posekey.key_items,
                         update=_source_changed)
    action: EnumProperty(
        name="Việc",
        items=(('FLIP', "Lật sang bên kia",
                "Tạo / ghi đè key bên kia: SmileL -> SmileR"),
               ('SYMM', "Đối xứng trong key",
                "Chép nửa này sang nửa kia ngay trong key nguồn")),
        default='FLIP')
    dest: EnumProperty(
        name="Lưu vào",
        items=(('NEW', "Tạo mới", "Tạo shape key mới"),
               ('OVERWRITE', "Ghi đè", "Ghi đè một shape key có sẵn")),
        default='NEW')
    key_name: StringProperty(name="Tên")
    target: EnumProperty(name="Shape key", items=posekey.key_items)
    keep: EnumProperty(
        name="Giữ bên",
        items=(('L', "Trái → Phải", "Lấy nửa bên L làm chuẩn"),
               ('R', "Phải → Trái", "Lấy nửa bên R làm chuẩn")),
        default='L')
    shape: BoolProperty(
        name="Lật theo hình (khớp cả khi Basis lệch)", default=True,
        description="Bật: bật key bên kia trông đúng ảnh gương của key nguồn, kể "
                    "cả khi Basis hai bên không đối xứng. Tắt: chỉ lật độ dời -- "
                    "Basis lệch thì hai bên ra hình khác nhau")

    @classmethod
    def poll(cls, context):
        arm, mesh = posekey.rig_and_mesh(context)
        return (arm is not None and mesh is not None and mesh.data.shape_keys is not None
                and len(mesh.data.shape_keys.key_blocks) > 1)

    def invoke(self, context, event):
        _arm, mesh = posekey.rig_and_mesh(context)
        act = mesh.active_shape_key
        if act is not None and act.name != 'Basis':
            self.source = act.name      # gọi luôn _source_changed
        else:
            _source_changed(self, context)
        return context.window_manager.invoke_props_dialog(self, width=340)

    def draw(self, context):
        L = self.layout
        _arm, mesh = posekey.rig_and_mesh(context)
        L.label(text="Mesh: %s" % mesh.name, icon='MESH_DATA')
        L.prop(self, "source")
        L.row().prop(self, "action", expand=True)
        if self.action == 'FLIP':
            L.row().prop(self, "dest", expand=True)
            if self.dest == 'NEW':
                L.prop(self, "key_name")
            else:
                L.prop(self, "target")
            L.prop(self, "shape")
        else:
            L.row().prop(self, "keep", expand=True)

    def execute(self, context):
        arm, mesh = posekey.rig_and_mesh(context)
        key = mesh.data.shape_keys if mesh is not None else None
        if arm is None or key is None:
            self.report({'ERROR'}, "Không tìm thấy rig hoặc shape key")
            return {'CANCELLED'}
        src = self.source
        if src not in key.key_blocks or src == 'Basis':
            self.report({'ERROR'}, "Chọn key nguồn")
            return {'CANCELLED'}
        if self.action == 'SYMM':
            dst = src
        elif self.dest == 'NEW':
            dst = self.key_name.strip()
            if not dst or dst == 'Basis':
                self.report({'ERROR'}, "Đặt tên cho shape key mới")
                return {'CANCELLED'}
            if dst in key.key_blocks:
                self.report({'ERROR'}, "Đã có shape key '%s' -- đổi tên hoặc chọn Ghi đè" % dst)
                return {'CANCELLED'}
        else:
            dst = self.target
            if dst not in key.key_blocks or dst == 'Basis':
                self.report({'ERROR'}, "Chọn shape key cần ghi đè")
                return {'CANCELLED'}

        kb, others, off, asym = mirror_key(arm, mesh, src, dst, self.action, self.keep,
                                           self.shape)
        mesh.active_shape_key_index = list(key.key_blocks).index(kb)
        if self.action == 'SYMM':
            msg = "Đã đối xứng '%s' (%s)" % (src, "L → R" if self.keep == 'L' else "R → L")
        else:
            msg = "'%s' → '%s'" % (src, dst)
        if others:
            msg += " | cả %s" % ", ".join(others)
        level = {'INFO'}
        if off > len(kb.data) * ASYM_WARN:
            level = {'WARNING'}
            msg += " | %d vertex không có cặp đối xứng khớp -- mesh lệch hai bên" % off
        # Basis hai bên lệch ở đúng vùng key làm động: thường là lỡ sửa vào
        # Basis lúc sửa key (Edit Mode mà key đang chọn là Basis).
        scale = max(arm.matrix_world.to_scale())
        if asym * scale > ASYM_BASIS:
            level = {'WARNING'}
            msg += (" | Basis hai bên lệch tới %.0f mm ở vùng key này -- có thể đã lỡ "
                    "sửa vào Basis%s" % (asym * scale * 1000,
                                         "; đã lật theo hình" if self.shape and self.action == 'FLIP' else ""))
        if dst != src and face.is_own(key, kb):
            level = {'WARNING'}
            msg += " | key của addon: bấm Dựng lại sẽ thay lại nó"
        self.report(level, msg)
        return {'FINISHED'}


CLASSES = (FACESHAPES_OT_mirror_key,)
