# -*- coding: utf-8 -*-
"""Shape key khuôn mặt nướng từ BỘ XƯƠNG MẶT CỦA RIG TẨM HÀNH.

Khác đường "theo rig" cũ trong `face.py`: đường đó đòi bộ bone điều khiển của
một họ rig khác (`Jaw_Base`, `UpperLip_Ctrl.L`...), nên trên rig do chính addon
này sinh ra -- Kid_Rig, hay bất kỳ rig nào dựng từ mục 3 -- nó báo thiếu bone
rồi lặng lẽ rơi về chế độ vùng. Module này đọc đúng tên trong
`refrig.FACE_GROUPS`: Jaw, Lip_Upper/Lower, Eyelid_*, Eyebrow*, Nose, Tongue*.

Cách nướng giữ nguyên nguyên tắc của `face.bake()`: shape key = Basis + (mesh
evaluated lúc pose - mesh evaluated lúc nghỉ). Cái mới là cách POSE:

  * Xương mặt của Rig Tẩm Hành là xương deform FK trần, không constraint. Nên tư
    thế được TÍNH THẲNG ra matrix_basis (xem `apply_pose`), không phải đặt
    `pb.matrix` từng cái rồi chờ depsgraph -- cách đó đọc ma trận cha CŨ khi
    con được đặt ngay sau cha.
  * Mí quay quanh TÂM NHÃN CẦU chứ không tịnh tiến. Tịnh tiến thẳng xuống thì
    da mí đi theo dây cung, cắt vào nhãn cầu tròn; quay quanh tâm thì giữ
    nguyên khoảng cách tới tâm, da trượt trên mặt cầu.
  * Khoé miệng: môi dưới con của Jaw, môi trên con của Head. Há hàm là hai
    khoé tách nhau và rách. Bù bằng cách đưa CẢ HAI khoé về trung điểm của
    chúng (`SEAL`), khỏi phải hiệu chỉnh một hằng số "nâng khoé / độ".

Hai thứ còn lại được ĐO trên mesh, như đường cũ: đường gặp mí (ray cast lên
nhãn cầu) và trần hạ hàm (độ giãn cạnh quanh khoé miệng).
"""

import math

import bpy
from mathutils import Matrix, Vector

from . import prefs

# Xương bắt buộc để coi một rig là "có face rig Rig Tẩm Hành". Mí, mày, mũi, lưỡi
# là tuỳ chọn: thiếu nhóm nào thì chỉ thiếu shape key của nhóm đó.
REQUIRED = ('Jaw', 'Lip_Upper_Mid', 'Lip_Lower_Mid',
            'Lip_Upper.L', 'Lip_Upper.R', 'Lip_Lower.L', 'Lip_Lower.R')

LIP_RING = ('', '.001', '.002')       # khoé -> giữa, theo FACE_GROUPS
LID_UP = ('Eyelid_Upper', 'Eyelid_Upper.001')
LID_LO = ('Eyelid_Lower', 'Eyelid_Lower.001', 'Eyelid_Lower.002')
BROW = ('Eyebrow.003', 'Eyebrow.002', 'Eyebrow.001', 'Eyebrow')   # trong -> ngoài
TONGUE = ('Tongue', 'Tongue.001', 'Tongue.002', 'Tongue.003')

# Phần hai khoé miệng gặp nhau khi há. 1.0 = khoé trên và khoé dưới về đúng
# trung điểm; nhỏ hơn thì khoé dưới theo hàm nhiều hơn.
SEAL = 1.0
# Khoé mí trong/ngoài đi theo trung bình mí trên + mí dưới -- 0 thì mép khe mí
# bị kéo nhọn; 0.25 (bản cũ) thì nhắm mắt còn hở hai khoé, lòi nhãn cầu.
LID_CORNER = 1.0
# Vertex có từ ngần này phần trọng số thuộc xương mí trở lên thì đi trọn.
LID_FULL = 0.5
# Dải mép mí / mặt trong (phía khe mắt của góc xương mí) nén lại còn ngần này
# khi khép, thay vì trượt nguyên khối qua đường gặp (xem Lids.field.slide)
LID_TUCK = 0.3
# Rìa dưới của vùng mí dưới không xa hơn ngần này dưới mép xương mí dưới
LID_LO_SPAN = math.radians(50)
# Làm mượt mép mí dọc theo cạnh lưới (xem Lids.field)
LID_SMOOTH = 6
LID_SMOOTH_ALPHA = 0.5
# Mí khép ôm vào ngần này phần quãng từ bán kính cũ tới (bán kính nhãn cầu x
# HUG_GAP). 0 = giữ nguyên bán kính.
HUG = 0.7
HUG_GAP = 1.08
# Trần giãn cạnh quanh khoé miệng, cùng ngưỡng với đường cũ (face.STRETCH_MAX).
STRETCH_MAX = 2.3
# Trần trên cùng 24°: Kid không rách khoé tới tận 30° nhưng ở đó cằm đã dài ra
# thành mặt ngựa. Khoé không rách chưa có nghĩa là đẹp.
JAW_SCAN = (6, 8, 10, 12, 14, 16, 18, 20, 22, 24)


def side_name(base, side, suffix=""):
    """`Lip_Upper` + L + `.001` -> `Lip_Upper.L.001` (quy ước tên của Kid)."""
    return "%s.%s%s" % (base, side, suffix)


def lid_name(base, side):
    head, dot, tail = base.partition('.')
    return side_name(head, side, dot + tail if dot else "")


def has_face_rig(arm):
    return (arm is not None and arm.type == 'ARMATURE'
            and all(n in arm.pose.bones for n in REQUIRED))


def missing(arm):
    if arm is None or arm.type != 'ARMATURE':
        return list(REQUIRED)
    return [n for n in REQUIRED if n not in arm.pose.bones]


# ============================================================ khung toạ độ

