# -*- coding: utf-8 -*-
"""FaceShapes - dựng bộ shape key biểu cảm & hội thoại từ face rig.

Nguyên tắc: KHÔNG nhét cứng con số. Mọi biên độ được suy ra từ kích thước đo
được trên chính rig (bề rộng miệng, tầm mí, sải mày), và ba hằng số khó -- đường
gặp mí, mức bù khóe miệng, trần hạ hàm -- được HIỆU CHỈNH BẰNG ĐO ĐẠC trên mesh
chứ không bằng công thức hình học. Lý do: trên rig STRETCH_TO, dự đoán hình học
sai lệch tới hơn hai lần so với giá trị thực tế tối ưu.

Cách làm: pose bone điều khiển khuôn mặt rồi nướng HIỆU giữa hai trạng thái
evaluated thành shape key. Bắt buộc lấy hiệu -- xem ghi chú ở hàm bake().

Panel nằm ở: View3D > sidebar (phím N) > tab "FaceShapes".
"""

import math
import re

import bpy
from bpy.props import (BoolProperty, FloatProperty, IntProperty, PointerProperty,
                       StringProperty)
from bpy.types import Operator, Panel, PropertyGroup
from mathutils import Euler, Matrix, Vector
from mathutils.bvhtree import BVHTree

from . import facerig, prefs, widgets

bl_info = {
    "name": "FaceShapes - Bộ shape key biểu cảm & hội thoại",
    "author": "Chú Pen Tẩm Hành",
    "version": (1, 13, 1),
    "blender": (4, 4, 0),
    "location": "View3D > Sidebar (N) > FaceShapes",
    "description": "Dựng bộ shape key modular (viseme lipsync, biểu cảm miệng, "
                   "mắt, mày, mũi) từ face rig HOẶC từ vertex group khoanh vùng. "
                   "Chạy được cả khuôn mặt thú: mõm dài há bằng bản lề hàm, mắt "
                   "xiên khép theo trục riêng của chính con mắt. Tự hiệu chỉnh "
                   "biên độ theo hình học, có slider cường điệu, kèm driver cho "
                   "răng và nhãn cầu và nút kiểm định",
    "category": "Rigging",
}


# ============================================================ nhận diện bone

# Rig họ này đặt tên bone điều khiển theo mẫu cố định. Tên dùng để TÌM bone,
# còn mọi con số thì đo, không đoán.
PAT = {
    'jaw':        'Jaw_Base',
    'lip_up_cor': 'UpperLip_Ctrl.%s',          # khóe miệng trên
    'lip_up_mid': 'UpperLip_Ctrl.%s.002',
    'lip_up_cen': 'UpperLip_Ctrl.Center',
    'lip_lo_cor': 'LowerLip_Ctrl.%s.003',      # khóe miệng dưới
    'lip_lo_mid': 'LowerLip_Ctrl.%s.001',
    'lip_lo_cen': 'LowerLip_Ctrl.Center',
    'lid_up':     ['UpperEyeLids_Ctrl.%s', 'UpperEyeLids_Ctrl.%s.001',
                   'UpperEyeLids_Ctrl.%s.002'],
    'lid_lo':     ['LowerEyeLids_Ctrl.%s', 'LowerEyeLids_Ctrl.%s.001'],
    'brow':       ['EyeBrow_Ctrl.%s', 'EyeBrow_Ctrl.%s.001', 'EyeBrow_Ctrl.%s.002',
                   'EyeBrow_Ctrl.%s.003', 'EyeBrow_Ctrl.%s.004'],
    'vg_lip_lo':  'LowerLips.%s',              # nhóm vertex khóe môi dưới
    'vg_lip_up':  'UpperLips.%s',
}


def bones_for(arm, key, side=None):
    """Trả về list pose bone khớp mẫu, bỏ qua bone không tồn tại."""
    pats = PAT[key]
    if isinstance(pats, str):
        pats = [pats]
    out = []
    for p in pats:
        name = p % side if '%s' in p else p
        pb = arm.pose.bones.get(name)
        if pb:
            out.append(pb)
    return out


def missing_bones(arm):
    """Danh sách bone bắt buộc mà rig không có -> dùng để báo rig không hợp."""
    need = []
    if not arm.pose.bones.get(PAT['jaw']):
        need.append(PAT['jaw'])
    for side in ('L', 'R'):
        for k in ('lip_up_cor', 'lip_lo_cor', 'lip_up_mid', 'lip_lo_mid'):
            n = PAT[k] % side
            if not arm.pose.bones.get(n):
                need.append(n)
        for k in ('lid_up', 'lid_lo', 'brow'):
            if not bones_for(arm, k, side):
                need.append(PAT[k][0] % side)
    for k in ('lip_up_cen', 'lip_lo_cen'):
        if not arm.pose.bones.get(PAT[k]):
            need.append(PAT[k])
    return need


def find_face_mesh(context, arm=None):
    """Tìm mesh khuôn mặt ĐỘC LẬP với rig.

    Không được đi qua armature: chế độ vùng chạy với mesh không có face rig, mà
    nhiều nhân vật chỉ có đúng một bone cho cả cái đầu. Ràng buộc cũ khiến addon
    không tìm nổi mesh trên những file như vậy.
    """
    st = context.scene.face_shapes
    if st.face and st.face.type == 'MESH':
        return st.face

    def biggest_rigged():
        best = None
        for o in context.scene.objects:
            if o.type != 'MESH':
                continue
            if not any(m.type == 'ARMATURE' and m.object == arm for m in o.modifiers):
                continue
            if best is None or len(o.data.vertices) > len(best.data.vertices):
                best = o
        return best

    # Có face rig đầy đủ thì tin rig trước, không tin object đang chọn: người dùng
    # rất dễ đang chọn cái áo, chọn nhầm áo làm mesh mặt là sai hẳn.
    if arm is not None and (not missing_bones(arm) or facerig.has_face_rig(arm)):
        b = biggest_rigged()
        if b is not None:
            return b
    ob = context.object
    if ob is not None and ob.type == 'MESH':
        return ob
    if arm is not None:
        b = biggest_rigged()
        if b is not None:
            return b
    # mesh hiện lớn nhất; mesh dùng làm hình bone thường bị ẩn nên tự loại
    vis = [o for o in context.scene.objects
           if o.type == 'MESH' and o.visible_get() and len(o.data.vertices) > 3]
    return max(vis, key=lambda o: len(o.data.vertices)) if vis else None


def outside_view_layer(context, *objects):
    """[(ten object, ten collection)] cua nhung object KHONG co trong view layer.

    Object nam trong collection bi exclude thi:
      - `view_layer.objects.active = obj` nem RuntimeError,
      - `evaluated_get()` tra ve ma tran CU ma khong bao gi.
    Cai dau lam operator vo ngay giua chung; cai sau con te hon vi no im lang
    va moi phep do ra so rac. Nen chan tu dau, va noi ro phai bat collection nao.
    """
    out = []
    for obj in objects:
        if obj is None or obj.name in context.view_layer.objects:
            continue
        homes = [c.name for c in obj.users_collection] or ["(khong collection nao)"]
        out.append((obj.name, ", ".join(homes)))
    return out


def report_hidden(operator, context, *objects):
    """Bao loi neu co object nam ngoai view layer. True = phai dung lai."""
    hidden = outside_view_layer(context, *objects)
    if not hidden:
        return False
    operator.report({'ERROR'}, "%s đang nằm ngoài view layer — bật collection "
                               "của nó lên rồi thử lại (%s)"
                    % (", ".join(n for n, _c in hidden),
                       "; ".join("%s o %s" % (n, c) for n, c in hidden)))
    return True


def deformed_by(face, arm):
    """Mesh có THẬT SỰ bị armature này làm biến dạng không.

    mesh_is_bound() chỉ đo khoảng cách nên không phân biệt được hai bộ rig đứng
    chồng nhau. Cái này đi theo đúng đường truyền biến dạng: modifier armature,
    hoặc chuỗi parent.
    """
    if face is None or arm is None:
        return False
    for m in face.modifiers:
        if m.type == 'ARMATURE' and m.object is arm:
            return True
    parent = face.parent
    while parent is not None:
        if parent is arm:
            return True
        parent = parent.parent
    return False


def find_rig(context, face=None):
    """Armature phù hợp. Ưu tiên cái có đủ bone điều khiển khuôn mặt, nhưng vẫn
    trả về armature thường để panel báo được 'thiếu bao nhiêu bone'."""
    st = context.scene.face_shapes
    if st.rig and st.rig.type == 'ARMATURE':
        return st.rig
    full = [o for o in context.scene.objects
            if o.type == 'ARMATURE'
            and (not missing_bones(o) or facerig.has_face_rig(o))]
    if full:
        # Trong số các rig đủ bone, chọn cái THẬT SỰ nối với mesh này trước.
        # Ver3_work.blend có hai bộ rig đứng chồng nhau: `3.0_Rig` (làm mesh
        # `Male` biến dạng, không có bone mặt) và `Simplified_Male` (đủ bone mặt,
        # nằm trong collection đã exclude). Lấy nhầm sang cái thứ hai thì pose
        # bone xong mesh đứng im, và addon nướng ra ĐÚNG 0 shape key mà không báo
        # một câu nào.
        drives = [o for o in full if deformed_by(face, o)]
        pool = drives or full
        vis = [o for o in pool if o.visible_get()]
        return (vis or pool)[0]
    if face is not None:
        for m in face.modifiers:
            if m.type == 'ARMATURE' and m.object is not None:
                return m.object
    ob = context.object
    if ob is not None and ob.type == 'ARMATURE':
        return ob
    arms = [o for o in context.scene.objects if o.type == 'ARMATURE']
    return arms[0] if arms else None


def find_rig_and_mesh(context):
    # Tìm mesh TRƯỚC rồi mới tìm rig: find_rig() cần biết mesh mới ưu tiên được
    # rig nối với nó.
    face = find_face_mesh(context)
    arm = find_rig(context, face)
    if face is None:
        face = find_face_mesh(context, arm)
    return arm, face


def near_face(face, objs, margin=0.12):
    """Lọc bỏ object của NHÂN VẬT KHÁC trong cùng scene.

    followers_for() trả về mọi thứ bám theo rig, nhưng mesh mặt đang dựng có thể
    thuộc nhân vật khác hẳn. Đo được trên một file có hai nhân vật: dựng shape
    key cho con sói mà kiểm định lại báo nhãn cầu của con chó "lòi 5.69%" -- con
    số y hệt trước và sau khi nhắm, vì hai thứ chẳng liên quan gì nhau.

    Điều kiện: tâm object phải nằm trong hộp bao của mesh mặt, nới ra `margin`
    lần đường chéo hộp.
    """
    pts = [face.matrix_world @ v.co for v in face.data.vertices]
    if not pts:
        return list(objs)
    mn = Vector((min(p.x for p in pts), min(p.y for p in pts),
                 min(p.z for p in pts)))
    mx = Vector((max(p.x for p in pts), max(p.y for p in pts),
                 max(p.z for p in pts)))
    m = (mx - mn).length * margin
    out = []
    for o in objs:
        if o is face:
            continue
        c = o.matrix_world @ (sum((Vector(b) for b in o.bound_box),
                                  Vector((0, 0, 0))) / 8.0)
        if all(mn[k] - m <= c[k] <= mx[k] + m for k in range(3)):
            out.append(o)
    return out


def followers_for(arm, face):
    """Object phụ đi theo rig: răng, nhãn cầu.

    Nhận cả hai kiểu gắn: có armature modifier, HOẶC chỉ parent vào armature.
    Nhân vật trong cùng một file có thể dùng kiểu khác nhau. Object nào rốt cuộc
    không biến dạng thì bake() tự bỏ qua vì hiệu bằng 0, nên bắt rộng là an toàn.

    Cuối cùng lọc theo vị trí -- xem near_face(). Bắt rộng chỉ an toàn trong
    phạm vi MỘT nhân vật; file nhiều nhân vật thì phải loại răng/mắt của con
    khác ra, nếu không kiểm định sẽ báo nhầm.
    """
    teeth, eyes = [], []
    for o in bpy.data.objects:
        if o.type != 'MESH' or o is face:
            continue
        rigged = any(m.type == 'ARMATURE' and m.object == arm for m in o.modifiers)
        if not rigged and o.parent is not arm:
            continue
        n = o.name.lower()
        if 'teeth' in n or 'tooth' in n or 'rang' in n:
            teeth.append(o)
        elif 'eye' in n and 'lid' not in n and 'brow' not in n:
            eyes.append(o)
    if face is not None:
        teeth = near_face(face, teeth)
        eyes = near_face(face, eyes)
    return teeth, eyes


def eye_side(ob):
    n = ob.name.lower()
    if '_l' in n or '.l' in n:
        return 'L'
    if '_r' in n or '.r' in n:
        return 'R'
    return None


# ============================================================ pose & bake

class PoseScope:
    """Đưa toàn bộ rig về rest để bake, xong trả lại y nguyên.

    Bắt buộc: nếu còn bone nào đang được pose (thường là IK tay), tư thế đó sẽ bị
    nướng vào MỌI shape key.
    """

    def __init__(self, arm):
        self.arm = arm
        self.saved = {}

    def __enter__(self):
        for pb in self.arm.pose.bones:
            m = pb.matrix_basis
            if m != Matrix():
                self.saved[pb.name] = m.copy()
        self.reset()
        return self

    def __exit__(self, *exc):
        self.reset()
        for n, m in self.saved.items():
            self.arm.pose.bones[n].matrix_basis = m
        bpy.context.view_layer.update()
        return False

    def reset(self):
        for pb in self.arm.pose.bones:
            pb.matrix_basis = Matrix()
        bpy.context.view_layer.update()


def set_rot(pb, deg_xyz):
    """Xoay bone theo trục cục bộ, không đụng tới rotation_mode sẵn có."""
    e = Euler([math.radians(d) for d in deg_xyz], 'XYZ')
    if pb.rotation_mode == 'QUATERNION':
        pb.rotation_quaternion = e.to_quaternion()
    elif pb.rotation_mode == 'AXIS_ANGLE':
        q = e.to_quaternion()
        pb.rotation_axis_angle = [q.angle, *q.axis]
    else:
        pb.rotation_euler = e
    bpy.context.view_layer.update()


def move(pb, delta):
    """Dịch bone theo toạ độ WORLD.

    Dùng pb.matrix chứ không pb.location: bone điều khiển khuôn mặt có roll tuỳ ý
    nên trục cục bộ không dự đoán được, còn cách này cho sai số bằng 0.
    """
    m = pb.matrix.copy()
    m.translation = m.translation + Vector(delta)
    pb.matrix = m
    bpy.context.view_layer.update()


def apply_ops(arm, ops):
    for kind, name, val in ops:
        pb = arm.pose.bones.get(name)
        if pb is None:
            continue
        (set_rot if kind == 'rot' else move)(pb, val)


def eval_mesh(obj, dg=None):
    """Lưới ĐÃ TÍNH của một object. Trả về (lưới, object cần dọn hoặc None).

    `to_mesh()` dựng một lưới TẠM và bắt buộc phải `to_mesh_clear()` sau đó.
    Gọi cặp ấy TRONG MỘT VÒNG LẶP đã làm Blender chết mất tiến trình ở chính dự
    án này (ghi lại 2026-08-21, lúc đo lặp trên object evaluated). `eyeball_
    shields()` đang làm đúng thế: lặp qua từng nhãn cầu, và bản thân nó được gọi
    ba lần mỗi lượt dựng -- 12 chu kỳ tạo/xoá lưới tạm cho một lần bấm nút.

    Với object kiểu MESH thì `evaluated_get(dg).data` cho ĐÚNG lưới ấy và không
    cần dọn gì -- không có bản tạm nào để quên dọn, không có hai bản sống chồng
    lên nhau. Chỉ curve/text/metaball mới thật sự cần `to_mesh()`, và ở đó vẫn
    trả object về cho chỗ gọi dọn.
    """
    dg = dg or bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    if obj.type == 'MESH':
        return ev.data, None
    return ev.to_mesh(), ev


def eval_coords(obj):
    me, own = eval_mesh(obj)
    co = [v.co.copy() for v in me.vertices]
    if own is not None:
        own.to_mesh_clear()
    return co


def ensure_basis(obj):
    if obj.data.shape_keys is None:
        obj.shape_key_add(name='Basis', from_mix=False)
    return obj.data.shape_keys


def bake(obj, name, rest_co, thresh=2e-4):
    """shape_key = Basis + (evaluated_posed - evaluated_rest).

    BẮT BUỘC lấy hiệu, không được nướng thẳng kết quả evaluated. Rig kiểu này có
    STRETCH_TO / IK chạy ngay cả ở rest pose, nên mesh-sau-armature-tại-rest KHÁC
    mesh gốc. Nướng thẳng sẽ nhét một độ lệch cố định vào mọi shape key, lan ra
    toàn thân tới tận bàn chân. Lỗi này im lặng: render trông vẫn bình thường,
    chỉ lộ khi đo biên độ và vùng ảnh hưởng của từng key.
    """
    posed = eval_coords(obj)
    delta = [p - r for p, r in zip(posed, rest_co)]
    if max(d.length for d in delta) < thresh:
        return None
    ensure_basis(obj)
    basis = obj.data.shape_keys.key_blocks['Basis']
    kb = own_key(obj, obj.shape_key_add(name=name, from_mix=False))
    kb.value = 0.0
    kb.slider_min, kb.slider_max = 0.0, 1.0
    for i, d in enumerate(delta):
        kb.data[i].co = basis.data[i].co + d
    return kb


def zero_keys(objs):
    for o in objs:
        if o.data.shape_keys:
            for kb in o.data.shape_keys.key_blocks:
                kb.value = 0.0
    bpy.context.view_layer.update()


# ============================================================ đo đạc rig

def measure(arm, face):
    """Đo kích thước rig -> mọi biên độ về sau tính theo tỉ lệ này, không theo mm.

    Nhờ vậy bộ shape key chạy đúng trên nhân vật khác tỉ lệ mà không phải chỉnh.
    """
    W = arm.matrix_world
    d = {}
    up = arm.pose.bones.get(PAT['lip_up_cor'] % 'L')
    lo = arm.pose.bones.get(PAT['lip_lo_cor'] % 'L')
    cen_u = arm.pose.bones[PAT['lip_up_cen']]
    cen_l = arm.pose.bones[PAT['lip_lo_cen']]
    d['mouth_w'] = abs((W @ up.head).x) * 2.0
    d['lip_gap'] = (W @ cen_u.head).z - (W @ cen_l.head).z
    d['mouth_z'] = (W @ cen_u.head).z

    ups = [(W @ pb.head).z for pb in bones_for(arm, 'lid_up', 'L')]
    los = [(W @ pb.head).z for pb in bones_for(arm, 'lid_lo', 'L')]
    # đường gặp mí = trung điểm giữa tầm mí trên và mí dưới
    d['meet'] = (sum(ups) / len(ups) + sum(los) / len(los)) * 0.5
    d['eye_open'] = sum(ups) / len(ups) - sum(los) / len(los)

    bro = [(W @ pb.head) for pb in bones_for(arm, 'brow', 'L')]
    d['brow_span'] = (bro[-1] - bro[0]).length if len(bro) > 1 else d['mouth_w']
    # Khoảng cách CENTROID mày <-> mí trên -> trần cho biên độ mày.
    # Không lấy hiệu min/max: hai vùng chồng nhau theo chiều dọc nên ra số âm và
    # trần thành 0, clamp không bao giờ ăn.
    d['brow_gap'] = (abs(sum(p.z for p in bro) / len(bro) - sum(ups) / len(ups))
                     if (bro and ups) else 0.0)

    jaw = arm.pose.bones[PAT['jaw']]
    d['jaw_z'] = (W @ jaw.head).z
    return d


# Không cạnh nào ở vùng khóe miệng được giãn quá ngần này lần so với lúc nghỉ.
# Đây là ngưỡng hình học thuần (tỉ số, không đơn vị) nên không phụ thuộc tỉ lệ
# nhân vật. Hiệu chuẩn bằng mắt trên rig thật: 2.27 là mức còn sạch, từ 2.9 trở
# lên khóe miệng bắt đầu nhô gai.
STRETCH_MAX = 2.3

# Mày được đi tối đa bao nhiêu lần khoảng cách centroid mày <-> mí trên.
# Hiệu chuẩn bằng mắt: 0.94x (mức 100%) trông tự nhiên, 1.9x là chỗ hai đầu mày
# bắt đầu giao nhau trên sống mũi thành gờ nhọn.
BROW_TRAVEL_MAX = 1.9


def corner_edges(arm, face, rest_co):
    """Các cạnh quanh khóe miệng, kèm chiều dài lúc nghỉ.

    Thước đo phải là ĐỘ GIÃN CẠNH, không phải độ hở khóe. Độ hở khóe chính là
    miệng đang há -- mọi shape mở miệng đều làm nó tăng, nên tối ưu theo nó là
    đi ghì một thứ vốn được phép hở, và cho ra mức bù sai. Cái gây xấu là mesh bị
    kéo giãn cục bộ thành gai nhọn, và độ giãn cạnh đo đúng cái đó.
    """
    Wf = face.matrix_world
    corner = arm.matrix_world @ arm.pose.bones[PAT['lip_lo_cor'] % 'L'].head
    W = abs(corner.x) * 2.0
    near = {v.index for v in face.data.vertices
            if ((Wf @ rest_co[v.index]) - corner).length < W * 0.30}
    if not near:
        return None, None
    raw = [(e.vertices[0], e.vertices[1]) for e in face.data.edges
           if e.vertices[0] in near or e.vertices[1] in near]
    ln = {e: (rest_co[e[0]] - rest_co[e[1]]).length for e in raw}
    if not ln:
        return None, None
    med = sorted(ln.values())[len(ln) // 2]
    # Loại cạnh suy biến: cạnh dài gần 0 làm tỉ số giãn nổ ra vô nghĩa (đo được
    # 14x trong khi phần còn lại của lưới chỉ 2.3x).
    edges = [e for e in raw if ln[e] >= med * 0.25]
    return edges, ln


def corner_stretch(face, edges, ln):
    co = eval_coords(face)
    return max((co[i] - co[j]).length / ln[(i, j)] for i, j in edges)


def mesh_is_bound(arm, face, rest_co):
    """Mesh có thật sự nằm ở chỗ rig không.

    Mesh chưa gắn vào rig vẫn có vertex group và vẫn chạy qua mọi phép đo, chỉ là
    ra số vô nghĩa. Kiểm tra rẻ: miệng của mesh phải nằm gần bone miệng.
    """
    cen = arm.matrix_world @ arm.pose.bones[PAT['lip_lo_cen']].head
    Wf = face.matrix_world
    near = min(((Wf @ c) - cen).length for c in rest_co)
    ref = abs((arm.matrix_world @ arm.pose.bones[PAT['lip_lo_cor'] % 'L'].head).x)
    return near < ref * 3.0, near


# ============================================================ công thức shape

def mouth_ops(arm, M, jaw=0.0, cen=0.0, mid=0.0, up_cen=0.0, up_mid=0.0,
              cor_z=0.0, cor_x=0.0, cor_y=0.0, ucor_z=None, anchor=0.0):
    """Mọi tham số tính theo TỈ LỆ bề rộng miệng (M['mouth_w']), trừ jaw là độ.

    anchor: mức nâng khóe miệng để bù cú tụt do xoay hàm (đơn vị: tỉ lệ / độ).
    """
    W = M['mouth_w']
    a = anchor * jaw
    ucor = cor_z if ucor_z is None else ucor_z
    ops = []
    if jaw:
        ops.append(('rot', PAT['jaw'], (-jaw, 0, 0)))
    ops.append(('loc', PAT['lip_lo_cen'], (0, 0, -cen * W)))
    ops.append(('loc', PAT['lip_up_cen'], (0, 0, up_cen * W)))
    for s in ('L', 'R'):
        sx = 1 if s == 'L' else -1
        ops += [
            ('loc', PAT['lip_lo_mid'] % s, (sx*cor_x*0.5*W, cor_y*0.5*W, -mid*W)),
            ('loc', PAT['lip_up_mid'] % s, (sx*cor_x*0.5*W, cor_y*0.5*W, up_mid*W)),
            ('loc', PAT['lip_lo_cor'] % s, (sx*cor_x*W, cor_y*W, (a + cor_z)*W)),
            ('loc', PAT['lip_up_cor'] % s, (sx*cor_x*W, cor_y*W, ucor*W)),
        ]
    return ops


def mouth_side_ops(M, side, cor_z=0.0, cor_x=0.0, cor_y=0.0, mid=0.0):
    W = M['mouth_w']
    sx = 1 if side == 'L' else -1
    return [
        ('loc', PAT['lip_lo_cor'] % side, (sx*cor_x*W, cor_y*W, cor_z*W)),
        ('loc', PAT['lip_up_cor'] % side, (sx*cor_x*W, cor_y*W, cor_z*W)),
        ('loc', PAT['lip_lo_mid'] % side, (sx*cor_x*0.45*W, cor_y*0.45*W,
                                           (cor_z*0.4 - mid)*W)),
        ('loc', PAT['lip_up_mid'] % side, (sx*cor_x*0.45*W, cor_y*0.45*W, cor_z*0.5*W)),
    ]


def mouth_lip_ops(M, side=None, up=0.0, lo=0.0, back=0.0):
    """Nhấc/hạ RIÊNG môi trên hoặc môi dưới, có thể chỉ một bên, kèm thụt ra sau.

    mouth_side_ops() không thay được: nó buộc cả bốn bone một bên đi theo cùng
    một cor_z, tức là môi trên và môi dưới luôn dính nhau. Nhếch môi trên hở
    răng, hay mím môi vào trong, đều đòi tách rời hai vành.

    Dương = đi LÊN (world +Z) cho cả hai vành; back dương = thụt vào trong.
    """
    W = M['mouth_w']
    sides = ('L', 'R') if side is None else (side,)
    # Bone giữa môi là bone CHUNG của hai bên. Làm một bên thì chỉ được lấy một
    # nửa, nếu không bật cả UpperUpL lẫn UpperUpR sẽ nhấc giữa môi gấp đôi.
    cen_k = 1.0 if side is None else 0.5
    ops = []
    for cen, mid, cor, amt in (
            ('lip_up_cen', 'lip_up_mid', 'lip_up_cor', up),
            ('lip_lo_cen', 'lip_lo_mid', 'lip_lo_cor', lo)):
        if not amt:
            continue
        ops.append(('loc', PAT[cen], (0, back * cen_k * W, amt * cen_k * W)))
        for s in sides:
            ops.append(('loc', PAT[mid] % s, (0, back * .80 * W, amt * .80 * W)))
            ops.append(('loc', PAT[cor] % s, (0, back * .30 * W, amt * .30 * W)))
    return ops


def mouth_fwd_ops(M, amt, cen=1.0, cor=0.45):
    """Đẩy cả vành môi ra trước, giữa môi đi xa nhất -> miệng thành hình chữ O.

    mouth_ops() chỉ đẩy được bone khoé và bone giữa-cạnh qua cor_y, không đụng
    tới hai bone chính giữa -- nên chu môi bằng nó ra cái miệng bị bóp ngang mà
    giữa môi vẫn phẳng lì.
    """
    W = M['mouth_w']
    ops = [('loc', PAT['lip_up_cen'], (0, -amt * cen * W, 0)),
           ('loc', PAT['lip_lo_cen'], (0, -amt * cen * W, 0))]
    for s in ('L', 'R'):
        for k in ('lip_up_mid', 'lip_lo_mid'):
            ops.append(('loc', PAT[k] % s, (0, -amt * 0.70 * W, 0)))
        for k in ('lip_up_cor', 'lip_lo_cor'):
            ops.append(('loc', PAT[k] % s, (0, -amt * cor * W, 0)))
    return ops


def mouth_shift_ops(M, amt):
    """Cả miệng trượt ngang. move() nhận toạ độ WORLD nên KHÔNG nhân dấu theo bên:
    nhân dấu là ra động tác banh rộng miệng, không phải lệch miệng."""
    W = M['mouth_w']
    ops = [('loc', PAT['lip_up_cen'], (amt * W, 0, 0)),
           ('loc', PAT['lip_lo_cen'], (amt * W, 0, 0))]
    for s in ('L', 'R'):
        for k in ('lip_up_mid', 'lip_lo_mid', 'lip_up_cor', 'lip_lo_cor'):
            ops.append(('loc', PAT[k] % s, (amt * W, 0, 0)))
    return ops


def lid_ops(arm, M, side, k=0.0, low_k=0.0):
    """k=1 nhắm kín, k âm = mở to. Đích là đường gặp mí ĐO ĐƯỢC, không phải số cố định.

    Nhắm kín phải kéo CẢ mí dưới lên: chỉ hạ mí trên thì nhãn cầu còn lòi ~5.6%
    diện tích (đo bằng ray cast). Kéo cả hai còn ~0.7%.
    KHÔNG đẩy mí ra trước: đo được là nó gần như không giảm lòi nhưng làm rách khe mí.
    """
    W = arm.matrix_world
    meet = M['meet']
    ops = []
    for pb in bones_for(arm, 'lid_up', side):
        ops.append(('loc', pb.name, (0, 0, (meet - (W @ pb.head).z) * k)))
    if low_k:
        for pb in bones_for(arm, 'lid_lo', side):
            ops.append(('loc', pb.name, (0, 0, (meet - (W @ pb.head).z) * low_k)))
    return ops


def brow_ops(arm, M, side, profile):
    """profile: 5 giá trị theo tỉ lệ sải mày, từ đầu mày (trong) ra đuôi mày."""
    S = M['brow_span']
    return [('loc', pb.name, (0, 0, v * S))
            for pb, v in zip(bones_for(arm, 'brow', side), profile)]


def build_recipes(arm, M, anchor, jaw_max, ex=1.0):
    """Toàn bộ bộ shape key. Miệng / mắt / mày tách rời -> cộng được tuỳ ý.

    ex: hệ số cường điệu. Nhân TRƯỚC khi kẹp trần hạ hàm, để clamp vẫn ăn --
    nếu không, cường điệu 200% sẽ đẩy hàm quá trần và làm rách khóe miệng.
    """
    def J(x):
        return min(x * ex, jaw_max)

    def m(**kw):
        jaw = kw.pop('jaw', 0.0)
        return mouth_ops(arm, M, anchor=anchor, jaw=jaw,
                         **{k: v * ex for k, v in kw.items()})

    R = {}
    # --- viseme cho lipsync (im lặng = tắt hết, không cần shape key riêng)
    R['VIS_AA']  = m(jaw=J(14), cen=.204, mid=.163, up_cen=.031, up_mid=.020)
    R['VIS_EE']  = m(jaw=J(4),  cen=.061, mid=.061, up_cen=.020, up_mid=.020,
                     cor_x=.092, cor_z=.020)
    R['VIS_IH']  = m(jaw=J(6),  cen=.092, mid=.082, up_cen=.010, up_mid=.010, cor_x=.051)
    R['VIS_OH']  = m(jaw=J(11), cen=.153, mid=.112, up_cen=.020, cor_x=-.092, cor_y=-.071)
    R['VIS_OU']  = m(jaw=J(4),  cen=.051, mid=.041, up_cen=.010, cor_x=-.143, cor_y=-.122)
    R['VIS_MBP'] = m(cen=-.010, mid=-.010, up_cen=-.010, up_mid=-.010, cor_x=.010)
    R['VIS_FV']  = m(jaw=J(3),  cen=-.031, mid=-.020, up_cen=.010, up_mid=.010,
                     cor_x=.020, cor_y=.020)
    R['VIS_TH']  = m(jaw=J(7),  cen=.092, mid=.071, up_cen=.020, up_mid=.010)
    R['VIS_L']   = m(jaw=J(9),  cen=.122, mid=.102, up_cen=.020, up_mid=.010)
    R['VIS_SS']  = m(jaw=J(2),  cen=.031, mid=.031, up_cen=.010, up_mid=.010,
                     cor_x=.041, cor_z=.010)
    R['VIS_RR']  = m(jaw=J(5),  cen=.071, mid=.061, up_cen=.010, cor_x=-.071, cor_y=-.051)
    # --- miệng biểu cảm
    for s in ('L', 'R'):
        R['MTH_Smile' + s] = mouth_side_ops(M, s, cor_z=.112*ex, cor_x=.071*ex,
                                            cor_y=.031*ex)
        R['MTH_Frown' + s] = mouth_side_ops(M, s, cor_z=-.092*ex, cor_x=.020*ex,
                                            cor_y=.031*ex)
    R['MTH_Sneer'] = m(up_cen=.061, up_mid=.061, cor_z=.031, ucor_z=.082)
    R['MTH_Press'] = m(cen=-.031, mid=-.031, up_cen=-.031, up_mid=-.031, cor_x=.031)
    R['MTH_Pucker'] = (m(cen=.020, up_cen=.010, cor_x=-.184, cor_y=-.092)
                       + mouth_fwd_ops(M, .102 * ex))
    R['MTH_Funnel'] = (m(jaw=J(6), cen=.092, mid=.061, up_cen=.031,
                         cor_x=-.133, cor_y=-.061)
                       + mouth_fwd_ops(M, .071 * ex, cen=0.80))
    R['MTH_RollUpper'] = mouth_lip_ops(M, up=-.041 * ex, back=.033 * ex)
    R['MTH_RollLower'] = mouth_lip_ops(M, lo=.041 * ex, back=.033 * ex)
    R['MTH_ChinUp'] = mouth_lip_ops(M, lo=.061 * ex)
    R['MTH_Left'] = mouth_shift_ops(M, .071 * ex)
    R['MTH_Right'] = mouth_shift_ops(M, -.071 * ex)
    for s in ('L', 'R'):
        R['MTH_Stretch' + s] = mouth_side_ops(M, s, cor_x=.133*ex, cor_y=.020*ex)
        R['MTH_Dimple' + s] = mouth_side_ops(M, s, cor_x=.041*ex, cor_z=.031*ex,
                                             cor_y=.071*ex)
        R['MTH_UpperUp' + s] = mouth_lip_ops(M, s, up=.071*ex)
        R['MTH_LowerDown' + s] = mouth_lip_ops(M, s, lo=-.071*ex)
    # Má và nhăn mũi KHÔNG dựng được ở chế độ rig: họ rig này không có bone má
    # cũng không có bone cánh mũi. Muốn CHK_* và NOS_* thì dùng chế độ vùng.
    # --- mắt
    for s in ('L', 'R'):
        R['EYE_Blink' + s]  = lid_ops(arm, M, s, k=scale_lid(1.0, ex),
                                      low_k=scale_lid(1.0, ex))
        R['EYE_Squint' + s] = lid_ops(arm, M, s, k=scale_lid(0.45, ex),
                                      low_k=scale_lid(0.45, ex))
        R['EYE_Wide' + s]   = lid_ops(arm, M, s, k=-0.35*ex, low_k=-0.30*ex)
    # --- mày
    brow_cap = M.get('brow_gap', 0.0) * BROW_TRAVEL_MAX
    def B(p):
        return cap_profile([v * ex for v in p], M['brow_span'], brow_cap)
    for s in ('L', 'R'):
        R['BRW_Up' + s]    = brow_ops(arm, M, s, B([.147, .147, .126, .105, .074]))
        R['BRW_Down' + s]  = brow_ops(arm, M, s, B([-.105, -.105, -.084, -.063, -.042]))
        R['BRW_Angry' + s] = brow_ops(arm, M, s, B([-.147, -.105, -.042, .021, .042]))
        R['BRW_Sad' + s]   = brow_ops(arm, M, s, B([.147, .105, .021, -.042, -.074]))
    return R


ORDER = ['VIS_', 'JAW_', 'MTH_', 'TNG_', 'NOS_', 'CHK_', 'EYE_', 'BRW_']


def sort_key(name):
    for i, p in enumerate(ORDER):
        if name.startswith(p):
            return (i, name)
    return (len(ORDER), name)


# ------------------------------------------------------- shape key của ai

# Bản trước dựng lại bộ shape key bằng `shape_key_clear()` -- xoá SẠCH, kể cả
# shape key người ta nắn tay từ trước. Đã mất trắng 10 key trên mesh `Mouth` của
# FruitNPCs vì chạy nhầm vào đó. Chặn bằng cách hỏi trước khi xoá thì vẫn bế
# tắc: muốn dựng bộ mới là buộc phải hy sinh bộ cũ.
#
# Nên ở đây định nghĩa QUYỀN SỞ HỮU rồi chỉ xoá phần của mình. Hai đường nhận:
#   1. Cờ ID property gắn lúc tạo -- đúng tuyệt đối, kể cả khi người dùng đổi tên.
#   2. Tên nằm trong đúng danh sách addon sinh ra -- cứu bộ dựng bằng bản cũ,
#      chưa có cờ.
# Không dùng "cứ tiền tố MTH_ là của addon": người ta hoàn toàn có thể tự đặt
# `MTH_Kiss`, và mất nó cũng đau như mất `Kiss`.

OWN_TAG = "srp_face"


def _own_names():
    """Mọi tên shape key addon có thể sinh ra. Dùng khi mesh chưa có bản kê khai."""
    n = ['VIS_AA', 'VIS_EE', 'VIS_IH', 'VIS_OH', 'VIS_OU', 'VIS_MBP', 'VIS_FV',
         'VIS_TH', 'VIS_L', 'VIS_SS', 'VIS_RR',
         'MTH_Sneer', 'MTH_Press', 'MTH_Pucker', 'MTH_Funnel',
         'MTH_RollUpper', 'MTH_RollLower', 'MTH_ChinUp', 'MTH_Left', 'MTH_Right']
    for s in ('L', 'R'):
        n += ['MTH_Smile' + s, 'MTH_Frown' + s, 'MTH_Stretch' + s,
              'MTH_Dimple' + s, 'MTH_UpperUp' + s, 'MTH_LowerDown' + s,
              'CHK_Puff' + s, 'CHK_Suck' + s, 'CHK_Squint' + s,
              'NOS_Flare' + s, 'NOS_Wrinkle' + s,
              'EYE_Blink' + s, 'EYE_Squint' + s, 'EYE_Wide' + s,
              'BRW_Up' + s, 'BRW_Down' + s, 'BRW_Angry' + s, 'BRW_Sad' + s]
    return frozenset(n + facerig.all_names())


OWN_NAMES = _own_names()


def own_list(key):
    """Bản kê khai: tên các shape key addon đã dựng trên mesh này. None = chưa có.

    Cờ nằm trên datablock `Key` chứ không trên từng key block: `ShapeKey` KHÔNG
    nhận ID property ("this type doesn't support IDProperties"), thử là dựng
    được nửa bộ rồi mới nổ.
    """
    if key is None:
        return None
    raw = key.get(OWN_TAG)
    return None if raw is None else set(raw)


def set_own_list(key, names):
    if key is not None:
        key[OWN_TAG] = sorted(names)


def is_own(key, kb):
    """kb có phải addon dựng ra không.

    Ưu tiên bản kê khai vì nó ghi đúng những gì addon đã dựng trên CHÍNH mesh
    này: một key tên `MTH_Kiss` người ta tự nắn vẫn an toàn kể cả sau này addon
    có thêm `MTH_Kiss` vào từ vựng. Không có bản kê khai (mesh dựng bằng bản cũ)
    thì đành đối chiếu tên.
    """
    if kb.name == 'Basis':
        return False
    own = own_list(key)
    return kb.name in own if own is not None else kb.name in OWN_NAMES


def own_key(obj, kb):
    """Ghi nhận shape key vừa tạo vào bản kê khai, rồi trả lại chính nó."""
    if kb is None:
        return kb
    key = obj.data.shape_keys
    names = own_list(key) or set()
    names.add(kb.name)
    set_own_list(key, names)
    return kb


def foreign_keys(objs):
    """[(object, shape key)] những key KHÔNG phải của addon."""
    out = []
    for obj in objs:
        key = getattr(getattr(obj, "data", None), "shape_keys", None)
        if key is None:
            continue
        for kb in key.key_blocks:
            if not is_own(key, kb) and kb.name != 'Basis':
                out.append((obj, kb))
    return out


def drop_driver(key, name):
    """Bỏ driver trỏ tới một key block sắp bị xoá -- không thì thành driver mồ côi."""
    anim = key.animation_data
    if anim is None:
        return
    path = 'key_blocks["%s"].value' % name
    for fcurve in list(anim.drivers):
        if fcurve.data_path == path:
            anim.drivers.remove(fcurve)


def clear_own(objs, wipe=False):
    """Xoá shape key CỦA ADDON, giữ nguyên key làm tay. wipe=True: xoá sạch.

    Giữ luôn cả Basis: `shape_key_clear()` xoá cả nó rồi `ensure_basis()` dựng
    lại từ `mesh.vertices`, mà hai thứ đó lệch nhau nếu người ta từng nắn Basis.
    """
    n = 0
    for obj in objs:
        key = getattr(getattr(obj, "data", None), "shape_keys", None)
        if key is None:
            continue
        doomed = [kb for kb in key.key_blocks
                  if kb.name != 'Basis' and (wipe or is_own(key, kb))]
        for kb in doomed:
            drop_driver(key, kb.name)
            obj.shape_key_remove(kb)
            n += 1
        if wipe:
            if obj.data.shape_keys is not None:
                obj.shape_key_clear()
        else:
            left = {kb.name for kb in key.key_blocks}
            set_own_list(key, (own_list(key) or set()) & left)
    return n


class KeyScope:
    """Tắt hết shape key trong lúc nướng, xong trả lại đúng như cũ.

    Bắt buộc từ lúc giữ lại key làm tay: `eval_coords()` trả về mesh ĐÃ cộng mọi
    shape key đang bật, nên một key làm tay để giá trị 0.6 sẽ bị nhét vào TẤT CẢ
    shape key mới. Cùng loại bẫy im lặng đã ghi ở bake() -- render trông vẫn
    thường, chỉ lộ khi đo.
    """

    def __init__(self, objs):
        self.objs = list(objs)
        self.saved = []

    def __enter__(self):
        for obj in self.objs:
            key = getattr(getattr(obj, "data", None), "shape_keys", None)
            if key is None:
                continue
            self.saved.append((obj, obj.show_only_shape_key,
                               [(kb.name, kb.value, kb.mute)
                                for kb in key.key_blocks]))
            obj.show_only_shape_key = False
            for kb in key.key_blocks:
                kb.value, kb.mute = 0.0, False
        bpy.context.view_layer.update()
        return self

    def __exit__(self, *exc):
        for obj, only, vals in self.saved:
            obj.show_only_shape_key = only
            key = getattr(getattr(obj, "data", None), "shape_keys", None)
            if key is None:
                continue
            for name, value, mute in vals:
                kb = key.key_blocks.get(name)
                if kb is not None:
                    kb.value, kb.mute = value, mute
        bpy.context.view_layer.update()
        return False


# ============================================================ hiệu chỉnh

def calibrate_meet(arm, face, M, eyes, side='L'):
    """Tìm đường gặp mí bằng cách tối thiểu hoá phần nhãn cầu lòi ra.

    Trung điểm hình học giữa tầm mí trên và mí dưới KHÔNG phải đáp án: đo trên
    rig thật, nó lệch khoảng 1/4 tầm mở mắt so với vị trí tốt nhất. Có nhãn cầu
    thì đo được, không có thì đành lấy trung điểm.
    """
    eye = next((e for e in eyes if eye_side(e) == side), None)
    if eye is None:
        return M['meet'], None
    span = M['eye_open']
    best_e, best_m = None, M['meet']
    for frac in (-0.40, -0.30, -0.20, -0.10, 0.0, 0.10, 0.20):
        cand = dict(M)
        cand['meet'] = M['meet'] + span * frac
        for pb in arm.pose.bones:
            pb.matrix_basis = Matrix()
        bpy.context.view_layer.update()
        apply_ops(arm, lid_ops(arm, cand, side, k=1.0, low_k=1.0))
        e = eyeball_exposure(eye, n=26)
        if best_e is None or e < best_e:
            best_e, best_m = e, cand['meet']
    return best_m, best_e


def stretch_at(arm, face, M, edges, ln, jaw, anchor):
    for pb in arm.pose.bones:
        pb.matrix_basis = Matrix()
    bpy.context.view_layer.update()
    apply_ops(arm, mouth_ops(arm, M, jaw=jaw, cen=.204, mid=.163, anchor=anchor))
    return corner_stretch(face, edges, ln)


def calibrate_anchor(arm, face, M, jaw_deg, edges, ln, lo=0.0, hi=0.03, steps=8):
    """Tìm mức nâng khóe miệng ít làm giãn lưới nhất, bằng chia ba trên số đo thật.

    Không dùng công thức hình học: trên rig này dự đoán hình học cho ra ~17mm
    trong khi giá trị thật tối ưu là ~8mm. Đo thắng đoán.
    """
    if not edges:
        return 0.0, None

    def f(a):
        return stretch_at(arm, face, M, edges, ln, jaw_deg, a)

    for _ in range(steps):
        m1 = lo + (hi - lo) / 3.0
        m2 = hi - (hi - lo) / 3.0
        if f(m1) <= f(m2):
            hi = m2
        else:
            lo = m1
    a = (lo + hi) / 2.0
    return a, f(a)


def calibrate(context, report=None):
    """Đo rig, hiệu chỉnh 3 hằng số khó, ghi vào settings."""
    st = context.scene.face_shapes
    arm, face = find_rig_and_mesh(context)
    if arm is None or face is None:
        return None, "Không tìm thấy armature hoặc mesh mặt"
    miss = missing_bones(arm)
    if miss:
        return None, "Rig thiếu bone điều khiển: " + ", ".join(miss[:5])
    st.rig, st.face = arm, face

    M = measure(arm, face)
    lines = ["Rig: %s | Mesh: %s (%d vertex)" % (arm.name, face.name,
                                                 len(face.data.vertices)),
             "Bề rộng miệng %.4f | khe môi %.4f | tầm mở mắt %.4f | sải mày %.4f"
             % (M['mouth_w'], M['lip_gap'], M['eye_open'], M['brow_span']),
             "Đường gặp mí (đo được): z = %.4f" % M['meet']]

    teeth, eyes = followers_for(arm, face)

    with PoseScope(arm) as scope:
        rest_co = eval_coords(face)
        bound, near = mesh_is_bound(arm, face, rest_co)
        if not bound:
            return None, ("Mesh '%s' không nằm ở vị trí rig '%s' (điểm gần miệng "
                          "nhất cách %.2f) -- mesh chưa được gắn vào rig này, "
                          "hoặc chọn nhầm cặp rig/mesh" % (face.name, arm.name, near))
        edges, ln = corner_edges(arm, face, rest_co)
        if not edges:
            lines.append("CẢNH BÁO: không khoanh được vùng khóe miệng -- bỏ qua bù "
                         "khóe, hạ hàm bị chặn ở mức dè dặt")

        # 1. đường gặp mí -- đo bằng ray cast nếu có nhãn cầu
        meet, expo = calibrate_meet(arm, face, M, eyes)
        M['meet'] = meet
        lines.append("Đường gặp mí: z = %.4f%s"
                     % (meet, "" if expo is None
                        else "  (nhãn cầu còn lòi %.2f%%)" % expo))

        # 2. mức bù khóe miệng, hiệu chỉnh ở góc hàm tham chiếu
        anchor, best = calibrate_anchor(arm, face, M, 14.0, edges, ln)
        lines.append("Bù khóe miệng: %.5f / độ  (giãn lưới còn %.2fx)"
                     % (anchor, best if best is not None else -1))

        # 3. trần hạ hàm: góc lớn nhất mà lưới khóe chưa giãn quá ngưỡng
        jaw_max = 8.0
        if edges:
            for ang in (6, 8, 10, 12, 14, 16, 18, 20, 24, 28):
                s = stretch_at(arm, face, M, edges, ln, ang, anchor)
                if s <= STRETCH_MAX:
                    jaw_max = float(ang)
                else:
                    break
            lines.append("Trần hạ hàm: %.0f độ  (ngưỡng giãn %.1fx)"
                         % (jaw_max, STRETCH_MAX))
        scope.reset()

    st.anchor = anchor
    st.jaw_max = jaw_max
    st.meet = M['meet']
    st.calibrated = True
    if report:
        for ln in lines:
            report(ln)
    return (arm, face, M), "\n".join(lines)


# ============================================================ nhãn cầu

def eyeball_exposure(eye, n=40):
    """% tia bắn từ trước mặt chạm nhãn cầu trước khi chạm da. Thước đo clip."""
    dg = bpy.context.evaluated_depsgraph_get()
    me, own = eval_mesh(eye, dg)
    mw = eye.evaluated_get(dg).matrix_world
    lo = Vector((1e9,)*3); hi = Vector((-1e9,)*3)
    for v in me.vertices:
        w = mw @ v.co
        for i in range(3):
            lo[i] = min(lo[i], w[i]); hi[i] = max(hi[i], w[i])
    if own is not None:
        own.to_mesh_clear()
    pad = (hi.x - lo.x) * 0.06
    depth = lo.y - 0.5
    hit = 0
    for i in range(n):
        for j in range(n):
            x = lo.x - pad + (hi.x - lo.x + 2*pad) * i / (n - 1)
            z = lo.z - pad + (hi.z - lo.z + 2*pad) * j / (n - 1)
            ok, _, _, _, obj, _ = bpy.context.scene.ray_cast(
                dg, Vector((x, depth, z)), Vector((0, 1, 0)))
            if ok and obj is eye:
                hit += 1
    return 100.0 * hit / (n * n)


def make_eyeball_key(eye, name, shrink, back):
    """Nhãn cầu co lại + thụt ra sau khi nhắm -> hết đâm qua khe mí."""
    ensure_basis(eye)
    basis = eye.data.shape_keys.key_blocks['Basis']
    n = len(basis.data)
    ctr = Vector((0, 0, 0))
    for i in range(n):
        ctr += basis.data[i].co
    ctr /= n
    off = eye.matrix_world.inverted().to_3x3() @ Vector((0, back, 0))
    kbs = eye.data.shape_keys.key_blocks
    kb = own_key(eye, kbs[name] if name in kbs
                 else eye.shape_key_add(name=name, from_mix=False))
    kb.value = 0.0
    kb.slider_min, kb.slider_max = 0.0, 1.0
    for i in range(n):
        kb.data[i].co = ctr + (basis.data[i].co - ctr) * shrink + off
    return kb


def add_driver(kb, key_id, src_name, threshold=0.0):
    """Cho shape key bám theo shape key trên mesh mặt."""
    fc = kb.driver_add('value')
    drv = fc.driver
    if threshold > 0.0:
        # Có ngưỡng: chưa thụt gì khi mí còn hé. Tuyến tính là lộ ngay -- ở
        # blink 0.5 mắt còn mở mà nhãn cầu đã co một nửa.
        drv.type = 'SCRIPTED'
        drv.expression = 'max(0.0, (v - %g) / %g)' % (threshold, 1.0 - threshold)
    else:
        drv.type = 'AVERAGE'
    var = drv.variables.new()
    var.name = 'v'
    var.type = 'SINGLE_PROP'
    var.targets[0].id_type = 'KEY'
    var.targets[0].id = key_id
    var.targets[0].data_path = 'key_blocks["%s"].value' % src_name
    return fc


# ============================================================ chế độ VÙNG
#
# Đường dựng thứ hai: không cần rig, chỉ cần vertex group khoanh vùng.
# Nắn thẳng trên MESH GỐC nên tránh sạch bẫy "evaluated khác mesh gốc", và
# TRỌNG SỐ vertex group chính là đường suy giảm -- tô đến đâu ảnh hưởng đến đó.
#
# Vì sao phải tách nhóm TRÊN và DƯỚI thay vì một khối "miệng", "mắt":
# bản đầu chỉ dùng một khối rồi cố dò khe môi / khe mí bằng hình học ("lát ngang
# rộng nhất"). Đo ra thì sai hẳn -- cùng một hình dạng mà mắt trái cho khe 0.1285,
# mắt phải cho 0.0320, và khe miệng rơi lên tận má. Ranh giới trên/dưới là thứ
# KHÔNG suy ra được từ một khối; phải để người tô (hoặc bộ tự sinh) chỉ định.

REGIONS = [
    ('FS_LipUpper',   r'upperlips?\.',              True),
    ('FS_LipLower',   r'lowerlips?\.',              True),
    ('FS_LidUpper.L', r'upper_eyelid\.l',           False),
    ('FS_LidLower.L', r'lower_eyelid\.l',           False),
    ('FS_LidUpper.R', r'upper_eyelid\.r',           False),
    ('FS_LidLower.R', r'lower_eyelid\.r',           False),
    ('FS_Brow.L',     r'^eyebrow\.l',               False),
    ('FS_Brow.R',     r'^eyebrow\.r',               False),
    ('FS_Nose',       r'^nose\.',                   False),
    ('FS_Jaw',        r'face_border\.[lr]\.00[678]', False),
    # Má gần như không rig nào có bone riêng, nên nhóm này thường rỗng sau khi
    # đổ từ vertex group. auto_cheeks() khoanh bù bằng phép loại trừ.
    ('FS_Cheek.L',    r'^cheek\.l',                 False),
    ('FS_Cheek.R',    r'^cheek\.r',                 False),
    # Răng là XƯƠNG. Hai nhóm này không sinh ra shape key nào cả -- chúng tồn
    # tại để GỠ răng khỏi các vùng mềm, và để hàm dưới quay cứng theo bản lề.
    ('FS_TeethUpper', r'teeth.*(up|upper)|(up|upper).*teeth', False),
    ('FS_TeethLower', r'teeth.*(low|bottom)|(low|bottom).*teeth', False),
    # Nhãn cầu NẰM TRONG CHÍNH MESH MẶT (không phải object riêng). Rất hay gặp ở
    # nhân vật stylize/game. Không có nhóm này thì nhãn cầu kiểu đó không bao giờ
    # bị che khi nhắm: đo trên Alien, mí đi đủ 101%% quãng đường tới khe mà mắt
    # vẫn mở nguyên, vì vòm mắt LỒI RA TRƯỚC mặt phẳng da nên kéo da quanh nó
    # bao nhiêu cũng không phủ tới.
    ('FS_Eyeball.L',  r'^eyeball\.l',               False),
    ('FS_Eyeball.R',  r'^eyeball\.r',               False),
]
REQUIRED = [n for n, _, req in REGIONS if req]


# ============================================ NHIỀU MẮT TRÊN CÙNG MỘT BÊN MẶT
#
# Bảng trên mô tả bộ mặc định HAI mắt. Nhân vật bốn mắt (hai cặp chồng nhau mỗi
# bên) không dựng được bằng MỘT nhóm mí cho mỗi bên -- và đây là chỗ HỎNG chứ
# không phải chỗ thiếu tính năng. Đo trên `Mesh_0.001` (4 mắt, 4 tay):
#
#     FS_LidUpper.L   33 vertex -- 17 gần mắt to, 16 gần mắt nhỏ
#     FS_LidLower.L   38 vertex -- 19 / 19
#
# Một nhóm gộp thì `PairFrame` + `seam_line()` khớp MỘT đường khe cho cả hai con
# mắt, và đường đó rơi đúng vào khoảng giữa: tâm nhãn cầu to cách khe +8,6 mm,
# tâm nhãn cầu nhỏ -14,5 mm (hai tâm cách nhau 37,4 mm, bán kính 23,4 mm). Gấp
# mí về đường ấy kéo da của CẢ HAI mắt vào giữa: không mắt nào nhắm, còn da thì
# đâm xuyên qua cả hai con ngươi -- `EYE_BlinkL` đẩy thêm 4 vertex vào nhãn cầu
# to và 6 vertex vào nhãn cầu nhỏ, sâu nhất 12,9 mm.
#
# Hậu tố dùng ĐÚNG quy ước xương của `rigdef.inst_name`: mắt thứ nhất giữ
# nguyên `.L`, mắt thứ hai là `_2.L`. Nhờ vậy rig hai mắt cũ không đổi một chữ
# nào, và tên nhóm luôn khớp tên xương (`Eye_2.L` <-> `FS_LidUpper_2.L`).
MAX_EYE = 8
EYE_FAMILY = ('FS_LidUpper', 'FS_LidLower', 'FS_Eyeball')


def eye_suffix(inst, side):
    """`.L` cho mắt thứ nhất, `_2.L` cho mắt thứ hai -- như `rigdef.bone_name`."""
    return ("" if inst <= 1 else "_%d" % inst) + "." + side


def eye_slots(face, side=None):
    """[(số thứ tự, bên)] các con mắt CÓ NHÓM MÍ thật trên mesh này."""
    out = []
    for s in (('L', 'R') if side is None else (side,)):
        for inst in range(1, MAX_EYE + 1):
            sfx = eye_suffix(inst, s)
            if (face.vertex_groups.get('FS_LidUpper' + sfx) is not None
                    or face.vertex_groups.get('FS_LidLower' + sfx) is not None):
                out.append((inst, s))
    return out


def eye_insts(regions, side):
    """Số thứ tự các mắt cùng bên có mặt trong `regions`. Không bao giờ rỗng."""
    out = [i for i in range(1, MAX_EYE + 1)
           if regions.get('FS_LidUpper' + eye_suffix(i, side))
           or regions.get('FS_LidLower' + eye_suffix(i, side))]
    return out or [1]


def lids_of(regions, side, fams=('FS_LidUpper', 'FS_LidLower')):
    """Gộp nhóm mí của MỌI con mắt cùng một bên."""
    names = []
    for inst in eye_insts(regions, side):
        sfx = eye_suffix(inst, side)
        names += [fam + sfx for fam in fams]
    return merged(regions, *names)


def all_lids(regions, fams=('FS_LidUpper', 'FS_LidLower')):
    """Gộp nhóm mí của mọi con mắt, cả hai bên."""
    out = {}
    for side in ('L', 'R'):
        for i, w in lids_of(regions, side, fams).items():
            out[i] = max(out.get(i, 0.0), w)
    return out


def region_table(face):
    """`REGIONS` mở rộng theo số mắt THẬT của mesh này.

    Nhóm của mắt thứ hai trở đi không có mẫu tên nào để dò -- rig nguồn không hề
    có bone `upper_eyelid_2.l`. Chúng chỉ sinh ra từ `split_eye_regions()` hoặc
    do người dùng tô tay, nên `pat` để None và mọi chỗ dò theo mẫu phải bỏ qua.
    """
    out = list(REGIONS)
    have = {n for n, _p, _r in out}
    for inst, side in eye_slots(face):
        for fam in EYE_FAMILY:
            nm = fam + eye_suffix(inst, side)
            if nm not in have:
                out.append((nm, None, False))
                have.add(nm)
    return out


# Nhãn cầu phải NẰM Ở MẶT NÀY thì mới tính. Danh sách nhãn cầu là thiết lập
# của cả scene, không phải của riêng một mesh: file `Ver3_work.blend` đang mở
# có `Male` (người, hai mắt) và `Mesh_0.001` (bốn mắt) dùng CHUNG một danh
# sách, nên đọc thẳng danh sách ấy là gán bốn con mắt của nhân vật này cho
# khuôn mặt của nhân vật kia rồi tách nhóm mí của người ta ra làm đôi.
#
# Thước đo là bán kính CỦA CHÍNH NHÃN CẦU: một con mắt nằm đúng hốc thì da mí
# ôm quanh nó, cách chưa tới một bán kính. Đặt ở 4 lần để nhân vật tạo hình
# (mắt lồi hẳn ra ngoài mặt) vẫn lọt, còn nhân vật khác thì cách hàng mét.
EYE_HOME = 4.0


def eye_meshes_for(context, face):
    """[(bên, object)] các nhãn cầu rời THUỘC VỀ khuôn mặt này, đúng thứ tự."""
    st = getattr(context.scene, "srp_generate", None) if context else None
    if st is None:
        return []
    inv = face.matrix_world.inverted()
    lid = []
    for inst, side in eye_slots(face):
        sfx = eye_suffix(inst, side)
        for fam in ('FS_LidUpper', 'FS_LidLower'):
            lid += list(read_region(face, fam + sfx))
    if lid:
        base = base_coords(face)
        near = [base[i] for i in lid]
    else:
        # Chưa tô nhóm mí nào -- lùi về hộp bao của chính mesh mặt.
        near = [Vector(c) for c in face.bound_box]
    out = []
    for e in st.eyes:
        if e.mesh is None or e.mesh.type != 'MESH' or not e.mesh.data.vertices:
            continue
        pts = [inv @ (e.mesh.matrix_world @ v.co) for v in e.mesh.data.vertices]
        c = sum(pts, Vector((0, 0, 0))) / len(pts)
        rad = max((p - c).length for p in pts)
        if min((p - c).length for p in near) > rad * EYE_HOME:
            continue
        out.append((e.side, e.mesh, c, rad))
    return out


def eye_anchors(context, face):
    """{(số thứ tự, bên): (tâm, bán kính)} từng nhãn cầu, hệ toạ độ của mesh mặt.

    Ba nguồn, ưu tiên giảm dần: danh sách nhãn cầu ở bước 1 (object riêng),
    xương `Eye*` của rig đang skin mesh, rồi nhóm `FS_Eyeball*` (nhãn cầu nằm
    trong chính mesh mặt). Nguồn nào ra kết quả trước thì DỪNG ở đó -- trộn hai
    nguồn sinh ra mắt ma khi cả hai cùng mô tả một con mắt.
    """
    inv = face.matrix_world.inverted()
    out = {}
    n = {'L': 0, 'R': 0}
    for side, _obj, c, rad in eye_meshes_for(context, face):
        n[side] = n.get(side, 0) + 1
        out[(n[side], side)] = (c, rad)
    if out:
        return out

    arm = next((m.object for m in face.modifiers
                if m.type == 'ARMATURE' and m.object is not None), None)
    if arm is not None:
        for side in ('L', 'R'):
            for inst in range(1, MAX_EYE + 1):
                bone = arm.data.bones.get("Eye" + eye_suffix(inst, side))
                if bone is None:
                    continue
                c = inv @ (arm.matrix_world @ bone.head_local)
                out[(inst, side)] = (c, max(bone.length, 1e-6))
    if out:
        return out

    base = base_coords(face)
    for inst, side in eye_slots(face):
        reg = read_region(face, 'FS_Eyeball' + eye_suffix(inst, side))
        if not reg:
            continue
        pts = [base[i] for i in reg]
        c = sum(pts, Vector((0, 0, 0))) / len(pts)
        out[(inst, side)] = (c, max((p - c).length for p in pts))
    return out


def split_eye_regions(context, face):
    """Tách nhóm mí GỘP của một bên ra thành từng con mắt một.

    Chia theo nhãn cầu gần nhất, đo bằng khoảng cách tới MẶT CẦU (|p-c| - r) chứ
    không tới tâm: hai con mắt cùng bên rất hay khác cỡ, và khoảng cách tới tâm
    thì luôn thiên vị quả to.

    Không vứt gì đi -- mỗi vertex giữ nguyên trọng số đã tô, chỉ đổi chỗ ở. Chia
    ra mà nhóm nào tụt dưới `MIN_REGION` thì để nguyên cả cụm: nhóm quá nhỏ
    không dựng nổi một đường khe, thà giữ chỗ hỏng đã biết còn hơn tạo chỗ hỏng
    mới mà không ai ngờ.
    """
    anchors = eye_anchors(context, face)
    if not anchors:
        return {}
    base = base_coords(face)
    out = {}
    for side in ('L', 'R'):
        insts = sorted(i for i, s in anchors if s == side)
        if len(insts) < 2:
            continue
        for fam in ('FS_LidUpper', 'FS_LidLower'):
            src = {}
            for inst in insts:
                src.update(read_region(face, fam + eye_suffix(inst, side)))
            if len(src) < MIN_REGION * len(insts):
                continue

            def far(i, k):
                c, r = anchors[(k, side)]
                return (base[i] - c).length - r

            bucket = {i: {} for i in insts}
            for i, w in src.items():
                bucket[min(insts, key=lambda k: far(i, k))][i] = w
            if any(len(b) < MIN_REGION for b in bucket.values()):
                continue
            for inst in insts:
                nm = fam + eye_suffix(inst, side)
                old = face.vertex_groups.get(nm)
                if old is not None:
                    face.vertex_groups.remove(old)
                g = face.vertex_groups.new(name=nm)
                for i, w in bucket[inst].items():
                    g.add([i], w, 'REPLACE')
                out[nm] = len(bucket[inst])
    return out


# ------------------------------------------- chặn da đâm xuyên qua nhãn cầu
#
# Khép mí là da TRƯỢT TRÊN mặt cầu, nhưng shape key chỉ là một trường vector
# tuyến tính: nó đi thẳng, còn nhãn cầu thì cong. Đo trên `Mesh_0.001` với bộ
# key dựng bằng luật cũ -- lúc nghỉ đã có 7 vertex mí nằm trong mỗi nhãn cầu
# (phần da cuộn vào sau vành mắt, hoàn toàn đúng), rồi `EYE_BlinkL` đẩy THÊM 4
# vertex vào nhãn cầu to và 6 vào nhãn cầu nhỏ, sâu nhất 12,9 mm trên bán kính
# 23,4 mm. Hơn nửa bán kính -- đó chính là con ngươi lòi qua mí.
#
# Bất biến dùng để chặn: KHÔNG VERTEX NÀO ĐƯỢC LÚN SÂU HƠN LÚC NGHỈ. Nói "đẩy
# hết ra ngoài" là sai: 7 vertex kia vốn đã ở trong, kéo chúng ra là banh hốc
# mắt. Chặn bằng MẶT CẦU cũng sai với nhãn cầu tạo hình (giác mạc lồi ra trước),
# nên hình chặn của nhãn cầu rời lấy từ CHÍNH lưới của nó qua BVH.
EYE_CLEAR = 0.02    # da phải cách mặt nhãn cầu ngần này lần bán kính
EYE_NEAR = 2.2      # chỉ xét vertex nằm trong ngần này lần bán kính quanh tâm
# Phải LẶP, vì hai nhãn cầu cùng bên gần như chạm nhau (tâm cách nhau 1,6 lần
# bán kính): đẩy một vertex ra khỏi quả này là đẩy nó vào quả kia. Đo trên bộ
# thử bốn mắt -- một lượt duy nhất chỉ hạ 125 lượt đâm xuống 6, lặp thì về 0.
EYE_PASSES = 6


class _Shield:
    """Một nhãn cầu, ở dạng hỏi được "điểm này lún vào bao sâu"."""

    def __init__(self, centre, radius, tree=None):
        self.c, self.r, self.tree = centre, radius, tree

    def probe(self, p):
        """(độ lún, hướng RA NGOÀI). Độ lún dương = đang ở trong nhãn cầu."""
        if self.tree is None:
            v = p - self.c
            n = v.length
            if n < 1e-12:
                return self.r, Vector((0.0, 0.0, 1.0))
            return self.r - n, v / n
        loc, nrm, _i, _d = self.tree.find_nearest(p)
        if loc is None:
            return None
        v = p - loc
        n = v.length
        if n < 1e-12:
            return 0.0, nrm.copy()
        inside = v.dot(nrm) < 0.0
        return (n if inside else -n), (-v / n if inside else v / n)


# ==================================== MÍ TRƯỢT QUA TRƯỚC NHÃN CẦU, KHÔNG ĐI THẲNG
#
# Đây là chỗ hỏng nặng nhất của cả bộ dựng, và nó nấp được hai ngày vì mọi phép
# đo đều đúng nhưng đo nhầm thứ.
#
# Bản cũ đẩy vertex mí theo ĐƯỜNG THẲNG về đường khe. Đường khe nằm giữa hai
# nhóm mí, mà chỗ đó lại nằm PHÍA SAU mặt trước của nhãn cầu -- nên mí trượt
# vòng ra sau con ngươi thay vì phủ qua trước nó. Không lần nào "đâm xuyên"
# (`eyeball_guard` báo 0 lượt, đúng), và `_pair_gap` cũng báo "khép 54%" (đúng
# nốt, vì hai NHÓM có xích lại gần nhau thật) -- trong khi con ngươi lồ lộ.
#
# Đo trên `Mesh_0.001`, tắt trò co nhãn cầu để xem một mình cái mí làm được gì
# (% mặt nhãn cầu hướng về người xem còn nhìn thấy):
#
#       mở mắt      21%
#       nhắm 0.50   23%
#       nhắm 1.00   26%      <-- nhắm hết cỡ còn HỞ HƠN lúc mở
#
# Nghĩa là cái "mắt nhắm" xưa nay hoàn toàn do NHÃN CẦU TỰ CO còn 80% và thụt
# vào 6 mm để trốn, chứ mí không hề che. Driver co ấy lại có ngưỡng 0.6, nên mọi
# giá trị lưng chừng và toàn bộ `EYE_Squint` (không có driver) đều lòi con ngươi.
#
# Cách đúng: cho vertex mí QUAY QUANH TÂM NHÃN CẦU. Khoảng cách tới tâm không
# đổi nên mí luôn nằm trên mặt cầu, tức luôn ở PHÍA TRƯỚC con ngươi. Đo lại,
# vẫn chỉ mí làm việc:
#
#       quay  0°  21%      quay 30°   7%
#       quay 10°   7%      quay 40°  12%
#       quay 20°   2%      quay 50°  26%
#
# Có điểm tối ưu rõ rệt -- và quá đà thì mí lại vượt sang bên kia làm hở trở
# lại. Không có công thức nào cho ra con số đó: nó phụ thuộc hình mí, cỡ nhãn
# cầu, độ lồi của mặt. Nên `solve_lid_angles()` DÒ BẰNG ĐO.

LID_ARC_MAX = 1.30      # bội số khép tối đa khi dò (1.0 = mép lỗ tới đúng khe)
LID_RINGS = 2           # sàn: dù mesh thô đến đâu cũng tắt dần qua ngần này vòng
# Vành da sau mép lỗ phải TRẢI RỘNG ÍT NHẤT NGẦN NÀY LẦN quãng mép lỗ đi. Mép đi
# `d` mà phần tắt dần chỉ trải `D` thì biến dạng cỡ `d/D` -- muốn giãn cạnh dưới
# ~1,7 thì `D` phải cỡ 1,6 lần `d`. Đếm theo SỐ VÒNG thì con số này trôi theo mật
# độ lưới: đúng trên `Mesh_0.001` (7 vertex quanh lỗ 14 mm) và rách trên lưới
# dày -- đo trên canh cầu 96x48, cùng LID_RINGS=2 mà bộ dò phải dừng ở khẩu độ
# 64% vì chạm trần giãn cạnh. Đo bằng MÉT trên lưới thì mật độ không còn ảnh
# hưởng.
LID_SPREAD = 1.6
LID_CONV_MAX = 1.30     # bội số khép lỗ tối đa (1.0 = mép lỗ tới đúng khe)
LID_TAPER_P = 2.0       # độ "phẳng" của hàm tắt dần về hai khoé mắt
LID_ARC_STEPS = 13      # số điểm quét thô
LID_ARC_REFINE = 5      # số điểm quét tinh quanh điểm tốt nhất
# Che kín mà lưới nhúm thành gai thì vô dụng. Anh Art nhìn ra ngay ở bản đầu:
# con ngươi che được 6% nhưng cả vùng mí gãy nát. Nên bộ dò là bài tối ưu CÓ
# RÀNG BUỘC -- che ít nhất trong số các bội số giữ được lưới sạch.
LID_FLIP_MAX = 0.06     # tỉ lệ đa giác mí được phép gập ngược
LID_STRETCH_MAX = 2.4   # trần giãn cạnh p99 trong vùng mí
LID_COVER_FACE = 0.35   # vertex nhãn cầu coi là "hướng về người xem" khi dot >=
LID_COVER_GOOD = 0.10   # che tới mức này thì coi là đã kín, không gấp thêm nữa


def mesh_holes(face):
    """[tập vertex] của từng vòng biên hở trên mesh -- tức từng cái LỖ THỦNG."""
    count = {}
    for poly in face.data.polygons:
        vs = list(poly.vertices)
        for k in range(len(vs)):
            e = (min(vs[k], vs[(k + 1) % len(vs)]),
                 max(vs[k], vs[(k + 1) % len(vs)]))
            count[e] = count.get(e, 0) + 1
    link = {}
    for (a, b), c in count.items():
        if c == 1:
            link.setdefault(a, []).append(b)
            link.setdefault(b, []).append(a)
    seen, out = set(), []
    for v in list(link):
        if v in seen:
            continue
        stack, comp = [v], []
        while stack:
            u = stack.pop()
            if u in seen:
                continue
            seen.add(u)
            comp.append(u)
            stack.extend(link.get(u, ()))
        out.append(set(comp))
    return out


def eye_holes(face, regions):
    """{(số thứ tự, bên): tập vertex trên MÉP LỖ MẮT}.

    Rất nhiều nhân vật stylize khoét hẳn một lỗ ở mỗi mắt rồi đặt nhãn cầu vào
    sau -- `Mesh_0.001` có đúng bốn lỗ 7 vertex. Với kiểu đó, "nhắm mắt" nghĩa
    là KHÉP CÁI LỖ, và đó là mục tiêu duy nhất đo được mà không cần nhãn cầu.
    Nhận một lỗ là của con mắt nào bằng cách hỏi mép lỗ có nằm trong nhóm mí của
    mắt đó không -- gần đúng hơn hẳn so với so khoảng cách tâm.
    """
    holes = [h for h in mesh_holes(face) if len(h) >= 3]
    out = {}
    for inst, side in eye_slots(face):
        sfx = eye_suffix(inst, side)
        reg = set(regions.get('FS_LidUpper' + sfx, {})) \
            | set(regions.get('FS_LidLower' + sfx, {}))
        if not reg:
            continue
        best, score = None, 0
        for h in holes:
            hit = len(h & reg)
            if hit > score:
                best, score = h, hit
        if best is not None and score >= 3 and score >= len(best) * 0.6:
            out[(inst, side)] = best
    return out


def eye_pairs(context, face):
    """[(số thứ tự, bên, object nhãn cầu, tâm, bán kính)] -- tâm ở hệ mesh mặt."""
    out = []
    count = {}
    for side, obj, c, rad in eye_meshes_for(context, face):
        count[side] = count.get(side, 0) + 1
        out.append((count[side], side, obj, c, rad))
    return out


# ĐÃ THỬ VÀ BỎ -- đẩy đích mí ra TRƯỚC nhãn cầu theo trục `out`, với lý lẽ "mí
# thật khép ở trước giác mạc chứ không ở đáy hốc mắt". Dựng xong, đo trên
# `Mesh_0.001`: **không ra tay một lần nào**, cả bảy vertex mép lỗ đều đẩy thêm
# 0,00 mm. Lý do đo được, và nó lật ngược cả giả thiết:
#
#   bán kính nhãn cầu                        23,4 mm
#   mép lỗ so với TÂM nhãn cầu, theo `out`   -3,5 tới -5,8 mm  (nằm SAU tâm)
#   mép lỗ lún trong nhãn cầu LÚC NGHỈ        4,6 tới 14,4 mm
#   pháp tuyến mặt cầu chấm với `out`        -0,22 tới -0,76   (hướng RA SAU)
#
# Nhãn cầu KHÔNG lồi qua cái lỗ -- nó nuốt trọn mép lỗ. Vành mắt cuộn vào phía
# sau quả cầu, đúng như mắt thật. Nên không có "phía trước" nào để đẩy tới:
# đường thoát gần nhất chạy ngược ra sau. Chỗ hỏng nằm ở LUẬT của `eyeball_guard`
# chứ không ở đường đi của mí -- xem ghi chú ở đó.


# ================== BIẾN DẠNG THEO MỤC TIÊU: đặt ĐÍCH rồi GIẢI, không đi bằng
#                    công thức
#
# Bảy lần liên tiếp tôi sửa mí bằng cách viết một công thức hình học mới, và
# lần nào cũng có một nhân vật làm hỏng giả định của nó: có lỗ / không lỗ, nhãn
# cầu trong / ngoài da, khe ngang / khe xiên, mép lỗ cuộn vào / không cuộn, lưới
# thưa / lưới dày, trọng số đều / trọng số dốc. Anh Art nói đúng -- đó là một
# quỹ đạo sai, không phải một chuỗi lỗi rời rạc.
#
# Chỗ sai nằm ở KIẾN TRÚC. Bản cũ là: công thức tính đường đi -> tắt dần theo
# một hàm tự chọn -> làm mượt -> chốt giãn cạnh -> chốt chặn nhãn cầu. Năm bước
# nối tiếp, mỗi bước phá bảo đảm của bước trước, và cái duy nhất *đúng nghĩa* --
# "mắt phải nhắm" -- thì không bước nào phát biểu ra được.
#
# Cách này ngược lại. Chỉ nói **ĐÍCH**:
#
#   * mép lỗ mắt phải tới đường khe                    (khép cái lỗ)
#   * vành da đang ôm mặt cầu phải TRƯỢT TRÊN mặt cầu
#     tới đường khe                                    (che con ngươi)
#   * viền ngoài vùng đứng yên                         (không kéo cả mặt)
#
# rồi để một phép GIẢI tìm chỗ đứng cho toàn bộ da ở giữa, sao cho mặt cong ít
# nhất -- `biharmonic_field()`. Không còn `LID_SPREAD`, `LID_RINGS`,
# `LID_TAPER_P`, không còn bội số nào để dò: đích đã nói hết.
#
# Cái được không chỉ là bớt hằng số. Ba thứ trước đây phải cài tay giờ TỰ RA:
#
#   * **Tắt dần** -- nghiệm biharmonic tự trải rộng theo hình lưới thật, nên
#     lưới dày hay thưa đều đúng. Trước đây phải đo `LID_SPREAD` và nó sai ngay
#     khi đổi mật độ lưới.
#   * **Khoé mắt đứng yên** -- ở khoé, đường khe đi qua đúng chỗ vertex đang
#     đứng nên độ dịch ĐÍCH tự bằng 0. Trước đây phải nhân thêm `taper()`.
#   * **Không đâm nhãn cầu** -- đưa vào thành ràng buộc của chính phép giải
#     (lặp: giải -> đẩy chỗ lún ra -> ghim nó lại -> giải lại), nên nó không còn
#     là một bước hạ nguồn phá công của bước trên.


def biharmonic_field(ids, adj, pin, ridge=1e-6):
    """{vertex: vector dịch} trên một mảng lưới, biết dịch của vài vertex.

    Cực tiểu hoá ``|L d|^2`` -- năng lượng uốn của trường độ dịch -- với `pin`
    là ràng buộc cứng. Nói nôm na: "cho tôi cách trải đều nhất có thể, biết mấy
    chỗ này phải đi tới đúng đây". Đó chính là thứ mà mọi hàm tắt dần tự chế
    xưa nay đang xấp xỉ một cách vụng về.

    Dùng Laplacian đều (umbrella) chứ không cotangent: cotangent cho trọng số ÂM
    trên tam giác tù, và lưới nhân vật stylize đầy tam giác tù. Đổi lại nó hơi
    kém chính xác trên lưới rất không đều -- chấp nhận được, vì phép giải chỉ
    quyết định phần TRẢI, còn phần ĐÍCH thì đã ghim cứng.

    Ma trận đặc, giải bằng `numpy.linalg.solve`. Mảng mí chỉ cỡ 60-200 vertex
    nên đặc là đủ nhanh (đo được 3,1 ms mỗi con mắt); thưa chỉ đáng khi cả mặt.
    """
    import numpy as np

    order = list(ids)
    pos = {v: k for k, v in enumerate(order)}
    n = len(order)
    if n == 0:
        return {}
    L = np.zeros((n, n))
    for v, k in pos.items():
        nb = [pos[j] for j in adj.get(v, ()) if j in pos]
        L[k, k] = 1.0
        if nb:
            w = -1.0 / len(nb)
            for j in nb:
                L[k, j] = w
    A = L.T @ L
    free = [k for v, k in pos.items() if v not in pin]
    con = [k for v, k in pos.items() if v in pin]
    d = np.zeros((n, 3))
    for v, dv in pin.items():
        if v in pos:
            d[pos[v]] = (dv.x, dv.y, dv.z)
    if not free:
        return {v: Vector(d[k]) for v, k in pos.items()}
    Aff = A[np.ix_(free, free)] + np.eye(len(free)) * ridge
    rhs = -A[np.ix_(free, con)] @ d[con] if con else np.zeros((len(free), 3))
    try:
        d[free] = np.linalg.solve(Aff, rhs)
    except np.linalg.LinAlgError:
        d[free] = np.linalg.lstsq(Aff, rhs, rcond=None)[0]
    return {v: Vector(d[k]) for v, k in pos.items()}


def grow_patch(ids, adj, rings):
    """Nới một tập vertex ra thêm `rings` vòng cạnh. Trả về (tập, viền ngoài)."""
    cur = set(ids)
    for _ in range(max(rings, 0)):
        nxt = set(cur)
        for i in cur:
            nxt |= set(adj.get(i, ()))
        cur = nxt
    edge = {i for i in cur if any(j not in cur for j in adj.get(i, ()))}
    return cur, edge


def slide_on_ball(p, centre, close, target_c, origin):
    """Trượt `p` TRÊN mặt cầu quanh `centre` tới khi toạ độ ngang khe = đích.

    Giữ nguyên khoảng cách tới tâm nhãn cầu, nên vertex đang ôm mặt cầu thì vẫn
    ôm mặt cầu sau khi đi -- đó là điều kiện để nó còn CHE được con ngươi. Đi
    thẳng tới khe thì nó chui vào trong quả cầu và biến mất khỏi tầm nhìn: mắt
    khép mà người xem không thấy gì đổi.

    Trả về vector dịch, hoặc None nếu không trượt được (vertex nằm đúng trên
    trục khép, không có mặt phẳng quay).
    """
    u = p - centre
    if u.length < 1e-9:
        return None
    axis = u.cross(close)
    if axis.length < 1e-9:
        return None
    e1 = u.normalized()
    e2 = axis.normalized().cross(e1)
    A = u.dot(close)
    B = u.length * e2.dot(close)
    M = math.hypot(A, B)
    if M < 1e-12:
        return None
    T = target_c + close.dot(origin) - close.dot(centre)
    phi = math.atan2(B, A)
    r = max(-1.0, min(1.0, T / M))
    dt = math.acos(r)
    th = min(phi - dt, phi + dt, key=abs)
    return (Matrix.Rotation(th, 3, axis.normalized()) @ u) - u


LID_PATCH_RINGS = 2     # nới mảng giải ra ngoài nhóm mí ngần này vòng


def lid_goal(regions, base, frame, inst, side, shield, hole, adj, amount=1.0):
    """{vertex: vector dịch} khi khép mí -- ĐẶT ĐÍCH RỒI GIẢI.

    Ba loại ràng buộc, và chỉ có thế:

    1. **mép lỗ** đi thẳng tới đường khe -- khép cái lỗ. Nó nằm sẵn phía sau mặt
       cầu (đo trên `Mesh_0.001`: lún 4,5-18,3 mm) nên không cần né gì.
    2. **vành ôm cầu** -- vertex đang ở NGOÀI nhãn cầu mà có hàng xóm ở TRONG.
       Đó đúng là đường bao của cái cửa sổ mà người xem nhìn thấy con ngươi qua.
       Nó phải TRƯỢT TRÊN mặt cầu tới khe, không đi thẳng.
    3. **viền mảng** đứng yên.

    Định nghĩa (2) bằng TÔ PÔ (ngoài, có hàng xóm ở trong) chứ không bằng ngưỡng
    khoảng cách: ngưỡng nào cũng phải hiệu chỉnh theo cỡ nhãn cầu và độ dày da,
    còn "chỗ mặt cầu chui ra khỏi da" thì chỉ có một.

    `amount` nhân thẳng vào đích. Shape key vốn là trường tuyến tính nên nhân
    đích rồi giải cho ra đúng cùng kết quả với giải rồi nhân -- phép giải là
    tuyến tính. Nhờ vậy `EYE_Squint` (0.45) và `EYE_Wide` (âm) dùng chung một
    nghiệm, không phải giải lại.
    """
    sfx = eye_suffix(inst, side)
    u_reg = regions.get('FS_LidUpper' + sfx, {})
    l_reg = regions.get('FS_LidLower' + sfx, {})
    if not u_reg or not l_reg or abs(amount) < 1e-9:
        return {}
    ef = PairFrame(u_reg, l_reg, base, frame)
    if not ef.ok:
        return {}
    a_seam, b_seam = seam_line(u_reg, l_reg, ef, base)

    core = set(u_reg) | set(l_reg) | set(hole or ())
    patch, rim_edge = grow_patch(core, adj, LID_PATCH_RINGS)

    def seam_at(i):
        return a_seam + b_seam * ef.sc(base[i])[0]

    pin = {}
    # --- (1) mép lỗ -------------------------------------------------------
    for i in (hole or ()):
        if i in rim_edge:
            continue
        pin[i] = ef.close * (seam_at(i) - ef.sc(base[i])[1])

    # --- (2) vành ôm cầu --------------------------------------------------
    if shield is not None:
        deep = {}
        for i in patch:
            pr = shield.probe(base[i])
            deep[i] = None if pr is None else pr[0]
        for i in patch:
            if i in pin or i in rim_edge:
                continue
            d0 = deep.get(i)
            if d0 is None or d0 > 0.0:
                continue        # đang ở TRONG cầu -> không phải vành bao
            if not any(deep.get(j) is not None and deep[j] > 0.0
                       for j in adj.get(i, ())):
                continue        # không giáp phần chìm -> không phải vành bao
            dv = slide_on_ball(base[i], shield.c, ef.close, seam_at(i),
                               ef.origin)
            if dv is not None:
                pin[i] = dv

    if not pin:
        return {}
    # --- (3) viền mảng đứng yên ------------------------------------------
    Z = Vector((0.0, 0.0, 0.0))
    for i in rim_edge:
        pin.setdefault(i, Z.copy())

    if abs(amount - 1.0) > 1e-12:
        pin = {i: v * amount for i, v in pin.items()}

    field = biharmonic_field(patch, adj, pin)

    # --- ràng buộc bất đẳng thức: không lún sâu hơn lúc nghỉ --------------
    #
    # Đây là chỗ kiến trúc cũ hỏng nặng nhất: chốt chặn chạy CUỐI CHUỖI và đẩy
    # vertex đi mà không ai giải lại, nên nó vừa cứu vừa phá. Ở đây nó là một
    # vòng lặp của chính phép giải -- đẩy ra, GHIM lại, giải lại phần còn lại.
    if shield is not None:
        for _ in range(LID_SOLVE_PASSES):
            bad = {}
            for i in patch:
                if i in pin:
                    continue
                r0 = shield.probe(base[i])
                pr = shield.probe(base[i] + field.get(i, Z))
                if r0 is None or pr is None:
                    continue
                # KHÔNG ĐƯỢC LẠI GẦN NHÃN CẦU HƠN LÚC NGHỈ -- chặt hơn "không
                # chui vào", và phải thế. Da mí ở nhân vật này chỉ cách mặt cầu
                # 0,4-11 mm; phép giải kéo nó trượt vào trong vài mm là quả cầu
                # ló ra thành hai cục u ngay trên mí, dù không vertex nào lún
                # vào. Đo được: `v103` đi từ -1,12 mm ra -0,47 mm và đó đúng chỗ
                # cục u hiện lên. Luật "không chui vào" cho qua ca đó.
                if pr[0] > r0[0] + 1e-9:
                    bad[i] = field[i] + pr[1] * (pr[0] - r0[0])
            if not bad:
                break
            pin.update(bad)
            field = biharmonic_field(patch, adj, pin)
    return field


LID_SOLVE_PASSES = 3    # số vòng lặp giải <-> đẩy ra khỏi nhãn cầu


def lid_arc(regions, base, frame, inst, side, centre, swing, conv=0.0,
            hole=None, adj=None, shield=None):
    """{vertex: vector dịch} khi khép mí -- HAI CHUYỂN ĐỘNG CỘNG LẠI.

    Anh Art bấm "Nhắm mắt" và mắt mở trân trân, ngay sau khi tôi báo đã sửa
    xong. Cả hai lần trước tôi đều làm ĐÚNG MỘT NỬA việc, vì tưởng đây là một
    bài toán trong khi nó là hai:

    * **`swing`** -- cả tấm mí QUAY quanh tâm nhãn cầu, một góc chung (radian).
      Đây là thứ làm mắt TRÔNG NHƯ nhắm: da mí trượt qua trước quả cầu và che
      nó đi. Bỏ nó thì mí khép xong vẫn bị nhãn cầu che mất, người xem không
      thấy gì đổi.
    * **`conv`** -- MÉP LỖ tiến vào đường khe (bội số, 1 = chạm khe). Đây là thứ
      KHÉP CÁI LỖ. Bỏ nó thì giấu nhãn cầu đi là thấy lỗ vẫn mở toang.

    Hai cái tác dụng lên hai nhóm vertex khác nhau, nên chúng không tranh nhau.
    Đo trên `Mesh_0.001`, mép lỗ nằm cách tâm nhãn cầu 5,3-18,8 mm còn da mí
    ngoài thì 23 mm: quay 30 độ đưa da ngoài đi 12 mm nhưng mép lỗ chỉ 2,6 mm --
    nên **quay không khép nổi lỗ**, và ngược lại **khép lỗ không che nổi cầu**
    vì cái lỗ nằm trọn phía sau mặt cầu.

    Hình học đo được của `Mesh_0.001`, giải thích vì sao phải thế:

    | | |
    |---|---|
    | bán kính nhãn cầu | 23,4 |
    | tâm nhãn cầu so với mặt phẳng mép lỗ | +4,6 (ở PHÍA TRƯỚC) |
    | cực trước nhãn cầu so với mép lỗ | +28,0 |
    | vành da sát mép lỗ | nằm NGOÀI mặt cầu 0,4-4,8 |
    | mép lỗ | nằm TRONG mặt cầu 4,5-18,3 |

    Tức hốc mắt là một cái phễu: vành ngoài ôm sát mặt cầu, còn mép lỗ thì cuộn
    vào phía sau nó. Muốn mí đi ra TRƯỚC quả cầu thì mép lỗ phải vọt lên 19-34
    mm -- bằng cả đường kính quả cầu, không đời nào. Nên mép lỗ khép ở phía sau
    (đúng chỗ của nó), còn phần che là việc của vành da ngoài.

    Tắt dần cũng khác nhau theo từng chuyển động, vì chúng phục vụ hai thứ:
    `swing` tắt theo TRỌNG SỐ ĐÃ TÔ (nghệ sĩ quyết định mảng da nào là mí),
    `conv` tắt theo KHOẢNG CÁCH TRÊN LƯỚI tính từ mép lỗ, đo bằng mét (đếm số
    vòng thì con số trôi theo mật độ lưới; canh cầu 96x48 rách ngay).

    Vành tắt dần của `conv` là HÌNH HỌC quanh cái lỗ, không phải phần nghệ sĩ đã
    tô. Mép lỗ là mép mí theo định nghĩa; bỏ sót một vertex mép là để lại đúng
    chỗ giữ cái lỗ mở -- đo trên canh cầu 96x48 nơi 4/12 vertex mép nằm ngoài
    nhóm tô, khẩu độ ghim ở 64% dù ràng buộc lưới còn thừa chỗ.
    `region_invariants` vẫn báo CẢNH BÁO để nghệ sĩ tô lại.

    Vertex nằm trong CẢ hai nhóm mí thì phải CHỌN MỘT BÊN theo vị trí so với
    khe. Trước đây cộng cả hai phép dịch ngược chiều lên cùng vertex nên chúng
    triệt tiêu -- đo được: mép lỗ trọng số 1.0 mà dịch đúng 0,0 mm. Cùng bài học
    đã ghi cho xương hàm: thuộc cả hai phía thì phải quyết, không chia đôi.

    ĐÃ THỬ VÀ BỎ -- đẩy đích mí ra TRƯỚC nhãn cầu theo trục `out` ("mí thật khép
    ở trước giác mạc"). Không ra tay một lần nào: bảng trên nói vì sao.

    `shield` nhận vào nhưng không dùng để nắn đường đi -- giữ tham số để chỗ gọi
    khỏi phải biết chuyện đó.
    """
    sfx = eye_suffix(inst, side)
    u_reg = regions.get('FS_LidUpper' + sfx, {})
    l_reg = regions.get('FS_LidLower' + sfx, {})
    if not u_reg or not l_reg:
        return {}
    if abs(swing) < 1e-9 and abs(conv) < 1e-9:
        return {}
    ef = PairFrame(u_reg, l_reg, base, frame)
    if not ef.ok:
        return {}
    a_seam, b_seam = seam_line(u_reg, l_reg, ef, base)

    paint = {}
    for part in (u_reg, l_reg):
        for i, w in part.items():
            paint[i] = max(paint.get(i, 0.0), w)
    ws = sorted(paint.values())
    wref = max(ws[int(len(ws) * PCTL)] if ws else 1.0, 1e-6)

    ids = set(paint)
    dist, span = None, 1.0
    if hole and adj:
        rim = list(hole)
        travel, edge, n = 0.0, 0.0, 0.0
        for i in rim:
            s_, c_ = ef.sc(base[i])
            # LỚN NHẤT, không phải trung bình: vertex đỉnh lỗ đi gấp đôi vertex
            # ở khoé, mà vành tắt dần thì chỉ có một bề rộng. Lấy trung bình là
            # vành hụt đúng ở chỗ đi xa nhất -- canh cầu: giãn 2,63 (rách) so
            # với 2,17 khi lấy lớn nhất.
            travel = max(travel, abs(a_seam + b_seam * s_ - c_))
            nb = list(adj.get(i, ()))
            if nb:
                edge += min((base[j] - base[i]).length for j in nb)
                n += 1.0
        span = max(travel * LID_SPREAD, edge / max(n, 1.0) * LID_RINGS, 1e-9)
        dist = {i: 0.0 for i in rim}
        front = list(rim)
        while front:                    # lan sóng, nới dần -- vùng nhỏ nên đủ
            nxt = []
            for i in front:
                for j in adj.get(i, ()):
                    d = dist[i] + (base[j] - base[i]).length
                    if d >= span or d >= dist.get(j, 1e30) - 1e-12:
                        continue
                    dist[j] = d
                    nxt.append(j)
            front = nxt
        ids |= set(dist)

    # KHOÉ MẮT LÀ ĐIỂM NEO. Hai nửa mí dính liền nhau ở hai khoé, nên ở đó
    # chúng KHÔNG được đi ngược chiều nhau. Phép quay không tự biết điều đó:
    # nó lật dấu ngay khi qua đường khe, và hai vertex kề nhau nằm hai bên khe
    # bay ra hai hướng. Đo trên `Mesh_0.001` ở góc quay 0,20 rad -- cạnh v98-v131
    # dài 2,6 mm giãn thành 10,3 mm (3,91 lần), cạnh v94-v100 co từ 12,5 xuống
    # 4,0; cả bốn vertex đều trọng số 1,0 và đều dịch ~5 mm, chỉ khác dấu. Đó là
    # lý do bộ dò cũ phải dừng ở 0,09 rad và mí gần như không nhúc nhích.
    #
    # Phần khép lỗ không bị vì nó nhân với `gap` -- khoảng cách tới khe -- vốn
    # tự về 0 ở khoé. Phép quay phải mượn đúng ý đó: nhân thêm một hàm tắt dần
    # theo trục DỌC KHE, 1 ở giữa và 0 ở hai khoé, y như `taper()` dùng cho môi.
    half = pair_half(ef, paint, base)

    # HAI LƯỢT, không một. Phép khép phải đo khoảng cách tới khe TỪ CHỖ VERTEX
    # ĐÃ ĐỨNG SAU KHI QUAY, không phải từ chỗ nghỉ: quay đã dời mép lỗ đi rồi,
    # nên khép theo số cũ là khép hụt chỗ này thừa chỗ kia. Đo trên `Mesh_0.001`
    # mắt .L -- khép theo số nghỉ chạm đáy ở khẩu độ 19% rồi hở trở lại, dù ràng
    # buộc lưới còn thừa cả một khoảng.
    out = {}
    Z = Vector((0.0, 0.0, 0.0))
    swung = {}
    for i in ids:
        if centre is None or abs(swing) < 1e-9:
            break
        s_along, cc = ef.sc(base[i])
        gap = a_seam + b_seam * s_along - cc
        if i in u_reg or i in l_reg:
            sgn = -1.0 if u_reg.get(i, 0.0) >= l_reg.get(i, 0.0) else 1.0
        else:
            sgn = 1.0 if gap >= 0.0 else -1.0
        fw = min(paint.get(i, 0.0) / wref, 1.0) * taper(s_along, half,
                                                        LID_TAPER_P)
        if fw <= 0.0:
            continue
        v = base[i] - centre
        axis = v.cross(ef.close)
        if v.length > 1e-9 and axis.length > 1e-9:
            swung[i] = ((Matrix.Rotation(swing * fw * sgn, 3,
                                         axis.normalized()) @ v) - v)

    for i in ids:
        dv = swung.get(i, Z).copy()
        s_along, cc = ef.sc(base[i] + dv)
        gap = a_seam + b_seam * s_along - cc
        if dist is not None and abs(conv) > 1e-9:
            fh = max(0.0, 1.0 - dist.get(i, 1e30) / span)
            if fh > 0.0:
                dv = dv + ef.close * (gap * conv * fh)

        if dv.length_squared > 1e-24:
            out[i] = dv
    return out


def _face_bvh(context, face):
    """BVH của mesh mặt ĐÃ TÍNH (kèm modifier + shape key đang bật), hệ thế giới."""
    dg = context.evaluated_depsgraph_get()
    fe = face.evaluated_get(dg)
    me = fe.data
    M = fe.matrix_world
    vts = [M @ v.co for v in me.vertices]
    tris = []
    for poly in me.polygons:
        vs = list(poly.vertices)
        for k in range(1, len(vs) - 1):
            tris.append((vs[0], vs[k], vs[k + 1]))
    if len(vts) < 4 or not tris:
        return None
    return BVHTree.FromPolygons(vts, tris, all_triangles=True)


def eyeball_uncovered(context, face, ball, view):
    """Tỉ lệ mặt nhãn cầu HƯỚNG VỀ NGƯỜI XEM còn nhìn thấy (0 = bị che kín).

    Bắn tia từ chính vertex nhãn cầu đi ra phía người xem, và CHỈ bắn vào mesh
    mặt -- mũ, kính, mặt nạ không được tính là che, không thì nhân vật đội mũ
    nào cũng chấm 0 và bảng điểm thành vô dụng (bài học từ `eyeball_exposure`).
    """
    tree = _face_bvh(context, face)
    if tree is None:
        return None
    dg = context.evaluated_depsgraph_get()
    oe = ball.evaluated_get(dg)
    M = oe.matrix_world
    N = M.to_3x3().inverted().transposed()
    seen = total = 0
    for v in oe.data.vertices:
        if (N @ v.normal).normalized().dot(view) < LID_COVER_FACE:
            continue
        total += 1
        if tree.ray_cast(M @ v.co + view * 1e-4, view)[0] is None:
            seen += 1
    return (float(seen) / total) if total else None


def _goal_note(context, face, regions, base, frame, inst, side, ball, view,
               hole, field, probe, basis, cover):
    """Một dòng báo cáo cho con mắt do PHÉP GIẢI lo. Đo, không đoán."""
    Z = Vector((0.0, 0.0, 0.0))
    sfx = eye_suffix(inst, side)
    u_reg = regions.get('FS_LidUpper' + sfx, {})
    l_reg = regions.get('FS_LidLower' + sfx, {})
    ef = PairFrame(u_reg, l_reg, base, frame)
    a_h, b_h = seam_line(u_reg, l_reg, ef, base)
    s0 = {i: ef.sc(base[i])[0] for i in hole}

    def gap(d):
        v = [ef.sc(base[i] + d.get(i, Z))[1] - (a_h + b_h * s0[i]) for i in hole]
        return max(v) - min(v)

    lid = set(u_reg) | set(l_reg) | set(hole)
    polys = region_polys(face, lid)
    edges = region_edges(face, base, lid)

    def seen(d):
        for i in range(len(base)):
            probe.data[i].co = basis.data[i].co + d.get(i, Z)
        context.view_layer.update()
        got = eyeball_uncovered(context, face, ball, view)
        return 1.0 if got is None else got

    o_cover, rest = seen({}), gap({})
    c_cover = seen(field)
    c_gap = gap(field) / rest if rest > 1e-9 else 1.0
    pk = [p for p in polys if all(v in field for v in p)]
    fl = (flipped(pk, field, base, 1.0) / float(len(pk))) if pk else 0.0
    ek = [e for e in edges if e[0] in field or e[1] in field]
    sx = _stretch(field, ek, base, 1.0) if ek else 1.0
    cover[(inst, side)] = (o_cover, c_cover)
    return ("mắt %s: GIẢI theo đích (%d vertex) -- con ngươi hở %.0f%% -> "
            "%.0f%%, khẩu độ 100%% -> %.0f%% | gập ngược %.0f%%, giãn p99 %.2f"
            % (sfx, len(field), o_cover * 100, c_cover * 100, c_gap * 100,
               fl * 100, sx))


def solve_lid_angles(context, face, regions, base, frame, smooth=0):
    """Góc gấp mí cho TỪNG con mắt, dò bằng ĐO độ che phủ chứ không bằng công thức.

    Không có công thức nào ra được con số này: nó phụ thuộc hình mí, cỡ nhãn
    cầu và độ lồi của khuôn mặt cùng lúc. Và quá đà thì hở TRỞ LẠI (mí vượt qua
    bên kia con ngươi), nên đây là bài tìm cực tiểu chứ không phải bài "càng
    nhiều càng tốt" -- một chốt chặn trần đơn thuần sẽ không bao giờ tìm ra.

    Trả về ({(số thứ tự, bên): bội số}, danh sách dòng báo cáo,
    {(số thứ tự, bên): (hở lúc mở, hở lúc nhắm)}).

    Đây là bài tối ưu CÓ RÀNG BUỘC, không phải "che càng nhiều càng tốt": che
    kín mà lưới nhúm thành gai thì vô dụng.

    Phép đo phải khớp với thứ THẬT SỰ đi vào mesh, không thì góc dò ra vô
    nghĩa. Đã trả giá đúng bài này: bộ dò tối ưu trên số thô ra 1% hở, dựng xong
    lại thành 15% vì `smooth_field` chạy sau và kéo mí về phía mở. Cho bộ dò tự
    bù (`smooth > 0`) chỉ gỡ tới 11% -- làm mượt đặt một TRẦN CỨNG lên mức khép,
    tăng góc bao nhiêu cũng không vượt. Cách đúng là miễn làm mượt cho vùng mí
    (xem `region_shapes`), và khi đó bộ dò đo số thô là chuẩn -- nên `smooth`
    mặc định 0.
    """
    adj = vertex_adjacency(face)
    holes = eye_holes(face, regions)
    shields = eyeball_shields(context, face)
    pairs = eye_pairs(context, face)
    if not pairs:
        # Không có mesh nhãn cầu nào chỉ tới khuôn mặt này -> không đo được che
        # phủ, `_lid_one` tự lùi về đường thẳng. Robot, đạo cụ, nhân vật mắt vẽ
        # trên texture đều rơi vào đây và đó là chuyện bình thường.
        return {}, [], {}
    view = (face.matrix_world.to_3x3() @ frame.fwd).normalized()

    sk = face.data.shape_keys
    old = {}
    if sk is not None:
        for kb in sk.key_blocks:
            old[kb.name] = kb.value
            kb.value = 0.0
    ensure_basis(face)
    basis = face.data.shape_keys.key_blocks['Basis']
    probe = face.shape_key_add(name='_SRP_LidSolve', from_mix=False)
    probe.slider_min, probe.slider_max = 0.0, 1.0
    probe.value = 1.0

    angles, rows, cover = {}, [], {}
    try:
        for inst, side, ball, centre, rad in pairs:
            sfx = eye_suffix(inst, side)
            shield = shields.get((inst, side)) or _Shield(centre, rad)
            hole0 = holes.get((inst, side))
            if hole0:
                # Mắt này do PHÉP GIẢI lo, không có tham số nào để dò. Vẫn đo và
                # báo cáo -- người dùng cần con số, chỉ là không cần cái núm.
                fld = lid_goal(regions, base, frame, inst, side, shield, hole0,
                               adj, 1.0)
                angles[(inst, side)] = None
                rows.append(_goal_note(context, face, regions, base, frame,
                                       inst, side, ball, view, hole0, fld,
                                       probe, basis, cover))
                continue

            lid_ids = set(regions.get('FS_LidUpper' + sfx, {})) \
                | set(regions.get('FS_LidLower' + sfx, {}))
            polys = region_polys(face, lid_ids) if lid_ids else []
            edges = region_edges(face, base, lid_ids) if lid_ids else []
            hole = holes.get((inst, side))

            # MỤC TIÊU LÀ KHÉP CÁI LỖ, không phải che nhãn cầu. Che phủ đã lừa
            # hai lần: mảng da mí trượt ra TRƯỚC nhãn cầu -- che nó tới 98% --
            # mà cái lỗ vẫn mở toang, nhìn xuyên vào trong đầu. Giấu nhãn cầu đi
            # rồi nhìn là thấy ngay. Chỉ mesh nào KHÔNG khoét lỗ mới phải lùi về
            # đo che phủ.
            ef_h = None
            if hole:
                ef_h = PairFrame(regions.get('FS_LidUpper' + sfx, {}),
                                 regions.get('FS_LidLower' + sfx, {}),
                                 base, frame)
                if not ef_h.ok:
                    hole, ef_h = None, None

            s_rest = {}
            if hole:
                a_h, b_h = seam_line(regions.get('FS_LidUpper' + sfx, {}),
                                     regions.get('FS_LidLower' + sfx, {}),
                                     ef_h, base)
                s_rest = {i: ef_h.sc(base[i])[0] for i in hole}

            def wide_open(disp):
                """Bề rộng lỗ, đo SO VỚI ĐƯỜNG KHE.

                Không trừ đường khe đi thì một cái khe NGHIÊNG tự nó đã có bề
                rộng: mép lỗ khép đúng vào khe vẫn cho ra một dải. Đo trên canh
                cầu có mắt xiên 24 độ -- khép hết cỡ mà thước vẫn báo hở 25%,
                và bộ dò tưởng mình đã hết cách. Trên mặt người khe gần ngang
                nên chênh lệch không lộ ra, đó là lý do nó nấp được.
                """
                Z = Vector((0.0, 0.0, 0.0))
                vals = []
                for i in hole:
                    c_ = ef_h.sc(base[i] + disp.get(i, Z))[1]
                    vals.append(c_ - (a_h + b_h * s_rest[i]))
                return max(vals) - min(vals)

            rest_gap = wide_open({}) if hole else 0.0

            def probe_at(swing, conv):
                """(che phủ, khẩu độ, gập ngược, giãn p99) ở một cặp tham số."""
                disp = lid_arc(regions, base, frame, inst, side, centre, swing,
                               conv, hole=hole, adj=adj, shield=shield)
                if smooth > 0 and disp:
                    disp = smooth_field(disp, adj, iters=smooth)
                for i in range(len(base)):
                    probe.data[i].co = basis.data[i].co + disp.get(
                        i, Vector((0.0, 0.0, 0.0)))
                context.view_layer.update()
                cv = eyeball_uncovered(context, face, ball, view)
                cv = 1.0 if cv is None else cv
                ap = (wide_open(disp) / rest_gap) if (hole and rest_gap > 1e-9) \
                    else 1.0
                pk = [p for p in polys if all(v in disp for v in p)]
                fl = (flipped(pk, disp, base, 1.0) / float(len(pk))) if pk else 0.0
                ek = [e for e in edges if e[0] in disp or e[1] in disp]
                sx = _stretch(disp, ek, base, 1.0) if ek else 1.0
                return cv, ap, fl, sx

            # HAI CHẶNG, vì có hai tham số phục vụ hai mục tiêu khác nhau
            # (xem `lid_arc`). Dò riêng chứ không quét lưới 2 chiều: chúng gần
            # như độc lập -- quay tác dụng lên da ngoài, khép tác dụng lên mép
            # lỗ -- nên dò tuần tự cho cùng kết quả với 1/13 số phép đo.
            #
            # Mục tiêu là MỨC NHỎ NHẤT đạt, không phải mức đạt nhiều nhất. Khi
            # mí đã phủ hết thì cả một DẢI cùng cho 0%, và "chọn cái tốt nhất"
            # thì trôi tới tận trần -- đo được: mắt trái chốt 55,9° còn mắt phải
            # cùng hình dạng trôi lên 74,5° (chạm trần) dù cả hai đều 0%.
            base_cv, base_ap, _f0, _s0 = probe_at(0.0, 0.0)

            def clean(row):
                return row[-2] <= LID_FLIP_MAX and row[-1] <= LID_STRETCH_MAX

            def pick(rows, col):
                ok = [r for r in rows if clean(r)]
                pool = ok or rows
                good = [r for r in pool if r[col] <= LID_COVER_GOOD]
                if good:
                    return min(good, key=lambda r: r[0])
                return min(pool, key=lambda r: (r[col], r[0]))

            def sweep(hi_lim, col, other):
                """Quét thô rồi quét tinh quanh điểm tốt nhất. col: 1=che, 2=lỗ."""
                step = hi_lim / (LID_ARC_STEPS - 1)
                got = [(0.0, base_cv, base_ap, _f0, _s0)]
                for k in range(1, LID_ARC_STEPS):
                    x = step * k
                    got.append((x,) + other(x))
                best = pick(got, col)
                lo = max(0.0, best[0] - step)
                hi = min(hi_lim, best[0] + step)
                if hi > lo:
                    fine = (hi - lo) / (LID_ARC_REFINE + 1)
                    for k in range(1, LID_ARC_REFINE + 1):
                        x = lo + fine * k
                        got.append((x,) + other(x))
                    best = pick([r for r in got if lo <= r[0] <= hi] or got, col)
                return best

            # chặng 1 -- QUAY, chấm bằng che phủ nhãn cầu
            sw = sweep(LID_ARC_MAX, 1, lambda x: probe_at(x, 0.0))
            best_sw = sw[0]
            # chặng 2 -- KHÉP LỖ, chấm bằng khẩu độ, giữ nguyên góc quay
            if hole:
                cv = sweep(LID_CONV_MAX, 2, lambda x: probe_at(best_sw, x))
                best_cv = cv[0]
                _x, f_cover, f_aper, f_flip, f_str = cv
            else:
                best_cv = 0.0
                _x, f_cover, f_aper, f_flip, f_str = sw

            cover[(inst, side)] = (base_cv, f_cover)
            if f_flip > LID_FLIP_MAX or f_str > LID_STRETCH_MAX:
                rows.append("mắt %s: KHÔNG có mức nào vừa khép vừa giữ lưới "
                            "sạch -- chọn quay %.2f + khép %.2f, %.0f%% đa giác "
                            "gập ngược, giãn p99 %.2f. Nhóm mí tô quá hẹp?"
                            % (sfx, best_sw, best_cv, f_flip * 100, f_str))
            if best_sw <= 1e-9 and best_cv <= 1e-9:
                rows.append("mắt %s: KHÔNG tìm được mức nào tốt hơn lúc mở "
                            "(con ngươi hở %.0f%%) -- nhóm mí tô thiếu, hoặc "
                            "nhãn cầu chỉ sang sai mắt" % (sfx, base_cv * 100))
                continue
            angles[(inst, side)] = (best_sw, best_cv)
            rows.append("mắt %s: quay %.2f + khép %.2f -- con ngươi hở "
                        "%.0f%% -> %.0f%%, khẩu độ %.0f%% -> %.0f%% "
                        "| gập ngược %.0f%%, giãn p99 %.2f"
                        % (sfx, best_sw, best_cv, base_cv * 100, f_cover * 100,
                           base_ap * 100, f_aper * 100, f_flip * 100, f_str))
    finally:
        face.shape_key_remove(probe)
        sk = face.data.shape_keys
        if sk is not None:
            for kb in sk.key_blocks:
                if kb.name in old:
                    kb.value = old[kb.name]
        context.view_layer.update()
    return angles, rows, cover




# ================== HỢP ĐỒNG: VÙNG PHẢI THOẢ GÌ, SHAPE KEY PHẢI LÀM ĐƯỢC GÌ
#
# Bốn lỗi nặng của ngày 20-21/08 đều là CÙNG MỘT KIỂU SAI, lặp lại bốn lần. Ghi
# ra đây vì cái đắt không phải từng lỗi, mà là cái kiểu:
#
#   1. ĐO BẰNG THƯỚC NỘI BỘ CỦA CÔNG THỨC. `_pair_gap` đo khoảng cách giữa hai
#      nhóm vertex mí -- đúng cái mà công thức được thiết kế để giảm. Nó chấm
#      "khép 54%%, ĐẠT" trong khi con ngươi hở 26%%.
#   2. BẤT BIẾN ĐÚNG NHƯNG KHÔNG LIÊN QUAN. `eyeball_guard` cấm da nằm TRONG
#      nhãn cầu và báo 0 lượt -- thật. Nhưng mí trượt RA SAU nhãn cầu, không đâm
#      lần nào mà con ngươi vẫn lồ lộ. Cấm xuyên không phải là cấm bị che.
#   3. TỐI ƯU MỘT SỐ, LÀM HỎNG SỐ KHÁC. Bản 1.3.0 hạ che phủ xuống 6%% và làm
#      17%% đa giác mí gập ngược. Không ai canh con số thứ hai.
#   4. BẢO ĐẢM Ở THƯỢNG NGUỒN BỊ HẠ NGUỒN XOÁ. `smooth_field` ăn mất công của
#      mí (5%% -> 15%%); `cap_stretch` và chốt chặn cũng dời vertex sau đó.
#
# Nên hợp đồng ở đây theo bốn nguyên tắc ngược lại:
#
#   * Chỉ chấm bằng thứ NGƯỜI XEM THẤY (tia bắn vào con ngươi), không bằng tham
#     số của chính công thức.
#   * Chấm NHIỀU tiêu chí cùng lúc; đạt một cái mà hỏng cái kia là KHÔNG đạt.
#   * Chấm trên mesh ĐÃ TÍNH, sau khi mọi bước hạ nguồn đã chạy xong -- tức đúng
#     thứ được ghi vào file.
#   * Chấm cả GIÁ TRỊ LƯNG CHỪNG và TỔ HỢP, không chỉ từng key ở 1.0. Shape key
#     cộng tuyến tính nên hai chuyện đó là hai nguồn lỗi riêng.
#
# Hợp đồng KHÔNG chặn việc dựng (anh Art chốt 21/08): nhân vật hình khó vẫn phải
# dùng được, chỉ là phải BIẾT mình đang dùng cái gì.

CONTRACT_STEPS = (0.0, 0.25, 0.5, 0.75, 1.0)
CONTRACT_SLACK = 0.02      # sai số cho phép khi xét tính đơn điệu
# Lún nông hơn ngần này lần bán kính nhãn cầu thì bỏ qua: da mí vốn ôm sát mặt
# cầu (phân vị 25 chỉ cách 0,4 mm), nên đếm từng phần mười mm là kêu suốt ngày
# về thứ không ai nhìn thấy. Đếm cả `EYE_Wide` vào diện "hở thêm" cũng sai --
# mở to mắt thì con ngươi PHẢI hở thêm, đó là công năng chứ không phải lỗi.
CONTRACT_DEEP = 0.05


HOLE_NEAR = 1.2     # vòng biên nằm trong ngần này lần bán kính = lỗ của mắt đó


def region_invariants(context, face):
    """Những điều một vùng mí PHẢI thoả, kiểm ngay lúc tạo ra nó.

    Bất biến quan trọng nhất -- và là thứ lẽ ra bắt được lỗi bốn mắt ngay ngày
    đầu: MỌI VERTEX TRONG VÙNG MÍ CỦA MẮT N PHẢI CÓ MẮT N LÀ NHÃN CẦU GẦN NHẤT.
    Một vùng mí không phải "một đám vertex quanh mắt"; nó là phần da TRƯỢT TRÊN
    đúng một nhãn cầu, và đó là thứ kiểm được bằng một dòng.
    """
    rows = []
    pairs = eye_pairs(context, face)
    if not pairs:
        return rows
    base = base_coords(face)
    cen = {(i, s): (c, r) for i, s, _o, c, r in pairs}

    for inst, side in eye_slots(face):
        sfx = eye_suffix(inst, side)
        if (inst, side) not in cen:
            rows.append(('CẢNH BÁO', 'FS_Lid' + sfx,
                         "có nhóm mí nhưng không có mesh nhãn cầu nào chỉ tới "
                         "-- không chấm được che phủ, mí sẽ dựng bằng đường lui"))
            continue
        reg = {}
        for fam in ('FS_LidUpper', 'FS_LidLower'):
            part = read_region(face, fam + sfx)
            if len(part) < MIN_REGION:
                rows.append(('HỎNG', fam + sfx,
                             "chỉ có %d vertex, cần ít nhất %d -- tô rộng thêm"
                             % (len(part), MIN_REGION)))
            reg.update(part)
        if not reg:
            continue

        stray = 0
        for i in reg:
            near = min(cen, key=lambda k: (base[i] - cen[k][0]).length - cen[k][1])
            if near != (inst, side):
                stray += 1
        if stray:
            rows.append(('HỎNG', 'FS_Lid' + sfx,
                         "%d/%d vertex nằm gần một con mắt KHÁC -- nhóm mí đang "
                         "ôm nhiều hơn một nhãn cầu, khe mí sẽ rơi lọt giữa hai "
                         "mắt. Bấm 'Đánh dấu vùng mặt' để tách"
                         % (stray, len(reg))))

        u_reg = read_region(face, 'FS_LidUpper' + sfx)
        l_reg = read_region(face, 'FS_LidLower' + sfx)
        if u_reg and l_reg:
            regions = {n: read_region(face, n) for n, _p, _r in region_table(face)}
            frame = FaceFrame(face, regions, base)
            if frame.ok and not PairFrame(u_reg, l_reg, base, frame).ok:
                rows.append(('HỎNG', 'FS_Lid' + sfx,
                             "không dựng nổi hệ trục cho cặp mí này -- hai nhóm "
                             "trùng nhau hoàn toàn?"))

    # --- LỖ MẮT PHẢI CÓ CHỦ ------------------------------------------------
    # Mesh khoét lỗ ở mắt thì "nhắm mắt" nghĩa là KHÉP CÁI LỖ, và cả bộ dựng lẫn
    # hợp đồng đều chuyển sang đo khẩu độ. Nhưng chuyển thế nào? Bằng cách hỏi
    # mép lỗ có nằm trong nhóm mí không. Nhóm tô hụt vài vertex ở mép là lỗ
    # KHÔNG được nhận, cả bộ lặng lẽ tụt về đo che phủ nhãn cầu, và cái lỗ không
    # bao giờ khép -- đúng kiểu hỏng đắt nhất: không ai báo gì cả.
    regions = {n: read_region(face, n) for n, _p, _r in region_table(face)}
    loops = [h for h in mesh_holes(face) if len(h) >= 3]
    claimed = eye_holes(face, regions)
    for inst, side in eye_slots(face):
        if (inst, side) not in cen:
            continue
        c, r = cen[(inst, side)]
        sfx = eye_suffix(inst, side)
        reg = set(regions.get('FS_LidUpper' + sfx, {})) \
            | set(regions.get('FS_LidLower' + sfx, {}))
        got = claimed.get((inst, side))
        if got is not None:
            miss = len(got - reg)
            if miss:
                rows.append(('CẢNH BÁO', 'FS_Lid' + sfx,
                             "%d/%d vertex MÉP LỖ nằm ngoài nhóm mí -- bộ dựng "
                             "vẫn kéo chúng theo (mép lỗ là mép mí theo định "
                             "nghĩa) nhưng trọng số ở đó là đoán, không phải do "
                             "anh tô. Tô nhóm mí phủ hết mép lỗ thì chắc hơn"
                             % (miss, len(got))))
            continue
        for h in loops:
            if not all((base[i] - c).length <= r * HOLE_NEAR for i in h):
                continue
            rows.append(('HỎNG', 'FS_Lid' + sfx,
                         "mesh có LỖ ở đúng chỗ con mắt này (%d vertex mép) "
                         "nhưng chỉ %d trong số đó nằm trong nhóm mí -- lỗ sẽ "
                         "không được nhận, mí chấm bằng che phủ nhãn cầu và "
                         "cái lỗ KHÔNG BAO GIỜ KHÉP. Tô nhóm mí phủ hết mép lỗ"
                         % (len(h), len(h & reg))))
            break
    return rows


def eye_contract(context, face, presets=None):
    """Chấm bộ key mắt ĐÃ GHI, đo trên mesh ĐÃ TÍNH. Trả về list dòng báo cáo.

    Chạy sau khi key đã nằm trên mesh, nên nó chấm đúng thứ sẽ dùng -- kể cả
    phần mà làm mượt, chốt giãn cạnh và chốt chặn nhãn cầu đã sửa lại.
    """
    rows = []
    sk = face.data.shape_keys
    pairs = eye_pairs(context, face)
    if sk is None or not pairs:
        return rows

    regions = {n: read_region(face, n) for n, _p, _r in region_table(face)}
    base = base_coords(face)
    frame = FaceFrame(face, regions, base)
    if not frame.ok:
        return rows
    # Chấm trên ĐÚNG bộ vùng bộ dựng đã dùng, tức bản ĐÃ VUỐT MỀM. Đọc lại nhóm
    # thô rồi chấm là đo trên một hệ trục khác hệ trục đã dựng: cùng một con mắt
    # ra 9% hay 15% tuỳ chọn hệ nào. Sai lệch nhỏ nhưng đúng kiểu đã trả giá --
    # thước phải đo cùng thứ mà bộ dựng làm ra.
    st = getattr(context.scene, "face_shapes", None)
    if st is not None:
        regions = soften_regions(face, regions, st.soften)
    view = (face.matrix_world.to_3x3() @ frame.fwd).normalized()
    shields = eyeball_shields(context, face)

    # Có lỗ mắt thì thước là KHẨU ĐỘ, không phải che phủ nhãn cầu. Hai thứ đó
    # từng lệch nhau đúng một lần và nó tốn hai ngày: mảng da mí trượt ra TRƯỚC
    # nhãn cầu, che nó tới 98%, mà cái lỗ vẫn mở toang -- nhìn xuyên vào trong
    # đầu. Che phủ báo ĐẠT, mắt thì hỏng. Giấu nhãn cầu đi rồi nhìn là thấy.
    holes = eye_holes(face, regions)
    hframe = {}
    for kk in holes:
        sfx = eye_suffix(*kk)
        ef = PairFrame(regions.get('FS_LidUpper' + sfx, {}),
                       regions.get('FS_LidLower' + sfx, {}), base, frame)
        if not ef.ok:
            continue
        a_h, b_h = seam_line(regions.get('FS_LidUpper' + sfx, {}),
                             regions.get('FS_LidLower' + sfx, {}), ef, base)
        hframe[kk] = (ef, a_h, b_h, {i: ef.sc(base[i])[0] for i in holes[kk]})
    hrest = {}

    def gap_now(kk):
        """Bề rộng lỗ mắt lúc này, đo trên mesh ĐÃ TÍNH, SO VỚI đường khe."""
        dg = context.evaluated_depsgraph_get()
        me = face.evaluated_get(dg).data
        ef, a_h, b_h, s0 = hframe[kk]
        vals = [ef.sc(me.vertices[i].co)[1] - (a_h + b_h * s0[i])
                for i in holes[kk] if i < len(me.vertices)]
        return (max(vals) - min(vals)) if len(vals) >= 2 else 0.0

    def what(kk):
        return "khẩu độ" if kk in hrest else "con ngươi"

    keep = {kb.name: kb.value for kb in sk.key_blocks}

    def apply(vals):
        for kb in sk.key_blocks:
            kb.value = 0.0
        for nm, v in vals:
            if nm in sk.key_blocks:
                sk.key_blocks[nm].value = v
        context.view_layer.update()

    def seen():
        """{(số thứ tự, bên): tỉ lệ CÒN HỞ} -- khẩu độ nếu có lỗ, không thì che phủ."""
        out = {}
        for i, s, o, _c, _r in pairs:
            r0 = hrest.get((i, s))
            if r0:
                out[(i, s)] = gap_now((i, s)) / r0
            else:
                out[(i, s)] = eyeball_uncovered(context, face, o, view) or 0.0
        return out

    def dug():
        """(số vertex mí lún vào nhãn cầu, mét sâu nhất) trên mesh đã tính."""
        dg = context.evaluated_depsgraph_get()
        me = face.evaluated_get(dg).data
        cnt, deep = 0, 0.0
        for sh in shields.values():
            floor = sh.r * CONTRACT_DEEP
            for i in lid_ids:
                if i >= len(me.vertices):
                    continue
                pr = sh.probe(me.vertices[i].co)
                if pr is None:
                    continue
                over = pr[0] - rest_deep.get((id(sh), i), 0.0)
                if over > floor:
                    cnt += 1
                    deep = max(deep, over)
        return cnt, deep

    lid_ids = set()
    for inst, side in eye_slots(face):
        sfx = eye_suffix(inst, side)
        lid_ids |= set(regions.get('FS_LidUpper' + sfx, {}))
        lid_ids |= set(regions.get('FS_LidLower' + sfx, {}))

    try:
        apply([])
        dgp = context.evaluated_depsgraph_get()
        rest_mesh = face.evaluated_get(dgp).data
        rest_deep = {}
        for sh in shields.values():
            for i in lid_ids:
                if i >= len(rest_mesh.vertices):
                    continue
                pr = sh.probe(rest_mesh.vertices[i].co)
                rest_deep[(id(sh), i)] = max(pr[0], 0.0) if pr else 0.0
        for kk in hframe:
            g = gap_now(kk)
            if g > 1e-9:
                hrest[kk] = g
        wide = seen()

        # --- 1. che phủ + đơn điệu theo slider, TỪNG CON MẮT
        for side in ('L', 'R'):
            key = 'EYE_Blink%s' % side
            if key not in sk.key_blocks:
                continue
            curve = []
            for v in CONTRACT_STEPS:
                apply([(key, v)])
                curve.append(seen())
            for inst, s in [(i, s) for i, s, _o, _c, _r in pairs if s == side]:
                seq = [c[(inst, s)] for c in curve]
                sfx = eye_suffix(inst, s)
                lvl = ('ĐẠT' if seq[-1] <= GOAL_COVER
                       else 'HỎNG' if seq[-1] >= seq[0] else 'CẢNH BÁO')
                rows.append((lvl, key, "mắt %s: %s hở %s%% (cần cuối "
                                       "<= %.0f%%)"
                             % (sfx, what((inst, s)),
                                " -> ".join("%.0f" % (x * 100) for x in seq),
                                GOAL_COVER * 100)))
                bad = [i for i in range(1, len(seq))
                       if seq[i] > seq[i - 1] + CONTRACT_SLACK]
                if bad:
                    rows.append(('HỎNG', key,
                                 "mắt %s: KHÔNG đơn điệu -- nhắm thêm mà %s "
                                 "lại hở thêm ở mức %s. Đây là ca hay gặp "
                                 "nhất và mắt thường chỉ nhìn ra khi diễn"
                                 % (sfx, what((inst, s)),
                                    ", ".join("%.2f" % CONTRACT_STEPS[i]
                                              for i in bad))))

        # --- 1b. KHÉP LỖ THÔI CHƯA ĐỦ: nhãn cầu cũng phải bị che
        #
        # Mép lỗ nằm SAU mặt cầu, nên khép nó lại là khép ở chỗ không ai nhìn
        # thấy -- người xem vẫn thấy đúng quầng nhãn cầu như cũ. Anh Art bấm
        # "Nhắm mắt" và mắt mở trân trân, đúng lúc bảng điểm báo khẩu độ 10%.
        # Hai thước, hai chuyện; thiếu thước nào cũng ra một bộ key nhìn hỏng.
        for side in ('L', 'R'):
            key = 'EYE_Blink%s' % side
            if key not in sk.key_blocks:
                continue
            apply([])
            was = {(i, s): (eyeball_uncovered(context, face, o, view) or 0.0)
                   for i, s, o, _c, _r in pairs if s == side}
            apply([(key, 1.0)])
            now = {(i, s): (eyeball_uncovered(context, face, o, view) or 0.0)
                   for i, s, o, _c, _r in pairs if s == side}
            for kk in sorted(was):
                o, c = was[kk], now[kk]
                lvl = ('ĐẠT' if c <= max(o * GOAL_SEEN, GOAL_COVER)
                       else 'HỎNG' if c >= o - CONTRACT_SLACK else 'CẢNH BÁO')
                rows.append((lvl, key, "mắt %s: con ngươi hở %.0f%% -> %.0f%% "
                                       "(nhắm hết cỡ phải che bớt ít nhất "
                                       "%.0f%%)"
                             % (eye_suffix(*kk), o * 100, c * 100,
                                (1.0 - GOAL_SEEN) * 100)))

        # --- 2. nheo không được banh mắt ra
        for side in ('L', 'R'):
            key = 'EYE_Squint%s' % side
            if key not in sk.key_blocks:
                continue
            apply([(key, 1.0)])
            now = seen()
            for inst, s in [(i, s) for i, s, _o, _c, _r in pairs if s == side]:
                sfx = eye_suffix(inst, s)
                o, c = wide[(inst, s)], now[(inst, s)]
                lvl = 'ĐẠT' if c <= o + CONTRACT_SLACK else 'HỎNG'
                rows.append((lvl, key, "mắt %s: %s hở %.0f%% -> %.0f%% "
                                       "(nheo không được hở thêm)"
                             % (sfx, what((inst, s)), o * 100, c * 100)))

        # --- 3. lưới mí phải sạch, đo trên CHÍNH key đã ghi
        polys = region_polys(face, lid_ids) if lid_ids else []
        edges = region_edges(face, base, lid_ids) if lid_ids else []
        basis = sk.key_blocks['Basis']
        for key in ('EYE_BlinkL', 'EYE_BlinkR', 'EYE_SquintL', 'EYE_SquintR'):
            kb = sk.key_blocks.get(key)
            if kb is None:
                continue
            d = {}
            for i in lid_ids:
                v = kb.data[i].co - basis.data[i].co
                if v.length > 1e-9:
                    d[i] = v
            if not d:
                continue
            pk = [p for p in polys if all(x in d for x in p)]
            ek = [e for e in edges if e[0] in d or e[1] in d]
            fl = (flipped(pk, d, base, 1.0) / float(len(pk))) if pk else 0.0
            sx = _stretch(d, ek, base, 1.0) if ek else 1.0
            lvl = ('ĐẠT' if fl <= LID_FLIP_MAX and sx <= LID_STRETCH_MAX
                   else 'CẢNH BÁO')
            rows.append((lvl, key, "lưới mí: %.0f%% đa giác gập ngược (trần "
                                   "%.0f%%), giãn cạnh p99 %.2f (trần %.2f)"
                         % (fl * 100, LID_FLIP_MAX * 100, sx, LID_STRETCH_MAX)))

        # --- 4. TỔ HỢP: shape key cộng tuyến tính nên chấm riêng từng cái không đủ
        scale = max(face.matrix_world.to_scale())
        for name, vals in (presets or ()):
            apply(list(vals.items()))
            now = seen()
            cnt, deep = dug()
            # Mẫu nào cố ý MỞ TO mắt thì con ngươi phải hở thêm -- đó là công
            # năng. Chỉ xét "hở thêm" ở những mẫu không dùng `EYE_Wide`.
            opens = any(k.startswith('EYE_Wide') and v > 0.0
                        for k, v in vals.items())
            worse = [] if opens else [
                eye_suffix(i, s) for (i, s) in sorted(now)
                if now[(i, s)] > wide[(i, s)] + CONTRACT_SLACK]
            note = []
            if worse:
                note.append("con ngươi hở thêm ở mắt " + ", ".join(worse))
            if cnt:
                note.append("%d vertex mí lún vào nhãn cầu, sâu nhất %.1f mm"
                            % (cnt, deep * scale * 1000))
            if note:
                rows.append(('CẢNH BÁO', "tổ hợp " + name, " | ".join(note)))
    finally:
        for kb in sk.key_blocks:
            if kb.name in keep:
                kb.value = keep[kb.name]
        context.view_layer.update()
    return rows


def eyeball_shields(context, face):
    """{(số thứ tự, bên): _Shield} cho từng nhãn cầu RỜI của khuôn mặt này.

    Tách ra khỏi `eyeball_guard` vì giờ có hai chỗ cần: chốt chặn (chạy cuối,
    sửa lại chỗ đã lún) và `lid()` (chạy đầu, dùng chính mặt cầu để ĐỊNH HÌNH
    đường đi). Dựng BVH tốn tiền nên chỉ dựng một lần cho cả bộ key.
    """
    Z = Vector((0.0, 0.0, 0.0))
    inv = face.matrix_world.inverted()
    out = {}
    mine = eye_meshes_for(context, face) if context else []
    if not mine:
        return out
    dg = bpy.context.evaluated_depsgraph_get()
    count = {}
    for side, obj, _c, _r in mine:
        me, own = eval_mesh(obj, dg)
        try:
            M = inv @ obj.matrix_world
            vts = [M @ v.co for v in me.vertices]
            tris = []
            for poly in me.polygons:
                vs = list(poly.vertices)
                for k in range(1, len(vs) - 1):
                    tris.append((vs[0], vs[k], vs[k + 1]))
        finally:
            if own is not None:
                own.to_mesh_clear()
        count[side] = count.get(side, 0) + 1
        if len(vts) < 4 or not tris:
            continue
        c = sum(vts, Z) / len(vts)
        out[(count[side], side)] = _Shield(
            c, max((p - c).length for p in vts),
            tree=BVHTree.FromPolygons(vts, tris, all_triangles=True))
    return out


# --------------------------- MÍ TRƯỢT TRÊN NHÃN CẦU, không đi thẳng rồi bị đẩy
#
# `eyeball_guard` là sửa SAU: mí đi thẳng, lún vào nhãn cầu, rồi bị đẩy ngược ra
# theo pháp tuyến. Cứu được, nhưng cái bị đẩy ra không còn là đường đi đã hiệu
# chỉnh nữa -- và với tổ hợp nhiều key thì nó không cứu nổi (đo được: mẫu "Buồn"
# vẫn thêm 2 vertex vào trong).
#
# Cách đúng hơn, anh Art đề xuất 2026-08-20: dùng chính mesh con ngươi để ĐỊNH
# HÌNH biên độ. Mí mắt thật là một cái vỏ TRƯỢT TRÊN quả cầu, và nó quay quanh
# đúng cái tâm mà nhãn cầu quay quanh. Cho vertex mí quay quanh tâm nhãn cầu
# thay vì đi thẳng thì khoảng cách tới tâm không đổi -- tức KHÔNG THỂ lún vào,
# không phải "lún rồi được cứu".
#
# Quãng đường giữ nguyên: góc quay = |độ dịch đã hiệu chỉnh| / bán kính tới tâm,
# nên vertex đi đúng ngần ấy mét, chỉ khác là đi theo CUNG chứ không theo dây.
# Mọi con số hiệu chỉnh trước đây (đường khe, chuẩn hoá trọng số, `scale_lid`)
# vẫn nguyên giá trị.
#
# Chỉ áp cho vertex ĐỦ GẦN nhãn cầu. Rìa ngoài vùng mí nằm cách mặt cầu gần một
# bán kính -- đó là da hốc mắt, nó không trượt trên nhãn cầu, và bắt nó quay
# quanh tâm mắt là bẻ cong một đường đi vốn đã đúng.
# ĐÃ THỬ VÀ BỎ -- dùng mesh con ngươi để CHẶN TỪ ĐẦU thay vì sửa sau.
#
# Anh Art hỏi đúng câu đáng hỏi (2026-08-20): sao không lấy chính mesh con ngươi
# đã chọn ở bước 1 mà định hình biên độ mí, để không bao giờ có gì phải cứu? Đã
# dựng và đo cả hai cách hiểu của câu đó, trên `Mesh_0.001`, cường điệu 150%:
#
#   (1) TRƯỢT TRÊN MẶT CẦU -- cho vertex mí quay quanh tâm nhãn cầu thay vì đi
#       thẳng, giữ nguyên độ dài quãng đường. Về lý thì khoảng cách tới tâm
#       không đổi nên "không thể lún vào".
#   (2) KẸP QUÃNG ĐƯỜNG -- giữ nguyên hướng đã hiệu chỉnh, chỉ cắt ngắn quãng
#       đi ở đúng chỗ vertex chạm mặt nhãn cầu.
#
#                              khép mí        đâm vào      giãn cạnh mí
#   đi thẳng, không chốt      60,3 / 59,7    30 lượt        1,66 / 1,87
#   đi thẳng + CHỐT CHẶN      59,5 / 58,7     0 lượt        1,66 / 1,87   <-- giữ
#   (1) trượt, không chốt     55,7 / 53,6    34 lượt        1,66 / 2,29
#   (2) kẹp, không chốt       50,2 / 47,7    38 lượt        1,66 / 1,88
#   (2) kẹp + chốt chặn       47,9 / 47,6     0 lượt        1,66 / 1,88
#
# Sau lượt trên đo trên nhóm vùng THÔ (tắt vuốt mềm viền) để chúng so được với
# nhau; bật vuốt mềm thì cả sáu cùng tụt khoảng 5 điểm khép mí, thứ hạng không
# đổi. Cột "đâm vào" đếm trên cả 56 shape key × 4 nhãn cầu.
#
# Cả hai đều THUA trên mọi cột, và -- điều quyết định -- **cả hai vẫn đâm vào
# nhãn cầu**, đúng thứ chúng sinh ra để chặn.
#
# Lý do nằm ở THỨ TỰ: sau `lid()` còn `smooth_field()` (lấy trung bình với láng
# giềng) rồi `cap_stretch()` (nhân đều cả trường độ dịch). Hai bước đó dời
# vertex lần nữa, nên mọi bảo đảm hình học dựng trong `lid()` đều bị phá ở hạ
# nguồn. Trong một chuỗi như thế, **chỗ duy nhất bảo đảm được là chỗ CUỐI CÙNG**
# -- và đó chính là `eyeball_guard`.
#
# Còn cái giá thì ngược lại với trực giác: chốt chặn chỉ tốn 0,8 điểm khép mí,
# không đổi độ giãn, và ra tay đúng 36 lượt trên cả 56 shape key. Chặn từ đầu
# tốn 4,6 điểm (trượt) tới 11,7 điểm (kẹp) vì nó cắt ngắn quãng đi của đúng
# những vertex làm nhiệm vụ che, rồi làm mượt đem phần hụt đó lan sang hàng xóm.
#
# Muốn chặn từ đầu THẬT thì phải đổi kiến trúc: làm mượt và chốt giãn cạnh phải
# biết về nhãn cầu, hoặc lặp cả ba bước tới khi hội tụ. Chưa đáng, vì chốt chặn
# hiện tại đã cho 0 lượt đâm.


def eyeball_guard(context, face, regions, base, R, clear=EYE_CLEAR,
                  shields=None):
    """Không cho shape key nào làm NHÃN CẦU LÒI RA chỗ lúc nghỉ nó không lòi.

    Chạy SAU chốt chặn giãn cạnh, và là tiếng nói cuối cùng: chốt chặn nhân đều
    cả trường độ dịch nên nó có thể kéo một vertex đã được cứu chui vào lại.

    Bất biến là **vertex NGOÀI nhãn cầu lúc nghỉ thì không được chui vào**. Nói
    "không sâu hơn lúc nghỉ" nghe chặt hơn nhưng SAI, và cái sai đó đắt: mép lỗ
    mắt của `Mesh_0.001` nằm sẵn 4,6-14,4 mm TRONG quả cầu bán kính 23,4 mm
    (vành mắt cuộn vào sau nhãn cầu -- hoàn toàn đúng về giải phẫu). Khép mí đẩy
    chúng sâu thêm 2-4 mm, luật cũ lôi ngược ra, và khẩu độ mắt bật từ 10% lên
    26%. Lôi ra chẳng được gì: quả cầu đục, vertex nằm sau mặt cầu thì đi sâu
    thêm bao nhiêu cũng vẫn khuất. Thứ PHẢI chặn là vertex đang ở NGOÀI mà chui
    vào -- đúng lúc đó nhãn cầu mới thò qua da.

    Trả về {tên key: (số vertex đã đẩy ra, mét sâu nhất đã cứu)}.
    """
    Z = Vector((0.0, 0.0, 0.0))
    if shields is None:
        shields = eyeball_shields(context, face)
    fixed = list(shields.values())    # nhãn cầu là object riêng -- đứng yên

    # Nhãn cầu NẰM TRONG mesh mặt thì chính nó cũng co và thụt theo `eyeball()`,
    # nên hình chặn phải lấy vị trí ĐÃ DỊCH của nó -- và ở đó mặt cầu là đúng,
    # vì `eyeball()` co đều theo bán kính.
    balls = [reg for nm, reg in regions.items()
             if nm.startswith('FS_Eyeball') and len(reg) >= 4]
    own = set()
    for reg in balls:
        own |= set(reg)
    if not fixed and not balls:
        return {}

    cand = []
    for sh in fixed:
        lim = sh.r * EYE_NEAR
        cand.append([i for i in range(len(base))
                     if i not in own and (base[i] - sh.c).length <= lim])

    rest = {}
    report = {}
    for name in R:
        d = R[name]
        if not d:
            continue
        shields = list(zip(fixed, cand))
        for reg in balls:
            pts = [base[i] + d.get(i, Z) for i in reg]
            c = sum(pts, Z) / len(pts)
            sh = _Shield(c, max((p - c).length for p in pts))
            lim = sh.r * EYE_NEAR
            # Ứng viên đo trên vị trí NGHỈ của nhãn cầu: hình chặn di động thì
            # tập ứng viên không được đổi theo key, không thì cùng một vertex
            # lúc bị canh lúc không.
            c0 = sum((base[i] for i in reg), Z) / len(reg)
            shields.append((sh, [i for i in range(len(base))
                                 if i not in own and (base[i] - c0).length <= lim]))

        touched, deepest, left = set(), 0.0, 0
        for step in range(EYE_PASSES):
            left = 0
            for k, (sh, idx) in enumerate(shields):
                floor = -sh.r * clear
                for i in idx:
                    if i not in d:
                        continue
                    if k < len(fixed):
                        if (k, i) not in rest:
                            r0 = fixed[k].probe(base[i])
                            rest[(k, i)] = None if r0 is None else r0[0]
                        d0 = rest[(k, i)]
                    else:
                        r0 = sh.probe(base[i])
                        d0 = None if r0 is None else r0[0]
                    if d0 is None or d0 > 0.0:
                        # NGHỈ ĐÃ NẰM TRONG NHÃN CẦU -> miễn. Quả cầu đục, nó
                        # đứng sau mặt cầu nên không ai nhìn thấy; đi sâu thêm
                        # vẫn không thấy. Luật cũ "không sâu hơn lúc nghỉ" giữ
                        # chúng ở đúng độ sâu cũ, và đó chính là thứ banh cái lỗ
                        # mắt ra lại.
                        continue
                    pr = sh.probe(base[i] + d[i])
                    if pr is None:
                        continue
                    depth, outward = pr
                    allow = max(d0, floor)
                    if depth > allow + 1e-9:
                        d[i] = d[i] + outward * (depth - allow)
                        touched.add(i)
                        left += 1
                        if step == 0:
                            deepest = max(deepest, depth - allow)
            if not left:
                break
        if touched:
            report[name] = (len(touched), deepest, left)
    return report

CORE_W = 0.5        # trọng số coi là "lõi" khi tìm ranh giới trên/dưới
PCTL = 0.85         # phân vị dùng cho bề rộng, cắt đuôi trọng số thấp lan ra má


def read_region(face, name, min_w=0.01):
    """{chỉ số vertex: trọng số} của một nhóm vùng."""
    g = face.vertex_groups.get(name)
    if g is None:
        return {}
    out = {}
    gi = g.index
    for v in face.data.vertices:
        for gg in v.groups:
            if gg.group == gi and gg.weight > min_w:
                out[v.index] = gg.weight
    return out


def base_coords(face):
    """Toạ độ gốc của mesh.

    Đọc từ Basis khi có: build_from_regions() ghi shape key theo `Basis + dịch`,
    nên `base` phải chính là Basis. Trước đây luôn dùng `mesh.vertices` vì bộ
    dựng xoá sạch shape key trước khi làm nên hai thứ chắc chắn trùng nhau; giờ
    giữ lại key làm tay thì Basis có thể đã bị nắn khác đi.
    """
    key = face.data.shape_keys
    if key is not None and 'Basis' in key.key_blocks:
        return [p.co.copy() for p in key.key_blocks['Basis'].data]
    return [v.co.copy() for v in face.data.vertices]


def merged(regions, *names):
    out = {}
    for n in names:
        for i, w in regions.get(n, {}).items():
            out[i] = max(out.get(i, 0.0), w)
    return out


class FaceFrame:
    """Hệ trục khuôn mặt, suy ra từ chính các vùng -- không giả định +Z là trên.

    lat : sang phía .L của nhân vật
    up  : từ miệng lên mắt
    fwd : hướng mặt nhìn ra, xác định bằng pháp tuyến trung bình của vùng mặt
    """

    def __init__(self, face, regions, base):
        def centroid(reg):
            if not reg:
                return None
            s = Vector((0, 0, 0)); t = 0.0
            for i, w in reg.items():
                s += base[i] * w; t += w
            return s / t if t else None

        mo = centroid(merged(regions, 'FS_LipUpper', 'FS_LipLower'))
        eL = centroid(lids_of(regions, 'L'))
        eR = centroid(lids_of(regions, 'R'))
        self.ok = mo is not None
        if not self.ok:
            return

        if eL is not None and eR is not None:
            lat = (eL - eR).normalized()
            eye_c = (eL + eR) * 0.5
        else:
            # không có vùng mí: lấy trục ngang từ chính bề ngang của môi
            reg = merged(regions, 'FS_LipUpper', 'FS_LipLower')
            far = max(reg, key=lambda i: (base[i] - mo).length)
            lat = base[far] - mo
            lat = lat.normalized() if lat.length > 1e-9 else Vector((1, 0, 0))
            eye_c = mo + Vector((0, 0, 1))

        up = eye_c - mo
        up = (up - lat * up.dot(lat)).normalized()
        fwd = lat.cross(up).normalized()

        n = Vector((0, 0, 0))
        for src in (regions.get('FS_LipUpper', {}), regions.get('FS_LipLower', {}),
                    all_lids(regions, ('FS_LidUpper',))):
            for i in src:
                n += face.data.vertices[i].normal
        if n.length > 1e-9 and fwd.dot(n) < 0:
            fwd = -fwd

        self.lat, self.up, self.fwd, self.origin = lat, up, fwd, mo

    def uvw(self, p):
        d = p - self.origin
        return Vector((d.dot(self.lat), d.dot(self.up), d.dot(self.fwd)))

    def world(self, u=0.0, v=0.0, w=0.0):
        return self.lat * u + self.up * v + self.fwd * w


def weighted_half(reg, frame, base, q=PCTL):
    """Nửa bề ngang của vùng, lấy theo phân vị có trọng số của |u|.

    Không lấy |u| lớn nhất: vertex group da luôn có đuôi trọng số thấp lan ra má,
    làm bề rộng phồng lên hơn 2 lần (đo được 0.112 trong khi khóe miệng thật ở
    0.049), khiến shape mở miệng quá mạnh và shape cười quá yếu.
    """
    if not reg:
        return 1e-9
    su = sorted((abs(frame.uvw(base[i]).x), w) for i, w in reg.items())
    tot = sum(w for _, w in su) or 1e-9
    run = 0.0
    for u, w in su:
        run += w
        if run >= tot * q:
            return max(u, 1e-9)
    return max(su[-1][0], 1e-9)


def pair_metrics(upper, lower, frame, base):
    """Ranh giới và bề rộng của một cặp vùng trên/dưới (môi, hoặc mí một bên)."""
    vu = [frame.uvw(base[i]).y for i, w in upper.items() if w > CORE_W]
    vl = [frame.uvw(base[i]).y for i, w in lower.items() if w > CORE_W]
    both = merged({'a': upper, 'b': lower}, 'a', 'b')
    allv = [frame.uvw(base[i]).y for i in both]
    if vu and vl:
        seam = (min(vu) + max(vl)) * 0.5
    elif allv:
        seam = (min(allv) + max(allv)) * 0.5
    else:
        seam = 0.0
    span = (max(allv) - min(allv)) if allv else 1e-9
    return {'seam': seam, 'half': weighted_half(both, frame, base),
            'span': max(span, 1e-9)}


class PairFrame:
    """Hệ trục RIÊNG của một cặp vùng trên/dưới -- môi, hoặc mí một bên mắt.

    Bản đầu dùng chung một hệ trục cho cả khuôn mặt: mí luôn khép theo trục 'up'
    của mặt, miệng luôn há theo 'down'. Đúng với mặt người vì mắt nằm ngang và
    khe môi cũng ngang, nhưng SAI với mõm thú. Đo trên đầu sói của Dogs.blend:
    trục dài của hốc mắt nghiêng 44.9 độ so với phương ngang và còn xoay ra
    ngoài 14.7 độ. Khép mí theo 'up' toàn cục ở góc đó nghĩa là mí trượt CHÉO
    qua nhãn cầu chứ không sập xuống che nó.

    close : hướng khép = centroid(nửa trên) - centroid(nửa dưới). Đo từ chính
            hai nửa của khe nên đúng với mọi giải phẫu, không cần biết con vật.
    along : dọc theo khe, là phương trải rộng nhất còn lại sau khi bỏ close.
    out   : pháp tuyến của khe.

    Trên mặt người, close tự ra ≈ up và along ≈ lat, nên kết quả không đổi.
    """

    def __init__(self, upper, lower, base, frame):
        def cen(reg):
            s = Vector((0, 0, 0))
            t = 0.0
            for i, w in reg.items():
                s += base[i] * w
                t += w
            return (s / t) if t else None

        both = merged({'a': upper, 'b': lower}, 'a', 'b')
        self.ok = len(both) >= 3
        if not self.ok:
            return
        pts = [base[i] for i in both]
        self.origin = sum(pts, Vector((0, 0, 0))) / len(pts)

        cu, cl = cen(upper), cen(lower)
        close = (cu - cl) if (cu is not None and cl is not None) else None
        if close is None or close.length < 1e-7:
            close = frame.up.copy()
        # ĐÃ THỬ VÀ BỎ: gọt bớt thành phần theo pháp tuyến trung bình của vùng,
        # với lý lẽ "mí trượt trên da chứ không thọc vào trong". Đo lại thì nó
        # không cải thiện gì (phần trượt dọc khe 30%% -> 31%%) vì pháp tuyến trung
        # bình của một vùng cong không phải pháp tuyến của khe. Hiệu hai centroid
        # để nguyên là đủ và đúng.
        self.close = close.normalized()

        # along: vector riêng lớn nhất của ma trận tán xạ, sau khi chiếu bỏ close
        acc = [[0.0] * 3 for _ in range(3)]
        for p in pts:
            d = p - self.origin
            d = d - self.close * d.dot(self.close)
            for a in range(3):
                for b in range(3):
                    acc[a][b] += d[a] * d[b]
        v = Vector((1.0, 0.37, 0.71))
        M = Matrix(acc)
        for _ in range(60):
            v = M @ v
            if v.length < 1e-18:
                v = frame.lat.copy()
                break
            v.normalize()
        v = v - self.close * v.dot(self.close)
        self.along = v.normalized() if v.length > 1e-7 else frame.lat.copy()
        if self.along.dot(frame.lat) < 0:
            self.along = -self.along
        self.out = self.along.cross(self.close).normalized()

    def sc(self, p):
        """(toạ độ dọc khe, toạ độ ngang khe) của một điểm."""
        d = p - self.origin
        return d.dot(self.along), d.dot(self.close)

    def world(self, s=0.0, c=0.0, o=0.0):
        return self.along * s + self.close * c + self.out * o


def pair_half(pf, reg, base, q=PCTL):
    """Nửa chiều dài khe đo theo trục along của chính cặp vùng đó."""
    if not reg:
        return 1e-9
    su = sorted((abs(pf.sc(base[i])[0]), w) for i, w in reg.items())
    tot = sum(w for _, w in su) or 1e-9
    run = 0.0
    for u, w in su:
        run += w
        if run >= tot * q:
            return max(u, 1e-9)
    return max(su[-1][0], 1e-9)


def seam_line(upper, lower, pf, base):
    """Khe giữa hai nửa, xấp xỉ bằng ĐƯỜNG THẲNG dọc theo khe: c = a + b*s.

    Bản đầu lấy khe là MỘT SỐ -- một mức 'up' cố định cho cả vùng. Với mắt xiên
    hoặc khe môi chạy vòng theo mõm, một số duy nhất làm đầu này khép quá đà
    trong khi đầu kia vẫn còn hở. Trên mặt người b ra ≈ 0 nên không đổi gì.
    """
    us = [pf.sc(base[i]) for i, w in upper.items() if w > CORE_W]
    ls = [pf.sc(base[i]) for i, w in lower.items() if w > CORE_W]
    both = merged({'a': upper, 'b': lower}, 'a', 'b')
    allsc = [pf.sc(base[i]) for i in both]
    if not allsc:
        return (0.0, 0.0)
    smin = min(s for s, _ in allsc)
    smax = max(s for s, _ in allsc)
    span = max(smax - smin, 1e-9)
    pts = []
    N = 7
    for k in range(N):
        a = smin + span * k / N
        b = smin + span * (k + 1) / N
        uu = [c for s, c in us if a <= s < b]
        ll = [c for s, c in ls if a <= s < b]
        if uu and ll:
            pts.append(((a + b) * 0.5, (min(uu) + max(ll)) * 0.5))
    if len(pts) < 2:
        cs = [c for _, c in allsc]
        return ((min(cs) + max(cs)) * 0.5, 0.0)
    n = len(pts)
    ms = sum(p[0] for p in pts) / n
    mc = sum(p[1] for p in pts) / n
    den = sum((p[0] - ms) ** 2 for p in pts)
    k = (sum((p[0] - ms) * (p[1] - mc) for p in pts) / den) if den > 1e-12 else 0.0
    return (mc - k * ms, k)


def solve_hinge(frame, base, lo_lip, jaw, close, origin, W, edges, fallback):
    """DÒ vị trí trục bản lề hàm: thử một lưới vị trí, chọn chỗ lưới giãn ít nhất.

    jaw_hinge() chỉ ĐOÁN -- cao bằng khoảng cách miệng↔mắt, lùi ra sau đúng ngần
    ấy. Trên mõm sói con số đó tình cờ hợp lý, nhưng đó là may chứ không phải
    suy ra được. Ở đây dò thật: mỗi vị trí ứng viên đều quay hàm tới CÙNG một độ
    há rồi đo giãn cạnh, lấy chỗ nhỏ nhất.

    Cùng phương pháp đã dùng cho `anchor` và `jaw_max` ở chế độ rig, và lần đó
    máy dò ra jaw_max = 14 trùng đúng con số dò tay.
    """
    if not lo_lip or not edges:
        return fallback
    ax = frame.lat
    src = list(lo_lip.items()) + [(i, w * 0.55) for i, w in jaw.items()]
    # Bản lề đặt quá sát miệng thì bán kính bé, góc quay phải rất lớn -- hàm
    # "há" bằng cách gập vào chính nó. Hàm thật mở cỡ 15-25 độ, nên loại thẳng
    # ứng viên nào đòi quá 30 độ. Không có chốt này, phép dò chọn ngay chỗ sát
    # miệng nhất (đo được: bản lề rơi cách trọng tâm môi 7 cm, VIS_AA bị chốt
    # lật-mặt cắt còn 34%% biên độ).
    ANG_MAX = math.radians(30.0)
    cands = [origin + frame.up * (a * W) - frame.fwd * (b * W)
             for a in (0.4, 0.8, 1.3, 2.0, 2.8)
             for b in (0.0, 0.4, 0.9, 1.6, 2.6)]
    if fallback is not None:
        cands.append(fallback)
    # Bản lề phải nằm SAU toàn bộ phần chuyển động. Nếu nó lọt vào giữa vùng
    # môi thì phần phía sau nó quay NGƯỢC chiều với phần phía trước -- dải môi
    # gập đôi lại. Đo được: bản lề rơi vào y=-0.313 trong khi môi trải từ -0.477
    # tới -0.297, và VIS_AA bị chốt lật-mặt cắt còn 34%% biên độ.
    back = -frame.fwd
    rear = max((base[i] - origin).dot(back) for i in lo_lip)
    best, bp = None, None
    for hp in cands:
        if (hp - origin).dot(back) < rear:
            continue
        rad = 0.0
        far = None
        for i in lo_lip:
            r = base[i] - hp
            r = r - ax * r.dot(ax)
            if r.length > rad:
                rad, far = r.length, i
        if rad < 1e-9 or far is None:
            continue
        ang = 0.30 * W / rad          # chuẩn hoá: cùng một độ há cho mọi ứng viên
        if ang > ANG_MAX:
            continue
        M = Matrix.Rotation(ang, 4, ax)
        rf = base[far] - hp
        if ((M @ rf) - rf).dot(close) > 0:     # phải là chiều HÁ RA
            M = Matrix.Rotation(-ang, 4, ax)
        d = {}
        for i, w in src:
            r = base[i] - hp
            d[i] = d.get(i, Vector((0, 0, 0))) + ((M @ r) - r) * w
        ek = [e for e in edges if e[0] in d or e[1] in d]
        if not ek:
            continue
        s = _stretch(d, ek, base, 1.0)
        if best is None or s < best:
            best, bp = s, hp
    return bp if bp is not None else fallback


def jaw_hinge(frame, regions, base, mouth_origin, W):
    """Trục bản lề của hàm dưới: nằm ngang, đặt phía sau-trên miệng.

    Hàm dưới QUAY quanh khớp thái dương hàm chứ không tịnh tiến xuống. Trên mặt
    người hai cách gần như nhau vì miệng ngắn và nằm sát trục, nhưng trên mõm
    dài thì khác hẳn. Đo trên sói: khóe miệng cách trục 0.18, chóp mõm cách 0.37
    -- chóp phải đi gấp đôi khóe. Tịnh tiến đều làm cả cái mõm trôi xuống thành
    khối chứ không há ra, và khóe miệng bị kéo rách vì nó lẽ ra phải đứng yên.
    """
    lids = all_lids(regions)
    h = None
    if lids:
        s = Vector((0, 0, 0))
        t = 0.0
        for i, w in lids.items():
            s += base[i] * w
            t += w
        if t:
            h = (s / t - mouth_origin).dot(frame.up)
    if h is None or h < W * 0.5:
        h = max(W, 1e-6)
    return mouth_origin + frame.up * h - frame.fwd * h


def cap_profile(profile, amp, cap):
    """Hạ đều cả profile mày nếu biên độ vượt trần, giữ nguyên hình dáng profile.

    Trần cần thiết vì đầu mày trái và phải chỉ cách nhau vài cm: cường điệu cao
    làm hai bên chạy quá đà rồi GIAO NHAU trên sống mũi, thành gờ nhọn. Đo được:
    ở 250%% mày đi 0.0592 trên cái đầu cao 0.42 -- 14%% chiều cao đầu.
    """
    mx = max(abs(v) for v in profile) * amp if profile else 0.0
    if cap > 0.0 and mx > cap:
        f = cap / mx
        return [v * f for v in profile]
    return profile


def scale_lid(k, ex):
    """Nhân mức gấp mí, nhưng KHÔNG cho vượt mức khép kín.

    k=1 đã là mí trên gặp đúng mí dưới. Nhân tiếp thì mí đi vượt qua khe, mắt
    nhắm quá đà và lộn mí. Chỉ hướng MỞ TO (k âm) mới cho cường điệu tự do.
    """
    return min(k * ex, 1.0) if k > 0 else k * ex


def taper(u, half, p=2.0):
    """1 ở giữa, 0 ở hai đầu -- khóe miệng là điểm neo, giữa môi mới di chuyển."""
    return max(1.0 - min(abs(u) / half, 1.0) ** p, 0.0)


def edge(u, half, p=2.0):
    """0 ở giữa, 1 ở hai đầu -- dùng cho cười, banh miệng, chụm môi."""
    return min(abs(u) / half, 1.0) ** p


def vertex_adjacency(face):
    adj = {}
    for e in face.data.edges:
        a, b = e.vertices
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    return adj


ZERO = Vector((0.0, 0.0, 0.0))


def smooth_field(disp, adj, iters=2, alpha=0.5, eps=1e-7):
    """Làm mượt trường độ dịch trên đồ thị mesh.

    Bắt buộc có bước này ở chế độ vùng: độ dịch tính riêng cho từng vertex theo
    profile nhân trọng số skin, mà trọng số skin không trơn, nên vertex kề nhau
    lệch nhau và viền môi ra răng cưa. Đường đi qua rig không bị vì bone nội suy
    mượt sẵn. Lấy trung bình với láng giềng (kể cả láng giềng bất động, nhờ vậy
    biên tự mềm) vài lượt là hết.
    """
    if iters <= 0 or not disp:
        return disp
    cur = dict(disp)
    for _ in range(iters):
        touched = set(cur)
        for i in list(cur):
            touched.update(adj.get(i, ()))
        nxt = {}
        for i in touched:
            nb = adj.get(i)
            if not nb:
                continue
            avg = ZERO.copy()
            for j in nb:
                avg += cur.get(j, ZERO)
            avg /= len(nb)
            v = cur.get(i, ZERO) * (1.0 - alpha) + avg * alpha
            if v.length > eps:
                nxt[i] = v
        cur = nxt
    return cur


DEGEN_EDGE = 0.05   # cạnh ngắn hơn ngần này lần trung vị coi là suy biến


def region_edges(face, base, verts):
    """Cạnh có ít nhất một đầu nằm trong vùng, kèm chiều dài lúc nghỉ.

    Sàn loại cạnh suy biến lấy TRUNG VỊ CỦA TOÀN MESH, không lấy trung vị của
    riêng tập cạnh đang xét. Lý do đã đo được: trung vị của tập con đổi theo tập
    vertex truyền vào (0.0181 với nhóm FS_, 0.0207 với tập vertex bị dịch), nên
    cùng một cạnh lúc bị loại lúc được giữ, và trần giãn ra kết quả khác nhau
    giữa hai lần đo.

    Sàn cũng phải THẤP. Bản đầu để trung vị/4, nhưng đo phân bố cạnh thật thì
    ngưỡng đó rơi đúng vào phân vị 5 -- tức cắt mất cạnh thật ở viền môi (4.6 mm
    trên mặt người, trung vị 19.6 mm), là chỗ hay rách nhất. Trung vị/20 chỉ còn
    loại cạnh gần bằng 0.
    """
    ls = sorted((base[e.vertices[0]] - base[e.vertices[1]]).length
                for e in face.data.edges)
    if not ls:
        return []
    lo = max(ls[len(ls) // 2] * DEGEN_EDGE, 1e-12)
    out = []
    for e in face.data.edges:
        a, b = e.vertices
        if a not in verts and b not in verts:
            continue
        r0 = (base[a] - base[b]).length
        if r0 >= lo:
            out.append((a, b, r0))
    return out


STRETCH_PCTL = 0.99   # cho phép 1% số cạnh trong vùng vượt trần


def _stretch(disp, edges, base, f, q=STRETCH_PCTL):
    """Độ giãn ở phân vị q, KHÔNG phải max.

    Dùng max thì một cạnh bệnh duy nhất kéo sập cả shape key: đo trên mặt người
    ở 150%%, lấy max làm VIS_AA bị hạ còn 7%% biên độ trong khi 99%% số cạnh
    hoàn toàn bình thường. Rách lưới là hiện tượng của một MẢNG cạnh chứ không
    phải của một cạnh, nên phân vị mới là thước đo đúng.
    """
    rs = []
    for a, b, r0 in edges:
        da = disp.get(a)
        db = disp.get(b)
        p = base[a] - base[b]
        if da is not None:
            p = p + da * f
        if db is not None:
            p = p - db * f
        rs.append(p.length / r0)
    if not rs:
        return 1.0
    rs.sort()
    return rs[min(int(len(rs) * q), len(rs) - 1)]


def _newell(pts):
    """Pháp tuyến đa giác n cạnh (Newell) -- dùng được cho cả ngon."""
    n = Vector((0.0, 0.0, 0.0))
    m = len(pts)
    for k in range(m):
        a, b = pts[k], pts[(k + 1) % m]
        n.x += (a.y - b.y) * (a.z + b.z)
        n.y += (a.z - b.z) * (a.x + b.x)
        n.z += (a.x - b.x) * (a.y + b.y)
    return n


def region_polys(face, disp, inner_only=True):
    """Đa giác trong vùng.

    inner_only: chỉ lấy đa giác có TOÀN BỘ đỉnh bị dịch. Đa giác nằm vắt qua
    biên vùng (một số đỉnh đứng yên) gần như chắc chắn bị lật khi biên độ lớn,
    nhưng đó là do vùng tô có biên CỨNG chứ không phải shape key sai. Lấy cả
    chúng vào chốt chặn thì tai hại: đo trên mõm sói với nhóm tô trọng số 1.0
    đều, VIS_AA bị hạ còn 34%% biên độ -- hỏng hẳn shape trong khi bề mặt thật
    chẳng gập chỗ nào. Biên cứng được báo riêng ở bảng điểm.
    """
    out = []
    for p in face.data.polygons:
        vs = list(p.vertices)
        if inner_only:
            if all(v in disp for v in vs):
                out.append(vs)
        elif any(v in disp for v in vs):
            out.append(vs)
    return out


FLIP_AREA = 0.25    # đa giác còn giữ trên ngần này diện tích mới tính là gập


def flipped(polys, disp, base, f=1.0):
    """Số đa giác bị LẬT MẶT so với lúc nghỉ mà VẪN CÒN DIỆN TÍCH đáng kể.

    Lật mặt là dấu hiệu chắc chắn của biến dạng quá đà: da gập ngược vào trong,
    render ra vệt đen. Giãn cạnh không bắt được lỗi này vì cạnh có thể vẫn ngắn
    trong khi đa giác đã tự chui qua chính nó.

    Nhưng phải loại đa giác CO VỀ GẦN BẰNG 0 rồi mới lật: đó chính là chuyện xảy
    ra khi khép mí hay mím môi -- hai nửa sập vào cùng một đường nên đa giác nằm
    ngay khe bị bóp dẹt, lật là tất nhiên và hoàn toàn đúng ý. Không loại thì
    chốt cắt nhầm: đo trên mặt người, EYE_Blink bị hạ còn 71%% biên độ, mắt
    không nhắm kín được nữa. Độ dài vector Newell tỉ lệ với diện tích nên dùng
    luôn nó để so.
    """
    n = 0
    Z = Vector((0.0, 0.0, 0.0))
    for vs in polys:
        r = [base[v] for v in vs]
        d = [base[v] + disp.get(v, Z) * f for v in vs]
        nr, nd = _newell(r), _newell(d)
        if nr.length < 1e-12 or nd.length < 1e-12:
            continue
        if nd.length < nr.length * FLIP_AREA:
            continue                    # bóp dẹt -> khép, không phải gập
        if nr.dot(nd) < 0.0:
            n += 1
    return n


def _bisect(ok, iters=12):
    """Hệ số lớn nhất trong [0,1] mà ok(f) còn đúng."""
    if ok(1.0):
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(iters):
        mid = (lo + hi) * 0.5
        if ok(mid):
            lo = mid
        else:
            hi = mid
    return lo


def cap_stretch(disp, edges, base, cap, polys=None):
    """Hạ đều biên độ tới khi không còn cạnh nào giãn quá `cap` lần.

    CHỈ giãn cạnh mới được tự động hạ. Lật mặt thì chỉ ĐẾM VÀ BÁO, không hạ --
    đã thử hạ và hỏng nặng ở cả hai ca đúng:
      - mặt người: EYE_Blink bị cắt 25%%, nhãn cầu lòi từ 0.00%% lên 5.36%%;
      - mõm sói:   VIS_AA bị cắt còn 39%%, miệng gần như không há.
    Lý do là lật mặt lưỡng nghĩa: khép mí và mím môi vốn LÀM hai nửa sập vào
    nhau nên đa giác quanh khe lật là đúng ý. Giãn cạnh thì không lưỡng nghĩa,
    và ngưỡng 2.3 của nó đã được hiệu chỉnh bằng đo đạc.

    Chế độ rig đã có trần giãn (hiệu chỉnh bằng cách pose thử bone rồi đo), chế
    độ vùng thì chưa hề có: đo trên mõm sói ở 200%% có cạnh vùng môi giãn 3.35
    lần -- đó chính là chỗ lưới rách. Độ giãn KHÔNG tuyến tính theo biên độ nên
    không chia thẳng được, phải chia đôi dần.

    Trả về (trường độ dịch đã hạ, hệ số đã nhân, lý do).
    """
    if not disp:
        return disp, 1.0, ''
    ek = [e for e in edges if e[0] in disp or e[1] in disp] if edges else []
    if cap <= 0.0 or not ek:
        return disp, 1.0, ''

    def ok(f):
        return _stretch(disp, ek, base, f) <= cap

    if ok(1.0):
        return disp, 1.0, ''
    f = _bisect(ok)
    return {i: v * f for i, v in disp.items()}, f, 'giãn cạnh'


def region_shapes(face, regions, frame, base, smooth=2, ex=1.0,
                  cap=STRETCH_MAX, context=None, lid_angles=None):
    """{tên shape: {vertex: vector dịch}}. Vector cùng không gian với base."""
    # Răng phải được gỡ khỏi vùng mềm TRƯỚC MỌI PHÉP ĐO. Người rig hay skin răng
    # vào chính bone môi nên nhóm môi quét tự động hút trọn cả hai hàm -- đo trên
    # mesh `Male`: 170/170 vertex hàm trên nằm trong FS_LipUpper, 168/168 hàm
    # dưới trong FS_LipLower. Để nguyên thì hỏng hai lần: khe môi đo lệch (răng
    # nằm lùi vào trong nên kéo cả mặt phẳng khe thụt theo), và mọi shape key
    # miệng bẻ cong răng như bẻ môi.
    teeth_up = regions.get('FS_TeethUpper', {})
    teeth_lo = regions.get('FS_TeethLower', {})
    teeth = set(teeth_up) | set(teeth_lo)
    up_lip = {i: w for i, w in regions.get('FS_LipUpper', {}).items()
              if i not in teeth}
    lo_lip = {i: w for i, w in regions.get('FS_LipLower', {}).items()
              if i not in teeth}
    lips = merged({'a': up_lip, 'b': lo_lip}, 'a', 'b')
    mm = pair_metrics(up_lip, lo_lip, frame, base)
    # Hệ trục riêng của khe môi. Trên mặt người nó trùng với hệ trục mặt; trên
    # mõm thú nó nghiêng theo mõm -- xem ghi chú ở PairFrame.
    mf = PairFrame(up_lip, lo_lip, base, frame)
    if mf.ok:
        half = pair_half(mf, lips, base)
        m_seam = seam_line(up_lip, lo_lip, mf, base)
    else:
        half = mm['half']
        m_seam = (mm['seam'], 0.0)
    W = half * 2.0
    mm = dict(mm, half=half, seam=m_seam[0], seam_slope=m_seam[1])
    jaw = {i: w for i, w in regions.get('FS_Jaw', {}).items()
           if i not in lips and i not in teeth}
    nose = {i: w for i, w in regions.get('FS_Nose', {}).items() if i not in teeth}
    nrm = [v.normal.copy() for v in face.data.vertices]   # cho má, xem cheek()
    # Dựng MỘT LẦN cho cả bộ key: `lid()` dùng để nắn đường đi, chốt chặn dùng
    # lại chính chúng ở cuối. Dựng BVH mỗi key một lần là 56 lần thừa.
    shields = eyeball_shields(context, face) if context else {}
    lid_angles = lid_angles or {}
    eye_centre, eye_ball = {}, {}
    for i, s, _o, c, r in (eye_pairs(context, face) if context else []):
        eye_centre[(i, s)] = c
        eye_ball[(i, s)] = shields.get((i, s)) or _Shield(c, r)
    lid_holes = eye_holes(face, regions)
    lid_adj = vertex_adjacency(face)
    # Mảng vertex mà PHÉP GIẢI đã đụng tới. Làm mượt hạ nguồn phải miễn đúng
    # mảng này chứ không phải nhóm mí đã tô: phép giải trải ra rộng hơn nhóm
    # (nhóm + 2 vòng), và phần trải đó chính là phần chịu biến dạng -- làm mượt
    # nó là bào mòn đúng chỗ vừa giải xong.
    lid_touched = set()

    def acc(d, i, vec):
        d[i] = d.get(i, Vector((0, 0, 0))) + vec

    def LW(s=0.0, c=0.0, o=0.0):
        """Dịch chuyển trong hệ trục của khe môi, lùi về hệ trục mặt nếu hỏng."""
        return mf.world(s, c, o) if mf.ok else frame.world(u=s, v=c, w=o)

    def lip_sc(i):
        if mf.ok:
            return mf.sc(base[i])
        p = frame.uvw(base[i])
        return p.x, p.y

    # --- bản lề hàm: dò, không đoán -----------------------------------------
    _org = mf.origin if mf.ok else frame.origin
    _cls = mf.close if mf.ok else frame.up
    _guess = jaw_hinge(frame, regions, base, _org, W)
    _allreg = set(lips) | set(jaw)
    _edg = region_edges(face, base, _allreg) if _allreg else []
    hinge_p = solve_hinge(frame, base, lo_lip, jaw, _cls, _org, W, _edg, _guess)
    hinge_ax = frame.lat

    def _swing(idx_w, ang, out):
        """Quay quanh trục bản lề, chính xác (ma trận quay, không xấp xỉ nhỏ)."""
        M = Matrix.Rotation(ang, 4, hinge_ax)
        for i, w in idx_w:
            r = base[i] - hinge_p
            acc(out, i, ((M @ r) - r) * w)

    # Bán kính quay lớn nhất trong môi dưới, dùng để quy đổi góc <-> biên độ.
    _rad, _far = 1e-9, None
    for i in (lo_lip or lips):
        r = base[i] - hinge_p
        r = r - hinge_ax * r.dot(hinge_ax)
        if r.length > _rad:
            _rad, _far = r.length, i

    # Dấu quay: chọn chiều làm môi dưới đi về phía -close (tức là há ra). Thử
    # trên chính vertex xa bản lề nhất để phép thử không rơi vào điểm gần trục.
    SGN = 1.0
    if _far is not None:
        _p = {}
        _swing([(_far, 1.0)], 0.01, _p)
        if _p[_far].dot(mf.close if mf.ok else frame.up) > 0:
            SGN = -1.0

    # GHI CHÚ -- đã nghi ngờ và đã bác bỏ bằng đo đạc:
    #
    # edge(s) bằng 1 ở CẢ HAI đầu khe, nên tưởng rằng trên mõm dài nó sẽ nhấc
    # luôn chóp mũi khi cười. Đo lại trên mõm sói thật: mf.along ra ĐÚNG trục
    # ngang (lệch 0.0 độ so với frame.lat), và chóp mõm nằm ở s = 0.0000 tức
    # edge = 0.00. Hai đầu khe là hai khóe miệng trái/phải, y như mặt người.
    #
    # Lý do: PairFrame bỏ thành phần close rồi mới tìm phương trải rộng nhất, mà
    # bề ngang miệng sói vẫn nhỉnh hơn bề dài dọc mõm, nên along bám trục ngang.
    # Chóp mõm rơi vào GIỮA khe chứ không phải đầu khe.
    #
    # Hai cách sửa đã thử đều làm hỏng mặt người (MTH_Smile tụt còn 3%% rồi 38%%
    # biên độ) mà không cải thiện gì cho mõm. Giữ nguyên edge().

    def m_open(amt, lift=0.25, jaw_follow=0.55):
        """Hàm dưới QUAY quanh bản lề -- không tịnh tiến đều.

        Quay làm khóe miệng (sát bản lề) gần như đứng yên còn phần xa bản lề đi
        nhiều, nên neo khóe có sẵn trong hình học, không cần profile búp như
        trước. Với mặt người kết quả gần như y hệt; với mõm dài thì đây là khác
        biệt sống còn -- xem ghi chú ở jaw_hinge().
        """
        ang = SGN * amt * W / _rad
        d = {}
        _swing(lo_lip.items(), ang, d)
        _swing(up_lip.items(), -ang * lift, d)
        _swing(jaw.items(), ang * jaw_follow, d)
        # Hàm răng dưới gắn cứng vào xương hàm nên quay ĐÚNG góc bản lề, không
        # phải jaw_follow (0.55 là mức da má trượt theo, da co giãn được, răng
        # thì không). Trọng số ép về 1.0 dù nhóm tô thế nào: nửa hàm quay nhiều
        # hơn nửa kia là răng bị bẻ.
        _swing(((i, 1.0) for i in teeth_lo), ang, d)
        return d

    def m_corner(du=0.0, dv=0.0, dw=0.0, side=None, p=2.0):
        """du chạy theo trục ngang của MẶT (trái/phải thật), dv/dw theo khe môi."""
        d = {}
        for i, w in lips.items():
            x = frame.uvw(base[i]).x
            if (side == 'L' and x < 0) or (side == 'R' and x > 0):
                continue
            e = edge(lip_sc(i)[0], half, p) * w
            sg = 1.0 if x >= 0 else -1.0
            acc(d, i, frame.lat * (du * W * e * sg) + LW(c=dv * W * e, o=dw * W * e))
        return d

    def m_press(amt):
        d = {}
        for i, w in lo_lip.items():
            acc(d, i, LW(c=amt * W * taper(lip_sc(i)[0], half) * w))
        for i, w in up_lip.items():
            acc(d, i, LW(c=-amt * W * taper(lip_sc(i)[0], half) * w))
        return d

    def m_upper(dv, dw=0.0):
        d = {}
        for i, w in up_lip.items():
            acc(d, i, LW(c=dv * W * w, o=dw * W * w))
        for i, w in nose.items():
            acc(d, i, frame.world(v=dv * W * 0.45 * w))
        return d

    def lid(side, k, low_k=None):
        """Gấp mí về đường khe, trong hệ trục RIÊNG của mắt đó.

        ĐÃ THỬ VÀ BỎ -- ghép cặp viền: mỗi vertex mí trên tìm vertex mí dưới gần
        nhất rồi cả hai đi về trung điểm. Ý tưởng là bỏ nốt giả định "mắt thuôn
        theo một trục". Đo lại thì tệ hẳn: khi hai nhóm mí người dùng tô CHỒNG
        lên nhau (rất hay gặp, nhất là nhóm sinh tự động từ trọng số skin), mỗi
        vertex bắt cặp với hàng xóm ngay cạnh nó chứ không phải với vertex bên
        kia khe mắt. Trên mặt người EYE_Blink tụt từ 0.0321 xuống 0.0098 m.
        Muốn ghép cặp đúng thì phải biết khe mắt ở đâu -- mà đó chính là thứ
        trục + đường khe đang cung cấp. Nên giữ cách này.

        Một công thức cho cả hai mí: mí trên có c > khe nên (khe - c) âm -> đi
        xuống; mí dưới c < khe nên đi lên. Điểm khác bản đầu: 'lên/xuống' ở đây
        là theo trục khép của chính con mắt (mắt sói nghiêng 44.9 độ), và khe là
        một ĐƯỜNG chứ không phải một mức cố định.

        NHIỀU MẮT MỘT BÊN: mỗi con mắt gấp trong hệ trục và đường khe của RIÊNG
        nó rồi mới cộng lại -- xem khối ghi chú ở `split_eye_regions()`.
        """
        d = {}
        for inst in eye_insts(regions, side):
            _lid_one(d, side, inst, k, low_k)
        return d

    def _lid_one(d, side, inst, k, low_k):
        sfx = eye_suffix(inst, side)
        u_reg = regions.get('FS_LidUpper' + sfx, {})
        l_reg = regions.get('FS_LidLower' + sfx, {})
        if not u_reg and not l_reg:
            return
        ef = PairFrame(u_reg, l_reg, base, frame)
        if ef.ok:
            a, b = seam_line(u_reg, l_reg, ef, base)
        else:
            a, b = pair_metrics(u_reg, l_reg, frame, base)['seam'], 0.0
        low_k = k if low_k is None else low_k
        # Trọng số phải CHUẨN HOÁ trước khi dùng làm tỉ lệ đường đi. Trọng số skin
        # thô của mí phần lớn chỉ 0.3-0.5 (đo được: cả vùng mí trên chỉ 2 vertex
        # có w>0.7), nên dùng thô thì mí đi được nửa đường tới khe, mắt vẫn hé và
        # nhãn cầu lòi ~8.7%. Chia cho phân vị cao rồi kẹp về 1 để lõi mí khép
        # hẳn, còn rìa mí vẫn giữ hình.
        ws = sorted(list(u_reg.values()) + list(l_reg.values()))
        wref = max(ws[int(len(ws) * PCTL)] if ws else 1.0, 1e-6)

        # ĐÃ THỬ VÀ BỎ -- kẹp quãng đường mỗi vertex ở một bội của bề rộng khe
        # mí, với lý lẽ "mí trượt xuống che khe, chứ không phải cả mảng da sụp
        # vào một đường". Thước tham chiếu sai: _pair_gap đo khoảng cách giữa
        # hai NHÓM, mà nhóm mí trên và mí dưới thường CHỒNG nhau nên nó xấp xỉ
        # 0. Đo lại: mặt người tụt từ khép 41%% xuống 2%%, Bride 69%% -> 47%%,
        # còn Rabbit -- ca cần cứu -- chỉ nhích 41%% -> 47%%.
        # Có nhãn cầu và đã dò được góc -> đi theo CUNG quanh tâm nhãn cầu.
        # Đường thẳng chỉ còn là đường lui cho mesh không có nhãn cầu nào chỉ
        # tới (robot, đạo cụ, nhân vật mắt vẽ trên texture).
        theta = lid_angles.get((inst, side))
        centre = eye_centre.get((inst, side))
        hole = lid_holes.get((inst, side))
        shield = eye_ball.get((inst, side))
        # Mắt có LỖ và có NHÃN CẦU -> đủ dữ kiện để đặt đích, khỏi cần công
        # thức nào. Thiếu một trong hai thì lùi về đường cũ (robot, đạo cụ,
        # nhân vật mắt vẽ trên texture, hốc mắt liền da).
        if hole and shield is not None and lid_adj is not None:
            got = lid_goal(regions, base, frame, inst, side, shield, hole,
                           lid_adj, k)
            if got:
                lid_touched.update(got)
                for i, dv in got.items():
                    acc(d, i, dv)
                return
        if theta is not None and centre is not None:
            sw, cv = theta if isinstance(theta, tuple) else (theta, 0.0)
            for i, dv in lid_arc(regions, base, frame, inst, side, centre,
                                 sw * k, cv * k, hole=hole, adj=lid_adj,
                                 shield=shield).items():
                acc(d, i, dv)
            return

        for reg, kk in ((u_reg, k), (l_reg, low_k)):
            for i, w in reg.items():
                we = min(w / wref, 1.0)
                if ef.ok:
                    s, c = ef.sc(base[i])
                    dv = ef.world(c=(a + b * s - c) * kk * we)
                else:
                    p = frame.uvw(base[i])
                    dv = frame.world(v=(a - p.y) * kk * we)
                acc(d, i, dv)

    def eyeball(side, k):
        """Co và thụt nhãn cầu NẰM TRONG mesh mặt, theo mức nhắm.

        Cùng ý với make_eyeball_key() dùng cho nhãn cầu là object riêng, nhưng ở
        đây nhãn cầu là một mảng vertex của chính mesh mặt nên phải nắn thẳng.
        Cả hai lượng đều tính theo BÁN KÍNH của chính nhãn cầu, không dùng con
        số tuyệt đối, nên mesh to nhỏ cỡ nào cũng đúng.
        """
        if k <= 0.0:
            return {}
        d = {}
        for inst in eye_insts(regions, side):
            _ball_one(d, regions.get('FS_Eyeball' + eye_suffix(inst, side), {}), k)
        return d

    def _ball_one(d, reg, k):
        if not reg:
            return
        s = Vector((0, 0, 0))
        t = 0.0
        for i, w in reg.items():
            s += base[i] * w
            t += w
        if t <= 0.0:
            return
        c = s / t
        rad = max((base[i] - c).length for i in reg)
        if rad < 1e-9:
            return
        kk = min(k, 1.0)
        for i, w in reg.items():
            v = base[i] - c
            acc(d, i, (v * (EYEBALL_SHRINK - 1.0)
                       - frame.fwd * (rad * EYEBALL_BACK)) * (kk * w))

    def brow(side, profile):
        reg = regions.get('FS_Brow.%s' % side, {})
        if not reg:
            return {}
        us = [abs(frame.uvw(base[i]).x) for i in reg]
        u0, u1 = min(us), max(us)
        rng = max(u1 - u0, 1e-9)
        n = len(profile) - 1
        amp = weighted_half(reg, frame, base) * 2.0
        d = {}
        for i, w in reg.items():
            f = (abs(frame.uvw(base[i]).x) - u0) / rng * n
            a = int(min(f, n - 1e-6))
            val = profile[a] + (profile[a + 1] - profile[a]) * (f - a)
            acc(d, i, frame.world(v=val * amp * w))
        return d

    def nose_flare(side, amt):
        d = {}
        for i, w in nose.items():
            pt = frame.uvw(base[i])
            if (side == 'L') != (pt.x >= 0):
                continue
            s = 1.0 if pt.x >= 0 else -1.0
            acc(d, i, frame.world(u=amt * W * s * w, v=amt * W * 0.3 * w))
        return d

    def nose_wrinkle(side, amt):
        """Nhăn mũi: cánh mũi cùng bên dồn LÊN và vào giữa, môi trên nhếch theo.

        Khác MTH_Sneer ở chỗ Sneer nhấc cả môi trên hai bên còn cái này lệch hẳn
        một bên -- đó là nửa dưới của biểu cảm ghê tởm, và là thứ làm nếp nhăn
        chạy chéo từ cánh mũi lên khoé mắt.
        """
        d = {}
        for i, w in nose.items():
            pt = frame.uvw(base[i])
            if (side == 'L') != (pt.x >= 0):
                continue
            sg = 1.0 if pt.x >= 0 else -1.0
            acc(d, i, frame.world(u=-amt * W * 0.30 * sg * w, v=amt * W * w))
        for i, w in up_lip.items():
            if (side == 'L') != (frame.uvw(base[i]).x >= 0):
                continue
            acc(d, i, LW(c=amt * W * 0.45 * w))
        return d

    def m_pucker(amt, out=0.0):
        """Chu môi: hai khoé dồn về giữa khe rồi cả vành môi đẩy ra trước.

        Dồn theo edge() chứ không taper(): mạnh nhất ở HAI ĐẦU khe, tắt ở giữa.
        Đẩy ra trước thì ngược lại -- giữa môi đi xa nhất. Hai đường suy giảm
        ngược nhau chính là thứ làm miệng thành hình chữ O chứ không phải bị bóp
        bẹp.
        """
        d = {}
        for i, w in lips.items():
            s = lip_sc(i)[0]
            e = edge(s, half, 2.0)
            sg = 1.0 if s >= 0 else -1.0
            acc(d, i, LW(s=-amt * W * e * sg * w,
                         o=out * W * w * (1.0 - 0.55 * e)))
        return d

    def m_lip(side=None, up=0.0, lo=0.0, p=2.0):
        """Nhấc/hạ RIÊNG môi trên hoặc môi dưới, có thể chỉ một bên.

        Dương = đi theo chiều khép (lên với môi dưới, lên với môi trên). Nên
        nhếch môi trên là up dương, còn hạ môi dưới hở răng là lo âm.
        """
        d = {}
        for reg, amt in ((up_lip, up), (lo_lip, lo)):
            if not amt:
                continue
            for i, w in reg.items():
                x = frame.uvw(base[i]).x
                if (side == 'L' and x < 0) or (side == 'R' and x > 0):
                    continue
                acc(d, i, LW(c=amt * W * taper(lip_sc(i)[0], half, p) * w))
        return d

    def m_roll(up=0.0, lo=0.0):
        """Mím môi vào trong: vành môi cuộn về khe RỒI thụt ra sau."""
        d = {}
        for reg, amt, sg in ((up_lip, up, -1.0), (lo_lip, lo, 1.0)):
            if not amt:
                continue
            for i, w in reg.items():
                t = taper(lip_sc(i)[0], half) * w
                acc(d, i, LW(c=sg * amt * W * t, o=-amt * W * 0.8 * t))
        return d

    def m_chin(amt):
        """Nâng môi dưới đè lên môi trên, cằm dồn theo -- kiểu mặt dỗi."""
        d = m_lip(lo=amt)
        for i, w in jaw.items():
            acc(d, i, LW(c=amt * W * 0.45 * w))
        return d

    def m_shift(amt):
        """Cả miệng trượt ngang theo trục MẶT. Hàm đi theo một phần."""
        d = {}
        for i, w in lips.items():
            acc(d, i, frame.lat * (amt * W * w))
        for i, w in jaw.items():
            acc(d, i, frame.lat * (amt * W * 0.4 * w))
        return d

    def cheek(side, out=0.0, upv=0.0, pull=0.0):
        """Má phồng/hóp theo PHÁP TUYẾN của chính lưới, không theo một trục cố định.

        Má là mặt cong bọc quanh hàm: hướng "ra ngoài" ở gò má gần như là fwd,
        còn ở mép hàm đã ngoặt gần hết sang lat. Đẩy cả vùng theo một trục thì
        đúng một nửa vùng, nửa còn lại thụt vào trong. Pháp tuyến là thứ duy
        nhất đúng cho cả mặt người lẫn mõm thú.

        Biên độ suy giảm theo bình phương khoảng cách tới tâm vùng -> phồng ra
        hình vòm. Chỉ nhân trọng số nhóm thì được một mảng phẳng dày lên, nhìn
        như dán miếng đệm chứ không phải má phồng hơi.

        Thang biên độ lấy theo BỀ NGANG CỦA CHÍNH VÙNG MÁ, không dùng
        weighted_half() như mày và môi. weighted_half() đo |u| tính từ gốc hệ
        trục mặt, mà má nằm lệch hẳn sang một bên nên con số đó phản ánh khoảng
        cách má-tới-sống-mũi chứ không phải kích cỡ má: đo trên mặt thử ra 0.24
        thay vì 0.16, và CHK_Puff phồng 4.6 cm trên khuôn mặt rộng 32 cm.
        """
        reg = {i: w for i, w in regions.get('FS_Cheek.%s' % side, {}).items()
               if i not in teeth}
        if not reg:
            return {}
        s = Vector((0, 0, 0))
        t = 0.0
        for i, w in reg.items():
            s += base[i] * w
            t += w
        if t <= 0.0:
            return {}
        c = s / t
        ds = sorted((base[i] - c).length for i in reg)
        rad = ds[-1]                                   # bao trọn vùng -> biên tắt hẳn
        scale = ds[min(len(ds) - 1, int(len(ds) * PCTL))] * 2.0   # cỡ má
        if rad < 1e-9 or scale < 1e-9:
            return {}
        target = mf.origin if mf.ok else frame.origin
        d = {}
        for i, w in reg.items():
            f = max(0.0, 1.0 - ((base[i] - c).length / rad) ** 2) * w
            v = nrm[i] * (out * scale * f) + frame.world(v=upv * scale * f)
            if pull:
                v += (target - base[i]) * (pull * f)
            acc(d, i, v)
        return d

    def merge(*ds):
        out = {}
        for dd in ds:
            for i, v in dd.items():
                acc(out, i, v)
        return out

    E = ex          # hệ số cường điệu; mí có clamp riêng qua scale_lid()

    # trần biên độ mày = 90% khe dọc giữa mày và mí trên, đo trên chính mesh
    brow_cap, brow_amp = 0.0, 0.0
    br = merged(regions, 'FS_Brow.L', 'FS_Brow.R')
    lidu = all_lids(regions, ('FS_LidUpper',))
    if br and lidu:
        def cen_v(reg):
            sv = tv = 0.0
            for i, w in reg.items():
                sv += frame.uvw(base[i]).y * w
                tv += w
            return sv / tv if tv else 0.0
        brow_cap = abs(cen_v(br) - cen_v(lidu)) * BROW_TRAVEL_MAX
        brow_amp = weighted_half(regions.get('FS_Brow.L', br), frame, base) * 2.0

    def B(p):
        return cap_profile([v * E for v in p], brow_amp, brow_cap)

    R = {}
    jaw_ang = {}          # tên shape -> góc quay hàm, để chỉnh lại răng sau cap

    def OPEN(name, amt, **kw):
        """m_open() có GHI LẠI góc quay hàm dưới tên shape key.

        Cần vì chốt chặn giãn cạnh hạ biên độ bằng cách nhân đều cả trường độ
        dịch. Với mô mềm thế là đúng, nhưng nhân một phép quay thì kết quả không
        còn là phép quay: hàm răng dưới bị bóp theo dây cung. Có góc gốc thì
        dựng lại được phép quay đúng bằng góc đã hạ.
        """
        jaw_ang[name] = SGN * amt * W / _rad
        return m_open(amt, **kw)

    R['VIS_AA'] = OPEN('VIS_AA', .30*E)
    R['VIS_EE'] = merge(OPEN('VIS_EE', .09*E), m_corner(du=.07*E, dv=.03*E))
    R['VIS_IH'] = merge(OPEN('VIS_IH', .13*E), m_corner(du=.04*E))
    R['VIS_OH'] = merge(OPEN('VIS_OH', .23*E), m_corner(du=-.07*E, dw=.05*E))
    R['VIS_OU'] = merge(OPEN('VIS_OU', .07*E), m_corner(du=-.13*E, dw=.09*E))
    R['VIS_MBP'] = m_press(.015*E)
    R['VIS_FV'] = merge(m_press(.025*E), m_corner(du=.03*E, dw=-.015*E))
    R['VIS_TH'] = OPEN('VIS_TH', .13*E)
    R['VIS_L'] = OPEN('VIS_L', .19*E)
    R['VIS_SS'] = merge(OPEN('VIS_SS', .045*E), m_corner(du=.05*E))
    R['VIS_RR'] = merge(OPEN('VIS_RR', .10*E), m_corner(du=-.06*E, dw=.04*E))
    for s in ('L', 'R'):
        R['MTH_Smile' + s] = m_corner(du=.07*E, dv=.14*E, side=s)
        R['MTH_Frown' + s] = m_corner(du=.02*E, dv=-.11*E, side=s)
    R['MTH_Sneer'] = m_upper(.075*E, dw=.015*E)
    R['MTH_Press'] = m_press(.035*E)
    R['MTH_Pucker'] = m_pucker(.115*E, out=.085*E)
    R['MTH_Funnel'] = merge(OPEN('MTH_Funnel', .085*E),
                            m_pucker(.065*E, out=.055*E))
    R['MTH_RollUpper'] = m_roll(up=.050*E)
    R['MTH_RollLower'] = m_roll(lo=.050*E)
    R['MTH_ChinUp'] = m_chin(.070*E)
    R['MTH_Left'] = m_shift(.075*E)
    R['MTH_Right'] = m_shift(-.075*E)
    for s in ('L', 'R'):
        R['MTH_Stretch' + s] = m_corner(du=.130*E, dv=.010*E, side=s)
        R['MTH_Dimple' + s] = m_corner(du=.040*E, dv=.030*E, dw=-.060*E, side=s)
        R['MTH_UpperUp' + s] = m_lip(side=s, up=.075*E)
        R['MTH_LowerDown' + s] = m_lip(side=s, lo=-.075*E)
        R['CHK_Puff' + s] = cheek(s, out=.100*E)
        R['CHK_Suck' + s] = cheek(s, out=-.075*E, pull=.045*E)
        R['CHK_Squint' + s] = cheek(s, upv=.075*E, out=.025*E)
        R['NOS_Wrinkle' + s] = nose_wrinkle(s, .050*E)
    for s in ('L', 'R'):
        R['EYE_Blink' + s] = merge(lid(s, scale_lid(1.0, E)),
                                   eyeball(s, scale_lid(1.0, E)))
        R['EYE_Squint' + s] = merge(lid(s, scale_lid(0.45, E)),
                                    eyeball(s, scale_lid(0.45, E) * 0.6))
        R['EYE_Wide' + s] = lid(s, -0.35*E, low_k=-0.30*E)
        R['BRW_Up' + s] = brow(s, B([.16, .15, .13, .11, .08]))
        R['BRW_Down' + s] = brow(s, B([-.11, -.11, -.09, -.07, -.05]))
        R['BRW_Angry' + s] = brow(s, B([-.16, -.11, -.04, .02, .05]))
        R['BRW_Sad' + s] = brow(s, B([.16, .11, .02, -.05, -.08]))
        R['NOS_Flare' + s] = nose_flare(s, .07*E)
    if smooth > 0:
        adj = vertex_adjacency(face)
        # Mí đi theo CUNG quanh nhãn cầu không được làm mượt, cùng lý do với
        # răng nhưng nghiêm trọng hơn: quãng đi của nó do phép ĐO quyết định,
        # mà làm mượt lấy trung bình với láng giềng NGOÀI vùng mí -- những
        # vertex đứng yên -- nên nó kéo cái mí vừa khép quay về phía mở. Đo trên
        # `Mesh_0.001`: cùng một góc, con ngươi hở 5%% khi không làm mượt và
        # 15%% khi có. Bảo bộ dò tự bù bằng cách đo trên số đã mượt cũng chỉ gỡ
        # được tới 11%% -- làm mượt đặt một trần cứng lên mức khép, tăng góc
        # bao nhiêu cũng không vượt qua.
        #
        # Viền không bị gãy vì `soften_regions()` đã vuốt TRỌNG SỐ nhóm rồi, tức
        # chính biên độ đã tắt dần ở rìa mí -- đó mới là chỗ chữa đúng.
        keep_raw = set(teeth) | lid_touched
        for (inst, side) in lid_angles:
            sfx = eye_suffix(inst, side)
            keep_raw |= set(regions.get('FS_LidUpper' + sfx, {}))
            keep_raw |= set(regions.get('FS_LidLower' + sfx, {}))
        out = {}
        for k, v in R.items():
            sm = smooth_field(v, adj, iters=smooth)
            for i in keep_raw:
                if i in v:
                    sm[i] = v[i]
                else:
                    sm.pop(i, None)
            out[k] = sm
        R = out

    # Chốt chặn -- đặt SAU khi làm mượt vì làm mượt cũng đổi độ giãn.
    capped = {}
    allv = set()
    for d in R.values():
        allv |= set(d)
    # Răng ra khỏi phép đo giãn cạnh: cạnh của khối cứng luôn có tỉ số đúng 1.0
    # nên chúng chỉ pha loãng phân vị, làm chốt chặn nới ra một cách giả tạo.
    allv -= teeth
    edges = region_edges(face, base, allv) if allv else []
    polys = region_polys(face, allv) if allv else []
    for k in list(R):
        # Trần 2.3 được hiệu chỉnh trên KHÓE MIỆNG -- chỗ lưới bắt đầu rách khi
        # hạ hàm. Da mí khi khép lại giãn nhiều hơn thế một cách chính đáng, và
        # phần giãn đó nằm ở nếp gấp mí, khép xong là bị che. Dùng chung một
        # trần thì mắt bị cắt oan: đo trên bốn nhân vật, pig giãn 2.70 bị hạ còn
        # 82%% (khép 59%%), Rabbit giãn 3.95 bị hạ còn 48%% (khép 41%%), trong
        # khi tắt trần thì hai con khép được 73%% và 82%% mà nhìn vẫn sạch.
        kcap = cap * LID_CAP_MULT if k.startswith('EYE_') else cap
        R[k], f, why = cap_stretch(R[k], edges, base, kcap, polys)
        if f < 0.995:
            capped[k] = (f, why)
            # Dựng lại phép quay của hàm răng dưới bằng góc ĐÃ HẠ, thay vì để
            # chốt chặn nhân đều vector. Nhân đều một phép quay ra phép biến
            # hình bóp theo dây cung: đo được răng biến dạng 1.90% ở VIS_AA.
            if teeth_lo and k in jaw_ang:
                for i in teeth_lo:
                    R[k].pop(i, None)
                _swing(((i, 1.0) for i in teeth_lo), jaw_ang[k] * f, R[k])
    # SAU chốt chặn: chốt chặn nhân đều cả trường độ dịch nên nó có thể kéo một
    # vertex vừa được cứu chui vào lại trong nhãn cầu.
    guard = (eyeball_guard(context, face, regions, base, R, shields=shields)
             if context else {})
    return R, dict(mm, capped=capped, hinge=hinge_p, guard=guard)


def build_from_regions(face, shapes, thresh=1e-5):
    """Ghi shape key thẳng lên mesh gốc -- không qua armature, không lấy hiệu."""
    ensure_basis(face)
    basis = face.data.shape_keys.key_blocks['Basis']
    made = []
    for name in sorted(shapes, key=sort_key):
        disp = shapes[name]
        if not disp or max(v.length for v in disp.values()) < thresh:
            continue
        kb = own_key(face, face.shape_key_add(name=name, from_mix=False))
        kb.value = 0.0
        kb.slider_min, kb.slider_max = 0.0, 1.0
        for i, dv in disp.items():
            kb.data[i].co = basis.data[i].co + dv
        made.append(name)
    return made


# ====================================================== bất biến & bảng điểm
#
# Mọi lỗi gặp phải khi đem addon sang khuôn mặt lạ đều cùng một loại: một con số
# hoặc một hướng bị ĐOÁN trước thay vì đo từ mesh, và mắt thường không phát hiện
# ra. Nên thay vì thêm nhánh xử lý cho từng loài, ở đây định nghĩa những điều
# kiện mà BẤT KỲ khuôn mặt biến dạng đúng nào cũng phải thoả, rồi đo sau khi
# dựng. Cái nào sửa được thì tự hạ biên độ, cái nào không thì báo rõ.

# Hai ngưỡng dưới đây được HIỆU CHỈNH TỪ SỐ ĐO trên hai ca đã kiểm chứng bằng
# mắt (mặt người Male.002 và mõm sói), chứ không phải chọn cho đẹp. Đo được:
#
#            khép mí        mở miệng
#   người      0.40           0.08
#   sói        0.63           0.21
#
# Lần đầu đặt bừa 0.85 và 0.25 thì CẢ HAI ca tốt đều trượt -- bảng điểm mà báo
# động ở ca đúng thì vô dụng. Ngưỡng ở đây đặt dưới ca yếu nhất một quãng, nên
# nó chỉ kêu khi hỏng thật: mí không nhúc nhích, miệng không há.
# Nhắm mắt phải che được con ngươi. `GOAL_COVER` là phần mặt nhãn cầu hướng
# về người xem CÒN NHÌN THẤY khi nhắm hết cỡ -- thước duy nhất nói đúng chuyện
# "mắt đã nhắm chưa".
#
# `GOAL_BLINK` bên dưới đo khoảng cách giữa hai NHÓM vertex mí. Nó là đường lui
# cho mesh không có mesh nhãn cầu nào chỉ tới, và nó ĐÃ TỪNG ĐÁNH LỪA: trên bộ
# key cũ nó chấm "khép 54%%, ĐẠT" trong khi con ngươi hở 26%% -- hở hơn cả lúc
# mở mắt -- vì mí trượt ra SAU nhãn cầu và hai nhóm vẫn xích lại gần nhau thật.
# Có nhãn cầu thì luôn chấm bằng `GOAL_COVER`.
GOAL_COVER = 0.10   # nhắm hết cỡ, con ngươi chỉ được hở tới ngần này
# Che phủ nhãn cầu chấm theo TỈ LỆ so với lúc mở, không theo số tuyệt đối.
# `eyeball_uncovered` đếm vertex nhãn cầu hướng về người xem mà tia không gặp da
# -- với nhãn cầu to nằm gọn trong đầu (`Mesh_0.001`: bán kính 23,4 trên lỗ mắt
# 14,4) con số lúc mở đã là 24%, nên đòi 10% tuyệt đối là đòi một thứ vô nghĩa.
GOAL_SEEN = 0.5     # nhắm hết cỡ, con ngươi phải bị che bớt ít nhất một nửa
GOAL_BLINK = 0.30   # (đường lui) khép được ít nhất ngần này phần khe mí
GOAL_OPEN = 0.05    # VIS_AA phải mở khe môi thêm ít nhất ngần này lần nửa rộng
GOAL_BAD = 0.40     # dưới ngần này lần ngưỡng thì coi là HỎNG chứ không cảnh báo
SYM_TOL = 0.15      # lệch trái/phải quá ngần này thì cảnh báo
MIN_REGION = 8      # dưới ngần này vertex thì không dựng nổi một khe
EYEBALL_SHRINK = 0.78   # nhãn cầu trong mesh co còn ngần này khi nhắm hẳn
EYEBALL_BACK = 0.30     # và thụt vào ngần này lần bán kính của chính nó
LID_CAP_MULT = 2.0      # trần giãn cạnh cho key mắt = ngần này lần trần miệng


def _cen(reg, base, disp=None):
    """Trọng tâm có trọng số của một vùng, có/không áp dịch chuyển."""
    Z = Vector((0.0, 0.0, 0.0))
    s = Vector((0.0, 0.0, 0.0))
    t = 0.0
    for i, w in reg.items():
        s += (base[i] + (disp.get(i, Z) if disp else Z)) * w
        t += w
    return (s / t) if t else None


def _pair_gap(A, B, base, disp=None):
    """Khoảng cách TRUNG BÌNH từ mỗi vertex nửa trên tới vertex gần nhất nửa dưới.

    Hai thước đo đã thử và bỏ:
      - khoảng cách GẦN NHẤT giữa hai tập: vô dụng, vì nhóm trên và nhóm dưới
        người dùng tô thường chạm nhau ở khóe nên nó bằng 0 cả trước lẫn sau
        (đo trên mõm sói ra đúng "0.0000 -> 0.0000");
      - khoảng cách giữa hai TRỌNG TÂM: luôn xác định nhưng không khớp với cách
        biến dạng thật. Khép mí kiểu ghép cặp viền chỉ kéo trọng tâm lại gần
        khoảng một nửa, nên nó báo "khép được 44%%" trong khi mắt đã nhắm hẳn.

    Trung bình khoảng cách tới láng giềng gần nhất thì bám đúng chuyện hai nửa
    có gặp nhau hay không, và không bao giờ suy biến về 0.

    Phải đo ĐỐI XỨNG hai chiều. Chỉ đo một chiều thì nhóm nào bị tô thiếu sẽ
    lọt lưới: thử cắt nhóm mí trên xuống còn 2 vertex, đo một chiều vẫn báo
    "đạt hết" vì hai vertex ấy có chạy, trong khi cả con mắt không hề nhắm.
    """
    if not A or not B:
        return None
    Z = Vector((0.0, 0.0, 0.0))
    pa = [base[i] + (disp.get(i, Z) if disp else Z) for i in A]
    pb = [base[j] + (disp.get(j, Z) if disp else Z) for j in B]
    ab = sum(min((p - q).length for q in pb) for p in pa) / len(pa)
    ba = sum(min((q - p).length for p in pa) for q in pb) / len(pb)
    return (ab + ba) * 0.5


def audit_shapes(face, regions, base, R, frame, mm, cap=STRETCH_MAX,
                 cover=None):
    """Chấm từng shape key theo các bất biến. Trả về list dòng báo cáo.

    Mỗi dòng: (mức, tên, thông điệp). Mức: 'ĐẠT' / 'CẢNH BÁO' / 'HỎNG'.
    """
    rows = []

    # --- nhóm có đủ vertex để định nghĩa được một khe không ---
    # Vài vertex thì không dựng nổi một đường khe: hướng khép, đường khe và bề
    # rộng đều suy ra từ phân bố vertex. Thử cắt nhóm mí trên còn 2 vertex thì
    # mọi phép đo khác vẫn "đạt" trong khi mắt không nhắm -- nên phải chặn ngay
    # từ đây.
    for nm, _, req in region_table(face):
        n = len(regions.get(nm, {}))
        if n == 0:
            if req:
                rows.append(('HỎNG', nm, "nhóm rỗng -- đây là nhóm BẮT BUỘC"))
            continue
        if n < MIN_REGION:
            rows.append(('HỎNG', nm, "chỉ có %d vertex, cần ít nhất %d -- "
                                     "tô rộng thêm" % (n, MIN_REGION)))

    allv = set()
    for d in R.values():
        allv |= set(d)
    edges = region_edges(face, base, allv) if allv else []
    polys = region_polys(face, allv) if allv else []
    capped = mm.get('capped') or {}
    scale = max(face.matrix_world.to_scale())

    # --- từng key: giãn cạnh, lật mặt, biên độ ---
    # Key nào phụ thuộc vùng TUỲ CHỌN mà vùng đó bỏ trống thì chỉ là BỎ QUA, chứ
    # không phải hỏng. Alien không có lông mày thật -- báo 8 key BRW_* là HỎNG
    # rồi kết luận "chưa dùng được" là báo động sai, che mất lỗi thật.
    OPT = {'BRW_': ('FS_Brow.L', 'FS_Brow.R'), 'NOS_': ('FS_Nose',),
           'CHK_': ('FS_Cheek.L', 'FS_Cheek.R')}
    skipped = []

    amps = {}
    for name in sorted(R, key=sort_key):
        d = R[name]
        if not d:
            opt = next((v for k, v in OPT.items() if name.startswith(k)), None)
            if opt and not any(regions.get(g) for g in opt):
                skipped.append(name)
            else:
                rows.append(('HỎNG', name, "không dịch chuyển vertex nào -- "
                                           "thiếu nhóm vùng tương ứng?"))
            continue
        amp = max(v.length for v in d.values()) * scale
        amps[name] = amp
        ek = [e for e in edges if e[0] in d or e[1] in d]
        s99 = _stretch(d, ek, base, 1.0) if ek else 1.0
        smax = _stretch(d, ek, base, 1.0, q=1.0) if ek else 1.0
        pk = [p for p in polys if all(v in d for v in p)]
        fl = flipped(pk, d, base, 1.0)
        # Ngưỡng theo TỈ LỆ, hiệu chỉnh từ hai ca đã kiểm chứng bằng mắt: nhắm
        # mắt người gập 3/50 đa giác, há mõm sói gập 10/200 -- đều quanh 5-6%%
        # và đều hoàn toàn bình thường (đa giác ngay khe khép thì phải gập).
        # Đặt 15%% để chỉ kêu khi cả một MẢNG da lộn ngược.
        frac = fl / max(len(pk), 1)
        note = []
        if name in capped:
            f, why = capped[name]
            note.append("đã hạ còn %.0f%% (%s)" % (f * 100, why))
        # Key mắt được dựng với trần NỚI, nên phải chấm bằng đúng trần đó --
        # không thì bảng điểm kêu oan chính những key mà chốt chặn cố ý cho qua.
        kcap = cap * LID_CAP_MULT if name.startswith('EYE_') else cap
        lvl = 'ĐẠT'
        if frac > 0.15:
            lvl = 'CẢNH BÁO'
            note.append("%d/%d đa giác gập ngược (%.0f%%) -- hạ cường điệu "
                        "hoặc tăng Làm mượt" % (fl, len(pk), frac * 100))
        elif kcap > 0.0 and s99 > kcap * 1.02:
            lvl = 'CẢNH BÁO'
            note.append("giãn p99 %.2f vượt trần %.2f" % (s99, kcap))
        rows.append((lvl, name, "biên độ %.4f m | giãn p99 %.2f, max %.2f%s"
                     % (amp, s99, smax,
                        " | " + ", ".join(note) if note else "")))

    # --- mục tiêu: nhắm mắt phải khép được khe mí ---
    # Chấm TỪNG CON MẮT. Gộp cả hai mắt cùng bên vào một phép đo thì mắt nào
    # không nhắm cũng bị mắt kia gánh điểm hộ -- đúng cái bẫy đã làm bộ key bốn
    # mắt qua được bảng điểm trong khi không con mắt nào khép.
    cover = cover or {}
    for inst, s in (eye_slots(face) or [(1, 'L'), (1, 'R')]):
        sfx = eye_suffix(inst, s)
        U = regions.get('FS_LidUpper' + sfx, {})
        L = regions.get('FS_LidLower' + sfx, {})
        key = 'EYE_Blink%s' % s
        if not U or not L or key not in R:
            continue
        g0 = _pair_gap(U, L, base)
        g1 = _pair_gap(U, L, base, R[key])
        if g0 is None or g0 < 1e-9:
            continue
        got = 1.0 - g1 / g0

        # Có mesh nhãn cầu -> chấm bằng CHE PHỦ. Khoảng cách hai nhóm chỉ còn là
        # số liệu tham khảo, in kèm chứ không quyết định đạt/hỏng.
        if (inst, s) in cover:
            o, c = cover[(inst, s)]
            lvl = ('ĐẠT' if c <= GOAL_COVER
                   else 'HỎNG' if c >= o else 'CẢNH BÁO')
            rows.append((lvl, key, "mắt %s: con ngươi hở %.0f%% -> %.0f%% khi "
                                   "nhắm (cần <= %.0f%%) | hai nửa mí xích lại "
                                   "%.0f%%"
                         % (sfx, o * 100, c * 100, GOAL_COVER * 100, got * 100)))
            continue

        lvl = ('ĐẠT' if got >= GOAL_BLINK
               else 'HỎNG' if got < GOAL_BLINK * GOAL_BAD else 'CẢNH BÁO')
        rows.append((lvl, key, "mắt %s: hai nửa mí cách nhau %.4f -> %.4f m "
                               "(khép được %.0f%%, cần >= %.0f%%) -- KHÔNG có "
                               "mesh nhãn cầu nên chỉ đo được gián tiếp"
                     % (sfx, g0 * scale, g1 * scale, got * 100, GOAL_BLINK * 100)))

    # --- mục tiêu: VIS_AA phải mở được miệng ---
    U, L = regions.get('FS_LipUpper', {}), regions.get('FS_LipLower', {})
    if U and L and 'VIS_AA' in R:
        g0 = _pair_gap(U, L, base)
        g1 = _pair_gap(U, L, base, R['VIS_AA'])
        half = mm.get('half') or 1e-9
        if g0 is not None:
            got = (g1 - g0) / half
            lvl = ('ĐẠT' if got >= GOAL_OPEN
                   else 'HỎNG' if got < GOAL_OPEN * GOAL_BAD else 'CẢNH BÁO')
            rows.append((lvl, 'VIS_AA', "hai nửa môi cách nhau %.4f -> %.4f m "
                                        "(mở thêm %.2f lần nửa rộng miệng, "
                                        "cần >= %.2f)"
                         % (g0 * scale, g1 * scale, got, GOAL_OPEN)))

    # --- biên vùng có cứng quá không (đa giác vắt qua biên bị lật) ---
    outer = region_polys(face, allv, inner_only=False)
    inner = set(tuple(p) for p in region_polys(face, allv, inner_only=True))
    edgep = [p for p in outer if tuple(p) not in inner]
    if edgep:
        worst, wk = 0, None
        for name, d in R.items():
            n = flipped(edgep, d, base, 1.0)
            if n > worst:
                worst, wk = n, name
        if worst:
            rows.append(('CẢNH BÁO', 'biên vùng',
                         "%d đa giác vắt qua biên nhóm bị lật (nhiều nhất ở %s)"
                         " -- nhóm tô có biên cứng, tăng Làm mượt hoặc tô "
                         "trọng số giảm dần ở rìa" % (worst, wk)))

    # --- răng phải cứng, và hàm trên phải đứng yên ---
    # Hai bất biến này rẻ mà bắt được đúng loại lỗi khó thấy nhất: răng bị kéo
    # theo môi. Nhìn ở tư thế nghỉ không phát hiện được, chỉ lộ khi há miệng --
    # mà lúc đó lại hay bị đổ cho "skin weight xấu".
    tup = set(regions.get('FS_TeethUpper', {}))
    tset = tup | set(regions.get('FS_TeethLower', {}))
    if tset:
        te = [e for e in region_edges(face, base, tset)
              if e[0] in tset and e[1] in tset]
        rest = {e: (base[e[0]] - base[e[1]]).length for e in te}
        bend, bend_k, drift, drift_k = 0.0, None, 0.0, None
        for name, d in R.items():
            for e in te:
                if rest[e] < 1e-9:
                    continue
                now = ((base[e[0]] + d.get(e[0], ZERO))
                       - (base[e[1]] + d.get(e[1], ZERO))).length
                if abs(now / rest[e] - 1.0) > bend:
                    bend, bend_k = abs(now / rest[e] - 1.0), name
            for i in tup:
                if d.get(i, ZERO).length > drift:
                    drift, drift_k = d[i].length, name
        rows.append(('ĐẠT' if bend < 0.01 else 'CẢNH BÁO', 'răng cứng',
                     "cạnh răng biến dạng nhiều nhất %.2f%%%s -- răng là xương, "
                     "phải bằng 0" % (bend * 100,
                                      " (%s)" % bend_k if bend_k else "")))
        rows.append(('ĐẠT' if drift * scale < 1e-5 else 'CẢNH BÁO', 'hàm trên',
                     "xê dịch nhiều nhất %.6f m%s -- gắn vào sọ, phải đứng yên"
                     % (drift * scale, " (%s)" % drift_k if drift_k else "")))
    elif regions.get('FS_LipUpper'):
        rows.append(('BỎ QUA', 'răng',
                     "chưa có nhóm FS_TeethUpper/Lower -- nếu mesh có răng thì "
                     "chúng đang bị bẻ cong theo môi"))

    # --- đối xứng trái/phải ---
    for a in sorted(amps):
        if not a.endswith('L'):
            continue
        b = a[:-1] + 'R'
        if b not in amps or amps[a] < 1e-9:
            continue
        dl = abs(amps[a] - amps[b]) / max(amps[a], amps[b])
        if dl > SYM_TOL:
            rows.append(('CẢNH BÁO', a + '/' + b,
                         "lệch trái-phải %.0f%% (%.4f vs %.4f m) -- "
                         "nhóm vùng hai bên tô không cân?"
                         % (dl * 100, amps[a], amps[b])))
    if skipped:
        rows.append(('BỎ QUA', '%d key' % len(skipped),
                     "không dựng vì nhóm tuỳ chọn bỏ trống: %s"
                     % ", ".join(skipped[:6])
                     + (" ..." if len(skipped) > 6 else "")))
    return rows


def region_zone(face, pad=1.6):
    """Khoảng z hợp lệ suy từ các nhóm FS_*. None nếu mesh chưa có nhóm nào."""
    zs = []
    for name, _, _ in region_table(face):
        for i in read_region(face, name):
            zs.append(face.data.vertices[i].co.z)
    if len(zs) < 8:
        return None
    lo, hi = min(zs), max(zs)
    m = (hi - lo) * pad
    return (lo - m, hi + m)


# ============================================================ operator

class FACESHAPES_Settings(PropertyGroup):
    mode: bpy.props.EnumProperty(
        name="Cách dựng",
        items=[('AUTO', "Tự chọn",
                "Có nhóm FS_* thì dựng theo vùng, không thì thử theo rig"),
               ('REGION', "Theo vùng vertex group",
                "Nắn thẳng mesh gốc theo nhóm FS_*. Không cần rig, chạy với mọi mesh"),
               ('RIG', "Theo face rig",
                "Pose xương mặt rồi nướng hiệu. Chạy với face rig do Rig Tẩm Hành "
                "sinh ra (Jaw, Lip_*, Eyelid_*, Eyebrow*, Nose, Tongue*)")],
        default='AUTO')
    rig: PointerProperty(name="Rig", type=bpy.types.Object,
                         poll=lambda s, o: o.type == 'ARMATURE')
    face: PointerProperty(name="Mesh mặt", type=bpy.types.Object,
                          poll=lambda s, o: o.type == 'MESH')
    exaggerate: FloatProperty(
        name="Mức cường điệu", default=150.0, min=0.0, soft_max=250.0, max=400.0,
        subtype='PERCENTAGE',
        description="100%% là biên độ đã hiệu chỉnh theo hình học khuôn mặt. "
                    "Kéo lên để cường điệu kiểu hoạt hình. 150% rõ hơn hẳn mà vẫn "
                    "sạch, 200% là cường điệu mạnh, từ 250% miệng bắt đầu nhúm "
                    "khóe. Hạ hàm, nháy mắt và mày đều có trần an toàn riêng")
    smooth: IntProperty(name="Làm mượt", default=2, min=0, max=6,
                        description="Số lượt làm mượt trường độ dịch. 0 là tắt, "
                                    "khi đó viền môi/mí có thể ra răng cưa")
    stretch_cap: FloatProperty(
        name="Trần giãn cạnh", default=STRETCH_MAX, min=0.0, max=8.0,
        description="Không cho cạnh nào trong vùng bị kéo giãn quá số lần này. "
                    "Shape key nào vượt sẽ bị hạ đều biên độ cho tới khi đạt. "
                    "2.3 là ngưỡng đo được lúc lưới khóe miệng bắt đầu rách. "
                    "Đặt 0 để tắt. Chỉ áp cho chế độ vùng")
    grow: IntProperty(name="Nới vùng", default=0, min=0, max=4,
                      description="Số lần nới nhóm ra vertex lân cận khi tự sinh, "
                                  "kèm giảm trọng số -- cho biên mềm, không gãy")
    soften: IntProperty(
        name="Vuốt mềm viền nhóm", default=2, min=0, max=5,
        description="Số vành ngoài cùng của mỗi nhóm vùng được hạ trọng số dần "
                    "khi dựng shape key. Nhóm tô tay là nhị phân nên viền của "
                    "nó là bậc thang dựng đứng, mà bậc thang thì thành vết gãy "
                    "trên mesh. 2 giảm 12% cạnh gãy, đổi lại biên độ hụt 4,9%. "
                    "0 là tắt. KHÔNG sửa nhóm đã tô. Vertex giáp nhóm khác "
                    "được ghim nên khe môi và khe mí vẫn cắt ngọt")
    calibrated: BoolProperty(default=False)
    anchor: FloatProperty(name="Bù khóe miệng", default=0.0, precision=5,
                          description="Mức nâng khóe miệng trên mỗi độ hạ hàm, "
                                      "theo tỉ lệ bề rộng miệng. Hiệu chỉnh tự động")
    jaw_max: FloatProperty(name="Trần hạ hàm", default=14.0, min=2.0, max=40.0,
                           description="Quá mức này khóe miệng rách, bù không cứu được")
    meet: FloatProperty(name="Đường gặp mí", default=0.0, precision=4,
                        description="Cao độ nơi mí trên gặp mí dưới khi nhắm")
    eye_shrink_on: BoolProperty(
        name="Cho nhãn cầu co lại khi nhắm", default=False,
        description="Mặc định TẮT. Trò này từng là thứ DUY NHẤT làm mắt trông "
                    "như đã nhắm: mí không hề che, nhãn cầu tự co còn 80% rồi "
                    "thụt vào để trốn. Đo trên nhân vật bốn mắt, tắt nó đi thì "
                    "nhắm hết cỡ con ngươi còn hở 26% -- hở hơn cả lúc mở mắt. "
                    "Giờ mí che thật nên không cần nữa; chỉ bật lại khi mí quá "
                    "ngắn, không phủ nổi nhãn cầu lồi")
    eye_shrink: FloatProperty(name="Nhãn cầu co", default=0.80, min=0.3, max=1.0)
    eye_back: FloatProperty(name="Nhãn cầu thụt", default=0.006, min=0.0, max=0.05,
                            unit='LENGTH')
    eye_threshold: FloatProperty(name="Ngưỡng thụt", default=0.6, min=0.0, max=0.95,
                                 description="Nhãn cầu chỉ bắt đầu thụt khi giá trị "
                                             "nhắm vượt mức này")
    do_teeth: BoolProperty(name="Kèm răng", default=True)
    do_eyes: BoolProperty(name="Kèm nhãn cầu", default=True)


class FACESHAPES_OT_calibrate(Operator):
    bl_idname = "face_shapes.calibrate"
    bl_label = "Đo khuôn mặt (tự động)"
    bl_description = ("Đo kích thước khuôn mặt và hiệu chỉnh mức bù khóe miệng, "
                      "trần hạ hàm, đường gặp mí -- bằng đo đạc trên mesh")
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        arm, _face = find_rig_and_mesh(context)
        if facerig.has_face_rig(arm):
            self.report({'INFO'}, "Face rig Rig Tẩm Hành tự đo trần hàm và đường gặp "
                                  "mí mỗi lần dựng -- không cần bước này")
            return {'FINISHED'}
        res, msg = calibrate(context)
        if res is None:
            self.report({'ERROR'}, msg)
            return {'CANCELLED'}
        for ln in msg.split("\n"):
            prefs.log("[FaceShapes] " + ln)
        self.report({'INFO'}, "Hiệu chỉnh xong -- xem chi tiết trong Console")
        return {'FINISHED'}


def auto_eyeballs(face, max_frac=0.35):
    """Tự dò nhãn cầu nằm TRONG mesh mặt, điền vào FS_Eyeball.L/R.

    Nhãn cầu kiểu này gần như luôn là một ĐẢO LƯỚI riêng (không nối cạnh với da)
    nằm lọt trong vùng mí. Nhận ra được thì người dùng khỏi phải tô -- mà nếu
    không có nhóm này thì nhãn cầu lồi sẽ không bao giờ bị che khi nhắm, dù mí
    có đi đủ quãng đường.

    Chỉ nhận đảo nào có trọng tâm nằm gần trọng tâm nhóm mí của cùng bên hơn là
    gần bên kia, và nhỏ hơn max_frac lần tổng số vertex (để không nhầm với thân).
    """
    lid = {}
    for s in ('L', 'R'):
        idx = set()
        for inst, _s in eye_slots(face, s):
            sfx = eye_suffix(inst, s)
            idx |= set(read_region(face, 'FS_LidUpper' + sfx))
            idx |= set(read_region(face, 'FS_LidLower' + sfx))
        if len(idx) >= MIN_REGION:
            pts = [face.data.vertices[i].co for i in idx]
            lid[s] = (sum(pts, Vector((0, 0, 0))) / len(pts),
                      max((p - sum(pts, Vector((0, 0, 0))) / len(pts)).length
                          for p in pts))
    if not lid:
        return {}

    adj = {}
    for e in face.data.edges:
        a, b = e.vertices
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    seen = set()
    out = {}
    n_all = len(face.data.vertices)
    for v in range(n_all):
        if v in seen:
            continue
        stack = [v]
        comp = []
        while stack:
            u = stack.pop()
            if u in seen:
                continue
            seen.add(u)
            comp.append(u)
            stack.extend(w for w in adj.get(u, ()) if w not in seen)
        if len(comp) < MIN_REGION or len(comp) > n_all * max_frac:
            continue
        pts = [face.data.vertices[i].co for i in comp]
        c = sum(pts, Vector((0, 0, 0))) / len(pts)
        best = min(lid, key=lambda s: (lid[s][0] - c).length)
        if (lid[best][0] - c).length > lid[best][1] * 1.2:
            continue
        nm = 'FS_Eyeball.%s' % best
        if nm in out:
            continue
        old = face.vertex_groups.get(nm)
        if old:
            face.vertex_groups.remove(old)
        g = face.vertex_groups.new(name=nm)
        for i in comp:
            g.add([i], 1.0, 'REPLACE')
        out[nm] = len(comp)
    return out


def eyeball_object(context, side, inst=1):
    """Mesh nhãn cầu bên `side`, cặp thứ `inst`, khi nó là object RIÊNG.

    Một nguồn sự thật duy nhất: danh sách nhãn cầu ở bước 1. Nhân vật bốn mắt
    thì bên trái có `Eye.L` và `Eye_2.L` — `inst` chọn cặp nào.
    """
    settings = getattr(context.scene, "srp_generate", None)
    if settings is None:
        return None
    seen = 0
    for entry in getattr(settings, "eyes", ()):
        if entry.mesh is None or entry.mesh.type != 'MESH' or entry.side != side:
            continue
        seen += 1
        if seen == inst:
            return entry.mesh
    if seen:
        return None
    # Đường lui: hai ô chọn cũ, chỉ có cặp thứ nhất.
    obj = getattr(settings, "eye_%s" % side, None) if inst == 1 else None
    return obj if (obj is not None and obj.type == 'MESH') else None


def _eye_inst(name):
    """`Eye.L` -> 1, `Eye_2.R` -> 2."""
    stem = name.rsplit(".", 1)[0]
    return int(stem.rsplit("_", 1)[1]) if "_" in stem else 1


def eye_bone_names(arm, eye_name="Eye"):
    """Tên mọi xương mắt trên rig, xếp theo cặp: `Eye.L`, `Eye.R`, `Eye_2.L`...

    Đọc thẳng từ rig chứ không gõ cứng hai cái: nhân vật bốn mắt là chuyện
    bình thường, và `weigh_face_bones` phải dọn trọng số cho ĐỦ chúng.
    """
    pattern = re.compile(r"^%s(?:_(\d+))?\.([LR])$" % re.escape(eye_name))
    found = []
    for bone in arm.data.bones:
        match = pattern.match(bone.name)
        if match:
            found.append((int(match.group(1) or 1), match.group(2), bone.name))
    return [name for _inst, _side, name in sorted(found)]


def eyeball_points(context, face, regions, side, base=None):
    """Điểm trên khối nhãn cầu bên `side`, đổi về hệ toạ độ của `face`.

    Ưu tiên mesh riêng; chỉ đọc nhóm `FS_Eyeball.<side>` khi nhãn cầu vẫn còn
    nằm trong mesh mặt. Nhờ vậy hai kiểu bố trí đều đo được bằng cùng một câu
    lệnh, và việc tách nhãn cầu ra thành object riêng không làm mất phép đo
    nào — bản lề hàm vẫn lấy được cao độ mép dưới nhãn cầu, xương mắt vẫn khớp
    được quả cầu.

    Đọc toạ độ HIỆN TẠI của object riêng chứ không đọc Basis: nhãn cầu là khối
    cứng, không có shape key, nên hai thứ đó là một.
    """
    obj = eyeball_object(context, side)
    if obj is not None and len(obj.data.vertices):
        to_face = face.matrix_world.inverted() @ obj.matrix_world
        return [to_face @ v.co for v in obj.data.vertices]
    reg = (regions or {}).get('FS_Eyeball.%s' % side, {})
    if not reg:
        return []
    if base is None:
        base = base_coords(face)
    return [base[i] for i in reg]


def mesh_islands(face):
    """Các mảng lưới rời nhau, sắp theo số vertex giảm dần."""
    adj = vertex_adjacency(face)
    seen, out = set(), []
    for v in range(len(face.data.vertices)):
        if v in seen:
            continue
        stack, comp = [v], []
        while stack:
            u = stack.pop()
            if u in seen:
                continue
            seen.add(u)
            comp.append(u)
            stack.extend(w for w in adj.get(u, ()) if w not in seen)
        out.append(comp)
    out.sort(key=len, reverse=True)
    return out


def auto_teeth(face, want=('FS_TeethUpper', 'FS_TeethLower')):
    """Tự khoanh hai hàm răng nằm TRONG mesh mặt.

    Răng gần như luôn là đảo lưới riêng lọt trong vùng môi, mà người rig lại hay
    skin chúng vào chính bone môi -- nên make_regions() quét theo trọng số hút
    trọn cả hai hàm vào nhóm môi. Đo trên mesh `Male`: 170/170 vertex hàm trên
    nằm trong FS_LipUpper, 168/168 hàm dưới trong FS_LipLower.

    Chia trên/dưới theo TỪNG ĐẢO khi có từ hai đảo trở lên, vì mỗi hàm là một
    khối cứng nên phải nguyên khối. Chỉ khi hai hàm dính chung một đảo mới đành
    cắt theo khe môi từng vertex -- và khi đó đầu răng cửa trên chìa xuống dưới
    khe sẽ bị chia nhầm sang hàm dưới.
    """
    regions = {n: read_region(face, n) for n, _, _ in region_table(face)}
    up_lip, lo_lip = regions.get('FS_LipUpper', {}), regions.get('FS_LipLower', {})
    if not up_lip or not lo_lip:
        return {}
    base = [v.co.copy() for v in face.data.vertices]
    frame = FaceFrame(face, regions, base)
    if not frame.ok:
        return {}

    def cen(idx):
        pts = [base[i] for i in idx]
        return sum(pts, Vector((0, 0, 0))) / len(pts)

    lips = merged(regions, 'FS_LipUpper', 'FS_LipLower')
    lip_c = cen(lips)
    reach = max((base[i] - lip_c).length for i in lips) * 1.2
    seam = (frame.uvw(cen(up_lip)).y + frame.uvw(cen(lo_lip)).y) * 0.5
    eyeball = set(regions.get('FS_Eyeball.L', {})) | set(regions.get('FS_Eyeball.R', {}))

    islands = mesh_islands(face)
    if len(islands) < 2:
        return {}
    hits = [c for c in islands[1:]              # bỏ đảo lớn nhất = chính cái đầu
            if len(c) >= MIN_REGION
            and not (set(c) & eyeball)
            and (cen(c) - lip_c).length <= reach]
    if not hits:
        return {}

    if len(hits) >= 2:
        # Đảo cao nhất là hàm trên, thấp nhất là hàm dưới. Đảo nằm giữa (lưỡi,
        # nướu rời) bỏ qua -- không đoán bừa cái mình không nhận ra.
        hits.sort(key=lambda c: frame.uvw(cen(c)).y, reverse=True)
        pick = {'FS_TeethUpper': hits[0], 'FS_TeethLower': hits[-1]}
    else:
        comp = hits[0]
        pick = {'FS_TeethUpper': [i for i in comp if frame.uvw(base[i]).y >= seam],
                'FS_TeethLower': [i for i in comp if frame.uvw(base[i]).y < seam]}

    out = {}
    for name, idx in pick.items():
        if name not in want or len(idx) < MIN_REGION:
            continue
        old = face.vertex_groups.get(name)
        if old:
            face.vertex_groups.remove(old)
        g = face.vertex_groups.new(name=name)
        for i in idx:
            g.add([i], 1.0, 'REPLACE')      # khối cứng -> trọng số phải là 1
        out[name] = len(idx)
    return out


def strip_teeth(face):
    """Gỡ vertex răng khỏi mọi nhóm vùng MỀM. Trả về số vertex đã gỡ."""
    teeth = set()
    for name in ('FS_TeethUpper', 'FS_TeethLower'):
        teeth |= set(read_region(face, name))
    if not teeth:
        return 0
    n = 0
    for name, _, _ in region_table(face):
        if name.startswith('FS_Teeth'):
            continue
        g = face.vertex_groups.get(name)
        if g is None:
            continue
        hit = sorted(teeth & set(read_region(face, name)))
        if hit:
            g.remove(hit)
            n += len(hit)
    return n


def auto_cheeks(face, want=('L', 'R')):
    """Tự khoanh vùng má, điền vào FS_Cheek.L/R.

    Má là vùng duy nhất trong bộ này KHÔNG có mốc riêng nào để bám: rig không có
    bone má, mesh không có nhóm tên `cheek`. Nhưng nó có một định nghĩa bằng
    phép loại trừ rất chắc: phần da nằm giữa khoé miệng và mí dưới, không thuộc
    môi / mí / mày / mũi, và quay MẶT RA NGOÀI.

    Điều kiện pháp tuyến là thứ không bỏ được. Quả cầu quanh trung điểm
    khoé-miệng và mí-dưới cũng tóm luôn cả mặt trong của túi miệng và phần lợi;
    thổi phồng đám đó thì má ngoài phình một nửa còn nửa kia thụt vào trong.
    """
    regions = {n: read_region(face, n) for n, _, _ in region_table(face)}
    if not regions.get('FS_LipUpper') or not regions.get('FS_LipLower'):
        return {}
    base = [v.co.copy() for v in face.data.vertices]
    frame = FaceFrame(face, regions, base)
    if not frame.ok:
        return {}

    taken = set()
    for name, _, _ in REGIONS:
        if not name.startswith('FS_Cheek'):
            taken |= set(regions.get(name, {}))
    lips = merged(regions, 'FS_LipUpper', 'FS_LipLower')

    out = {}
    for side in want:
        sg = 1.0 if side == 'L' else -1.0
        corner = max(lips, key=lambda i: frame.uvw(base[i]).x * sg)
        eye = lids_of(regions, side) or regions.get('FS_Brow.%s' % side, {})
        if not eye:
            continue
        pts = [base[i] for i in eye]
        eye_c = sum(pts, Vector((0, 0, 0))) / len(pts)
        centre = (base[corner] + eye_c) * 0.5
        rad = (base[corner] - eye_c).length * 0.70
        if rad < 1e-6:
            continue
        # hướng "ra ngoài" của má bên này: chếch giữa mặt trước và cạnh mặt
        outward = (frame.fwd * 0.5 + frame.lat * sg).normalized()

        acc = {}
        for i, v in enumerate(face.data.vertices):
            if i in taken:
                continue
            dist = (base[i] - centre).length
            if dist > rad:
                continue
            if frame.uvw(base[i]).x * sg <= 0.0:
                continue
            if v.normal.dot(outward) < 0.15:
                continue
            w = 1.0 - (dist / rad) ** 2
            if w > 0.05:
                acc[i] = w
        if len(acc) < MIN_REGION:
            continue

        nm = 'FS_Cheek.%s' % side
        old = face.vertex_groups.get(nm)
        if old:
            face.vertex_groups.remove(old)
        g = face.vertex_groups.new(name=nm)
        for i, w in acc.items():
            g.add([i], w, 'REPLACE')
        out[nm] = len(acc)
    return out


class FACESHAPES_OT_make_regions(Operator):
    bl_idname = "face_shapes.make_regions"
    bl_label = "Đánh dấu vùng mặt"
    bl_description = ("Tạo sẵn các nhóm FS_Lip / FS_Lid / FS_Brow / FS_Nose / "
                      "FS_Jaw / FS_Cheek. Nếu mesh đã skin thì tự đổ trọng số từ "
                      "vertex group sẵn có, còn không thì tạo nhóm rỗng để bạn tô. "
                      "Nhãn cầu và má được tự dò")
    bl_options = {'REGISTER', 'UNDO'}

    keep_painted: BoolProperty(
        name="Giữ nhóm đã có", default=True,
        description="Mặc định BẬT: nhóm FS_* nào đã có sẵn trọng số thì để yên, "
                    "chỉ tạo nhóm còn thiếu. Tắt thì đổ lại toàn bộ và MẤT phần "
                    "đã tô tay")

    def execute(self, context):
        st = context.scene.face_shapes
        # Mesh nhân vật đã chọn ở bước 1 được tính là mặc định — xem
        # `region_target`. Trước đây chỉ có `st.face` rồi rơi thẳng xuống
        # `context.object`, nên bấm nút lúc đang chọn nhầm object là tô nhóm
        # FS_ lên một mesh khác, còn mesh thật thì vẫn trống.
        face = region_target(context) or context.object
        if face is None or face.type != 'MESH':
            self.report({'ERROR'}, "Chọn mesh khuôn mặt trước")
            return {'CANCELLED'}
        st.face = face

        # kề nhau qua cạnh, để nới vùng ra biên mềm
        adj = {}
        for e in face.data.edges:
            a, b = e.vertices
            adj.setdefault(a, []).append(b)
            adj.setdefault(b, []).append(a)

        made, empty, kept, dropped = [], [], [], []
        for name, pat, _req in region_table(face):
            if pat is None:
                # Mắt thứ hai trở đi: không có mẫu tên nào để dò, nhóm chỉ đến
                # từ `split_eye_regions()` bên dưới. Bỏ qua chứ đừng tạo rỗng.
                continue
            # Nhãn cầu đã là mesh RIÊNG thì nhóm này không còn gì để chỉ vào.
            # Tạo ra một nhóm rỗng còn tệ hơn không tạo: `split_eyeballs` và
            # mọi phép dò nhãn cầu chỉ hỏi "có nhóm không", nên nhóm rỗng làm
            # chúng tưởng nhãn cầu vẫn nằm trong mesh mặt. Xoá luôn nếu lỡ có.
            side = name[-1] if name.startswith('FS_Eyeball.') else None
            if side and eyeball_object(context, side) is not None:
                old = face.vertex_groups.get(name)
                if old is not None:
                    face.vertex_groups.remove(old)
                    dropped.append(name)
                continue
            # Đổ lại một nhóm đã tô tay là xoá mất công tô. Cùng loại lỗi với
            # `build` xoá shape key làm tay -- nên mặc định cũng là giữ lại.
            if self.keep_painted and read_region(face, name):
                kept.append(name)
                continue
            src = [g for g in face.vertex_groups
                   if not g.name.startswith('FS_') and re.search(pat, g.name, re.I)]
            acc = {}
            for g in src:
                gi = g.index
                for v in face.data.vertices:
                    for gg in v.groups:
                        if gg.group == gi and gg.weight > 0.01:
                            acc[v.index] = max(acc.get(v.index, 0.0), gg.weight)
            # nới ra lân cận, trọng số giảm dần -> biên không gãy
            for _ in range(st.grow):
                add = {}
                for i, w in acc.items():
                    for j in adj.get(i, ()):
                        if j not in acc:
                            add[j] = max(add.get(j, 0.0), w * 0.55)
                acc.update(add)

            old = face.vertex_groups.get(name)
            if old:
                face.vertex_groups.remove(old)
            g = face.vertex_groups.new(name=name)
            if acc:
                for i, w in acc.items():
                    g.add([i], min(w, 1.0), 'REPLACE')
                made.append("%s (%d)" % (name, len(acc)))
            else:
                empty.append(name)

        # Tách nhóm mí gộp thành từng con mắt TRƯỚC mọi phép tự dò: nhãn cầu,
        # má và răng đều lấy nhóm mí làm mốc, chạy trên nhóm gộp là đo lệch.
        split = split_eye_regions(context, face)

        auto = dict(auto_eyeballs(face)) if 'FS_Eyeball.L' in empty \
            or 'FS_Eyeball.R' in empty else {}
        want_t = [n for n in ('FS_TeethUpper', 'FS_TeethLower') if n in empty]
        if want_t:
            auto.update(auto_teeth(face, want_t))
        # Gỡ răng chạy KHÔNG ĐIỀU KIỆN, kể cả khi giữ nhóm cũ: nhóm môi đang có
        # sẵn nhiều khả năng vẫn đang ôm trọn hai hàm răng từ lần quét trước.
        pulled = strip_teeth(face)
        # Má chạy SAU cùng: nó khoanh bằng phép loại trừ nên phải có đủ mọi nhóm
        # khác trên mesh rồi mới biết chỗ nào còn trống.
        want = [s for s in ('L', 'R') if 'FS_Cheek.%s' % s in empty]
        if want:
            auto.update(auto_cheeks(face, want))
        for nm, n in auto.items():
            made.append("%s (%d, tự dò)" % (nm, n))
            if nm in empty:
                empty.remove(nm)

        # Nhóm nhãn cầu RỖNG là cái bẫy chứ không phải chỗ trống chờ tô: nó
        # không bao giờ tô tay (luôn tự dò), mà `split_eyeballs` cùng các phép
        # dò khác chỉ hỏi "có nhóm không". Dò không ra nghĩa là mesh này không
        # chứa nhãn cầu -- xoá đi thay vì để một cái tên rỗng đánh lừa.
        for nm in ('FS_Eyeball.L', 'FS_Eyeball.R'):
            if nm not in empty:
                continue
            group = face.vertex_groups.get(nm)
            if group is not None:
                face.vertex_groups.remove(group)
            empty.remove(nm)
            dropped.append(nm)

        if split:
            msg_split = ", ".join("%s (%d)" % (n, c)
                                  for n, c in sorted(split.items()))
            made.append("tách %d nhóm mí theo từng con mắt: %s"
                        % (len(split), msg_split))
        bad = region_invariants(context, face)
        for lvl, nm, why in bad:
            prefs.log("[FaceShapes] %s %s: %s" % (lvl, nm, why))

        msg = "Đã tạo: " + ", ".join(made) if made else "Không tạo nhóm mới nào"
        if kept:
            msg += " | giữ nguyên %d nhóm đã có: %s" % (len(kept), ", ".join(kept))
        if dropped:
            msg += (" | bỏ %s (nhãn cầu là mesh riêng hoặc không có trong mesh này)"
                    % ", ".join(sorted(set(dropped))))
        if pulled:
            msg += " | gỡ %d vertex răng khỏi nhóm mềm" % pulled
        if empty:
            msg += " | rỗng, cần tô tay: " + ", ".join(empty)
        broke = [r for r in bad if r[0] == 'HỎNG']
        if broke:
            msg += " | %d VÙNG KHÔNG ĐẠT: %s" % (
                len(broke), "; ".join("%s (%s)" % (r[1], r[2].split(' -- ')[0])
                                      for r in broke[:2]))
        prefs.log("[FaceShapes] " + msg)
        self.report({'WARNING'} if broke else
                    ({'INFO'} if (made or kept) else {'WARNING'}), msg)
        return {'FINISHED'}


# --------------------------------------------- làm mềm viền nhóm vùng
#
# Nhóm tô tay là NHỊ PHÂN: trong 1.0, ngoài 0.0, và giữa hai vertex kề nhau là
# một bậc thang dựng đứng. Đo trên `My_Body`: **mọi** nhóm đều có bước trọng số
# lớn nhất = 1.000 và bước trung bình ở viền cũng = 1.000, tức không có lấy một
# vertex chuyển tiếp nào. Shape key lấy trọng số đó làm biên độ, nên bậc thang
# trong trường trọng số thành vết gãy trên mesh.
#
# `smooth_field()` đã làm mượt TRƯỜNG ĐỘ DỊCH rồi, nhưng nó chỉ chữa phần ngọn:
# vertex ngay ngoài mặt nạ vẫn nhận đúng 0 rồi mới được láng giềng kéo lên một
# ít.

# Khối CỨNG: làm mềm viền của chúng là làm răng/nhãn cầu biến dạng.
def is_sharp(name):
    """Khối CỨNG -- răng và nhãn cầu. Vuốt mềm viền chúng là làm chúng méo.

    Dò theo TIỀN TỐ chứ không theo bảng tên đầy đủ: nhân vật nhiều mắt có
    `FS_Eyeball_2.L`, và liệt kê tay thì cứ thêm một con mắt là quên một tên.
    """
    return name.startswith(('FS_Teeth', 'FS_Eyeball'))

# Chỗ hai vùng gặp nhau ở một KHE thật sự phải mở ra được: môi trên rời môi
# dưới, mí trên rời mí dưới. Chỉ ở đây bậc thang dựng đứng mới là đúng.
#
# Bản đầu ghim vertex giáp BẤT KỲ vùng nào khác. Trên mặt người thưa thì tạm
# được, nhưng các vùng mặt vốn nằm sát nhau nên nó ghim sạch: đo trên nhân vật
# bốn mắt, `FS_LidUpper.L` bị ghim **33/33 vertex, không cái nào được vuốt** —
# tức cả bước làm mềm thành vô hiệu, và mí trông bị bóp bẹt khi nheo mắt.
# Giáp `FS_Brow` hay `FS_Cheek` thì không có khe nào để giữ, cứ vuốt mềm.
SEAM_PAIRS = (('FS_LipUpper', 'FS_LipLower'),
              ('FS_LidUpper', 'FS_LidLower'))


def seam_partner(name):
    """Nhóm nằm ĐỐI DIỆN qua khe -- chỗ duy nhất được giữ bậc thang dựng đứng.

    Ghép theo TIỀN TỐ chứ không theo tên đầy đủ: mắt thứ hai trở đi có hậu tố
    `_2.L`, và một bảng tên đầy đủ thì cứ thêm một con mắt là quên một cặp.
    """
    for a, b in SEAM_PAIRS:
        if name.startswith(a):
            return b + name[len(a):]
        if name.startswith(b):
            return a + name[len(b):]
    return None


def soften_regions(face, regions, amount):
    """Bản SAO của `regions` đã vuốt mềm viền ngoài. `amount` = 0 là tắt.

    Vuốt NGƯỢC VÀO TRONG: hạ trọng số của mấy vành ngoài cùng, chứ KHÔNG nới
    nhóm ra vertex mới. Đã thử cả hai và đo (`My_Body`, 56 shape key, tắt trần
    giãn cạnh để hai bên so được với nhau):

        cách làm            cạnh gãy   biên độ   giãn cạnh max
        để nguyên               1499        --           6,80x
        nới RA 2 vòng           1089    +37,5%          11,52x
        vuốt VÀO 2 vành         1099     -7,9%           7,33x

    Nới ra ngoài giảm gãy chừng ấy, nhưng biên độ vọt lên 37,5% và giãn cạnh
    gần gấp đôi. Vì mặt nạ không chỉ nói "mạnh bao nhiêu" -- nó còn nói "mô
    hình độ dịch còn đúng tới đâu". Kéo vertex ra ngoài vùng đã tô là bắt
    profile ngoại suy vào chỗ nó chưa từng được đo, và cái +37,5% kia là dấu
    hiệu hỏng chứ không phải lời khen. Vuốt vào trong không đụng tới miền xác
    định nên không có chuyện đó.

    Vertex giáp nhóm KHÁC được GHIM nguyên trọng số: khe môi và khe mí PHẢI cắt
    ngọt, đó là chỗ duy nhất mà một bậc thang dựng đứng là đúng. Vành môi mỏng
    nên phần lớn vertex của nó chạm CẢ khe lẫn da trần; không ghim thì cả 14
    vertex môi trên giáp khe bị vuốt xuống và miệng không hé ra hết. Cái ghim
    này lấy mất một nửa phần giảm gãy (-27% còn -12%) -- đổi lại miệng còn mở
    được, nên đổi:

        (`My_Body`, 56 shape key, tắt trần giãn cạnh để so được với nhau)
                            cạnh gãy   biên độ   giãn p99   khe môi giữ
        để nguyên               1499        --     2,192x            --
        vuốt 2, không ghim      1099     -7,9%     2,174x          0/14
        vuốt 2, CÓ ghim         1318     -4,9%     2,143x         14/14

    KHÔNG ghi đè nhóm vertex trên mesh -- cái người dùng tô vẫn nguyên bản sắc
    nét, chỗ vuốt chỉ sống trong bộ nhớ lúc dựng shape key. Nhờ vậy chạy lại
    bao nhiêu lần cũng không cộng dồn.
    """
    if amount <= 0 or not regions:
        return regions
    adjacency = vertex_adjacency(face)
    out = dict(regions)
    for name, region in regions.items():
        if not region or is_sharp(name):
            continue
        others = set()
        for other, reg in regions.items():
            if other != name and reg:
                others.update(reg)
        # Chỉ ghim vertex giáp vùng BÊN KIA KHE, không ghim mọi hàng xóm.
        partner = regions.get(seam_partner(name) or "") or {}
        pin = {i for i in region
               if any(j in partner for j in adjacency.get(i, ()))}
        # Vành ngoài = vertex trong vùng mà có láng giềng là DA TRẦN.
        rim = [i for i in region
               if i not in pin
               and any(j not in region and j not in others
                       for j in adjacency.get(i, ()))]
        if not rim:
            continue
        depth = {i: 0 for i in rim}
        frontier = set(rim)
        for ring in range(1, amount + 1):
            nxt = set()
            for i in frontier:
                for j in adjacency.get(i, ()):
                    if j in region and j not in depth and j not in pin:
                        depth[j] = ring
                        nxt.add(j)
            frontier = nxt
        span = amount + 1.0
        out[name] = {
            i: w if i in pin
            else w * _smooth(min(1.0, (depth.get(i, amount + 1) + 1.0) / span))
            for i, w in region.items()}
    return out


def region_context(context):
    """Trả về (face, regions, frame) nếu đủ nhóm vùng, ngược lại (face, None, None)."""
    st = context.scene.face_shapes
    face = st.face if (st.face and st.face.type == 'MESH') else None
    if face is None:
        _, face = find_rig_and_mesh(context)
    if face is None:
        return None, None, None
    regions = {n: read_region(face, n) for n, _, _ in region_table(face)}
    if any(not regions.get(n) for n in REQUIRED):
        return face, None, None
    base = base_coords(face)
    # Hệ trục dựng từ nhóm THÔ. Nó là thứ đã đo và chỉnh theo; viền mềm thêm
    # một vành trọng số thấp quanh mỗi nhóm, đủ để xê dịch trọng tâm và kéo
    # theo mọi phép giải hình học phía sau.
    frame = FaceFrame(face, regions, base)
    if not frame.ok:
        return face, None, None
    return face, soften_regions(face, regions, st.soften), frame


# ================================================ xương hàm & xương mắt
#
# Hai xương DEFORM thêm vào rig có sẵn, để hàm và hướng nhìn điều khiển bằng
# xương thay vì bằng shape key. Shape key vẫn chạy nguyên trên đó: Blender tính
# shape key TRƯỚC modifier, nên armature nhận vào mesh đã cộng shape key rồi mới
# biến dạng. Đã đo: hàm 12° mở thêm 0,0065 m, VIS_AA mở thêm 0,0107 m, bật cả
# hai được 0,0143 m -- chồng lên nhau thật, chỉ là không cộng tuyến tính vì hai
# phép quay quanh hai bản lề khác nhau đi qua linear blend skinning.


def fit_sphere(points):
    """Khớp cầu bình phương tối thiểu -> (tâm, bán kính, sai số max, sai số tb).

    Dời gốc về trọng tâm trước khi giải. Toạ độ nhân vật đứng ở z≈1.5 làm hệ
    phương trình chuẩn tắc mất điều kiện: giải thẳng ra bán kính 0.449 m cho một
    nhãn cầu 0.036 m, sai số 0.35 m.
    """
    if len(points) < 4:
        return None, 0.0, 0.0, 0.0
    origin = sum(points, Vector((0, 0, 0))) / len(points)
    q = [p - origin for p in points]
    A = [[0.0] * 4 for _ in range(4)]
    b = [0.0] * 4
    for p in q:
        row = (2 * p.x, 2 * p.y, 2 * p.z, 1.0)
        rhs = p.length_squared
        for r in range(4):
            for c in range(4):
                A[r][c] += row[r] * row[c]
            b[r] += row[r] * rhs
    try:
        x = Matrix(A).inverted() @ Vector(b)
    except ValueError:
        return None, 0.0, 0.0, 0.0
    c = Vector((x[0], x[1], x[2]))
    rad = max(x[3] + c.length_squared, 0.0) ** 0.5
    err = [abs((p - c).length - rad) for p in q]
    return c + origin, rad, max(err), sum(err) / len(err)


def minimax_center(points, iters=400):
    """Tâm quả cầu BAO NHỎ NHẤT (Badoiu-Clarkson).

    Đây mới là tâm quay đúng cho nhãn cầu, chứ không phải tâm khớp bình phương.
    Nhãn cầu stylize không tròn hẳn, nên quay nó quanh một tâm bất kỳ sẽ đưa chỗ
    lồi nhất đi vòng quanh và chọc qua mí ở góc nhìn nào đó. Thứ quyết định là
    BÁN KÍNH LỚN NHẤT tính từ tâm -- nó chặn trên toàn bộ vùng nhãn cầu có thể
    quét tới. Đo trên `Male`, mức chồi ra thêm so với lúc nghỉ:

        tâm khớp bình phương   Rmax 0.0398   +1.85 mm
        tâm quả cầu bao        Rmax 0.0392   +0.28 mm
        trọng tâm vertex       Rmax 0.0433   +4.06 mm

    Hai tâm đầu chỉ cách nhau 2.1 mm nên hướng quay vẫn đúng giải phẫu.
    """
    if not points:
        return None
    c = sum(points, Vector((0, 0, 0))) / len(points)
    for i in range(1, iters + 1):
        far = max(points, key=lambda p: (p - c).length_squared)
        c = c + (far - c) / (i + 1)
    return c


def eye_gaze(points, center, frame):
    """Hướng nhìn của nhãn cầu, ĐO từ chính khối hình, không lấy `frame.fwd`.

    `frame.fwd` là pháp tuyến trung bình của vùng mặt nên nó nghiêng theo độ ngửa
    của khuôn mặt -- trên `Male` nó chếch LÊN 15,9 độ, và xương mắt dựng theo nó
    trông vểnh hẳn lên. Hướng đúng lấy từ trọng tâm vỏ nhãn cầu so với tâm quay:
    vỏ dày về phía lồi ra, tức phía con mắt nhìn. Đo được (±0,06, −0,998, −0,035)
    -- gần như thẳng và ngang.

    Bỏ luôn thành phần NGANG để hai mắt song song: mắt nghỉ phải nhìn thẳng, còn
    hội tụ là việc của animator.
    """
    if not points:
        return frame.fwd.copy()
    shell = (sum(points, Vector((0, 0, 0))) / len(points)) - center
    if shell.length < 1e-9:
        return frame.fwd.copy()
    shell = shell.normalized()
    shell = shell - frame.lat * shell.dot(frame.lat)
    return shell.normalized() if shell.length > 1e-6 else frame.fwd.copy()


def _smooth(t):
    t = min(1.0, max(0.0, t))
    return t * t * (3.0 - 2.0 * t)


def jaw_bone_plan(context, face, regions, base, frame, parent='Head', jaw='Jaw'):
    """(đầu xương, đuôi xương, ghi chú) cho xương hàm, đo từ chính mesh.

    KHÔNG dùng bản lề mà region_shapes() giải ra. Bản lề đó được khớp để tái tạo
    biến dạng MÔI với ít giãn lưới nhất, nên nó nằm sát miệng (đo trên `Male`:
    chỉ lùi 4,6 cm sau khe môi). Xương hàm thật phải quay quanh lồi cầu, gần
    tai -- xa hơn nhiều, nhờ vậy cằm mới đi xuống chứ không đi giật lùi.

    Hai mốc dùng để đặt, cả hai đều đo được:
      - cao độ: MÉP DƯỚI nhãn cầu (lồi cầu hàm nằm xấp xỉ ngang mí dưới)
      - trước sau: điểm giữa bề dày đầu ở đúng dải cao độ đó
    Không có nhãn cầu thì lùi về 35% chiều cao đầu tính từ khe môi.

    Nhãn cầu đo qua `eyeball_points()` chứ không đọc thẳng nhóm `FS_Eyeball`:
    tách nhãn cầu ra thành mesh riêng thì nhóm đó biến mất, mà mốc cao độ thì
    vẫn còn đo được -- chỉ là phải hỏi đúng chỗ.
    """
    note = []
    eye = []
    for side in ('L', 'R'):
        pts = eyeball_points(context, face, regions, side, base)
        if len(pts) >= 4:               # fit_sphere cần ít nhất 4 điểm
            c, r, _m, _a = fit_sphere(pts)
            if c is not None:
                eye.append((c, r))
    # Lấy vùng đầu bằng TỔNG trọng số cha + hàm. Đọc riêng nhóm cha là đọc thứ
    # chính hàm này vừa làm mỏng đi ở lần chạy trước: vùng đầu tụt từ 315 xuống
    # 207 vertex và đuôi xương nhảy khỏi mặt phẳng đối xứng sang x = 0.0476.
    hv = set(read_region(face, parent)) | set(read_region(face, jaw))
    head = [base[i] for i in hv] or base

    if eye:
        low = min(frame.uvw(c).y - r for c, r in eye)
        note.append("cao độ = mép dưới nhãn cầu")
    else:
        vs = [frame.uvw(p).y for p in head]
        seam = (frame.uvw(_centroid(regions.get('FS_LipUpper', {}), base)).y
                + frame.uvw(_centroid(regions.get('FS_LipLower', {}), base)).y) * 0.5
        low = seam + (max(vs) - min(vs)) * 0.35
        note.append("không có nhãn cầu -> cao độ = khe môi + 35% chiều cao đầu")

    band = [p for p in head if abs(frame.uvw(p).y - low) < 0.05]
    ws = [frame.uvw(p).z for p in (band or head)]
    depth = (min(ws) + max(ws)) * 0.5
    note.append("trước sau = giữa bề dày đầu ở dải đó (%d vertex)" % len(band or head))

    hinge = frame.origin + frame.up * low + frame.fwd * depth
    # Đuôi chỉ về cằm: điểm thấp nhất và ra trước nhất của vùng đầu. Ép về mặt
    # phẳng đối xứng, không thì trục cục bộ của xương lệch và quay quanh X không
    # còn là hạ hàm thuần tuý.
    chin = min(head, key=lambda p: frame.uvw(p).y - frame.uvw(p).z * 0.5)
    chin = chin - frame.lat * frame.uvw(chin).x
    return hinge, chin, note


def _centroid(reg, base):
    if not reg:
        return Vector((0, 0, 0))
    return sum((base[i] for i in reg), Vector((0, 0, 0))) / len(reg)


def _new_bone(arm, name, head, tail, parent, x_axis=None, xform=None, keep=False):
    """Dựng xương. `head`/`tail` ở hệ toạ độ MESH; `xform` đưa sang hệ armature.

    `keep=True`: xương đã có thì GIỮ NGUYÊN chỗ nó đang đứng. Dùng cho rig sinh
    từ marker — chỗ đứng do marker quyết, hàm này chỉ lo trọng số.
    """
    eb = arm.data.edit_bones.get(name)
    if eb is not None and keep:
        eb.use_deform = True
        return eb.name
    if eb is None:
        eb = arm.data.edit_bones.new(name)
    if xform is not None:
        R = xform.to_3x3()
        head, tail = xform @ head, xform @ tail
        if x_axis is not None:
            x_axis = R @ x_axis
    eb.head, eb.tail = head, tail
    eb.use_deform = True
    eb.use_connect = False
    if parent and parent in arm.data.edit_bones:
        eb.parent = arm.data.edit_bones[parent]
    if x_axis is not None:
        # Muốn trục X cục bộ trùng x_axis: Blender xếp Y dọc xương, nên Z phải là
        # X_mong_muốn × Y. align_roll() nhận đúng vector Z đó.
        y = (eb.tail - eb.head).normalized()
        z = x_axis.normalized().cross(y)
        if z.length > 1e-6:
            eb.align_roll(z)
    return eb.name


def _bone_names(arm):
    return {b.name for b in arm.data.bones}


def _bone_rows(face, bones):
    """{chỉ số vertex: {tên xương: trọng số}} — đọc MỘT lượt cho cả mesh."""
    index = {g.index: g.name for g in face.vertex_groups if g.name in bones}
    out = {}
    for vertex in face.data.vertices:
        row = {}
        for item in vertex.groups:
            name = index.get(item.group)
            if name is not None and item.weight > 0.0:
                row[name] = item.weight
        if row:
            out[vertex.index] = row
    return out


def _shift_to_jaw(face, field, bones, jaw_name, parent, skip=()):
    """Chuyển tỉ lệ `field[i]` trọng số của MỌI xương sang xương hàm.

    Lấy từ MỌI xương chứ không riêng xương cha. Lấy riêng xương cha thì TRẦN
    của xương hàm chính là trọng số cha đang có: đo trên `My_Body`, vertex da
    cằm chỉ có 0,826 ở `Head` (0,174 còn lại nằm ở `Neck`), nên dù mặt nạ gọi
    f = 1,0 thì cằm cũng chỉ đi được 82,6% quãng đường của hàm. Trong khi RĂNG
    DƯỚI được `_only_group()` gắn cứng 1,0 và gỡ khỏi mọi nhóm khác -- răng đi
    trọn còn da đi một nửa, và răng lòi ra ngoài cằm. Đo được: hạ hàm 34,3°
    thì răng đi 51,4 mm còn da cằm 40,0 mm, trượt 11,4 mm. Lấy từ mọi xương:
    da cằm 47,6 mm, trượt còn 3,8 mm.

    TỔNG trọng số mỗi vertex KHÔNG đổi (hàm được `f * tổng`, phần còn lại được
    `(1-f) * tổng` chia theo đúng tỉ lệ cũ), nên tư thế nghỉ không xê dịch một
    micromet nào -- điều kiện sống còn của 31 action đã bake.

    Trả về (số vertex đã chuyển, số vertex nằm trong vùng mà không có trọng số
    xương nào để lấy).
    """
    groups = {g.name: g for g in face.vertex_groups}
    jaw = groups.get(jaw_name) or face.vertex_groups.new(name=jaw_name)
    groups[jaw_name] = jaw
    rows = _bone_rows(face, bones)
    moved = orphan = 0
    for index, share in field.items():
        if index in skip:
            continue
        weight = min(1.0, share)
        row = rows.get(index)
        if not row:
            if weight > 1e-4:
                orphan += 1
            continue
        total = sum(row.values())
        held = row.get(jaw_name, 0.0)
        rest = total - held
        if total <= 1e-6:
            continue
        if weight <= 1e-4:
            # Lần chạy trước có, lần này không -> trả lại đúng chỗ cũ.
            if held <= 1e-6:
                continue
            jaw.remove([index])
            if rest > 1e-6:
                for name, value in row.items():
                    if name != jaw_name:
                        groups[name].add([index], value * total / rest, 'REPLACE')
            elif parent in groups:
                groups[parent].add([index], total, 'REPLACE')
            continue
        jaw.add([index], weight * total, 'REPLACE')
        if rest > 1e-6:
            scale = (1.0 - weight) * total / rest
            for name, value in row.items():
                if name == jaw_name:
                    continue
                if scale <= 1e-6:
                    groups[name].remove([index])
                else:
                    groups[name].add([index], value * scale, 'REPLACE')
        moved += 1
    return moved, orphan


def _only_group(obj, indices, name, protect):
    """Gán trọn indices cho nhóm `name`, gỡ khỏi mọi nhóm BONE khác."""
    g = obj.vertex_groups.get(name) or obj.vertex_groups.new(name=name)
    idx = sorted(indices)
    g.add(idx, 1.0, 'REPLACE')
    for other in obj.vertex_groups:
        if other.name == name or other.name not in protect:
            continue
        other.remove(idx)
    return len(idx)


# ---------------------------------------- tách nhãn cầu thành mesh riêng
#
# Nhãn cầu nằm TRONG mesh mặt là kiểu hay gặp ở nhân vật game, nhưng nó ép mọi
# thứ đi đường vòng: xương mắt phải giành lại vertex từ nhóm da, mí nhắm phải
# nắn thẳng trên vertex nhãn cầu, và một lần tô lấn vùng là da hốc mắt xoay
# theo con ngươi. Tách ra thành object riêng gắn vào xương thì con ngươi quay
# bằng chính phép quay của xương -- không còn trọng số nào để tô sai.
#
# Addon vốn đã đi được đường "nhãn cầu là object riêng" (`followers_for()` nhận
# chúng, `make_eyeball_key()` co/thụt chúng khi nhắm, `eyeball_exposure()` đo độ
# hở). Thiếu đúng một việc: cắt chúng ra.

EYE_MESH_NAME = "EyeMesh_%s"


def eyeball_islands(face, side, islands=None, home=None):
    """Chỉ số vertex của khối nhãn cầu một bên, lấy TRỌN đảo lưới."""
    reg = read_region(face, 'FS_Eyeball.%s' % side)
    if not reg:
        return set()
    if islands is None:
        islands = mesh_islands(face)
        home = {i: k for k, comp in enumerate(islands) for i in comp}
    return _eye_verts(face, reg, side, islands, home)


def _bone_parent(obj, arm, bone_name):
    """Gắn object vào một xương, giữ nguyên chỗ nó đang đứng.

    Parent kiểu BONE lấy ĐUÔI xương làm gốc, nên phải gán lại `matrix_world`
    sau khi nối -- không thì con ngươi nhảy đi đúng một đoạn bằng chiều dài
    xương mắt và trông như bị bắn ra sau gáy.
    """
    keep = obj.matrix_world.copy()
    obj.parent = arm
    obj.parent_type = 'BONE'
    obj.parent_bone = bone_name
    obj.matrix_world = keep


class FACESHAPES_OT_split_eyeballs(Operator):
    bl_idname = "face_shapes.split_eyeballs"
    bl_label = "Tách nhãn cầu thành mesh riêng"
    bl_description = ("Cắt hai khối nhãn cầu ra khỏi mesh mặt thành hai object "
                      "riêng, gắn vào xương mắt. Xoá luôn nhóm vùng FS_Eyeball "
                      "và nhóm trọng số của xương mắt trên mesh mặt")
    bl_options = {'REGISTER', 'UNDO'}

    eye_name: StringProperty(name="Tên xương mắt", default="Eye")
    keep_keys: BoolProperty(
        name="Giữ shape key trên nhãn cầu", default=False,
        description="TẮT: nhãn cầu tách ra vốn mang theo cả bộ shape key của "
                    "mặt, toàn bộ đều bằng 0 và vô nghĩa với một khối cứng. "
                    "Bật nếu bạn có key nắn tay riêng cho nhãn cầu")
    link_blink: BoolProperty(
        name="Nối co/thụt theo nhắm mắt", default=True,
        description="Dựng key co+thụt trên nhãn cầu rồi cho nó bám theo "
                    "EYE_Blink của mặt, để con ngươi không đâm qua khe mí")

    @classmethod
    def poll(cls, context):
        return find_face_mesh(context) is not None

    def execute(self, context):
        st = context.scene.face_shapes
        face = st.face if (st.face and st.face.type == 'MESH') \
            else find_face_mesh(context)
        if face is None:
            self.report({'ERROR'}, "Không tìm thấy mesh mặt")
            return {'CANCELLED'}
        arm = st.rig if (st.rig and st.rig.type == 'ARMATURE') else None
        if arm is None:
            # `deformed_by(face, arm)` tra ve BOOL, khong phai ham di tim rig.
            # Ham tim la `find_rig()`. Goi nham o day la TypeError ngay giua
            # chung, va no nam im cho toi khi ai do bo trong o chon rig.
            arm = find_rig(context, face)
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        if report_hidden(self, context, face, arm):
            return {'CANCELLED'}

        if not any(read_region(face, 'FS_Eyeball.%s' % s) for s in ('L', 'R')):
            self.report({'ERROR'}, "Không có nhóm FS_Eyeball.L/R để biết cắt chỗ nào")
            return {'CANCELLED'}

        made, notes = [], []
        for side in ('L', 'R'):
            # Tính lại chỉ số NGAY TRƯỚC mỗi lần cắt. Cắt bên trái xong là
            # Blender đánh số lại toàn bộ vertex còn lại, nên bảng tính một lần
            # từ đầu cho cả hai bên sẽ trỏ vào chỗ không còn tồn tại — đo được:
            # sau nhát cắt đầu mesh còn 2786 vertex mà bảng cũ vẫn hỏi vertex
            # thứ 2816.
            verts = eyeball_islands(face, side)
            if not verts:
                continue
            obj = self.cut(context, face, side, verts)
            if obj is None:
                notes.append("bên %s cắt không ra mesh nào" % side)
                continue
            made.append(obj)
            # Ghi thẳng vào ô chọn của bước 1. Thiếu bước này thì phần còn lại
            # của quy trình không hề biết nhãn cầu đã ra riêng: `srp.bind`
            # không gắn cứng nó vào xương mắt, và `make_regions` lại đẻ ra một
            # nhóm `FS_Eyeball` rỗng vì tưởng nhãn cầu vẫn nằm trong mesh mặt.
            settings = getattr(context.scene, "srp_generate", None)
            if settings is not None:
                # Ghi vao DANH SACH nhan cau chu khong vao hai o cu: danh sach
                # la duong chinh, hai o kia chi con la duong lui cho file cu.
                entry = next((e for e in settings.eyes
                              if e.side == side and e.mesh is None), None)
                if entry is None:
                    entry = settings.eyes.add()
                    entry.side = side
                entry.mesh = obj
            bone = "%s.%s" % (self.eye_name, side)
            if arm is not None and bone in arm.data.bones:
                _bone_parent(obj, arm, bone)
            else:
                notes.append("rig không có xương %r nên %s chưa gắn vào đâu"
                             % (bone, obj.name))

        # Mesh mặt không còn giữ nhãn cầu -> mọi nhóm liên quan đều thành rác.
        # Để lại là lần sau `_eye_verts()` lại đi tìm một khối không còn ở đó.
        dropped = []
        for name in (['FS_Eyeball.L', 'FS_Eyeball.R']
                     + ["%s.%s" % (self.eye_name, s) for s in ('L', 'R')]):
            group = face.vertex_groups.get(name)
            if group is not None:
                face.vertex_groups.remove(group)
                dropped.append(name)
        # Nhóm NGUỒN mà `make_regions` đổ ra `FS_Eyeball` (thường tên
        # `Eyeball.L/R`, thuộc rig khác trong cùng file). Sau khi cắt chúng
        # rỗng hoàn toàn -- để lại chỉ là rác, mà lần chạy `make_regions` sau
        # lại đổ ra một `FS_Eyeball` rỗng và mọi phép dò nhãn cầu tưởng có.
        # Thu TEN truoc roi moi xoa. Xoa mot nhom la Blender danh so lai ca
        # danh sach, nen moi tham chieu VertexGroup dang cam tren tay deu chet
        # ngay sau nhat xoa dau tien ("StructRNA has been removed").
        stale = [g.name for g in face.vertex_groups
                 if g.name.lower().startswith("eyeball")
                 and not read_region(face, g.name, min_w=0.0)]
        for name in stale:
            group = face.vertex_groups.get(name)
            if group is not None:
                face.vertex_groups.remove(group)
                dropped.append(name)

        if self.link_blink:
            notes += self.blink(context, face, made)

        self.report({'INFO'}, "Tách %s | xoá %d nhóm trên %s%s"
                    % (", ".join(o.name for o in made) or "không được cái nào",
                       len(dropped), face.name,
                       " | " + "; ".join(notes) if notes else ""))
        return {'FINISHED'}

    def cut(self, context, face, side, verts):
        """Cắt `verts` ra khỏi mesh mặt thành object mới, trả về object đó."""
        before = set(bpy.data.objects)
        for o in list(context.selected_objects):
            o.select_set(False)
        face.select_set(True)
        context.view_layer.objects.active = face

        # Chọn vertex ở OBJECT mode: cờ `select` ghi trong Edit Mode không có
        # tác dụng, Blender đọc bản sao bmesh chứ không đọc mesh gốc.
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_mode(type='VERT')
        bpy.ops.mesh.select_all(action='DESELECT')
        bpy.ops.object.mode_set(mode='OBJECT')
        for i in verts:
            face.data.vertices[i].select = True
        bpy.ops.object.mode_set(mode='EDIT')
        try:
            bpy.ops.mesh.separate(type='SELECTED')
        finally:
            bpy.ops.object.mode_set(mode='OBJECT')

        fresh = [o for o in bpy.data.objects if o not in before]
        if not fresh:
            return None
        obj = fresh[0]
        obj.name = EYE_MESH_NAME % side
        obj.data.name = obj.name
        # Bỏ armature modifier: con ngươi giờ đi theo XƯƠNG bằng parent, để cả
        # hai đường cùng chạy là nó chịu biến dạng hai lần.
        for mod in [m for m in obj.modifiers if m.type == 'ARMATURE']:
            obj.modifiers.remove(mod)
        for group in list(obj.vertex_groups):
            obj.vertex_groups.remove(group)
        if not self.keep_keys and obj.data.shape_keys:
            obj.shape_key_clear()
        return obj

    def blink(self, context, face, eyes):
        """Dựng key co+thụt trên nhãn cầu, bám theo EYE_Blink của mặt."""
        st = context.scene.face_shapes
        src = face.data.shape_keys
        if src is None:
            return ["mặt chưa có shape key nên chưa nối được co/thụt"]
        made = 0
        for eye in eyes:
            side = eye_side(eye)
            name = 'EYE_Blink%s' % side if side else None
            if not name or name not in src.key_blocks or not st.eye_shrink_on:
                continue
            kb = make_eyeball_key(eye, name, st.eye_shrink, st.eye_back)
            add_driver(kb, src, name, st.eye_threshold)
            made += 1
        return [] if made else ["mặt chưa có EYE_Blink nên chưa nối co/thụt"]


class FACESHAPES_OT_add_bones(Operator):
    bl_idname = "face_shapes.add_bones"
    bl_label = "Tô lại trọng số hàm & mắt"
    bl_description = ("Tô lại trọng số cho xương hàm và hai xương mắt. Bind "
                      "skin đã làm việc này rồi — nút này để chạy lại sau khi "
                      "sửa nhóm vùng hoặc dời xương, khỏi phải bind lại cả "
                      "thân. Rig chưa có ba xương đó thì dựng luôn")
    bl_options = {'REGISTER', 'UNDO'}

    do_jaw: BoolProperty(name="Xương hàm", default=True)
    do_eyes: BoolProperty(name="Xương mắt", default=True)
    jaw_name: StringProperty(name="Tên xương hàm", default="Jaw")
    eye_name: StringProperty(name="Tên xương mắt", default="Eye")
    parent_name: StringProperty(name="Nối vào xương", default="Head")
    keep_position: BoolProperty(
        name="Giữ nguyên vị trí xương đã có", default=True,
        description="BẬT: xương nào đã có thì để yên chỗ, chỉ tô lại trọng số "
                    "— chỗ đứng là do bộ xương ref (hoặc do bạn) quyết. TẮT: "
                    "đo lại và dời xương về mốc addon đo được")
    hinge_at_cursor: BoolProperty(
        name="Bản lề hàm ở 3D cursor", default=False,
        description="Đặt bản lề đúng chỗ con trỏ 3D đang đứng, thay vì mốc addon "
                    "tự đo. Dùng khi bạn đã ngắm được vị trí lồi cầu bằng mắt")
    hinge_lower: FloatProperty(
        name="Hạ bản lề hàm", default=0.0, min=-0.10, max=0.10, unit='LENGTH',
        description="Hạ bản lề xuống thì cằm ĐI XUỐNG nhiều hơn và LÙI ít hơn "
                    "khi há, vì bán kính quay nằm ngang hơn. Nâng lên thì ngược "
                    "lại. 0 = đặt đúng mốc đo được (ngang mép dưới nhãn cầu)")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=340)

    def execute(self, context):
        st = context.scene.face_shapes
        face, regions, frame = region_context(context)
        arm = st.rig if (st.rig and st.rig.type == 'ARMATURE') else None
        if arm is None and face is not None:
            for m in face.modifiers:
                if m.type == 'ARMATURE' and m.object is not None:
                    arm = m.object
                    break
        if face is None or arm is None:
            self.report({'ERROR'}, "Cần cả mesh mặt lẫn rig làm nó biến dạng")
            return {'CANCELLED'}
        if regions is None:
            self.report({'ERROR'}, "Thiếu nhóm vùng FS_* -- bấm 'Đánh dấu vùng mặt'")
            return {'CANCELLED'}
        if self.parent_name and self.parent_name not in _bone_names(arm):
            self.report({'ERROR'}, "Rig không có xương %r để nối vào"
                        % self.parent_name)
            return {'CANCELLED'}

        if report_hidden(self, context, face, arm):
            return {'CANCELLED'}

        base = base_coords(face)
        lines, made = [], []
        mode = context.object.mode if context.object else 'OBJECT'
        prev_active = context.view_layer.objects.active
        # Mọi phép đo làm ở hệ toạ độ MESH; xform đưa kết quả sang hệ armature.
        xform = arm.matrix_world.inverted() @ face.matrix_world
        to_mesh = face.matrix_world.inverted()

        # ---------------------------------------------------------- dựng xương
        context.view_layer.objects.active = arm
        bpy.ops.object.mode_set(mode='EDIT')
        try:
            eye_fit = {}
            if self.do_eyes:
                for side in ('L', 'R'):
                    # Nhãn cầu có thể đang là mesh riêng — hỏi `eyeball_points`
                    # chứ đừng đọc nhóm `FS_Eyeball`, nhóm đó bị xoá khi tách.
                    pts = eyeball_points(context, face, regions, side, base)
                    if len(pts) < 4:
                        continue
                    c = minimax_center(pts)
                    _ls, r, emax, eavg = fit_sphere(pts)
                    if c is None:
                        continue
                    reach = max((p - c).length for p in pts)
                    gaze = eye_gaze(pts, c, frame)
                    eye_fit[side] = (c, r, emax, eavg, reach)
                    name = "%s.%s" % (self.eye_name, side)
                    made.append(_new_bone(arm, name, c, c + gaze * reach * 2.2,
                                          self.parent_name, x_axis=frame.lat,
                                          xform=xform, keep=self.keep_position))
                    lines.append("%s: tâm quả cầu bao (%.4f, %.4f, %.4f) Rmax=%.4f "
                                 " | khớp cầu R=%.4f sai số tb %.5f max %.5f"
                                 % (name, c.x, c.y, c.z, reach, r, eavg, emax))
                    lines.append("   chĩa theo %s, lệch %.1f° so với phương ngang"
                                 % (tuple(round(x, 3) for x in gaze),
                                    math.degrees(math.asin(
                                        max(-1.0, min(1.0, gaze.z))))))
            if self.do_jaw:
                hinge, chin, note = jaw_bone_plan(context, face, regions, base,
                                                  frame, self.parent_name,
                                                  self.jaw_name)
                if self.hinge_at_cursor:
                    hinge = to_mesh @ context.scene.cursor.location.copy()
                    note = ["bản lề lấy từ 3D cursor, không phải mốc tự đo"]
                hinge = hinge + frame.up * (-self.hinge_lower)
                kept = self.keep_position and self.jaw_name in arm.data.edit_bones
                made.append(_new_bone(arm, self.jaw_name, hinge, chin,
                                      self.parent_name, x_axis=frame.lat,
                                      xform=xform, keep=self.keep_position))
                # Bản lề dùng cho đường suy giảm trọng số phải lấy từ CHÍNH
                # xương vừa dựng, và báo cáo cũng vậy — không thì bản
                # `keep_position` in ra bản lề DỰ TÍNH chứ không phải chỗ xương
                # thật sự đứng, mà hai chỗ đó cách nhau 8 cm trên `3.0_Rig`.
                placed = arm.data.edit_bones.get(self.jaw_name)
                if placed is not None:
                    inv = xform.inverted()
                    hinge = inv @ placed.head.copy()
                    chin = inv @ placed.tail.copy()
                lines.append("%s: bản lề (%.4f, %.4f, %.4f) -> cằm "
                             "(%.4f, %.4f, %.4f), dài %.4f"
                             % (self.jaw_name, hinge.x, hinge.y, hinge.z,
                                chin.x, chin.y, chin.z, (chin - hinge).length))
                for n in (["giữ nguyên chỗ xương đang đứng"] if kept else note):
                    lines.append("   " + n)
                # Điểm quay nào cũng cho cằm đi theo CUNG TRÒN, nên tỉ lệ
                # xuống/lùi bị hình học quyết chứ không chọn được: nó bằng đúng
                # tỉ lệ hai thành phần của bán kính quay, đảo chỗ cho nhau.
                low = regions.get('FS_TeethLower') or regions.get('FS_LipLower', {})
                if low:
                    r = _centroid(low, base) - hinge
                    down, back = abs(r.dot(frame.fwd)), abs(r.dot(frame.up))
                    lines.append("   há miệng: hàm răng dưới đi xuống %.2f phần, "
                                 "lùi %.2f phần (hạ bản lề xuống thì xuống nhiều "
                                 "hơn)" % (down / max(down + back, 1e-9),
                                           back / max(down + back, 1e-9)))
        finally:
            bpy.ops.object.mode_set(mode='OBJECT')

        # Xương mới phải vào đúng bone collection của xương cha, không thì nó
        # nằm ngoài bộ công tắc ẩn/hiện của rig và picker không thấy.
        parent_bone = arm.data.bones.get(self.parent_name)
        target = list(parent_bone.collections) if parent_bone else []
        for name in made:
            bone = arm.data.bones.get(name)
            if bone is None:
                continue
            if target and not list(bone.collections):
                for coll in target:
                    coll.assign(bone)
            # overwrite=False: không đè lên hình người ta đã tự chỉnh tay.
            widgets.apply_face_widget(arm.pose.bones[name], overwrite=False)

        counts = weigh_face_bones(
            arm, face, self.jaw_name, self.eye_name, self.parent_name,
            eyes_apart=[n for n in eye_bone_names(arm, self.eye_name)
                        if eyeball_object(context, n[-1],
                                          _eye_inst(n)) is not None])
        n_eye, n_jaw, n_teeth = counts or (0, 0, 0)

        context.view_layer.objects.active = prev_active
        if prev_active is not None and mode != 'OBJECT':
            try:
                bpy.ops.object.mode_set(mode=mode)
            except RuntimeError:
                pass

        for line in lines:
            prefs.log("[FaceShapes] " + line)
        prefs.log("[FaceShapes] trọng số: %d vertex nhãn cầu, %d vertex da theo hàm, "
              "%d vertex răng dưới" % (n_eye, n_jaw, n_teeth))
        self.report({'INFO'}, "Xong xương hàm & mắt: %s%s"
                    % (", ".join(made) or "không xương nào",
                       prefs.detail(" | %d vertex nhãn cầu, %d da hàm, %d răng"
                                    % (n_eye, n_jaw, n_teeth))))
        return {'FINISHED'}


# --------------------------------------- trọng số xương hàm & xương mắt
#
# Xương hàm và hai xương mắt CHỈ được ăn theo những vùng đã tô ở bước tạo shape
# key. Bản trước khoanh vùng ảnh hưởng của hàm bằng hình học: một dải chuyển
# tiếp quanh khe môi, cắt bởi mặt phẳng đi qua bản lề. Nó chạy được, nhưng nó
# là một phép đoán chồng lên một phép đoán -- trong khi mặt nạ ĐÚNG thì đã nằm
# sẵn trong các nhóm `FS_*`, do chính người dùng tô. Hai xương mắt xưa nay vẫn
# đọc thẳng `FS_Eyeball.*` rồi, giờ hàm cũng vậy.

JAW_REGIONS = ('FS_Jaw', 'FS_LipLower')      # da đi theo hàm
JAW_RIGID = 'FS_TeethLower'                  # gắn cứng, không nội suy
# Vùng PHẢI đứng yên. Hàm không được chạm tới dù chúng nằm ngay sát bên.
JAW_BLOCK = ('FS_LipUpper', 'FS_TeethUpper', 'FS_Nose',
             'FS_Brow.L', 'FS_Brow.R')


def jaw_block_names(face):
    """`JAW_BLOCK` cộng nhóm mí/nhãn cầu của MỌI con mắt mesh này có.

    Bảng tên cứng chỉ liệt kê được cặp mắt thứ nhất. Nhân vật bốn mắt thì hai
    nhóm mí của cặp thứ hai không nằm trong danh sách cấm, nên hàm bò lên tận
    mí mắt trên.
    """
    out = list(JAW_BLOCK)
    for inst, side in eye_slots(face):
        for fam in EYE_FAMILY:
            out.append(fam + eye_suffix(inst, side))
    return out

# Số vòng cạnh loang ra ngoài mặt nạ trước khi tắt hẳn.
#
# Các nhóm FS_ là mặt nạ NHỊ PHÂN -- đo trên `Male`: cả 16 nhóm đều có tổng
# trọng số đúng bằng số vertex, tức mọi trọng số là 1.0. Cắt đúng biên thì
# vertex biên nhảy thẳng từ theo-hàm-hoàn-toàn sang đứng-yên-hoàn-toàn và da
# rách ngay đó khi há miệng. Cũng đo được: 24 vertex da cằm đang theo hàm nằm
# NGOÀI vùng tô, vì `FS_Jaw` đổ từ `face_border.*` nên nó là vành quai hàm chứ
# không phủ hết mặt trước cằm. Loang vài vòng vá đúng chỗ đó, và vẫn CHẶN cứng
# ở `JAW_BLOCK` nên nó không bò lên môi trên hay lên mũi được.
#
# Đặt 0 là bám tuyệt đối vào vùng đã tô, không loang một vertex nào.
#
# Hai hằng số dưới đây ĐO mà ra, không chọn cho tròn số. Hạ hàm 15° trên `Male`
# rồi đo độ giãn cạnh vùng da -- tách riêng cạnh khe miệng, vì cạnh đó PHẢI
# giãn (đó là miệng mở ra) và trộn chung vào thì con số chỉ nói "miệng có mở
# không" chứ không nói "da có rách không":
#
#            dải hình học cũ   loang 3 không mượt   loang 3 + mượt 8
#   max          2.26x               3.33x               2.08x
#   p99          1.33x               1.48x               1.30x
#   cạnh >1.4x     18                  29                   8
#
# Tức là: bám mặt nạ tô mà KHÔNG làm mượt thì tệ hơn hẳn cách cũ -- mặt nạ nhị
# phân là một bậc thang, và bậc thang trong trường trọng số chính là chỗ rách.
# Có làm mượt thì tốt hơn cách cũ ở cả ba chỉ số, số cạnh xấu giảm hơn một nửa.
#
# Kiểm lại phần chức năng, cùng phép hạ hàm 15°: miệng há 36,7 mm và răng dưới
# đi 38,3 mm -- KHỚP TỪNG PHẦN MƯỜI với cách cũ; môi trên, răng trên, mũi và
# lông mày đều đứng yên 0,0 mm ở cả hai cách.
JAW_GROW = 3
JAW_SMOOTH = 8


def _grow_mask(face, seed, rings, block, smooth=JAW_SMOOTH, pin=()):
    """Loang mặt nạ ra `rings` vòng cạnh rồi làm mượt, không vượt `block`.

    Loang theo TOPOLOGY chứ không theo khoảng cách: hai mảng lưới rời nhau (răng
    với da) có thể sát nhau vài milimet mà không hề dính, nên loang theo khoảng
    cách là hàm dưới kéo luôn cả hàm răng trên.

    Bước làm mượt là bắt buộc, không phải trang trí. Đo được: chỉ loang không
    thôi thì da giãn tới 3.3-4.0x khi há hàm 15°, tệ hơn hẳn dải hình học cũ
    (2.26x) -- vì mặt nạ tô là NHỊ PHÂN, biên của nó là một bậc thang dựng đứng
    dù có loang mấy vòng, mà bậc thang trong trường trọng số thì đúng là chỗ
    lưới rách. Lấy trung bình với láng giềng vài lượt biến bậc thang thành dốc.
    `pin` giữ nguyên phần lõi (vành môi dưới) để nó không bị làm mượt kéo tụt
    xuống, còn `block` luôn đọc ra 0 nên biên tự bị kéo về 0.
    """
    adj = vertex_adjacency(face)
    field = dict(seed)
    frontier = set(seed)
    for ring in range(1, max(rings, 0) + 1):
        value = _smooth(1.0 - ring / float(rings + 1))
        nxt = set()
        for i in frontier:
            for j in adj.get(i, ()):
                if j not in field and j not in block:
                    nxt.add(j)
        for j in nxt:
            field[j] = value
        frontier = nxt
    if smooth <= 0:
        return field

    pin = set(pin)
    zone = set(field)
    for i in list(field):
        zone.update(j for j in adj.get(i, ()) if j not in block)
    zone -= pin
    for _ in range(smooth):
        nxt = {}
        for i in zone:
            neighbours = adj.get(i, ())
            if not neighbours:
                continue
            nxt[i] = 0.5 * field.get(i, 0.0) + 0.5 * (
                sum(field.get(j, 0.0) for j in neighbours) / len(neighbours))
        field.update(nxt)
    return {i: w for i, w in field.items() if w > 1e-4}


# Nhãn cầu là KHỐI CỨNG, y như hai hàm răng. Nên xương mắt phải xoay TRỌN cái
# khối đó chứ không phải "những vertex nào có tên trong nhóm" -- đo trên `Male`:
# `FS_Eyeball.L` có 71 vertex, nhưng chỉ 57 nằm trên đảo lưới nhãn cầu (hộp bao
# 7,8 x 3,9 x 7,8 cm), còn 14 vertex kia nằm trên đảo THÂN NGƯỜI và trùng đúng
# với vùng mí. 14 vertex da đó nhận trọng số 1.0 nên chúng xoay cứng theo nhãn
# cầu, kéo theo hốc mắt và vùng mặt quanh đó.
#
# Cùng bài học với `auto_teeth()`: khối cứng thì chia theo ĐẢO, không cắt từng
# vertex.
EYE_NEIGHBOURS = ('FS_Brow.%s', 'FS_Cheek.%s')

# Một đảo được coi là nhãn cầu khi nhóm đã tô phủ ít nhất chừng này. Đo được:
# đảo nhãn cầu 57/57 = 100%, đảo thân người 14/2391 = 0,6%. Khoảng cách giữa
# hai con số đủ rộng để ngưỡng nằm đâu trong đó cũng cho cùng kết quả.
EYE_ISLAND_COVER = 0.5


def _eye_verts(face, reg, side, islands, home):
    """Tập vertex xương mắt được phép điều khiển."""
    hit = {}
    for i in reg:
        k = home.get(i)
        if k is not None:
            hit[k] = hit.get(k, 0) + 1
    whole = set()
    for k, n in hit.items():
        if n >= EYE_ISLAND_COVER * len(islands[k]):
            whole.update(islands[k])
    if whole:
        return whole
    # Nhãn cầu dính liền mặt (không phải đảo riêng) thì không có khối nào để
    # lấy trọn. Lùi về nhóm đã tô, TRỪ các vùng xung quanh -- vẫn giữ đúng yêu
    # cầu "đừng đụng vào hốc mắt", chỉ là không sắc nét bằng.
    out = set(reg)
    for pattern in EYE_NEIGHBOURS:
        out -= set(read_region(face, pattern % side))
    # Trừ mí của MỌI con mắt cùng bên, không riêng con mắt thứ nhất: nhãn cầu
    # dính liền mặt mà bên cạnh còn một con mắt nữa thì mí của con kia cũng là
    # hốc mắt, xoay nó theo là kéo rách chỗ giữa hai mắt.
    for inst, _s in eye_slots(face, side):
        sfx = eye_suffix(inst, side)
        out -= set(read_region(face, 'FS_LidUpper' + sfx))
        out -= set(read_region(face, 'FS_LidLower' + sfx))
    out -= set(read_region(face, 'FS_Nose'))
    return out


def _set_eye(face, keep, name, bones, parent):
    """Gán trọn `keep` cho xương mắt, và TRẢ phần dư về xương cha.

    Phần dư là thứ `_only_group` một mình không dọn được: nó chỉ thêm vào chứ
    không gỡ trọng số cũ mà xương mắt đang giữ ở chỗ khác. Trong quy trình mới,
    `srp.bind` chạy automatic weights lúc rig ĐÃ CÓ xương mắt, nên xương mắt
    được chia phần khắp hốc mắt trước khi hàm này chạy.
    """
    eye = face.vertex_groups.get(name)
    stray = {}
    if eye is not None:
        stray = {i: w for i, w in read_region(face, name, min_w=0.0).items()
                 if i not in keep}
    if stray:
        src = face.vertex_groups.get(parent)
        if src is not None:
            parent_w = read_region(face, parent, min_w=0.0)
            for i, w in stray.items():
                src.add([i], min(1.0, parent_w.get(i, 0.0) + w), 'REPLACE')
        eye.remove(sorted(stray))
    return _only_group(face, keep, name, bones), len(stray)


# --------------------------- trọng số hàm KHÔNG cần nhóm vùng FS_
#
# Đường thứ hai, dùng khi mesh chưa có nhóm `FS_*`. Nó chỉ cần XƯƠNG HÀM và
# nhóm trọng số của xương cha -- tức chạy được ngay ở bước bind, không phải đợi
# bước shape key (bước cuối) tạo nhóm vùng ra trước.
#
# Mô hình: hàm dưới là một khối quay quanh bản lề. Da đi theo hàm nhiều hay ít
# tuỳ vị trí GÓC của nó quanh trục quay, đo từ chính trục xương hàm:
#
#        bản lề ●──────────► trục xương (hướng cằm)     góc = 0
#               │╲
#               │ ╲  góc dương = phía dưới trục
#               ▼  ╲
#            xuống   ● cằm
#
# Dưới `JAW_ANG_LO` thì không theo, trên `JAW_ANG_HI` thì theo trọn, ở giữa thì
# chuyển tiếp mượt. Hai ngưỡng này ĐO mà ra -- xem bảng trong `JAW_ANG_HI`.

# Góc ĐO ĐƯỢC quanh bản lề, trên `Male` (chóp cằm = 0° theo định nghĩa):
#
#     môi trên  -33,3 .. -26,7   tâm -29,0
#     môi dưới  -27,3 .. -19,8   tâm -24,9
#     mũi       -67,8 .. -39,8
#     mày       -75,4 .. -67,6
#
# Khe miệng nằm ở khoảng -27°. Bản đầu tôi đặt -8°..+34°, tức nằm hoàn toàn
# ngoài vùng đó: đo lại thì môi dưới đi 0,0 mm — miệng không hề mở, mà số giãn
# da thì đẹp nhất bảng vì nó có làm gì đâu.
#
# GIỚI HẠN CỦA ĐƯỜNG NÀY, đã quét và xác nhận: hai vành môi CHỒNG LẤN về góc
# (trên -33,3..-26,7, dưới -27,3..-19,8), nên cắt theo góc buộc phải hoặc lấy
# nhầm môi trên, hoặc bỏ sót môi dưới. Không cửa sổ nào thoát được:
#
#     cửa sổ        mượt   da p99   cạnh xấu   môi trên đi
#     -30..-24        8     2,91x      306       21,7 mm
#     -30..-24       24     2,17x      256       25,4 mm   <- tốt nhất
#     -29..-25       24     2,90x      274       27,0 mm
#     -28..-26       24     3,98x      361       28,0 mm
#     -27,5..-26,5   24     4,43x      333       27,1 mm
#     (mặt nạ FS_)          1,30x        8        0,0 mm
#
# Nên đây là đường LÙI, không phải đường ngang hàng. Nó làm được việc chính --
# há miệng 37 mm, gần bằng 36,9 mm của mặt nạ -- còn chuyện môi trên đi theo
# thì chỉ hai nhóm `FS_LipUpper`/`FS_LipLower` mới chữa được.
JAW_ANG_LO = math.radians(-30.0)      # trên mức này thì KHÔNG theo hàm
JAW_ANG_HI = math.radians(-24.0)      # dưới mức này thì theo TRỌN
JAW_GEO_SMOOTH = 24                   # mượt nhiều hơn đường mặt nạ, xem bảng
# Hạ hàm 15° trên `Male` rồi đo độ giãn cạnh vùng da (đã tách riêng cạnh khe
# miệng). So ba đường, cùng một mesh:
#
#                        mặt nạ FS_   hình học từ xương   automatic weights
#      da: max              2.08x           2.19x              6.43x
#      da: p99              1.30x           1.35x              1.92x
#      môi trên đi          0.0 mm          0.0 mm            21.4 mm
#
# Tức là: có nhóm `FS_` thì vẫn nên dùng nhóm. Không có thì đường hình học sát
# nút, và tốt hơn hẳn việc để mặc automatic weights.


def _weigh_jaw_bone(face, arm, jaw_name, parent, smooth=JAW_GEO_SMOOTH,
                    lo=JAW_ANG_LO, hi=JAW_ANG_HI):
    """Tô trọng số hàm chỉ bằng hình học xương. Trả về (số vertex, 0)."""
    src = face.vertex_groups.get(parent)
    jaw_bone = arm.data.bones.get(jaw_name)
    if src is None or jaw_bone is None:
        return 0, 0
    to_mesh = face.matrix_world.inverted() @ arm.matrix_world
    hinge = to_mesh @ jaw_bone.head_local.copy()
    chin = to_mesh @ jaw_bone.tail_local.copy()
    axis = chin - hinge
    if axis.length < 1e-6:
        return 0, 0
    axis.normalize()
    # Trục quay của hàm = trục X cục bộ của xương. `down` vuông góc với cả hai,
    # hướng xuống dưới trục xương.
    turn = (to_mesh.to_3x3() @ (jaw_bone.matrix_local.to_3x3()
                                @ Vector((1.0, 0.0, 0.0)))).normalized()
    down = axis.cross(turn).normalized()
    if down.dot(Vector((0.0, 0.0, -1.0))) < 0.0:
        down = -down                       # ghim cho `down` thật sự đi xuống

    base = base_coords(face)
    head_w = read_region(face, parent, min_w=0.0)
    jaw_w = read_region(face, jaw_name, min_w=0.0)
    total = {i: head_w.get(i, 0.0) + jaw_w.get(i, 0.0)
             for i in set(head_w) | set(jaw_w)}

    field = {}
    for i in total:
        r = base[i] - hinge
        # Phía SAU bản lề thì không theo hàm: quay quanh bản lề sẽ hất gáy lên.
        if r.dot(axis) <= 0.0:
            continue
        ang = math.atan2(r.dot(down), r.dot(axis))
        f = _smooth((ang - lo) / (hi - lo))
        if f > 1e-4:
            field[i] = min(1.0, f)
    if not field:
        return 0, 0
    if smooth > 0:
        field = _grow_mask(face, field, 0, set(), smooth,
                           {i for i, w in field.items() if w > 0.99})

    # Cùng phép tách với đường mặt nạ: lấy từ MỌI xương, giữ nguyên tổng.
    n, _orphan = _shift_to_jaw(face, field, _bone_names(arm), jaw_name, parent)
    return n, 0


def has_face_regions(mesh):
    """Mesh co du nhom vung ĐÃ TÔ de to lai trong so xuong mat khong.

    Doc that trong so chu khong chi hoi ten nhom: `make_regions` tao ra nhom
    RONG cho nguoi dung to vao, va mot nhom rong thi to xuong ham ra so khong.
    Vi the ham nay dat — 11,1 ms tren mesh 2 729 vertex / 150 nhom. Chi goi khi
    that su can (luc bam bind, luc ve panel dang mo), dung goi trong `poll()`;
    bang tien do dung `face_region_groups()`.
    """
    if mesh is None or mesh.type != 'MESH':
        return False
    return all(read_region(mesh, name) for name in REQUIRED)


def face_region_groups(mesh):
    """Ten cac nhom vung BAT BUOC da duoc TAO tren mesh — khong doc trong so.

    Chi tra tu dien nen gan nhu mien phi, dung duoc trong `poll()`. Phan biet
    ro voi `has_face_regions()`: ham kia hoi "da to chua", ham nay hoi "da tao
    chua". Bang tien do can cau thu hai — no la bang dan duong, va no phai ve
    lai vai chuc lan moi lan nguoi dung keo chuot.
    """
    if mesh is None or mesh.type != 'MESH':
        return []
    return [name for name in REQUIRED if mesh.vertex_groups.get(name) is not None]


def attach_eye(obj, arm, bone_name):
    """Gan nhan cau CUNG vao mot xuong mat.

    Nhan cau la khoi cung: cho no di theo XUONG bang parent thay vi bang trong
    so skin thi khong con trong so nao de to sai. Bo armature modifier di —
    de ca hai duong cung chay la no chiu bien dang hai lan.
    """
    for mod in [m for m in obj.modifiers if m.type == 'ARMATURE']:
        obj.modifiers.remove(mod)
    _bone_parent(obj, arm, bone_name)
    return obj.name


def drop_bone_weight(face, name, parent):
    """Trả trọng số của một xương về xương CHA rồi XOÁ nhóm của nó.

    Dùng cho mọi xương chỉ để cõng khối cứng chứ không deform da: nhãn cầu đã
    tách thành mesh riêng, hay xương cõng phụ kiện gắn cứng (mũ, kính, trang
    sức — xem `generate.mount_bones`). Với chúng, mọi vertex còn dính trên
    mesh người đều là trọng số thừa: kéo cái phụ kiện là kéo theo cả da.

    Tổng trọng số mỗi vertex giữ nguyên (phần của xương này cộng thẳng vào
    xương cha) nên tư thế nghỉ không xê dịch. Trả về số vertex đã gỡ.
    """
    group = face.vertex_groups.get(name)
    if group is None:
        return 0
    weights = read_region(face, name, min_w=0.0)
    src = face.vertex_groups.get(parent)
    if src is not None:
        parent_w = read_region(face, parent, min_w=0.0)
        for index, weight in weights.items():
            src.add([index], min(1.0, parent_w.get(index, 0.0) + weight),
                    'REPLACE')
    face.vertex_groups.remove(group)
    return len(weights)


def weigh_face_bones(arm, face, jaw_name="Jaw", eye_name="Eye",
                     parent_name="Head", grow=JAW_GROW, smooth=JAW_SMOOTH,
                     eyes_apart=()):
    """Tô trọng số cho xương hàm & xương mắt trên rig ĐÃ CÓ sẵn hai thứ đó.

    Tách hẳn khỏi operator để `srp.bind` gọi thẳng: trọng số là việc của bước
    bind skin, không phải việc riêng của một nút.

    `eyes_apart` là TÊN các xương mắt đã có nhãn cầu rời — xem
    `eyeball_object()`. Với chúng, mesh mặt KHÔNG được giữ trọng số nào: nhãn
    cầu quay bằng phép quay của xương rồi, phần còn dính chỉ có thể là da hốc
    mắt bị automatic weights chia nhầm.

    Trả về (số vertex nhãn cầu, số vertex da theo hàm, số vertex răng dưới),
    hoặc None nếu mesh chưa đủ nhóm vùng.
    """
    regions = {n: read_region(face, n) for n, _, _ in region_table(face)}
    bones = _bone_names(arm)
    if any(not regions.get(n) for n in REQUIRED):
        # Chua co nhom vung: van to duoc HAM bang hinh hoc xuong. Buoc bind
        # khong phai doi buoc shape key (buoc cuoi) tao nhom ra truoc nua.
        if jaw_name not in bones:
            return None
        n_jaw, _ = _weigh_jaw_bone(face, arm, jaw_name, parent_name)
        return 0, n_jaw, 0

    islands = mesh_islands(face)
    home = {i: k for k, comp in enumerate(islands) for i in comp}
    n_eye = n_stray = 0
    # Nhom `FS_Eyeball.<ben>` chi ta duoc CAP THU NHAT — cap do moi co the con
    # nam trong mesh mat. Cap thu hai tro di ban chat da la mesh rieng.
    first = {}
    for name in eye_bone_names(arm, eye_name):
        side = name[-1]
        first.setdefault(side, name)
        reg = regions.get('FS_Eyeball.%s' % side, {}) if first[side] == name else {}
        if reg:
            keep = _eye_verts(face, reg, side, islands, home)
            got, stray = _set_eye(face, keep, name, bones, parent_name)
            n_eye += got
            n_stray += stray
        elif name in eyes_apart:
            n_stray += drop_bone_weight(face, name, parent_name)
    if n_stray:
        prefs.log("[FaceShapes] gỡ %d vertex khỏi xương mắt và trả về %r — "
                  "chúng không thuộc khối nhãn cầu" % (n_stray, parent_name))

    n_jaw = n_teeth = 0
    if jaw_name in bones:
        n_jaw, n_teeth = _weigh_jaw(face, regions, bones, jaw_name,
                                    parent_name, grow, smooth)
    return n_eye, n_jaw, n_teeth


def _weigh_jaw(face, regions, bones, jaw_name, parent, grow=JAW_GROW,
               smooth=JAW_SMOOTH):
    """Chuyển một phần trọng số từ xương cha sang xương hàm, theo MẶT NẠ ĐÃ TÔ.

    Lấy TỪ chính xương cha chứ không gán mới: `w_jaw = w_cha * f`,
    `w_cha = w_cha * (1-f)`. Nhờ vậy tổng trọng số mỗi vertex không đổi, nên
    ở tư thế nghỉ mesh giống hệt trước từng milimet -- 31 action đã bake
    không xê dịch một chút nào. Gán mới rồi để Blender chuẩn hoá là đổi tỉ
    lệ với cổ và vai, và mọi action cũ đổi theo.
    """
    src = face.vertex_groups.get(parent)
    if src is None:
        return 0, 0
    teeth_lo = set(regions.get(JAW_RIGID) or {})
    teeth_up = set(regions.get('FS_TeethUpper') or {})

    lower, upper = {}, {}
    for name in JAW_REGIONS:
        for i, w in (regions.get(name) or {}).items():
            lower[i] = max(lower.get(i, 0.0), w)
    for name in jaw_block_names(face):
        for i, w in (regions.get(name) or {}).items():
            upper[i] = max(upper.get(i, 0.0), w)

    # Vertex nằm trong CẢ hai phía thì phía "phải đứng yên" THẮNG, không chia
    # đôi. Khoé miệng là chỗ này: đo trên `Male` có 6 vertex vừa thuộc
    # `FS_LipLower` vừa thuộc `FS_LipUpper`, vì khoé miệng thật sự thuộc cả hai
    # vành. Đã thử chia theo tỉ lệ (mỗi bên một nửa) và đo lại: hạ hàm 15° thì
    # môi trên bị kéo đi 23,4 mm, trong khi cách cũ giữ nó đứng yên tuyệt đối.
    # 23 mm trên một khuôn mặt là môi trên rơi theo hàm -- hỏng hẳn. Trừ thẳng
    # là khoé về 0, đúng bằng hành vi cũ.
    seed = {}
    for i, w in lower.items():
        share = w - upper.get(i, 0.0)
        if share > 1e-4:
            seed[i] = min(1.0, share)
    if not seed:
        # Không có vùng nào tô cho hàm dưới thì hàm chỉ điều khiển răng dưới.
        n_teeth = _only_group(face, teeth_lo, jaw_name, bones) if teeth_lo else 0
        return 0, n_teeth

    block = set(teeth_lo) | set(teeth_up) | set(upper)
    # Giữ nguyên lõi vành môi dưới: đó là phần PHẢI đi trọn theo hàm, làm mượt
    # nó là miệng há ra ít hơn góc hàm thật sự quay.
    core = {i for i, w in seed.items() if w > 0.99}
    field = _grow_mask(face, seed, grow, block, smooth, core)

    jaw = face.vertex_groups.get(jaw_name) \
        or face.vertex_groups.new(name=jaw_name)
    # Răng xử lý riêng bên dưới: hàm dưới gắn cứng vào xương hàm, hàm trên trả
    # trọn về sọ. Không cho mặt nạ mềm đụng vào.
    #
    # Phép tách giữ nguyên TỔNG trọng số mỗi vertex, nên chạy lại bao nhiêu lần
    # cũng ra một kết quả và tư thế nghỉ không xê dịch. Trước đây nó chỉ lấy từ
    # xương cha -- xem `_shift_to_jaw` để biết vì sao thế là không đủ.
    n, orphan = _shift_to_jaw(face, field, bones, jaw_name, parent,
                              skip=teeth_lo | teeth_up)

    # Vertex nằm trong vùng tô nhưng không xương nào giữ tí trọng số nào thì
    # phép tách không có gì để lấy, và nó lặng lẽ đứng yên. Nói ra chứ không
    # giấu -- đó là dấu hiệu vùng tô lấn ra ngoài phần đã skin.
    if orphan:
        prefs.log("[FaceShapes] %d vertex trong vùng hàm không có trọng số "
                  "xương nào nên không theo hàm được" % orphan)

    n_teeth = (_only_group(face, teeth_lo, jaw_name, bones)
               if teeth_lo else 0)
    if teeth_up:
        # Hàm trên phải đứng yên hoàn toàn -> trả trọn về xương cha. CỘNG phần
        # của hàm vào cha rồi mới gỡ: chỉ gỡ thì vertex răng trên vốn chỉ dính
        # `Jaw` thành vertex không trọng số, đứng lại giữa không trung khi đầu
        # quay. Tổng mỗi vertex giữ nguyên như `drop_bone_weight`.
        jaw_w = read_region(face, jaw_name, min_w=0.0)
        parent_w = read_region(face, parent, min_w=0.0)
        for index in teeth_up:
            moved = jaw_w.get(index, 0.0)
            if moved > 0.0:
                src.add([index], min(1.0, parent_w.get(index, 0.0) + moved),
                        'REPLACE')
        jaw.remove(sorted(teeth_up))
    return n, n_teeth


class FACESHAPES_OT_build(Operator):
    bl_idname = "face_shapes.build"
    bl_label = "Dựng bộ shape key"
    bl_description = ("Dựng toàn bộ viseme + biểu cảm miệng/má/mũi/mắt/mày. "
                      "Dựng lại đè lên bộ cũ của addon, GIỮ NGUYÊN shape key "
                      "làm tay")
    bl_options = {'REGISTER', 'UNDO'}

    wipe_foreign: BoolProperty(
        name="Xoá cả shape key làm tay", default=False,
        description="Mặc định TẮT: shape key không phải do addon sinh ra được "
                    "giữ nguyên. Bật thì mesh bị dọn trắng trước khi dựng")
    follow_skin: BoolProperty(
        name="Lông mày / râu rời bám da", default=True,
        description="Dựng xong thì lông mày, râu, mi rời tự bám theo mọi key mới "
                    "của mặt (như nút 'Lông mày / râu rời bám da')")

    def invoke(self, context, event):
        _arm, face = find_rig_and_mesh(context)
        key = face.data.shape_keys if face is not None else None
        own = [kb for kb in key.key_blocks if is_own(key, kb)] if key else []
        if not own:
            return self.execute(context)
        hand = len(key.key_blocks) - 1 - len(own)
        msg = "%d shape key do addon dựng trên %s sẽ được dựng lại (chỉnh tay trên chúng sẽ mất)." % (
            len(own), face.name)
        if hand:
            msg += " %d key bạn tự làm được giữ nguyên." % hand
        return context.window_manager.invoke_confirm(
            self, event, title="Dựng lại bộ shape key", message=msg, confirm_text="Dựng lại",
            icon='WARNING')

    def execute(self, context):
        res = self._execute(context)
        if 'FINISHED' in res and self.follow_skin:
            from . import ux
            _arm, face = find_rig_and_mesh(context)
            if face is not None and face.data.shape_keys:
                lines = ux.follow_all(context, face)
                if lines:
                    self.report({'INFO'}, " | ".join(lines))
        return res

    def strip(self, objs):
        """Dọn chỗ cho bộ mới. Trả về False nếu phải dừng."""
        kept = foreign_keys(objs)
        gone = clear_own(objs, wipe=self.wipe_foreign)
        self.kept = ["%s / %s" % (o.name, kb.name) for o, kb in kept]
        if self.wipe_foreign and kept:
            prefs.log("[FaceShapes] đã xoá %d shape key làm tay theo yêu cầu: %s"
                  % (len(kept), ", ".join(self.kept)))
        elif kept:
            prefs.log("[FaceShapes] giữ nguyên %d shape key làm tay: %s"
                  % (len(kept), ", ".join(self.kept)))
        prefs.log("[FaceShapes] đã bỏ %d shape key cũ của addon" % gone)
        return True

    def build_region(self, context):
        st = context.scene.face_shapes
        face, regions, frame = region_context(context)
        if face is None:
            self.report({'ERROR'}, "Không tìm thấy mesh mặt")
            return {'CANCELLED'}
        if regions is None:
            self.report({'ERROR'}, "Thiếu nhóm vùng %s -- bấm 'Đánh dấu vùng mặt' "
                                   "rồi tô nếu cần" % ", ".join(REQUIRED))
            return {'CANCELLED'}

        arm = st.rig if (st.rig and st.rig.type == 'ARMATURE') else None
        teeth, eyes = followers_for(arm, face) if arm else ([], [])
        if not st.do_teeth:
            teeth = []
        if not st.do_eyes:
            eyes = []
        if not self.strip([face] + teeth + eyes):
            return {'CANCELLED'}
        base = base_coords(face)

        # Dò góc gấp mí TRƯỚC khi dựng: phép dò cần đo trên mesh ĐÃ TÍNH, mà
        # bộ dựng thì thuần toán học. Xem khối ghi chú ở `solve_lid_angles`.
        angles, notes, _cover = solve_lid_angles(context, face, regions,
                                                base, frame)
        for ln in notes:
            prefs.log("[FaceShapes] dò góc mí | " + ln)

        shapes, mm = region_shapes(face, regions, frame, base, smooth=st.smooth,
                                   ex=st.exaggerate / 100.0,
                                   cap=st.stretch_cap, context=context,
                                   lid_angles=angles)
        made = build_from_regions(face, shapes)

        # Nhãn cầu co+thụt giờ MẶC ĐỊNH TẮT -- xem `eye_shrink_on`. Nó vốn là
        # thứ che giấu chuyện mí không hề khép.
        for eye in eyes:
            s = eye_side(eye)
            key = 'EYE_Blink%s' % s if s else None
            if key and key in made and st.eye_shrink_on:
                make_eyeball_key(eye, key, st.eye_shrink, st.eye_back)
        src = face.data.shape_keys
        for o in eyes:
            # CHỈ nối driver cho key của addon: mắt cũng có thể mang shape key
            # làm tay, gán driver lên đó là cướp quyền điều khiển của người ta.
            key = o.data.shape_keys
            if key:
                for kb in key.key_blocks:
                    if is_own(key, kb) and kb.name in src.key_blocks:
                        add_driver(kb, src, kb.name, st.eye_threshold)

        # HỢP ĐỒNG chấm ở ĐÂY -- sau khi key đã nằm trên mesh, tức sau làm
        # mượt, sau chốt giãn cạnh, sau chốt chặn nhãn cầu. Chấm sớm hơn là chấm
        # một thứ không phải thứ sẽ dùng; đó đúng là cách bốn lỗi vừa rồi lọt.
        checks = region_invariants(context, face)
        checks += eye_contract(context, face, presets=sorted(EXPR_PRESETS.items()))
        for lvl, nm, why in checks:
            if lvl != 'ĐẠT' or prefs.verbose():
                prefs.log("[FaceShapes] hợp đồng | %s %s: %s" % (lvl, nm, why))
        self._contract = [r for r in checks if r[0] == 'HỎNG']

        have = [n for n, _, _ in region_table(face) if regions.get(n)]
        prefs.log("[FaceShapes] chế độ VÙNG | %s: %d shape key" % (face.name, len(made)))
        prefs.log("[FaceShapes] vùng dùng được: " + ", ".join(have))
        prefs.log("[FaceShapes] nửa rộng miệng %.4f | khe môi ở v=%.4f | cường điệu %.0f%%"
              % (mm['half'], mm['seam'], st.exaggerate))
        cp = mm.get('capped') or {}
        if cp:
            prefs.log("[FaceShapes] chốt chặn đã hạ %d shape key: %s"
                  % (len(cp), ", ".join(
                      "%s %.0f%% (%s)" % (k, v[0] * 100, v[1])
                      for k, v in sorted(cp.items(), key=lambda kv: kv[1][0]))))
        else:
            prefs.log("[FaceShapes] chốt chặn: không shape key nào chạm trần")
        gd = mm.get('guard') or {}
        if gd:
            scl = max(face.matrix_world.to_scale())
            prefs.log("[FaceShapes] chặn nhãn cầu: đẩy da ra khỏi nhãn cầu ở %d "
                      "shape key | %s" % (len(gd), ", ".join(
                          "%s %d vertex (%.1f mm)" % (k, v[0], v[1] * scl * 1000)
                          for k, v in sorted(gd.items(),
                                             key=lambda kv: -kv[1][1])[:6])))
            stuck = {k: v[2] for k, v in gd.items() if len(v) > 2 and v[2]}
            if stuck:
                prefs.log("[FaceShapes] chặn nhãn cầu: %d shape key chưa gỡ hết "
                          "sau %d vòng (%s) -- hai nhãn cầu chồng nhau quá sát?"
                          % (len(stuck), EYE_PASSES,
                             ", ".join("%s còn %d" % kv
                                       for kv in sorted(stuck.items())[:4])))
        else:
            prefs.log("[FaceShapes] chặn nhãn cầu: không key nào đâm vào nhãn cầu")
        broke = getattr(self, "_contract", [])
        if broke:
            self.report({'WARNING'},
                        "Đã dựng %d shape key trên %s -- nhưng %d mục KHÔNG ĐẠT "
                        "hợp đồng: %s (xem Console)"
                        % (len(made), face.name, len(broke),
                           "; ".join("%s %s" % (r[1], r[2].split(' -- ')[0])
                                     for r in broke[:2])))
        else:
            self.report({'INFO'}, "Đã dựng %d shape key theo vùng trên %s -- "
                                  "đạt hết hợp đồng" % (len(made), face.name))
        return {'FINISHED'}

    def _execute(self, context):
        st = context.scene.face_shapes
        if st.mode == 'REGION':
            return self.build_region(context)
        if st.mode == 'AUTO':
            # Rig do Rig Tẩm Hành sinh ra có sẵn xương mặt -> đi theo rig trước:
            # xương mặt chính là thứ người ta sẽ animate, shape key nướng từ
            # đó khớp đúng biên độ của rig.
            arm, _ = find_rig_and_mesh(context)
            if facerig.has_face_rig(arm):
                return self.build_rig(context)
            face, regions, frame = region_context(context)
            if regions is not None:
                return self.build_region(context)
            arm, _ = find_rig_and_mesh(context)
            if arm is None or missing_bones(arm):
                self.report({'ERROR'},
                            "Không có nhóm vùng FS_* mà rig cũng không đủ bone điều "
                            "khiển. Bấm 'Đánh dấu vùng mặt' để dùng chế độ vùng")
                return {'CANCELLED'}
        return self.build_rig(context)

    def build_rig(self, context):
        st = context.scene.face_shapes
        arm, face = find_rig_and_mesh(context)
        if facerig.has_face_rig(arm):
            if face is None:
                self.report({'ERROR'}, "Không tìm thấy mesh mặt")
                return {'CANCELLED'}
            if report_hidden(self, context, arm, face):
                return {'CANCELLED'}
            if not deformed_by(face, arm):
                self.report({'ERROR'}, "Rig %r không làm mesh %r biến dạng -- bind "
                                       "skin trước (mục 6)" % (arm.name, face.name))
                return {'CANCELLED'}
            return facerig.build(self, context, arm, face)
        if not st.calibrated:
            res, msg = calibrate(context)
            if res is None:
                self.report({'ERROR'}, msg)
                return {'CANCELLED'}
        arm, face = find_rig_and_mesh(context)
        if arm is None or face is None:
            self.report({'ERROR'}, "Không tìm thấy rig hoặc mesh mặt")
            return {'CANCELLED'}
        if not deformed_by(face, arm):
            # Không có chốt này thì hỏng lặng lẽ: pose bone xong mesh không nhúc
            # nhích, mọi hiệu số đều dưới ngưỡng, và addon báo "đã dựng 0 shape
            # key" như thể đó là chuyện bình thường.
            self.report({'ERROR'},
                        "Rig %r không làm mesh %r biến dạng (không có modifier "
                        "Armature trỏ tới nó, cũng không phải cha nó). Chọn đúng "
                        "rig ở ô Rig, hoặc dùng chế độ 'Theo vùng vertex group'."
                        % (arm.name, face.name))
            return {'CANCELLED'}

        M = measure(arm, face)
        M['meet'] = st.meet or M['meet']
        teeth, eyes = followers_for(arm, face)
        if not st.do_teeth:
            teeth = []
        if not st.do_eyes:
            eyes = []
        targets = [face] + teeth

        if not self.strip(targets + eyes):
            return {'CANCELLED'}

        recipes = build_recipes(arm, M, st.anchor, st.jaw_max,
                                ex=st.exaggerate / 100.0)
        made = {o.name: [] for o in targets}

        # `rest` phải đo SAU khi tắt hết shape key, không phải trước: key làm tay
        # còn bật thì nó nằm trong rest mà không nằm trong các trạng thái pose
        # sau đó, và hiệu số mang luôn hình dạng của nó vào mọi key mới.
        with PoseScope(arm) as scope, KeyScope(targets + eyes):
            for o in targets:
                ensure_basis(o)
            zero_keys(targets)
            rest = {o.name: eval_coords(o) for o in targets}
            for name in sorted(recipes, key=sort_key):
                scope.reset()
                zero_keys(targets)
                apply_ops(arm, recipes[name])
                for o in targets:
                    if bake(o, name, rest[o.name]) is not None:
                        made[o.name].append(name)
            scope.reset()
            zero_keys(targets)

        # nhãn cầu: shape key riêng, không bake từ pose
        for eye in eyes:
            s = eye_side(eye)
            key = 'EYE_Blink%s' % s if s else None
            if key and key in made[face.name] and st.eye_shrink_on:
                make_eyeball_key(eye, key, st.eye_shrink, st.eye_back)

        # driver: răng và nhãn cầu bám theo mesh mặt -> người dùng chỉ chỉnh 1 chỗ
        src = face.data.shape_keys
        for o in teeth + eyes:
            key = o.data.shape_keys
            if not key:
                continue
            thr = st.eye_threshold if o in eyes else 0.0
            for kb in key.key_blocks:
                if is_own(key, kb) and kb.name in src.key_blocks:
                    add_driver(kb, src, kb.name, thr)

        n = len(made[face.name])
        prefs.log("[FaceShapes] %s: %d shape key | cường điệu %.0f%%"
              % (face.name, n, st.exaggerate))
        for o in teeth + eyes:
            k = o.data.shape_keys
            prefs.log("[FaceShapes] %s: %d (driver)" % (o.name,
                                                    len(k.key_blocks) - 1 if k else 0))
        self.report({'INFO'}, "Đã dựng %d shape key trên %s" % (n, face.name))
        return {'FINISHED'}


class FACESHAPES_OT_audit(Operator):
    bl_idname = "face_shapes.audit"
    bl_label = "Kiểm tra nhân vật mới"
    bl_description = ("Dựng thử rồi chấm theo bộ bất biến -- giãn cạnh, lật mặt, "
                      "khép mí, mở miệng, đối xứng. Cho biết addon xử lý được "
                      "khuôn mặt này tới đâu, KHÔNG ghi shape key nào")
    bl_options = {'REGISTER'}

    def execute(self, context):
        st = context.scene.face_shapes
        face, regions, frame = region_context(context)
        if face is None:
            self.report({'ERROR'}, "Không tìm thấy mesh mặt")
            return {'CANCELLED'}
        if regions is None:
            self.report({'ERROR'}, "Thiếu nhóm vùng %s" % ", ".join(REQUIRED))
            return {'CANCELLED'}

        base = base_coords(face)
        angles, notes, cover = solve_lid_angles(context, face, regions, base,
                                                frame)
        R, mm = region_shapes(face, regions, frame, base, smooth=st.smooth,
                              ex=st.exaggerate / 100.0, cap=st.stretch_cap,
                              context=context, lid_angles=angles)
        rows = audit_shapes(face, regions, base, R, frame, mm,
                            cap=st.stretch_cap, cover=cover)

        nb = sum(1 for l, _, _ in rows if l == 'HỎNG')
        nw = sum(1 for l, _, _ in rows if l == 'CẢNH BÁO')
        have = [n for n, _, _ in region_table(face) if regions.get(n)]
        miss = [n for n, _, _ in region_table(face) if not regions.get(n)]
        out = ["BẢNG ĐIỂM - %s" % face.name,
               "=" * 66,
               "cường điệu %.0f%% | làm mượt %d | trần giãn cạnh %.2f"
               % (st.exaggerate, st.smooth, st.stretch_cap),
               "vùng đã tô : %s" % ", ".join(have),
               "vùng bỏ trống: %s" % (", ".join(miss) or "không có"),
               "nửa rộng miệng %.4f | bản lề hàm dò được ở %s (toạ độ thế giới)"
               % (mm.get('half', 0.0),
                  tuple(round(v, 3) for v in (face.matrix_world @ mm['hinge']))
                  if mm.get('hinge') else "-"),
               "", "%-6s %-16s %s" % ("mức", "shape key", "đo được"),
               "-" * 66]
        order = {'HỎNG': 0, 'CẢNH BÁO': 1, 'BỎ QUA': 2, 'ĐẠT': 3}
        for lvl, name, msg in sorted(rows, key=lambda r: (order[r[0]], r[1])):
            out.append("%-6s %-16s %s" % (lvl, name, msg))

        out += ["", "=" * 66]
        if nb:
            out.append("KẾT LUẬN: %d mục HỎNG -- chưa dùng được." % nb)
            out.append("  Lật mặt thì hạ cường điệu, hoặc tăng Làm mượt.")
            out.append("  Không dịch chuyển vertex nào thì thiếu nhóm vùng.")
        elif nw:
            out.append("KẾT LUẬN: dùng được, %d mục cần để ý." % nw)
            out.append("  Khép mí thiếu: tô rộng nhóm FS_LidUpper/LidLower ra "
                       "cho phủ hết mí.")
            out.append("  Mở miệng thiếu: tô rộng FS_LipUpper/FS_LipLower, "
                       "hoặc tăng cường điệu.")
            out.append("  Lệch trái-phải: tô lại cho cân, hoặc dùng Mirror.")
        else:
            out.append("KẾT LUẬN: đạt hết. Bấm Dựng bộ shape key được rồi.")

        txt = bpy.data.texts.get("FaceShapes_BangDiem") \
            or bpy.data.texts.new("FaceShapes_BangDiem")
        txt.clear()
        txt.write("\n".join(out))
        prefs.log("\n".join(out))
        lvl = {'ERROR'} if nb else ({'WARNING'} if nw else {'INFO'})
        self.report(lvl, "Bảng điểm: %d hỏng, %d cảnh báo -- xem text block "
                         "FaceShapes_BangDiem" % (nb, nw))
        return {'FINISHED'}


class FACESHAPES_OT_qc(Operator):
    bl_idname = "face_shapes.qc"
    bl_label = "Kiểm định bộ shape key"
    bl_description = ("Đo biên độ và vùng ảnh hưởng từng shape key, dò nhãn cầu "
                      "đâm qua mí. Kết quả ghi vào text block FaceShapes_QC")
    bl_options = {'REGISTER'}

    def execute(self, context):
        arm, face = find_rig_and_mesh(context)
        st = context.scene.face_shapes
        if face is None and st.face:
            face = st.face
        if face is None or not face.data.shape_keys:
            self.report({'ERROR'}, "Chưa có shape key để kiểm định")
            return {'CANCELLED'}
        # Mốc kiểm vùng ảnh hưởng: ưu tiên nhóm FS_*, vì chế độ vùng không cần rig
        zone = region_zone(face)
        height = lambda co: co.z            # noqa: E731 -- z object như cũ
        if zone is None and facerig.has_face_rig(arm):
            # Đo trong WORLD: mesh có thể xoay và mang scale (body của Kid
            # xoay -90° X, scale 0.01 -- z object của nó là CHIỀU SÂU). So z
            # object với bề rộng miệng tính theo armature là báo động giả trên
            # mọi key.
            F = facerig.Frame(arm)
            mouth = arm.matrix_world @ F.mouth
            reach = (arm.matrix_world.to_3x3() @ (F.up * F.W * 4)).length
            zone = (mouth.z - reach, mouth.z + reach)
            mw = face.matrix_world
            height = lambda co: (mw @ co).z  # noqa: E731
        if zone is None and arm and not missing_bones(arm):
            M = measure(arm, face)
            zone = (M['mouth_z'] - M['mouth_w'] * 4, M['mouth_z'] + M['mouth_w'] * 4)
        sk = face.data.shape_keys
        basis = sk.key_blocks['Basis']
        out = ["BÁO CÁO KIỂM ĐỊNH - %s" % face.name, "=" * 58, "",
               "%-16s %9s %7s  %s" % ("shape key", "biên độ", "vertex", "vùng z")]
        warn = []
        for kb in sk.key_blocks:
            if kb.name == 'Basis':
                continue
            d = [((kb.data[i].co - basis.data[i].co).length, i)
                 for i in range(len(basis.data))]
            moved = [x for x in d if x[0] > 2e-4]
            mx = max(d)[0] if d else 0.0
            if not moved:
                warn.append("%s: không tạo ra biến dạng nào" % kb.name)
                continue
            zs = [height(basis.data[i].co) for _, i in moved]
            out.append("%-16s %9.4f %7d  %.3f..%.3f"
                       % (kb.name, mx, len(moved), min(zs), max(zs)))
            # vùng ảnh hưởng phải nằm gọn trong khuôn mặt, không lan ra ngoài
            if zone and min(zs) < zone[0]:
                warn.append("%s: lan xuống z=%.3f, quá xa vùng mặt -- nhiều khả "
                            "năng bake sai (nướng thẳng evaluated thay vì lấy hiệu)"
                            % (kb.name, min(zs)))

        _, eyes = followers_for(arm, face) if arm else ([], [])
        if eyes:
            out += ["", "NHÃN CẦU ĐÂM QUA MÍ (ray cast)"]
            for kb in sk.key_blocks:
                if kb.name != 'Basis':
                    kb.value = 0.0
            for eye in eyes:
                s = eye_side(eye)
                key = 'EYE_Blink%s' % s if s else None
                if not key or key not in sk.key_blocks:
                    continue
                base = eyeball_exposure(eye)
                sk.key_blocks[key].value = 1.0
                bpy.context.view_layer.update()
                shut = eyeball_exposure(eye)
                sk.key_blocks[key].value = 0.0
                bpy.context.view_layer.update()
                out.append("  %-16s mở %5.2f%%  ->  nhắm %5.2f%%" % (eye.name, base, shut))
                if shut > 2.0:
                    warn.append("%s: nhắm rồi mà nhãn cầu còn lòi %.2f%% -- tăng "
                                "'Nhãn cầu co' hoặc 'Nhãn cầu thụt'" % (eye.name, shut))

        out += ["", "CẢNH BÁO"] + (["  - " + w for w in warn] or ["  không có"])
        txt = bpy.data.texts.get("FaceShapes_QC") or bpy.data.texts.new("FaceShapes_QC")
        txt.clear()
        txt.write("\n".join(out))
        prefs.log("\n".join(out))
        self.report({'WARNING' if warn else 'INFO'},
                    "%d cảnh báo -- xem text block FaceShapes_QC" % len(warn))
        return {'FINISHED'}


class FACESHAPES_OT_clear(Operator):
    bl_idname = "face_shapes.clear"
    bl_label = "Xoá bộ shape key"
    bl_description = "Xoá bộ shape key do addon dựng. Key làm tay được giữ nguyên"
    bl_options = {'REGISTER', 'UNDO'}

    wipe_foreign: BoolProperty(
        name="Xoá cả shape key làm tay", default=False,
        description="Bật thì dọn trắng mesh, kể cả key không phải của addon")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        arm, face = find_rig_and_mesh(context)
        if face is None:
            self.report({'ERROR'}, "Không tìm thấy mesh mặt")
            return {'CANCELLED'}
        teeth, eyes = followers_for(arm, face)
        objs = [face] + teeth + eyes
        if facerig.has_face_rig(arm):
            objs += [o for o in facerig.targets_for(arm, face) if o not in objs]
        kept = len(foreign_keys(objs)) if not self.wipe_foreign else 0
        n = clear_own(objs, wipe=self.wipe_foreign)
        msg = "Đã xoá %d shape key" % n
        if kept:
            msg += " | giữ nguyên %d key làm tay" % kept
        self.report({'INFO'}, msg)
        return {'FINISHED'}


# Bang bieu cam mau. Nam o MODULE chu khong trong operator vi hop dong
# (`eye_contract`) phai cham CA TO HOP -- shape key cong tuyen tinh nen
# cham rieng tung key khong bao gio du.
EXPR_PRESETS = {
    'Trung tính': {},
    'Vui': {'MTH_SmileL': 1, 'MTH_SmileR': 1, 'EYE_SquintL': .4,
            'EYE_SquintR': .4, 'BRW_UpL': .4, 'BRW_UpR': .4},
    'Giận dữ': {'BRW_AngryL': 1, 'BRW_AngryR': 1, 'EYE_SquintL': .5,
                'EYE_SquintR': .5, 'MTH_FrownL': .6, 'MTH_FrownR': .6,
                'VIS_AA': .35},
    'Buồn': {'BRW_SadL': 1, 'BRW_SadR': 1, 'MTH_FrownL': 1, 'MTH_FrownR': 1,
             'EYE_BlinkL': .35, 'EYE_BlinkR': .35},
    'Ngạc nhiên': {'BRW_UpL': 1, 'BRW_UpR': 1, 'EYE_WideL': 1, 'EYE_WideR': 1,
                   'VIS_OH': .8},
    'Sợ hãi': {'BRW_SadL': .8, 'BRW_SadR': .8, 'EYE_WideL': 1, 'EYE_WideR': 1,
               'VIS_AA': .5, 'MTH_FrownL': .5, 'MTH_FrownR': .5},
    'Kinh tởm': {'MTH_Sneer': 1, 'BRW_DownL': .7, 'BRW_DownR': .7,
                 'EYE_SquintL': .6, 'EYE_SquintR': .6},
    'Nghi ngờ': {'BRW_AngryL': .8, 'BRW_UpR': .9, 'EYE_SquintL': .6,
                 'MTH_FrownL': .4, 'MTH_SmileR': .3},
    'Nhắm mắt': {'EYE_BlinkL': 1, 'EYE_BlinkR': 1},
    'Huýt sáo': {'MTH_Pucker': 1, 'BRW_UpL': .3, 'BRW_UpR': .3,
                 'EYE_SquintL': .2, 'EYE_SquintR': .2},
    'Phồng má': {'CHK_PuffL': 1, 'CHK_PuffR': 1, 'MTH_Press': .6,
                 'BRW_DownL': .3, 'BRW_DownR': .3},
    'Cười thật': {'MTH_SmileL': 1, 'MTH_SmileR': 1, 'CHK_SquintL': 1,
                  'CHK_SquintR': 1, 'EYE_SquintL': .7, 'EYE_SquintR': .7},
    'Nhăn mặt': {'NOS_WrinkleL': 1, 'NOS_WrinkleR': 1, 'EYE_SquintL': .8,
                 'EYE_SquintR': .8, 'BRW_DownL': .6, 'BRW_DownR': .6,
                 'MTH_UpperUpL': .5, 'MTH_UpperUpR': .5},
    'Mím môi': {'MTH_RollUpper': 1, 'MTH_RollLower': 1, 'MTH_ChinUp': .5,
                'BRW_AngryL': .3, 'BRW_AngryR': .3},
    # Hai mẫu dưới chỉ có ở face rig Rig Tẩm Hành (có xương hàm, lưỡi riêng).
    'Lè lưỡi': {'JAW_Open': .45, 'TNG_Out': 1, 'EYE_SquintL': .5,
                'EYE_SquintR': .5, 'BRW_UpL': .3, 'BRW_UpR': .3},
    'Há hốc': {'JAW_Open': 1, 'BRW_UpL': 1, 'BRW_UpR': 1, 'EYE_WideL': 1,
               'EYE_WideR': 1},
}


class FACESHAPES_OT_test_expr(Operator):
    bl_idname = "face_shapes.test_expr"
    bl_label = "Thử biểu cảm"
    bl_description = "Đặt sẵn một biểu cảm mẫu để xem bộ shape key kết hợp ra sao"
    bl_options = {'REGISTER', 'UNDO'}

    expr: StringProperty(default="Vui")

    PRESETS = EXPR_PRESETS

    def execute(self, context):
        arm, face = find_rig_and_mesh(context)
        if face is None or not face.data.shape_keys:
            self.report({'ERROR'}, "Chưa có shape key")
            return {'CANCELLED'}
        kbs = face.data.shape_keys.key_blocks
        for kb in kbs:
            if kb.name != 'Basis':
                kb.value = 0.0
        for n, v in self.PRESETS.get(self.expr, {}).items():
            if n in kbs:
                kbs[n].value = v
        context.view_layer.update()
        self.report({'INFO'}, "Biểu cảm: %s" % self.expr)
        return {'FINISHED'}


class FACESHAPES_OT_guide(Operator):
    bl_idname = "face_shapes.guide"
    bl_label = "Ghi tài liệu hướng dẫn"
    bl_options = {'REGISTER'}

    def execute(self, context):
        st = context.scene.face_shapes
        arm, face = find_rig_and_mesh(context)
        doc = GUIDE % {
            'face': face.name if face else '?',
            'anchor': st.anchor, 'jaw_max': st.jaw_max,
            'meet': st.meet, 'thr': st.eye_threshold,
            'shrink': st.eye_shrink, 'back': st.eye_back,
        }
        t = bpy.data.texts.get("FaceShapes_HuongDan") or \
            bpy.data.texts.new("FaceShapes_HuongDan")
        t.clear()
        t.write(doc)
        self.report({'INFO'}, "Đã ghi vào text block FaceShapes_HuongDan")
        return {'FINISHED'}


GUIDE = """BỘ SHAPE KEY BIỂU CẢM & HỘI THOẠI
==================================================
Mesh mặt: %(face)s

MỨC CƯỜNG ĐIỆU (slider ngay trên nút Dựng)
  100%% = biên độ hiệu chỉnh theo hình học khuôn mặt (tự nhiên)
  150%% = mặc định, rõ hơn hẳn mà vẫn sạch
  200%% = cường điệu mạnh, vẫn dùng được
  250%%+ = miệng bắt đầu nhúm khóe; mày đã kẹp trần nên không đổi thêm
  Ba trần an toàn tự động, kéo slider cao đến đâu cũng không vượt:
    - hạ hàm: kẹp ở góc làm lưới khóe miệng giãn quá 2.3x
    - nháy mắt: không vượt mức mí trên gặp mí dưới (nếu không sẽ lộn mí)
    - mày: không quá 1.9 lần khoảng cách mày <-> mí trên (nếu không hai đầu
      mày giao nhau trên sống mũi thành gờ nhọn)

HAI CÁCH DỰNG
  THEO VÙNG (chạy với mọi mesh, không cần rig)
    Cần các nhóm vertex khoanh vùng. Bấm "Đánh dấu vùng mặt": nếu mesh đã skin
    thì addon tự đổ trọng số từ vertex group sẵn có, không thì tạo nhóm rỗng để
    bạn tô bằng Weight Paint.
      FS_LipUpper, FS_LipLower              (bắt buộc)
      FS_LidUpper.L/R, FS_LidLower.L/R      (cho shape mắt)
      FS_LidUpper_2.L/R, ...                (mắt thứ hai cùng bên, tự tách ra)
      FS_Brow.L/R, FS_Nose, FS_Jaw          (tuỳ chọn)
      FS_Cheek.L/R                          (cho CHK_*, tự dò nếu bỏ trống)
      FS_TeethUpper, FS_TeethLower          (tự dò; xem mục RĂNG bên dưới)

RĂNG
  Hai nhóm răng không sinh shape key nào. Chúng tồn tại để GỠ răng ra khỏi vùng
  mềm: người rig hay skin răng vào chính bone môi, nên nhóm môi quét tự động hút
  trọn cả hai hàm, và mọi shape key miệng bẻ cong răng như bẻ môi. Đo trên mesh
  Male: 170/170 vertex hàm trên nằm trong FS_LipUpper.
  Sau khi gỡ:
    - hàm dưới quay CỨNG đúng góc bản lề hàm ở mọi shape há miệng (trọng số ép
      về 1.0, không làm mượt) -- răng đi theo hàm chứ không bị bẻ
    - hàm trên đứng yên hoàn toàn, vì nó gắn vào sọ
    - khe môi và bản lề hàm được đo lại trên môi SẠCH, không bị răng (nằm lùi
      vào trong) kéo lệch
  "Kiểm định bộ shape key" có hai dòng riêng cho việc này: `răng cứng` và
  `hàm trên`. Cả hai phải ĐẠT.
    Vì sao tách trên/dưới: ranh giới khe môi và khe mí KHÔNG suy ra được từ một
    khối. Bản đầu thử dò bằng hình học và sai hẳn -- cùng hình dạng mà mắt trái
    ra khe 0.1285, mắt phải ra 0.0320.
    TRỌNG SỐ chính là đường suy giảm: tô đậm thì di chuyển nhiều, nhạt thì ít.
    Shape key được nắn thẳng trên mesh gốc, không qua armature.

  THEO RIG (cần đúng bộ bone điều khiển họ rig này)
    Pose bone rồi nướng hiệu giữa hai trạng thái evaluated. Giải phẫu nhúc nhích
    tự nhiên hơn vì đi qua chính hệ ràng buộc của rig, nhưng phải hiệu chỉnh
    chống rách khóe miệng nên độ hạ hàm bị chặn trần.

  Tự chọn: có nhóm FS_* thì dùng vùng, không thì thử rig.

CÁCH DÙNG
  Properties > Object Data > Shape Keys, kéo slider 0..1.
  Miệng / mắt / mày độc lập hoàn toàn, cộng được tuỳ ý:
      biểu cảm  = (mày) + (mắt) + (miệng biểu cảm)
      hội thoại = giữ nguyên mày/mắt, chỉ hoán đổi VIS_* theo âm

NHÓM
  VIS_*  11 viseme cho lipsync. Im lặng = tắt hết, không có key riêng.
  MTH_*  cười / mếu / kéo ngang / lúm đồng tiền (tách trái phải), nhếch môi
         trên và hạ môi dưới riêng từng bên, chu môi, loe phễu, mím môi vào
         trong (trên/dưới riêng), nâng cằm, lệch miệng trái/phải.
  CHK_*  phồng má / hóp má / má nâng khi cười thật, tách trái phải.
         CHỈ có ở chế độ vùng -- rig không có bone má.
  NOS_*  nở cánh mũi, nhăn mũi, tách trái phải. Cũng chỉ có ở chế độ vùng.
  EYE_*  nhắm / nheo / mở to, tách trái phải.
  BRW_*  nhướn / hạ / nhíu giận / đầu mày nhướn buồn, tách trái phải.

  Cộng lại: 56 shape key ở chế độ vùng, 46 ở chế độ rig.

GIỮ SHAPE KEY LÀM TAY
  "Dựng bộ shape key" chỉ xoá đúng những key CỦA ADDON rồi dựng lại. Key bạn tự
  nắn được giữ nguyên, kể cả khi tên bắt đầu bằng MTH_ / EYE_ ...
  Nhận diện bằng cờ `srp_face` gắn lúc tạo, phòng khi bạn đổi tên key đi.
  Muốn dọn trắng thì bật "Xoá cả shape key làm tay" trong hộp thoại.

HẰNG SỐ ĐÃ HIỆU CHỈNH CHO RIG NÀY
  Bù khóe miệng   %(anchor).5f / độ hạ hàm
  Trần hạ hàm     %(jaw_max).0f độ
  Đường gặp mí    z = %(meet).4f
  Nhãn cầu        co %(shrink).2f, thụt %(back).4f, ngưỡng %(thr).2f

BA ĐIỀU CẦN BIẾT
1. Lông mày có thể được vẽ trên texture chứ không có hình khối. Khi đó BRW_*
   vẫn chạy đúng nhưng ở chế độ Solid không texture sẽ trông như không đổi gì.
   Bật texture rồi xem lại trước khi kết luận là hỏng.
2. Hướng nhìn của mắt KHÔNG làm bằng shape key. Nhãn cầu xoay bằng bone
   (EyeLook / Eye_Target) sẽ đúng hình cầu hơn shape key nội suy tuyến tính.
3. Trần hạ hàm tồn tại vì rig gán vertex khóe miệng gần như trọn vẹn vào bone
   môi dưới, nên khi hạ hàm khóe tụt xuống bằng giữa môi và toác ra. Addon bù
   lại bằng cách nâng bone khóe, nhưng quá một góc nhất định thì bù không cứu
   được. Muốn miệng há to hơn phải sửa skin weight khóe miệng trước.

XUẤT SANG ENGINE
  Driver là cơ chế riêng của Blender, KHÔNG xuất theo FBX/glTF.
  Cách gọn nhất: join mesh mặt + răng + nhãn cầu thành một mesh trước khi xuất,
  shape key trùng tên sẽ gộp làm một và chạy đúng.
  Nếu giữ tách rời thì phải animate cả hai bên trong engine. Lưu ý driver nhãn
  cầu KHÔNG tuyến tính, có ngưỡng %(thr).2f.
"""


# ============================================================ panel

VERSION = bl_info["version"]


def draw_main(L, context):
        st = context.scene.face_shapes
        L.prop(st, "mode", text="")
        L.prop(st, "face")
        if st.mode != 'REGION':
            L.prop(st, "rig")

        arm, face = find_rig_and_mesh(context)
        face = face or st.face
        box = L.box()
        if face is None:
            box.label(text="Chưa tìm thấy mesh mặt", icon='ERROR')
        else:
            n = len(face.data.shape_keys.key_blocks) - 1 if face.data.shape_keys else 0
            box.label(text=face.name, icon='MESH_DATA')
            box.label(text="Đang có %d shape key" % n, icon='SHAPEKEY_DATA')
            need = [nm for nm, _, req in REGIONS if req and not read_region(face, nm)]
            srp = facerig.has_face_rig(arm) and st.mode != 'REGION'
            if srp:
                box.label(text="Face rig Rig Tẩm Hành: %s" % arm.name, icon='CHECKMARK')
                if not deformed_by(face, arm):
                    box.label(text="Mesh chưa bind vào rig này", icon='ERROR')
            elif need:
                box.label(text="Thiếu vùng bắt buộc: " + ", ".join(need), icon='ERROR')
            # Danh sách vùng đã tô và số bone còn thiếu là số liệu để dò lỗi,
            # không phải thứ người dùng cần để biết bấm nút nào tiếp.
            if prefs.verbose():
                have = [nm[3:] for nm, _, _ in region_table(face)
                        if read_region(face, nm)]
                if have:
                    box.label(text="Vùng: " + ", ".join(have), icon='GROUP_VERTEX')
                # bang bone cua ho rig cu -- face rig Rig Tẩm Hành khong dung toi
                if arm is not None and st.mode != 'REGION' and not srp:
                    mb = missing_bones(arm)
                    box.label(text="Rig %s: %s" % (
                        arm.name, "đủ bone" if not mb else "thiếu %d bone" % len(mb)),
                        icon='CHECKMARK' if not mb else 'ERROR')

        L.separator()
        srp = facerig.has_face_rig(arm) and st.mode != 'REGION'
        if not srp:
            L.operator("face_shapes.make_regions", icon='GROUP_VERTEX')
        if st.mode != 'REGION' and not srp:
            L.operator("face_shapes.calibrate", icon='DRIVER')
            if st.calibrated and prefs.verbose():
                L.label(text="Bù khóe %.5f/độ · trần hàm %.0f°"
                             % (st.anchor, st.jaw_max))
        L.prop(st, "exaggerate", slider=True)
        # Thứ tự thao tác: chấm TRƯỚC khi dựng, kiểm định SAU khi dựng.
        if not srp:
            L.operator("face_shapes.audit", text="1 · Kiểm tra nhân vật mới",
                       icon='VIEWZOOM')
        r = L.row()
        r.scale_y = 1.4
        r.operator("face_shapes.build", text="2 · Dựng bộ shape key",
                   icon='SHAPEKEY_DATA')
        L.operator("face_shapes.qc", text="3 · Kiểm định bộ shape key",
                   icon='CHECKMARK')
        L.separator()
        L.operator("face_shapes.guide", icon='TEXT')
        L.operator("face_shapes.clear", icon='TRASH')


def region_target(context):
    """Mesh de to vung FS_: o chon rieng truoc, roi den mesh chon o buoc 1.

    Buoc 1 da hoi mesh nhan vat roi. Bat hoi lai lan nua chi tao co hoi tro vao
    hai mesh khac nhau — luc do `srp.bind` doc nhom FS_ tren mesh nay con nguoi
    dung vua to len mesh kia, va khong cho nao bao gi.
    """
    st = getattr(context.scene, "face_shapes", None)
    if st is not None and st.face is not None and st.face.type == 'MESH':
        return st.face
    settings = getattr(context.scene, "srp_generate", None)
    return settings.target_mesh if settings is not None else None


def draw_regions(L, context):
    """Buoc TO VUNG KHUON MAT — nam TRUOC bind skin.

    Nhom `FS_*` la dau vao cua CA HAI viec: trong so xuong ham/mat luc bind, va
    bo shape key o buoc cuoi. Truoc day no chi co trong buoc shape key, tuc
    buoc CUOI CUNG — nen lan bind dau tien xuong ham bat buoc phai an theo
    automatic weights (keo ca moi tren, ca rang), roi nguoi dung phai quay
    nguoc lai bam "To lai trong so ham & mat". Chinh panel cu cung phai in ra
    cau "bam 'Tao nhom vung FS_*' o muc 6 truoc" — tuc quy trinh tu no thua
    nhan la dang chay nguoc.

    Doi cho la du. `srp.bind` von da hoi `has_face_regions()` va tu to lai ba
    xuong mat theo vung, kem noi bien + lam muot Laplacian; cai thieu chi la co
    hoi de vung ton tai truoc luc bind.
    """
    st = context.scene.face_shapes
    settings = getattr(context.scene, "srp_generate", None)
    fallback = settings.target_mesh if settings is not None else None
    mesh = region_target(context)

    L.prop(st, "face", text="Mesh mặt")
    if st.face is None and fallback is not None:
        note = L.column(align=True)
        note.scale_y = 0.8
        note.label(text="Để trống → dùng %r của bước 1" % fallback.name,
                   icon='DOT')
    if mesh is None:
        L.label(text="Chưa chọn mesh nhân vật ở bước 1", icon='ERROR')
        return

    box = L.box()
    table = region_table(mesh)
    have = [name for name, _pat, _req in table if read_region(mesh, name)]
    missing = [name for name in REQUIRED if not read_region(mesh, name)]
    box.label(text="%s: %d/%d nhóm vùng" % (mesh.name, len(have), len(table)),
              icon='GROUP_VERTEX')
    # Nhan cau roi thi KHONG co nhom `FS_Eyeball` — noi ro ra, khong thi con
    # so "14/16" trong nhu con thieu hai nhom.
    apart = [obj.name for obj in
             (eyeball_object(context, side) for side in ('L', 'R'))
             if obj is not None]
    if apart:
        box.label(text="Nhãn cầu rời: " + ", ".join(apart) + " (không cần vùng)",
                  icon='MESH_UVSPHERE')
    if missing:
        box.label(text="Thiếu: " + ", ".join(n[3:] for n in missing),
                  icon='ERROR')
    else:
        box.label(text="Đủ để bind tô xương hàm & mắt", icon='CHECKMARK')

    L.operator("face_shapes.make_regions", icon='GROUP_VERTEX')


def draw_face_weights(L, context):
    """Nut TO LAI trong so ham & mat, ve trong buoc "Bind skin".

    Khong con nut "tao xuong mat" rieng: ba xuong do da nam trong ban ve cua bo
    sinh rig, `srp.generate` dung chung nhu dung tay chan. Cai con lai o day la
    TRONG SO — `srp.bind` tu lam roi, nut nay chi de chay lai khi sua nhom vung
    hay doi cho xuong, khoi phai bind lai ca than nguoi.
    """
    st = context.scene.face_shapes
    face = st.face if (st.face and st.face.type == 'MESH') else find_face_mesh(context)
    if face is None:
        return

    # Ve CA HAI o chon ngay canh nut. Truoc day chi co `st.face`, con rig thi
    # `deformed_by()` tu suy ra — nen file nhieu nhan vat la no chon nham rig
    # cua nhan vat khac, va neu collection cua rig do dang tat thi bam nut chi
    # nhan duoc mot cau bao loi ma khong co cach nao chi lai cho dung.
    column = L.column(align=True)
    column.prop(st, "face", text="Mesh mặt")
    column.prop_search(st, "rig", context.scene, "objects", text="Rig",
                       icon='ARMATURE_DATA')
    guess = st.rig if (st.rig and st.rig.type == 'ARMATURE')         else find_rig(context, face)
    if st.rig is None and guess is not None:
        note = L.column(align=True)
        note.scale_y = 0.8
        note.label(text="Để trống → tự chọn %r" % guess.name, icon='DOT')

    missing = [n for n in REQUIRED if not read_region(face, n)]
    hidden = outside_view_layer(context, face, guess)
    row = L.row()
    row.enabled = not missing and not hidden
    row.operator("face_shapes.add_bones", icon='GROUP_VERTEX')
    if hidden:
        warn = L.column(align=True)
        warn.scale_y = 0.8
        warn.alert = True
        for name, homes in hidden:
            warn.label(text="%s đang tắt (ở %s)" % (name, homes), icon='ERROR')

    # Chi hien khi nhan cau CON nam trong mesh mat. Tach roi thi nut nay khong
    # con viec gi de lam, va de day chi tao co hoi bam nham lan thu hai.
    if read_region(face, 'FS_Eyeball.L') or read_region(face, 'FS_Eyeball.R'):
        box = L.box()
        box.label(text="Nhãn cầu đang nằm trong mesh mặt", icon='INFO')
        box.operator("face_shapes.split_eyeballs", icon='MESH_UVSPHERE')
    if missing:
        L.label(text="Thiếu nhóm %s -- tạo ở bước 5" % ", ".join(n[3:] for n in missing),
                icon='INFO')


def draw_test(L, context):
    grid = L.grid_flow(columns=2, even_columns=True)
    for name in FACESHAPES_OT_test_expr.PRESETS:
        grid.operator("face_shapes.test_expr", text=name).expr = name


def draw_config(L, context):
        st = context.scene.face_shapes
        L.label(text="Tự đo khi bấm hiệu chỉnh, sửa tay được:")
        L.prop(st, "anchor")
        L.prop(st, "jaw_max")
        L.prop(st, "meet")
        L.separator()
        L.prop(st, "eye_shrink")
        L.prop(st, "eye_back")
        L.prop(st, "eye_threshold")
        L.separator()
        L.prop(st, "stretch_cap")
        L.prop(st, "smooth")
        L.prop(st, "soften")
        L.prop(st, "grow")
        L.prop(st, "do_teeth")
        L.prop(st, "do_eyes")


# Panel do `ui.py` dinh nghia — o day chi con operator va settings. Giu nguyen
# idname `face_shapes.*`: 120 KB code ben trong tham chieu chung, doi ten la
# rui ro thuan tuy ma khong duoc gi.
CLASSES = (
    FACESHAPES_Settings,
    FACESHAPES_OT_make_regions,
    FACESHAPES_OT_add_bones, FACESHAPES_OT_split_eyeballs,
    FACESHAPES_OT_calibrate,
    FACESHAPES_OT_build,
    FACESHAPES_OT_audit,
    FACESHAPES_OT_qc,
    FACESHAPES_OT_clear,
    FACESHAPES_OT_test_expr,
    FACESHAPES_OT_guide,
)


def register_extra():
    bpy.types.Scene.face_shapes = PointerProperty(type=FACESHAPES_Settings)


def unregister_extra():
    try:
        del bpy.types.Scene.face_shapes
    except AttributeError:
        pass