class Frame:
    """Hệ trục của khuôn mặt trong không gian ARMATURE.

    Không giả định mặt nhìn về -Y: đọc hướng trước từ chính xương môi (giữa môi
    luôn nằm trước bản lề hàm), hướng lên từ xương mày/mí so với miệng, và
    phía trái từ dấu x của `Lip_Upper.L`.
    """

    def __init__(self, arm):
        B = arm.data.bones
        self.arm = arm
        self.rest = {b.name: b.matrix_local.copy() for b in B}
        h = {b.name: b.head_local.copy() for b in B}
        t = {b.name: b.tail_local.copy() for b in B}
        self.head, self.tail = h, t
        self.jaw = h['Jaw']
        mouth = (h['Lip_Upper_Mid'] + h['Lip_Lower_Mid']) * 0.5
        self.mouth = mouth
        corner = {s: (h[side_name('Lip_Upper', s)] + h[side_name('Lip_Lower', s)]) * 0.5
                  for s in 'LR'}
        self.corner = corner
        across = corner['L'] - corner['R']
        self.W = across.length                       # bề rộng miệng
        self.left = across.normalized()
        fwd = mouth - self.jaw
        fwd -= self.left * fwd.dot(self.left)
        # hướng lên: từ miệng tới trán; trán = mày hoặc mí hoặc mũi, có cái nào
        # dùng cái đó, không có thì lấy trục Z của armature
        top = [h[n] for n in ('Eyebrow.L.003', 'Eyebrow.R.003', 'Eyelid_Upper.L',
                              'Eyelid_Upper.R', 'Nose') if n in h]
        up = (sum(top, Vector()) / len(top) - mouth) if top else Vector((0, 0, 1))
        up -= self.left * up.dot(self.left)
        up -= fwd.normalized() * up.dot(fwd.normalized())
        self.up = up.normalized() if up.length > 1e-6 else Vector((0, 0, 1))
        self.fwd = self.left.cross(self.up).normalized()
        if self.fwd.dot(fwd) < 0:
            self.fwd = -self.fwd
        self.lip_gap = (h['Lip_Upper_Mid'] - h['Lip_Lower_Mid']).dot(self.up)

    def out(self, side):
        return self.left if side == 'L' else -self.left

    def has(self, name):
        return name in self.rest


# ============================================================ tư thế

class Pose:
    """Tích luỹ biến đổi cho từng xương, áp một lần.

    Mỗi bút toán là biến đổi trong không gian ARMATURE, nhân TRÁI vào tư thế mà
    xương đã thừa kế từ cha. Nên `Lip_Lower.L` vừa theo hàm (thừa kế) vừa nhận
    thêm phần bù khoé (bút toán riêng) mà không phải tính tay.
    """

    def __init__(self, frame):
        self.F = frame
        self.ops = {}

    def _add(self, name, op):
        if self.F.has(name):
            self.ops.setdefault(name, []).append(op)

    def move(self, name, vec):
        if vec.length > 0.0:
            self._add(name, ('T', vec.copy()))

    def turn(self, name, axis, angle, centre=None):
        """Quay quanh `centre` (None = quanh chính đầu xương lúc đó)."""
        if angle:
            self._add(name, ('R', None if centre is None else centre.copy(),
                             axis.normalized(), angle))

    def merge(self, other):
        for n, ops in other.ops.items():
            self.ops.setdefault(n, []).extend(ops)
        return self

    def final(self, inherited, name):
        m = inherited
        for op in self.ops.get(name, ()):
            if op[0] == 'T':
                m = Matrix.Translation(op[1]) @ m
            else:
                _k, c, axis, ang = op
                c = m.translation.copy() if c is None else c
                m = (Matrix.Translation(c) @ Matrix.Rotation(ang, 4, axis)
                     @ Matrix.Translation(-c) @ m)
        return m


def apply_pose(arm, pose):
    """Đặt matrix_basis cho đúng các xương có bút toán, cha trước con sau.

    pose_con = pose_cha @ rest_cha^-1 @ rest_con @ basis  (xương FK không
    constraint, thừa kế đủ xoay và scale) -> basis = thừa_kế^-1 @ đích.
    """
    F = pose.F
    bones = arm.data.bones
    cache = {}            # tên -> (thừa kế, đích)

    def solve(name):
        if name not in cache:
            b = bones[name]
            rest = F.rest[name]
            inh = (solve(b.parent.name)[1] @ F.rest[b.parent.name].inverted() @ rest
                   if b.parent else rest)
            cache[name] = (inh, pose.final(inh, name))
        return cache[name]

    for name in pose.ops:
        inh, fin = solve(name)
        arm.pose.bones[name].matrix_basis = inh.inverted() @ fin
    bpy.context.view_layer.update()


def reset(arm):
    for pb in arm.pose.bones:
        pb.matrix_basis = Matrix()
    bpy.context.view_layer.update()


# ============================================================ công thức

def jaw_open(F, P, deg, seal=SEAL):
    """Há hàm `deg` độ, kèm bù cho hai khoé gặp nhau."""
    if not deg:
        return P
    ang = math.radians(deg)
    # chiều quay: đuôi hàm (cằm) phải đi XUỐNG
    R = Matrix.Rotation(ang, 4, F.left)
    chin = F.tail['Jaw'] - F.jaw
    if (R @ chin).dot(F.up) > chin.dot(F.up):
        ang = -ang
        R = Matrix.Rotation(ang, 4, F.left)
    P.turn('Jaw', F.left, ang, F.jaw)
    for s in 'LR':
        for suf, k_lo, k_up in (('', .5, .5), ('.001', .15, .10)):
            lo, up = side_name('Lip_Lower', s, suf), side_name('Lip_Upper', s, suf)
            if lo not in F.head:
                continue
            c = F.head[lo]
            d = (F.jaw + R.to_3x3() @ (c - F.jaw)) - c      # hàm kéo khoé đi bao nhiêu
            P.move(lo, -d * k_lo * seal)
            P.move(up, d * k_up * seal)
    return P


def lips(F, P, cen=0.0, mid=0.0, up_cen=0.0, up_mid=0.0,
         cor_x=0.0, cor_y=0.0, cor_z=0.0, ucor_z=None, side=None):
    """Cùng ngữ nghĩa với `face.mouth_ops`, theo tỉ lệ bề rộng miệng.

    cen/mid: hạ giữa / cạnh môi dưới; up_cen/up_mid: nâng môi trên;
    cor_x: khoé banh ra ngoài; cor_y: khoé lùi vào trong; cor_z: khoé lên.
    """
    W, up, back = F.W, F.up, -F.fwd
    ucor = cor_z if ucor_z is None else ucor_z
    sides = 'LR' if side is None else side
    half = 1.0 if side is None else 0.5     # xương giữa là xương CHUNG hai bên
    P.move('Lip_Lower_Mid', -up * cen * W * half)
    P.move('Lip_Upper_Mid', up * up_cen * W * half)
    for s in sides:
        o = F.out(s)
        for suf, kx, lo_z, up_z in (('', 1.0, cor_z, ucor),
                                    ('.001', .5, -mid, up_mid),
                                    ('.002', .25, -(mid + cen) * .5, (up_mid + up_cen) * .5)):
            sh = (o * cor_x * kx + back * cor_y * kx) * W
            P.move(side_name('Lip_Lower', s, suf), sh + up * lo_z * W)
            P.move(side_name('Lip_Upper', s, suf), sh + up * up_z * W)
    return P


def lips_side(F, P, s, cor_z=0.0, cor_x=0.0, cor_y=0.0, mid=0.0):
    """Một bên khoé: cười, mếu, banh, lúm."""
    W, up, back, o = F.W, F.up, -F.fwd, F.out(s)
    for suf, k, lo_z, up_z in (('', 1.0, cor_z, cor_z),
                               ('.001', .45, cor_z * .4 - mid, cor_z * .5),
                               ('.002', .18, cor_z * .12, cor_z * .18)):
        sh = (o * cor_x + back * cor_y) * k * W
        P.move(side_name('Lip_Lower', s, suf), sh + up * lo_z * W)
        P.move(side_name('Lip_Upper', s, suf), sh + up * up_z * W)
    return P


def lip_rows(F, P, side=None, up=0.0, lo=0.0, back=0.0):
    """Nhấc / hạ riêng một vành môi, kèm thụt vào trong (mím, cong môi)."""
    W, U, B = F.W, F.up, -F.fwd
    half = 1.0 if side is None else 0.5
    for row, amt in (('Lip_Upper', up), ('Lip_Lower', lo)):
        if not amt and not back:
            continue
        P.move(row + '_Mid', (U * amt + B * back) * half * W)
        for s in ('LR' if side is None else side):
            for suf, k in (('.002', .9), ('.001', .8), ('', .3)):
                P.move(side_name(row, s, suf), (U * amt + B * back) * k * W)
    return P


def lips_forward(F, P, amt, cen=1.0, cor=.45):
    """Đẩy cả vành môi ra trước, giữa đi xa nhất -> miệng chữ O."""
    v = F.fwd * amt * F.W
    for row in ('Lip_Upper', 'Lip_Lower'):
        P.move(row + '_Mid', v * cen)
        for s in 'LR':
            for suf, k in (('.002', .85), ('.001', .70), ('', cor)):
                P.move(side_name(row, s, suf), v * k)
    return P


def lips_shift(F, P, amt):
    v = F.left * amt * F.W
    for row in ('Lip_Upper', 'Lip_Lower'):
        P.move(row + '_Mid', v)
        for s in 'LR':
            for suf in LIP_RING:
                P.move(side_name(row, s, suf), v)
    return P


# ------------------------------------------------------------- mí

def eye_centre(F, s):
    n = 'Eye.%s' % s
    return F.head[n].copy() if n in F.head else None


def _angle(F, centre, p):
    """Góc của điểm p quanh tâm mắt, đo trong mặt phẳng dọc (trục = left)."""
    v = p - centre
    v -= F.left * v.dot(F.left)
    return math.atan2(v.dot(F.up), v.dot(F.fwd))


def lid_angles(F, s):
    """(góc các mí trên, góc các mí dưới, tâm) hoặc None nếu thiếu."""
    c = eye_centre(F, s)
    ups = [lid_name(n, s) for n in LID_UP if lid_name(n, s) in F.head]
    los = [lid_name(n, s) for n in LID_LO if lid_name(n, s) in F.head]
    if c is None or not ups or not los:
        return None
    return ({n: _angle(F, c, F.head[n]) for n in ups},
            {n: _angle(F, c, F.head[n]) for n in los}, c)


def _lid_axis(F):
    """Trục quay sao cho góc dương (`_angle`) là đi LÊN."""
    probe = F.fwd.copy()
    R = Matrix.Rotation(0.1, 3, F.left)
    return F.left if (R @ probe).dot(F.up) > 0 else -F.left


class Lids:
    """Công thức mí: KHÔNG nướng qua pose xương mà quay từng vertex.

    Mắt hoạt hình mở to: trên Kid mí trên phải quay ~85° mới chạm mí dưới.
    Skin tuyến tính với góc lớn như thế đưa vertex trọng số lưng chừng đi theo
    DÂY CUNG -- w=0.5 rơi vào giữa dây, tức là chui vào trong nhãn cầu. Đo trên
    Kid: da mí bẹt thành tấm phẳng, rách ở mép, lông mày bị xé đôi.

    Ở đây mỗi vertex QUAY quanh tâm nhãn cầu, và góc quay đi theo góc của
    chính vertex đó (ánh xạ góc), không theo trọng số thuần:

        mép mí (góc của xương mí) -> đường gặp mí     : đi trọn
        rìa vùng mí (`extent`)    -> đứng yên          : da nếp mí, mày
        ở giữa                    -> nén tuyến tính theo góc

    Quay thì giữ bán kính nên da trượt trên mặt cầu thay vì cắt qua nó. Bản
    đầu chỉ lấy trung bình góc theo trọng số: trọng số mí của Kid lan lên gần
    tới mày, quay 85° là kéo luôn nếp mí và cả mesh lông mày xuống mắt. Trọng
    số của rig vẫn quyết định vertex nào thuộc mí và thuộc bao nhiêu -- shape
    key vẫn "từ face rig", chỉ là không để LBS nội suy góc lớn.
    """

    def __init__(self, s, meet, k_up, k_lo, extent=None, hug=None):
        self.s, self.meet, self.k_up, self.k_lo = s, meet, k_up, k_lo
        self.extent = extent        # (góc rìa trên, góc rìa dưới), xem lid_extent
        self.hug = hug              # bán kính mí khép ôm vào (armature), None = tắt

    def field(self, F, arm, obj, rest_co):
        """Độ dời từng vertex (không gian object của `obj`), hoặc None."""
        A = lid_angles(F, self.s)
        if A is None:
            return None
        ups, los, c = A
        groups = lid_groups(arm, obj, self.s)
        if groups is None:
            return None
        gi, kind = groups
        a_up = sum(ups.values()) / len(ups)
        a_lo = sum(los.values()) / len(los)
        T = a_lo + (a_up - a_lo) * self.meet
        top, bot = self.extent or (a_up + math.radians(40), a_lo - math.radians(40))
        bone_a = dict(ups, **los)
        full = abs(T - a_up)          # quãng mí trên đi khi khép kín
        to_arm = arm.matrix_world.inverted() @ obj.matrix_world
        to_obj = to_arm.inverted().to_3x3()
        axis = _lid_axis(F)

        def slide(phi, margin, k, edge, sign):
            """Góc dời của một vertex thuộc mí có mép ở `margin`.
            sign=+1 mí trên (rìa ở phía trên), -1 mí dưới."""
            goal = margin + (T - margin) * k
            if (phi - margin) * sign <= 0.0:          # mép mí và mặt trong
                # Gập vào sát đường gặp chứ không trượt nguyên khối: quay cùng
                # một góc thì dải mép mí phía dưới góc xương đi QUÁ đường gặp
                # 25-30° (Kid: v1805 tới -34°, key Kid làm đẹp dừng ở -8°), mí
                # trên chồng lên mí dưới -- hai mặt lưới cắt nhau thành răng cưa.
                return goal + (phi - margin) * LID_TUCK - phi
            if (edge - phi) * sign <= 0.0:            # ngoài vùng mí
                return 0.0
            span = edge - margin
            if abs(span) < 1e-4:
                return 0.0
            return (edge - (edge - phi) * (edge - goal) / span) - phi

        out = [Vector()] * len(rest_co)
        rows = {}
        for v in obj.data.vertices:
            tot = wu = wl = wc = au = al = 0.0
            for e in v.groups:
                n = gi.get(e.group)
                if n is None:
                    continue
                tot += e.weight
                k = kind.get(n)
                if k == 'U':
                    wu += e.weight
                    au += e.weight * bone_a[n]
                elif k == 'L':
                    wl += e.weight
                    al += e.weight * bone_a[n]
                elif k == 'C':
                    wc += e.weight
            if tot <= 0.0 or (wu + wl + wc) <= 0.0:
                continue
            p = to_arm @ rest_co[v.index]
            lid = wu + wl + wc
            rows[v.index] = [wu, wl, wc, tot, au / wu if wu else None,
                             al / wl if wl else None, p, _angle(F, c, p),
                             min(1.0, lid / tot / LID_FULL)]

        # Làm mượt MÉP MÍ (góc xương mí trung bình theo weight) dọc theo cạnh
        # lưới, chỉ giữa các vertex cùng có weight mí đó. Mép lấy theo weight
        # thì hai vertex kề nhau trên cùng đường mép (weight tô tay, mỗi cái một
        # tỉ lệ Upper/.001) có hai "mép" khác nhau và đi tới hai góc khác nhau
        # -- đo trên Adult: mép mí trên khép xong nằm rải từ -19° tới +12°, nhắm
        # mắt ra mép mí răng cưa. Làm mượt góc QUAY thay vì mép thì đường mí
        # trơn nhưng mép bị vùng da phía trên (quay ít) kéo lại: nhắm còn hở.
        # Độ thuộc-về-mí (cột 8) cũng làm mượt: vertex lẫn weight lông mày có
        # độ thuộc thấp hơn hàng xóm, quay ít hơn -- mí khép có nếp chữ W (Adult).
        if LID_SMOOTH and rows:
            adj = {}
            for e in obj.data.edges:
                a_, b_ = e.vertices
                if a_ in rows and b_ in rows:
                    adj.setdefault(a_, []).append(b_)
                    adj.setdefault(b_, []).append(a_)
            for k in (4, 5, 8):
                for _p in range(LID_SMOOTH):
                    new = {}
                    for i, r in rows.items():
                        if r[k] is None:
                            continue
                        nb = [rows[j][k] for j in adj.get(i, ()) if rows[j][k] is not None]
                        if nb:
                            new[i] = r[k] + (sum(nb) / len(nb) - r[k]) * LID_SMOOTH_ALPHA
                    for i, m in new.items():
                        rows[i][k] = m

        for i, (wu, wl, wc, tot, mu, ml, p, phi, sat) in rows.items():
            ang = 0.0
            if wu > 0.0:
                ang += wu * slide(phi, mu, self.k_up, top, 1.0)
            if wl > 0.0:
                ang += wl * slide(phi, ml, self.k_lo, bot, -1.0)
            if wc > 0.0:
                ang += wc * LID_CORNER * .5 * (
                    slide(phi, a_up, self.k_up, top, 1.0)
                    + slide(phi, a_lo, self.k_lo, bot, -1.0))
            # Chia cho phần trọng số MÍ chứ không cho tổng, rồi mới nhân độ
            # thuộc-về-mí đã bão hoà. Quay quanh trục ngang thì gần khoé (sát
            # trục) đã tự đi ít; để trọng số tắt dần theo chiều ngang nhân thêm
            # lần nữa là ra hai bức tường dựng đứng ở hai bên mí khép.
            ang = ang / (wu + wl + wc) * sat
            if abs(ang) < 1e-7:
                continue
            r = p - c
            q = Matrix.Rotation(ang, 3, axis) @ r
            if self.hug and q.length > self.hug and full:
                # Ôm sát nhãn cầu theo đúng phần đã khép: mắt hoạt hình hay
                # nằm lùi trong hốc, giữ nguyên bán kính là mí khép thành một
                # tấm phẳng nổi trước mặt.
                f = min(1.0, abs(ang) / full)
                q = q.normalized() * (q.length + (self.hug - q.length) * f * HUG)
            out[i] = to_obj @ (c + q - p)
        return out


def eye_hug(F, arm, eyes, s):
    """Bán kính mí khép ôm vào (không gian armature): bán kính nhãn cầu rời x
    HUG_GAP. Không có nhãn cầu rời thì None -- giữ nguyên bán kính."""
    from . import face
    c = eye_centre(F, s)
    eye = next((e for e in eyes if face.eye_side(e) == s), None)
    if c is None or eye is None or not HUG:
        return None
    to_arm = arm.matrix_world.inverted() @ eye.matrix_world
    r = max(((to_arm @ v.co) - c).length for v in eye.data.vertices)
    return r * HUG_GAP


def lid_groups(arm, obj, s):
    """({chỉ số group: tên xương deform}, {tên: 'U'|'L'|'C'}) hoặc None."""
    deform = {b.name for b in arm.data.bones if b.use_deform}
    gi = {g.index: g.name for g in obj.vertex_groups if g.name in deform}
    kind = {lid_name(n, s): 'U' for n in LID_UP}
    kind.update({lid_name(n, s): 'L' for n in LID_LO})
    kind.update({side_name(n, s): 'C' for n in ('Eyelid_Inner', 'Eyelid_Outer')})
    if not any(n in kind for n in gi.values()):
        return None
    return gi, kind


def lid_extent(F, arm, mesh, rest_co, s, q=.95):
    """Góc rìa trên / rìa dưới của vùng da thuộc mí, ĐO từ trọng số skin.

    Rìa = phân vị q của góc các vertex có trọng số mí đáng kể, phía trên mép
    mí trên (và dưới mép mí dưới). Vertex ở rìa đứng yên, nên da mí nối liền
    với da trán / gò má không gãy.
    """
    A = lid_angles(F, s)
    groups = lid_groups(arm, mesh, s)
    if A is None or groups is None:
        return None
    ups, los, c = A
    gi, kind = groups
    a_up = max(ups.values())
    a_lo = min(los.values())
    to_arm = arm.matrix_world.inverted() @ mesh.matrix_world
    above, below = [], []
    for v in mesh.data.vertices:
        tot = wu = wl = 0.0
        for e in v.groups:
            n = gi.get(e.group)
            if n is None:
                continue
            tot += e.weight
            wu += e.weight if kind.get(n) == 'U' else 0.0
            wl += e.weight if kind.get(n) == 'L' else 0.0
        if tot <= 0.0:
            continue
        phi = _angle(F, c, to_arm @ rest_co[v.index])
        if wu / tot > .05 and a_up < phi < math.pi * .75:
            above.append(phi)
        if wl / tot > .05 and -math.pi * .75 < phi < a_lo:
            below.append(phi)
    pad = math.radians(4)
    top = sorted(above)[int(len(above) * q)] if above else a_up + math.radians(35)
    bot = sorted(below)[int(len(below) * (1 - q))] if below else a_lo - math.radians(35)
    # Mày là chốt chặn cứng: trên Kid trọng số mí lan QUA cả mày, mà mày chỉ
    # nằm trên mép mí có 9°. Lấy rìa theo trọng số là mày bị kéo xuống mắt.
    brow = [_angle(F, c, F.head[n]) for n in
            (side_name('Eyebrow', s, b[len('Eyebrow'):]) for b in BROW) if n in F.head]
    brow = [a for a in brow if a > a_up]
    if brow:
        top = min(top, min(brow) - pad)
    # Mí dưới cũng có chốt: weight mí dưới Kid lan tới -131° (phủ gò má), mí
    # dưới nhích lên là cả má phồng theo.
    bot = max(bot, a_lo - LID_LO_SPAN)
    return max(top, a_up + pad), min(bot, a_lo - pad)


# ------------------------------------------------------------- mày

def brow_span(F, s):
    names = [side_name('Eyebrow', s, n[len('Eyebrow'):]) for n in BROW]
    pts = [F.head[n] for n in names if n in F.head]
    return (pts[-1] - pts[0]).length if len(pts) > 1 else F.W * .5


def brow_gap(F, s):
    """Khoảng cách (theo up) từ tâm mày xuống tâm mí trên: trần cho biên độ mày."""
    br = [F.head[side_name('Eyebrow', s, n[len('Eyebrow'):])] for n in BROW
          if side_name('Eyebrow', s, n[len('Eyebrow'):]) in F.head]
    li = [F.head[lid_name(n, s)] for n in LID_UP if lid_name(n, s) in F.head]
    if not br or not li:
        return 0.0
    return abs((sum(br, Vector()) / len(br) - sum(li, Vector()) / len(li)).dot(F.up))


def brows(F, P, s, profile, squeeze=0.0, cap=0.0):
    """profile: 4 giá trị TRONG -> NGOÀI, theo tỉ lệ sải mày. squeeze: đầu mày
    dồn vào giữa (nhíu)."""
    S = brow_span(F, s)
    mx = max(abs(v) for v in profile) * S
    f = cap / mx if cap > 0 and mx > cap else 1.0
    for n, v in zip(BROW, profile):
        name = side_name('Eyebrow', s, n[len('Eyebrow'):])
        P.move(name, F.up * v * S * f)
    if squeeze:
        name = side_name('Eyebrow', s, '.003')
        P.move(name, -F.out(s) * squeeze * S * f)
    return P


# ------------------------------------------------------------- lưỡi

def tongue_len(F):
    pts = [F.head[n] for n in TONGUE if n in F.head]
    if 'Tongue.003' in F.tail:
        pts.append(F.tail['Tongue.003'])
    return sum((pts[i + 1] - pts[i]).length for i in range(len(pts) - 1)) if len(pts) > 1 else 0.0


def tongue_bend(F, P, axis, deg, root=False):
    """Uốn từng đốt quanh chính đầu đốt. Đốt gốc chỉ uốn khi root=True."""
    for n in TONGUE[0 if root else 1:]:
        P.turn(n, axis, math.radians(deg))
    return P


def tongue_axis_up(F):
    """Trục quay làm chóp lưỡi đi LÊN."""
    tip = (F.tail.get('Tongue.003', F.mouth) - F.head.get('Tongue', F.jaw))
    R = Matrix.Rotation(0.1, 3, F.left)
    return F.left if (R @ tip).dot(F.up) > tip.dot(F.up) else -F.left


def tongue_axis_left(F):
    tip = (F.tail.get('Tongue.003', F.mouth) - F.head.get('Tongue', F.jaw))
    R = Matrix.Rotation(0.1, 3, F.up)
    return F.up if (R @ tip).dot(F.left) > tip.dot(F.left) else -F.up


# ------------------------------------------------------------- bộ đầy đủ

def recipes(F, meet=0.35, jaw_max=20.0, ex=1.0, extents=None, hugs=None):
    """Tên shape key -> Pose. Tên trùng bộ của `face.py` để bảng biểu cảm mẫu,
    kiểm định và driver dùng chung được."""

    def J(x):
        return min(x * ex, jaw_max)

    def mouth(jaw=0.0, **kw):
        P = Pose(F)
        jaw_open(F, P, J(jaw) if jaw else 0.0)
        return lips(F, P, **{k: v * ex for k, v in kw.items()})

    R = {}
    # --- viseme
    R['VIS_AA'] = mouth(jaw=14, cen=.10, mid=.08, up_cen=.031, up_mid=.020)
    R['VIS_EE'] = mouth(jaw=4, cen=.03, mid=.03, up_cen=.020, up_mid=.020,
                        cor_x=.092, cor_z=.020)
    R['VIS_IH'] = mouth(jaw=6, cen=.05, mid=.04, up_cen=.010, up_mid=.010, cor_x=.051)
    R['VIS_OH'] = mouth(jaw=11, cen=.07, mid=.05, up_cen=.020, cor_x=-.092, cor_y=-.071)
    R['VIS_OU'] = mouth(jaw=4, cen=.03, mid=.02, up_cen=.010, cor_x=-.143, cor_y=-.122)
    R['VIS_MBP'] = mouth(cen=-.010, mid=-.010, up_cen=-.010, up_mid=-.010, cor_x=.010)
    R['VIS_FV'] = mouth(jaw=3, cen=-.031, mid=-.020, up_cen=.010, up_mid=.010,
                        cor_x=.020, cor_y=.020)
    R['VIS_TH'] = mouth(jaw=7, cen=.05, mid=.04, up_cen=.020, up_mid=.010)
    R['VIS_L'] = mouth(jaw=9, cen=.06, mid=.05, up_cen=.020, up_mid=.010)
    R['VIS_SS'] = mouth(jaw=2, cen=.02, mid=.02, up_cen=.010, up_mid=.010,
                        cor_x=.041, cor_z=.010)
    R['VIS_RR'] = mouth(jaw=5, cen=.04, mid=.03, up_cen=.010, cor_x=-.071, cor_y=-.051)
    if 'Tongue.001' in F.head:
        # TH và L thấy được lưỡi: chóp lưỡi chạm răng trên / vòm miệng
        tongue_bend(F, R['VIS_TH'], tongue_axis_up(F), 10 * ex)
        R['VIS_TH'].move('Tongue', F.fwd * tongue_len(F) * .12 * ex)
        tongue_bend(F, R['VIS_L'], tongue_axis_up(F), 18 * ex)

    # --- hàm
    R['JAW_Open'] = jaw_open(F, Pose(F), jaw_max)
    R['JAW_Forward'] = Pose(F)
    R['JAW_Forward'].move('Jaw', F.fwd * .05 * ex * F.W)
    for s, name in (('L', 'JAW_Left'), ('R', 'JAW_Right')):
        P = Pose(F)
        P.move('Jaw', F.out(s) * .06 * ex * F.W)
        R[name] = P

    # --- miệng biểu cảm
    for s in 'LR':
        R['MTH_Smile' + s] = lips_side(F, Pose(F), s, cor_z=.112 * ex,
                                       cor_x=.071 * ex, cor_y=.031 * ex)
        R['MTH_Frown' + s] = lips_side(F, Pose(F), s, cor_z=-.092 * ex,
                                       cor_x=.020 * ex, cor_y=.031 * ex)
        R['MTH_Stretch' + s] = lips_side(F, Pose(F), s, cor_x=.133 * ex,
                                         cor_y=.020 * ex)
        R['MTH_Dimple' + s] = lips_side(F, Pose(F), s, cor_x=.041 * ex,
                                        cor_z=.031 * ex, cor_y=.071 * ex)
        R['MTH_UpperUp' + s] = lip_rows(F, Pose(F), s, up=.071 * ex)
        R['MTH_LowerDown' + s] = lip_rows(F, Pose(F), s, lo=-.071 * ex)
    R['MTH_Sneer'] = mouth(up_cen=.061, up_mid=.061, cor_z=.031, ucor_z=.082)
    R['MTH_Press'] = mouth(cen=-.031, mid=-.031, up_cen=-.031, up_mid=-.031, cor_x=.031)
    R['MTH_Pucker'] = mouth(cen=.020, up_cen=.010, cor_x=-.184, cor_y=-.092)
    lips_forward(F, R['MTH_Pucker'], .102 * ex)
    R['MTH_Funnel'] = mouth(jaw=6, cen=.05, mid=.03, up_cen=.031, cor_x=-.133, cor_y=-.061)
    lips_forward(F, R['MTH_Funnel'], .071 * ex, cen=.8)
    R['MTH_RollUpper'] = lip_rows(F, Pose(F), up=-.041 * ex, back=.033 * ex)
    R['MTH_RollLower'] = lip_rows(F, Pose(F), lo=.041 * ex, back=.033 * ex)
    R['MTH_ChinUp'] = lip_rows(F, Pose(F), lo=.061 * ex)
    R['MTH_Left'] = lips_shift(F, Pose(F), .071 * ex)
    R['MTH_Right'] = lips_shift(F, Pose(F), -.071 * ex)

    # --- mũi (một xương giữa)
    if 'Nose' in F.head:
        P = Pose(F)
        P.move('Nose', (F.up * .035 - F.fwd * .012) * ex * F.W)
        R['NOS_Wrinkle'] = P
        R['MTH_Sneer'].move('Nose', F.up * .015 * ex * F.W)

    # --- lưỡi
    if all(n in F.head for n in TONGUE):
        L = tongue_len(F)
        P = Pose(F)
        P.move('Tongue', F.fwd * L * .45 * ex)
        tongue_bend(F, P, tongue_axis_up(F), -4 * ex)
        R['TNG_Out'] = P
        R['TNG_Up'] = tongue_bend(F, Pose(F), tongue_axis_up(F), 22 * ex)
        R['TNG_Down'] = tongue_bend(F, Pose(F), tongue_axis_up(F), -16 * ex)
        R['TNG_Left'] = tongue_bend(F, Pose(F), tongue_axis_left(F), 12 * ex, root=True)
        R['TNG_Right'] = tongue_bend(F, Pose(F), tongue_axis_left(F), -12 * ex, root=True)

    # --- mắt: k=1 là khép kín, không cho cường điệu vượt qua
    for s in 'LR':
        if lid_angles(F, s) is None:
            continue
        ext, hug = (extents or {}).get(s), (hugs or {}).get(s)
        R['EYE_Blink' + s] = Lids(s, meet, 1.0, 1.0, ext, hug)
        k = min(.45 * ex, 1.0)
        R['EYE_Squint' + s] = Lids(s, meet, k * .6, min(k * 1.2, 1.0), ext, hug)
        R['EYE_Wide' + s] = Lids(s, meet, -.12 * ex, -.08 * ex, ext, hug)

    # --- mày, 4 xương TRONG -> NGOÀI
    for s in 'LR':
        if side_name('Eyebrow', s) not in F.head:
            continue
        cap = brow_gap(F, s) * 1.9
        R['BRW_Up' + s] = brows(F, Pose(F), s, [v * ex for v in (.147, .140, .115, .074)], cap=cap)
        R['BRW_Down' + s] = brows(F, Pose(F), s, [v * ex for v in (-.105, -.098, -.075, -.042)],
                                  cap=cap * .5)
        R['BRW_Angry' + s] = brows(F, Pose(F), s, [v * ex for v in (-.147, -.090, -.010, .042)],
                                   squeeze=.06 * ex, cap=cap * .6)
        R['BRW_Sad' + s] = brows(F, Pose(F), s, [v * ex for v in (.147, .090, -.010, -.074)],
                                 cap=cap)
    return R


def all_names():
    """Mọi tên module này có thể sinh -- cho `face.OWN_NAMES`."""
    n = ['JAW_Open', 'JAW_Forward', 'JAW_Left', 'JAW_Right', 'NOS_Wrinkle',
         'TNG_Out', 'TNG_Up', 'TNG_Down', 'TNG_Left', 'TNG_Right']
    return n


# ============================================================ đo trên mesh

def eval_co(obj):
    dg = bpy.context.evaluated_depsgraph_get()
    return [v.co.copy() for v in obj.evaluated_get(dg).data.vertices]


def corner_edges(F, arm, mesh, rest_co):
    """Cạnh quanh khoé miệng (không gian object của mesh) kèm chiều dài nghỉ."""
    to_obj = mesh.matrix_world.inverted() @ arm.matrix_world
    edges, ln = [], {}
    for s in 'LR':
        c = to_obj @ F.corner[s]
        r = F.W * .25 * (to_obj.to_scale()[0] or 1.0)
        near = {i for i, p in enumerate(rest_co) if (p - c).length < r}
        for e in mesh.data.edges:
            a, b = e.vertices
            if a in near or b in near:
                ln[(a, b)] = (rest_co[a] - rest_co[b]).length
    if not ln:
        return [], {}
    med = sorted(ln.values())[len(ln) // 2]
    edges = [e for e, l in ln.items() if l >= med * .25]
    return edges, ln


def stretch(mesh, edges, ln):
    co = eval_co(mesh)
    return max((co[a] - co[b]).length / ln[(a, b)] for a, b in edges) if edges else 1.0


def calibrate_jaw(F, arm, mesh, rest_co):
    """Góc há lớn nhất mà lưới khoé chưa giãn quá STRETCH_MAX."""
    edges, ln = corner_edges(F, arm, mesh, rest_co)
    if not edges:
        return 16.0, None, "không khoanh được khoé miệng -- trần hàm dè dặt 16°"
    best, worst = JAW_SCAN[0], None
    for ang in JAW_SCAN:
        reset(arm)
        apply_pose(arm, jaw_open(F, Pose(F), ang))
        s = stretch(mesh, edges, ln)
        if s > STRETCH_MAX:
            worst = s
            break
        best = ang
    reset(arm)
    return float(best), worst, "%d cạnh quanh khoé" % len(edges)


# Đường gặp ưu tiên khi hoà. Từng là .15 (mí trên đi gần hết quãng) -- trên mắt
# hoạt hình to như Kid/Adult mí trên phải quay >80°, da gấp nếp dọc thành mép
# mí răng cưa. .4 cho đường mí trơn; má không còn phồng vì vùng mí dưới đã có
# chốt LID_LO_SPAN.
MEET_PREF = .4


def calibrate_meet(F, arm, mesh, rest_co, eyes, exposure, extents, hugs):
    """Đường gặp mí ít lòi nhãn cầu nhất, đo bằng ray cast lên nhãn cầu rời.

    Hoà thì chọn gần MEET_PREF: mí dưới skin lan rất xa xuống má (trên Kid tới
    2.9 lần bán kính mắt), bắt nó đi nửa quãng là kéo cả gò má lên theo.
    """
    from . import face
    out = {}
    for s in 'LR':
        eye = next((e for e in eyes if face.eye_side(e) == s), None)
        if eye is None or lid_angles(F, s) is None:
            continue
        rows = []
        for t in (.0, .1, .15, .2, .3, .4, .5):
            d = Lids(s, t, 1.0, 1.0, extents.get(s), hugs.get(s)).field(F, arm, mesh, rest_co)
            if d is None:
                break
            kb = bake_delta(mesh, "SRP_meet_probe", d, own=False)
            kb.value = 1.0
            bpy.context.view_layer.update()
            rows.append((exposure(eye, n=26), t))
            mesh.shape_key_remove(kb)
        if not rows:
            continue
        lo = min(e for e, _t in rows)
        # Hoà trong 1 điểm %: 0.15% với 0.6% lòi nhãn cầu mắt không phân biệt
        # được, còn đường gặp thấp thì mép mí răng cưa (xem MEET_PREF).
        good = [t for e, t in rows if e <= lo + 1.0]
        out[s] = (min(good, key=lambda t: abs(t - MEET_PREF)), lo)
    bpy.context.view_layer.update()
    return out


def bake_delta(obj, name, delta, thresh=2e-4, own=True):
    """Như `face.bake` nhưng nhận sẵn độ dời (công thức mí)."""
    from . import face
    if delta is None or max(d.length for d in delta) < thresh:
        return None
    face.ensure_basis(obj)
    basis = obj.data.shape_keys.key_blocks['Basis']
    kb = obj.shape_key_add(name=name, from_mix=False)
    if own:
        face.own_key(obj, kb)
    kb.value = 0.0
    kb.slider_min, kb.slider_max = 0.0, 1.0
    for i, d in enumerate(delta):
        kb.data[i].co = basis.data[i].co + d
    return kb


# ============================================================ dựng

def targets_for(arm, face_mesh):
    """Mesh mặt trước, rồi mọi mesh khác do rig này làm biến dạng ở gần mặt
    (lông mày tách rời, răng, lưỡi rời...). Mesh nào không nhúc nhích thì
    `face.bake` tự bỏ qua."""
    from . import face
    others = [o for o in bpy.data.objects
              if o.type == 'MESH' and o is not face_mesh
              and any(m.type == 'ARMATURE' and m.object is arm for m in o.modifiers)]
    return [face_mesh] + face.near_face(face_mesh, others, margin=.05)


def build(op, context, arm, face_mesh):
    """Dựng cả bộ. Trả về set kết quả của operator."""
    from . import face
    st = context.scene.face_shapes
    F = Frame(arm)
    _teeth, eyes = face.followers_for(arm, face_mesh)
    if not st.do_eyes:
        eyes = []
    targets = targets_for(arm, face_mesh)
    if not op.strip(targets + eyes):
        return {'CANCELLED'}

    lines = ["Rig %s | mesh %s (%d vertex) | %d mesh phụ"
             % (arm.name, face_mesh.name, len(face_mesh.data.vertices), len(targets) - 1),
             "Bề rộng miệng %.4f | khe môi %.4f" % (F.W, F.lip_gap)]
    made = {o.name: [] for o in targets}
    with face.PoseScope(arm) as scope, face.KeyScope(targets + eyes):
        for o in targets:
            face.ensure_basis(o)
        face.zero_keys(targets)
        rest = {o.name: eval_co(o) for o in targets}

        jaw_max, worst, note = calibrate_jaw(F, arm, face_mesh, rest[face_mesh.name])
        lines.append("Trần hạ hàm %.0f° (%s%s)" % (
            jaw_max, note, "" if worst is None else ", góc kế tiếp giãn %.2fx" % worst))
        extents = {s: lid_extent(F, arm, face_mesh, rest[face_mesh.name], s) for s in 'LR'}
        hugs = {s: eye_hug(F, arm, eyes, s) for s in 'LR'}
        meets = calibrate_meet(F, arm, face_mesh, rest[face_mesh.name], eyes,
                               face.eyeball_exposure, extents, hugs)
        meet = (sum(t for t, _e in meets.values()) / len(meets)) if meets else MEET_PREF
        for s, ext in sorted(extents.items()):
            if ext:
                lines.append("Vùng mí %s: từ %.0f° tới %.0f° quanh tâm nhãn cầu"
                             % (s, math.degrees(ext[1]), math.degrees(ext[0])))
        for s, (t, e) in sorted(meets.items()):
            lines.append("Đường gặp mí %s: %.2f (nhãn cầu còn lòi %.2f%%)" % (s, t, e))

        R = recipes(F, meet=meet, jaw_max=jaw_max, ex=st.exaggerate / 100.0,
                    extents=extents, hugs=hugs)
        for name in sorted(R, key=face.sort_key):
            scope.reset()
            recipe = R[name]
            if isinstance(recipe, Lids):
                # Chỉ mesh mặt: mesh lông mày rời của Kid cũng mang trọng số
                # mí, và chớp mắt kéo luôn nửa dưới hàng mày xuống mắt.
                for o in targets[:1]:
                    d = recipe.field(F, arm, o, rest[o.name])
                    if bake_delta(o, name, d) is not None:
                        made[o.name].append(name)
                continue
            apply_pose(arm, recipe)
            for o in targets:
                if face.bake(o, name, rest[o.name]) is not None:
                    made[o.name].append(name)
        scope.reset()

    st.jaw_max, st.calibrated = jaw_max, True

    for eye in eyes:
        s = face.eye_side(eye)
        key = 'EYE_Blink%s' % s if s else None
        if key and key in made[face_mesh.name] and st.eye_shrink_on:
            face.make_eyeball_key(eye, key, st.eye_shrink, st.eye_back)

    # mesh phụ bám theo slider của mesh mặt: người dùng chỉ kéo một chỗ
    src = face_mesh.data.shape_keys
    for o in targets[1:] + eyes:
        key = o.data.shape_keys
        if not key:
            continue
        thr = st.eye_threshold if o in eyes else 0.0
        for kb in key.key_blocks:
            if face.is_own(key, kb) and kb.name in src.key_blocks:
                face.drop_driver(key, kb.name)
                face.add_driver(kb, src, kb.name, thr)

    n = len(made[face_mesh.name])
    lines.append("%s: %d shape key | cường điệu %.0f%%" % (face_mesh.name, n, st.exaggerate))
    for o in targets[1:]:
        if made[o.name]:
            lines.append("%s: %d shape key (driver theo %s)"
                         % (o.name, len(made[o.name]), face_mesh.name))
    skipped = sorted(set(R) - set(made[face_mesh.name]))
    if skipped:
        lines.append("Không làm %s nhúc nhích: %s" % (face_mesh.name, ", ".join(skipped)))
    for ln in lines:
        prefs.log("[FaceShapes] rig Rig Tẩm Hành | " + ln)
    op.report({'INFO'}, "Đã dựng %d shape key từ face rig %s trên %s"
              % (n, arm.name, face_mesh.name))
    return {'FINISHED'}
