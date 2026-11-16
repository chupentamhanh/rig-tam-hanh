"""Xuất rig + nhân vật + animation sang Unity, Rig Type = Humanoid.

Không xuất thẳng rig điều khiển. Rig Rig Tẩm Hành có hai thứ Unity không đọc được:
- bone deform chạy bằng constraint (IK_Follow / FK_Follow theo chuỗi FK/IK),
- `Hips` KHÔNG phải bone deform mà Spine / Pelvis.L / Pelvis.R là con của nó:
  xuất "chỉ bone deform" thì Unity mất Hips, mà Humanoid bắt buộc có Hips.

Nên lúc bấm Xuất, addon dựng một KHUNG XƯƠNG GAME tạm: bone deform + mọi bone
được ánh xạ Humanoid + bone gốc, cha của mỗi bone là tổ tiên gần nhất cũng nằm
trong khung. Không constraint nào ngoài một Copy Transforms bám rig gốc, nên
exporter FBX lấy mẫu từng frame ra đúng chuyển động đã qua toàn bộ IK/FK.

Mesh cũng xuất từ BẢN SAO: apply xoay/scale (body của Kid xoay -90° X, scale
0.01), gộp mesh có shape key chạy bằng driver vào mesh nó bám (driver không đi
qua FBX), skin nhãn cầu gắn-bone thành 100% vào bone đó, giới hạn 4 bone mỗi
vertex. Xong là xoá sạch, file không đổi.

Mỗi action ra một file `<tên>@<action>.fbx` (quy ước của Unity), mô hình ra
`<tên>.fbx`, bảng ánh xạ ra `<tên>.humanoid.json`. Script Unity
`RigTamHanhHumanoidImporter.cs` đọc file json đó và tự dựng Avatar Humanoid —
không dựa vào auto-map của Unity, vốn nhầm với tên như Bicep, Hand_Master,
Palm.*.
"""

import json
import os
import re

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, IntProperty,
                       PointerProperty, StringProperty)
from bpy.types import Operator, PropertyGroup, UIList
from mathutils import Matrix, Vector

from . import compat, prefs, rigdef

# ============================================================ bảng Humanoid

SIDES = (('L', 'Left'), ('R', 'Right'))
FINGERS = (('Thumb', 'Thumb'), ('Index', 'Index'), ('Middle', 'Middle'),
           ('Ring', 'Ring'), ('Pinky', 'Little'))
PHALANX = ('Proximal', 'Intermediate', 'Distal')

REQUIRED = ['Hips', 'Spine', 'Head'] + [
    s + n for _c, s in SIDES
    for n in ('UpperLeg', 'LowerLeg', 'Foot', 'UpperArm', 'LowerArm', 'Hand')]


def _human_parents():
    """Bone Humanoid -> các bone Humanoid có thể làm tổ tiên gần nhất của nó."""
    P = {'Spine': ('Hips',), 'Chest': ('Spine',), 'UpperChest': ('Chest',),
         'Neck': ('UpperChest', 'Chest', 'Spine'),
         'Head': ('Neck', 'UpperChest', 'Chest', 'Spine'), 'Jaw': ('Head',)}
    for _c, s in SIDES:
        P[s + 'Eye'] = ('Head',)
        P[s + 'Shoulder'] = ('UpperChest', 'Chest', 'Spine')
        P[s + 'UpperArm'] = (s + 'Shoulder', 'UpperChest', 'Chest', 'Spine')
        P[s + 'LowerArm'] = (s + 'UpperArm',)
        P[s + 'Hand'] = (s + 'LowerArm',)
        P[s + 'UpperLeg'] = ('Hips',)
        P[s + 'LowerLeg'] = (s + 'UpperLeg',)
        P[s + 'Foot'] = (s + 'LowerLeg',)
        P[s + 'Toes'] = (s + 'Foot',)
        for _f, uf in FINGERS:
            prev = s + 'Hand'
            for ph in PHALANX:
                name = "%s %s %s" % (s, uf, ph)
                P[name] = (prev,)
                prev = name
    return P


HUMAN_PARENTS = _human_parents()
HUMAN_ORDER = ['Hips'] + list(HUMAN_PARENTS)

MAP_TEXT = "SRP_Humanoid_Map"   # text block sửa tay: dòng "LeftHand = TênBone"

# ============================================================ đoán tên bone

_PREFIX = re.compile(r'^(mixamorig\d*:|def[-_]|org[-_]|b_|bip\d*\s?)', re.I)
_SUFFIX_SIDE = re.compile(r'[._\- ]([lr]|left|right)$', re.I)
_PREFIX_SIDE = re.compile(r'^(left|right|[lr][._\-])', re.I)

ALIAS = {
    'Hips': ('hips', 'hip', 'pelvis'),
    'Neck': ('neck',), 'Head': ('head',), 'Jaw': ('jaw',),
    'Eye': ('eye',),
    'Shoulder': ('shoulder', 'clavicle', 'collar'),
    'UpperArm': ('upperarm', 'bicep', 'arm'),
    'LowerArm': ('lowerarm', 'forearm', 'elbow'),
    'Hand': ('hand', 'handmaster', 'wrist'),
    'UpperLeg': ('upperleg', 'thigh', 'upleg'),
    'LowerLeg': ('lowerleg', 'shin', 'calf', 'knee', 'leg'),
    'Foot': ('foot', 'ankle'),
    'Toes': ('toes', 'toe', 'toebase', 'ball'),
}


def parse(name):
    """(gốc chữ thường không dấu nối, bên 'L'/'R'/None, số đuôi .00N)."""
    core = _PREFIX.sub('', name)
    num = None
    m = re.match(r'^(.*?)\.(\d{3})$', core)
    if m:
        core, num = m.group(1), int(m.group(2))
    side = None
    m = _SUFFIX_SIDE.search(core)
    if m:
        side = m.group(1)[0].upper()
        core = core[:m.start()]
    else:
        m = _PREFIX_SIDE.match(core)
        if m:
            side = m.group(1)[0].upper()
            core = core[m.end():]
    return re.sub(r'[._\- ]', '', core).lower(), side, num


def _depth(b):
    return len(b.parent_recursive)


def _chain(top, bottom):
    """Các bone nằm GIỮA top và bottom trên đường cha-con, từ trên xuống."""
    out, b = [], bottom.parent
    while b is not None and b != top:
        out.append(b)
        b = b.parent
    return list(reversed(out)) if b == top else None


def auto_map(arm):
    """{tên Humanoid: tên bone}. Quy ước Rig Tẩm Hành trước, rồi đoán theo tên."""
    B = arm.data.bones
    m = {}

    def put(human, bone):
        if bone and bone in B and human not in m:
            m[human] = bone

    # --- quy ước Rig Tẩm Hành (rigdef): biết chắc, không phải đoán
    arm_t = rigdef.TEMPLATE_BY_KIND['ARM']['deform']
    leg_t = rigdef.TEMPLATE_BY_KIND['LEG']['deform']
    put('Hips', 'Hips')
    put('Neck', 'Neck')
    put('Head', 'Head')
    put('Jaw', 'Jaw')
    for c, s in SIDES:
        bn = lambda base: rigdef.bone_name(base, 1, c)
        put(s + 'Eye', bn('Eye'))
        put(s + 'Shoulder', bn('Shoulder'))
        for human, base in zip(('UpperArm', 'LowerArm', 'Hand'), arm_t):
            put(s + human, bn(base))
        for human, base in zip(('UpperLeg', 'LowerLeg', 'Foot'), leg_t):
            put(s + human, bn(base))
        put(s + 'Toes', bn('Toe'))

    # --- đoán theo tên cho rig ngoài
    by = {}
    for b in B:
        base, side, num = parse(b.name)
        by.setdefault((base, side), []).append(b)
    for human, words in ALIAS.items():
        sided = human not in ('Hips', 'Neck', 'Head', 'Jaw')
        for c, s in (SIDES if sided else ((None, ''),)):
            key = s + human
            if key in m:
                continue
            for w in words:
                cands = by.get((w, c))
                if cands:
                    # cùng gốc nhiều bone (Spine, Spine1...) thì lấy cái gần gốc
                    m[key] = min(cands, key=_depth).name
                    break

    # --- cột sống: theo HÌNH chứ không theo tên, đoạn giữa Hips và Neck/Head
    top = B.get(m.get('Hips', ''))
    low = B.get(m.get('Neck', '')) or B.get(m.get('Head', ''))
    spine = _chain(top, low) if top and low else None
    if spine:
        if len(spine) == 1:
            names = ['Spine']
        elif len(spine) == 2:
            names = ['Spine', 'Chest']
        else:
            names = ['Spine'] + [None] * (len(spine) - 3) + ['Chest', 'UpperChest']
        for human, b in zip(names, spine):
            if human:
                m[human] = b.name

    # --- ngón tay: chuỗi 3 đốt dưới bàn tay, theo tên ngón
    for c, s in SIDES:
        hand = B.get(m.get(s + 'Hand', ''))
        if hand is None:
            continue
        under = [b for b in hand.children_recursive]
        for word, uf in FINGERS:
            w = word.lower()
            alts = (w, 'little') if w == 'pinky' else (w,)
            bones = sorted((b for b in under
                            if any(a in parse(b.name)[0] for a in alts)
                            and 'palm' not in parse(b.name)[0]
                            and 'meta' not in parse(b.name)[0]),
                           key=_depth)
            for ph, b in zip(PHALANX, bones[:3]):
                m.setdefault("%s %s %s" % (s, uf, ph), b.name)
    return m


def overrides():
    t = bpy.data.texts.get(MAP_TEXT)
    out = {}
    if t is None:
        return out
    for line in t.as_string().splitlines():
        line = line.split('#', 1)[0]
        if '=' in line:
            k, v = (x.strip() for x in line.split('=', 1))
            if k in HUMAN_PARENTS or k == 'Hips':
                out[k] = v or None
    return out


def humanoid_map(arm):
    m = auto_map(arm)
    for k, v in overrides().items():
        if v:
            m[k] = v
        else:
            m.pop(k, None)
    return m


# ============================================================ kiểm tra

def rig_meshes(arm):
    """(mesh skin vào rig, mesh gắn-bone vào rig). Bỏ mesh tắt render."""
    skinned, attached = [], []
    for o in bpy.data.objects:
        if o.type != 'MESH' or o.hide_render:
            continue
        if any(md.type == 'ARMATURE' and md.object is arm for md in o.modifiers):
            skinned.append(o)
        elif o.parent is arm and o.parent_type == 'BONE' and o.parent_bone:
            attached.append(o)
    return skinned, attached


def rig_clips(arm):
    """[(action, slot)] -- clip dành cho rig này, đọc theo SLOT của action: slot
    rig đang / đã dùng, slot trùng tên rig, hoặc slot OBJECT có phần lớn kênh
    trỏ vào bone có thật của rig. Action chỉ có slot shape key thì bỏ qua."""
    names = {b.name for b in arm.data.bones}
    out = []
    for a in bpy.data.actions:
        hit = None
        for s in a.slots:
            if s.target_id_type not in ('OBJECT', 'UNSPECIFIED'):
                continue
            users = getattr(s, "users", None)
            if (users is not None and arm in users()) or s.name_display == arm.name:
                hit = s
                break
            bones = {compat.bone_of(fc.data_path) for fc in compat.action_fcurves(a, s)}
            bones.discard(None)
            if hit is None and bones and len(bones & names) >= .5 * len(bones):
                hit = s
        if hit is not None:
            out.append((a, hit))
    return sorted(out, key=lambda p: p[0].name.lower())


def rig_actions(arm):
    """Action dành cho rig này (xem rig_clips)."""
    return [a for a, _s in rig_clips(arm)]


def picked_actions(arm):
    """Clip được tích "Xuất" trong danh sách của panel."""
    return [a for a in rig_actions(arm) if getattr(a, "srp_unity_export", True)]


SCOPES = (('RIG', "Mọi mesh của rig", "Mọi mesh skin / gắn vào rig (trừ mesh tắt render)"),
          ('SELECTED', "Mesh đang chọn", "Chỉ những mesh của rig đang được chọn trong viewport"),
          ('VISIBLE', "Mesh đang hiện", "Chỉ những mesh của rig đang hiện trong viewport"),
          ('COLLECTION', "Mesh trong collection", "Chỉ những mesh của rig nằm trong một collection"))


def scoped_meshes(context, arm, scope='RIG', coll=None):
    """rig_meshes lọc theo phạm vi xuất. Trả về (skinned, attached)."""
    skinned, attached = rig_meshes(arm)
    if scope == 'SELECTED':
        keep = lambda o: o.select_get()
    elif scope == 'VISIBLE':
        keep = lambda o: o.visible_get()
    elif scope == 'COLLECTION':
        objs = set(coll.all_objects) if coll is not None else set()
        keep = lambda o: o in objs
    else:
        return skinned, attached
    return [o for o in skinned if keep(o)], [o for o in attached if keep(o)]


def action_sets(arm):
    """[(bộ, [action])] -- bộ action được tích xuất, bỏ ô trống / action đã xoá."""
    out = []
    for st in getattr(arm, "srp_action_sets", ()):
        acts = []
        for r in st.actions:
            if r.action is not None and r.action not in acts:
                acts.append(r.action)
        if st.use and acts:
            out.append((st, acts))
    return out


def driven_into(meshes):
    """{mesh có key chạy bằng driver: mesh mà driver trỏ tới}."""
    keys = {o.data.shape_keys: o for o in meshes if o.data.shape_keys}
    out = {}
    for o in meshes:
        key = o.data.shape_keys
        anim = key.animation_data if key else None
        if not anim:
            continue
        for fc in anim.drivers:
            for var in fc.driver.variables:
                src = keys.get(var.targets[0].id)
                if src is not None and src is not o:
                    out[o] = src
    return out


def _angle(v, w):
    return v.angle(w) if v.length > 1e-9 else 0.0


def check(arm):
    """(lỗi, cảnh báo, ghi chú, bảng ánh xạ). Có lỗi thì không xuất."""
    import math
    errors, warns, notes = [], [], []
    B = arm.data.bones
    m = humanoid_map(arm)
    for h in REQUIRED:
        if h not in m:
            errors.append("Thiếu bone Humanoid bắt buộc: %s" % h)
    for h, bone in m.items():
        if bone not in B:
            errors.append("%s trỏ tới bone không có: %s" % (h, bone))
    if errors:
        return errors, warns, notes, m
    used = {}
    for h, bone in m.items():
        if bone in used:
            errors.append("%s và %s cùng trỏ vào %s" % (used[bone], h, bone))
        used[bone] = h
    for h, parents in HUMAN_PARENTS.items():
        if h not in m:
            continue
        up = next((p for p in parents if p in m), None)
        if up is None:
            continue
        if B[m[up]] not in B[m[h]].parent_recursive:
            errors.append("%s (%s) không nằm dưới %s (%s)" % (h, m[h], up, m[up]))

    # T-pose: Unity dựng Avatar ở T-pose; lệch nhiều thì phải Enforce T-Pose
    for c, s in SIDES:
        ua, la = B[m[s + 'UpperArm']], B[m[s + 'LowerArm']]
        out = Vector((1.0 if c == 'L' else -1.0, 0.0, 0.0))
        a = math.degrees(_angle(la.head_local - ua.head_local, out))
        ul, ft = B[m[s + 'UpperLeg']], B[m[s + 'Foot']]
        b = math.degrees(_angle(ft.head_local - ul.head_local, Vector((0, 0, -1))))
        if a > 15:
            warns.append("Tay %s lệch T-pose %.0f° -- Unity sẽ Enforce T-Pose" % (s, a))
        if b > 15:
            warns.append("Chân %s lệch thẳng đứng %.0f°" % (s, b))
        notes.append("Tay %s lệch T-pose %.0f°, chân %.0f°" % (s, a, b))

    skinned, attached = rig_meshes(arm)
    if not skinned:
        errors.append("Không có mesh nào skin vào %s" % arm.name)
    for o in skinned:
        over = sum(1 for v in o.data.vertices
                   if sum(1 for g in v.groups if g.weight > 1e-4) > 4)
        if over:
            notes.append("%s: %d vertex quá 4 bone -- sẽ cắt còn 4 lúc xuất" % (o.name, over))
    for o, src in driven_into(skinned).items():
        notes.append("%s: shape key chạy bằng driver -- sẽ gộp vào %s" % (o.name, src.name))
    for o in attached:
        notes.append("%s gắn vào bone %s -- sẽ skin 100%% vào bone đó" % (o.name, o.parent_bone))

    every = rig_actions(arm)
    acts = picked_actions(arm)
    for a in acts:
        for fc in compat.action_fcurves(a):
            if fc.data_path.endswith('.scale') and compat.curve_amplitude(fc) > 1e-4:
                warns.append("%s: có animation scale bone (%s) -- Humanoid bỏ qua scale"
                             % (a.name, compat.bone_of(fc.data_path)))
                break
    notes.append("%d clip cho rig này, xuất %d: %s" % (len(every), len(acts), ", ".join(a.name for a in acts) or "--"))
    skip = [a.name for a in every if a not in acts]
    if skip:
        notes.append("Bỏ không xuất: " + ", ".join(skip))
    extra = sorted(b.name for b in B if b.use_deform and b.name not in used)
    notes.append("%d bone Humanoid, %d bone thêm (mặt, tai, Palm...) đi theo dạng transform phụ"
                 % (len(m), len(extra)))
    return errors, warns, notes, m


# ============================================================ khung xương game

def game_bones(arm, hmap, only_human=False):
    """{tên bone: tên cha trong khung} theo thứ tự cha trước con.

    only_human: CHỈ các bone Humanoid (55 trên Kid thay vì 114) -- Hips là gốc,
    không Root, không bone mặt / tai / Palm / Pelvis / đốt sống thừa. Trọng số
    trên các bone bị bỏ được dồn sang bone giữ lại, xem `merge_map`.
    """
    B = arm.data.bones
    if only_human:
        keep = set(hmap.values())
    else:
        keep = {b.name for b in B if b.use_deform} | set(hmap.values())
        hips = B[hmap['Hips']]
        root = hips.parent_recursive[-1] if hips.parent_recursive else hips
        keep.add(root.name)
    out = {}
    for b in sorted((B[n] for n in keep), key=_depth):
        p = b.parent
        while p is not None and p.name not in keep:
            p = p.parent
        out[b.name] = p.name if p is not None else None
    return out


TORSO = ('Hips', 'Spine', 'Chest', 'UpperChest', 'Neck')


def _moves(arm, name):
    """Bone tự cử động được: animator cầm được (widget) hoặc có constraint."""
    pb = arm.pose.bones.get(name)
    return pb is not None and (pb.custom_shape is not None or len(pb.constraints) > 0)


def merge_map(arm, keep, torso=()):
    """{bone bị bỏ: [(bone giữ lại, tỉ lệ)]} để dồn trọng số lưới.

    - Bone nằm GIỮA một chuỗi THÂN (bone giữ lại phía trên thuộc `torso`, phía
      dưới đúng một bone giữ lại gần nhất) VÀ tự cử động được (có widget hoặc
      constraint): chia đôi cho bone trên và bone dưới. Spine.001 (có widget)
      giữa Spine và Chest -> nửa Spine nửa Chest, thân vẫn cong mượt.
      Bone cứng như Pelvis.L (không widget, không constraint) thì dồn hết về
      Hips: chia nửa cho đùi làm hông lệch tới 8 mm khi nhấc chân (đo trên Kid).
    - Còn lại: dồn hết về bone giữ lại gần nhất phía trên. Môi dưới, răng
      dưới, lưỡi -> Jaw; môi trên, mí, mày, tai -> Head; Palm -> Hand (không
      chia cho đốt ngón: lòng bàn tay mà cong theo ngón là sai). Biểu cảm mặt
      vẫn đi qua blendshape.
    """
    out = {}
    for b in arm.data.bones:
        if b.name in keep or not b.use_deform:
            continue
        up = b.parent
        while up is not None and up.name not in keep:
            up = up.parent
        below, stack = [], list(b.children)
        while stack:
            c = stack.pop()
            if c.name in keep:
                below.append(c.name)
            else:
                stack.extend(c.children)
        if up is None and not below:
            continue
        if up is None:
            out[b.name] = [(below[0], 1.0)]
        elif len(below) == 1 and up.name in torso and _moves(arm, b.name):
            out[b.name] = [(up.name, 0.5), (below[0], 0.5)]
        else:
            out[b.name] = [(up.name, 1.0)]
    return out


def merge_weights(obj, mapping):
    """Dồn nhóm vertex của bone bị bỏ sang bone giữ lại, rồi xoá nhóm cũ."""
    vg = obj.vertex_groups
    idx = {g.index: g.name for g in vg}
    src = {g.index for g in vg if g.name in mapping}
    if not src:
        return 0
    moved = 0
    for v in obj.data.vertices:
        add = {}
        for g in v.groups:
            if g.group in src and g.weight > 0:
                for dst, f in mapping[idx[g.group]]:
                    add[dst] = add.get(dst, 0.0) + g.weight * f
        if not add:
            continue
        moved += 1
        cur = {idx[g.group]: g.weight for g in v.groups if g.group not in src}
        for n, w in add.items():
            grp = vg.get(n) or vg.new(name=n)
            grp.add([v.index], cur.get(n, 0.0) + w, 'REPLACE')
    for g in [g for g in vg if g.name in mapping]:
        vg.remove(g)
    return moved


def _with(context, obj, sel=None):
    sel = sel if sel is not None else [obj]
    return context.temp_override(active_object=obj, object=obj,
                                 selected_objects=sel, selected_editable_objects=sel)


# Xoay 180° quanh Z (world) cả khung game lẫn mesh: nhân vật nhìn -Y trong
# Blender sẽ nhìn +Z trong Unity, đúng transform.forward.
FACE_Z = Matrix.Rotation(3.141592653589793, 4, 'Z')


def skeleton_name(name):
    """Tên node armature trong FBX. KHÔNG được trùng tên file: Unity đặt node
    gốc của mô hình theo tên file, rồi dựng Avatar bằng cách khớp transform theo
    TÊN -- trùng thì nó lấy nhầm node gốc thay cho armature, tư thế tham chiếu
    của Avatar bị xoay (đo: chân nằm ngang, T-pose hỏng)."""
    return safe(name) + "_Armature"


def build_skeleton(context, arm, hmap, name, coll, turn, only_human=False):
    data = bpy.data.armatures.new(skeleton_name(name))
    obj = bpy.data.objects.new(skeleton_name(name), data)
    coll.objects.link(obj)
    obj.matrix_world = turn @ arm.matrix_world
    bones = game_bones(arm, hmap, only_human)
    B = arm.data.bones
    context.view_layer.objects.active = obj
    with _with(context, obj):
        bpy.ops.object.mode_set(mode='EDIT')
        eb = data.edit_bones
        for n, parent in bones.items():
            src = B[n]
            e = eb.new(n)
            e.head, e.tail = (0, 0, 0), (0, src.length, 0)
            e.matrix = src.matrix_local
            e.use_deform = src.use_deform or n in hmap.values()
            if parent:
                e.parent = eb[parent]
        bpy.ops.object.mode_set(mode='OBJECT')
    for pb in obj.pose.bones:
        c = pb.constraints.new('COPY_TRANSFORMS')
        c.name = "SRP_Follow"
        c.target, c.subtarget = arm, pb.name
        # không gian armature: rest hai bên trùng nhau, nên khung game xoay
        # đi bao nhiêu thì chuyển động xoay theo bấy nhiêu
        c.target_space = c.owner_space = 'POSE'
    return obj


def follow(game, on):
    for pb in game.pose.bones:
        for c in pb.constraints:
            c.mute = not on
    bpy.context.view_layer.update()


# ============================================================ mesh

MAX_INFLUENCE = 4


def limit_weights(obj, deform):
    """Giữ 4 bone nặng nhất mỗi vertex, chuẩn hoá lại về tổng 1."""
    vg = obj.vertex_groups
    idx = {g.index: g for g in vg}
    for v in obj.data.vertices:
        ws = [(g.weight, g.group) for g in v.groups
              if idx[g.group].name in deform and g.weight > 0]
        if not ws:
            continue
        ws.sort(reverse=True)
        keep, drop = ws[:MAX_INFLUENCE], ws[MAX_INFLUENCE:]
        for _w, gi in drop:
            idx[gi].remove([v.index])
        tot = sum(w for w, _g in keep)
        for w, gi in keep:
            idx[gi].add([v.index], w / tot, 'REPLACE')


def prep_meshes(context, arm, game, coll, rename, made, turn, merge=None, src=None):
    """Bản sao mesh sẵn để xuất. Trả về [object]; data tạo ra ghi vào `made`.

    `rename`: {object gốc: tên gốc} -- bản gốc đang mang tên tạm để bản sao
    lấy được đúng tên.
    """
    skinned, attached = src if src is not None else rig_meshes(arm)
    deform = {b.name for b in game.data.bones if b.use_deform}
    copies = {}
    for o in skinned + attached:
        c = o.copy()
        c.data = o.data.copy()
        made.append(c.data)
        c.animation_data_clear()
        if c.data.shape_keys is not None:
            c.data.shape_keys.animation_data_clear()
        coll.objects.link(c)
        c.name = rename[o]
        c.data.name = rename[o]
        copies[o] = c
    for o in attached:
        c = copies[o]
        mw = turn @ o.matrix_world
        c.parent = None
        c.matrix_world = mw
        g = c.vertex_groups.new(name=o.parent_bone)
        g.add([v.index for v in c.data.vertices], 1.0, 'REPLACE')
        c.modifiers.new("Armature", 'ARMATURE')
    for o in skinned:
        c = copies[o]
        mw = turn @ o.matrix_world
        c.parent = None
        c.matrix_world = mw

    # gộp mesh có key chạy bằng driver vào mesh nó bám
    gone = set()
    for o, host in driven_into(skinned).items():
        if host not in copies:
            continue            # mesh nó bám không nằm trong phạm vi xuất
        t, s = copies[host], copies[o]
        with _with(context, t, [t, s]):
            bpy.ops.object.join()
        gone.add(o)
    out = [c for o, c in copies.items() if o not in gone]

    for c in out:
        with _with(context, c):
            bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        for md in c.modifiers:
            if md.type == 'ARMATURE':
                md.object = game
        c.parent = game
        c.matrix_parent_inverse = game.matrix_world.inverted()
        if merge:
            merge_weights(c, merge)
        # nhóm trỏ vào bone không deform (control) sẽ thành cluster thật trong
        # FBX và làm mesh bị kéo theo bone đó ở Unity
        for g in list(c.vertex_groups):
            if g.name in game.data.bones and g.name not in deform:
                c.vertex_groups.remove(g)
        limit_weights(c, deform)
        if c.data.shape_keys:
            for kb in c.data.shape_keys.key_blocks:
                kb.value = 0.0
    return out


# ============================================================ animation

def face_action(action):
    """(action, slot) cho shape key đi kèm action rig, hoặc (None, None).

    Hai cách: chính action đó có slot KEY (Blender 4.4+ cho một action giữ cả
    rig lẫn shape key), hoặc một action riêng tên `<action>_Face`.
    """
    for s in action.slots:
        if s.target_id_type == 'KEY':
            return action, s
    a = bpy.data.actions.get(action.name + "_Face")
    if a is not None:
        s = next((s for s in a.slots if s.target_id_type == 'KEY'), None)
        return a, s
    return None, None


def set_key_action(mesh, action, slot):
    key = mesh.data.shape_keys
    if key is None:
        return
    if action is None:
        if key.animation_data:
            key.animation_data.action = None
        for kb in key.key_blocks:
            kb.value = 0.0
        return
    anim = key.animation_data or key.animation_data_create()
    anim.action = action
    if slot is not None:
        anim.action_slot = slot


def safe(name):
    return re.sub(r'[\\/:*?"<>|@]+', '_', name).strip() or "Take"


# Hướng nhìn KHÔNG chỉnh được bằng axis_forward: Unity đọc hệ trục ghi trong
# FBX rồi bù lại, nên '-Z' hay 'Z' ra y hệt nhau (đo trong Unity 2022.3). Nhân
# vật Blender nhìn -Y thì sang Unity nhìn -Z, transform.forward chỉ ra sau
# lưng. Sửa bằng FACE_Z ở build_skeleton / prep_meshes.
FBX = dict(
    use_selection=True, object_types={'ARMATURE', 'MESH'},
    apply_unit_scale=True, apply_scale_options='FBX_SCALE_UNITS',
    axis_forward='-Z', axis_up='Y', use_space_transform=True,
    bake_space_transform=False,
    add_leaf_bones=False, primary_bone_axis='Y', secondary_bone_axis='X',
    use_armature_deform_only=False, armature_nodetype='NULL',
    use_mesh_modifiers=False, mesh_smooth_type='FACE',
    use_custom_props=False, path_mode='AUTO',
    bake_anim_use_all_bones=True, bake_anim_use_nla_strips=False,
    bake_anim_use_all_actions=False, bake_anim_force_startend_keying=True,
    bake_anim_step=1.0, bake_anim_simplify_factor=0.0,
)


def write_fbx(context, path, objs, anim, nla=False):
    for o in context.view_layer.objects:
        o.select_set(o in objs)
    context.view_layer.objects.active = objs[0]
    opts = dict(FBX, bake_anim_use_nla_strips=nla)
    bpy.ops.export_scene.fbx(filepath=path, bake_anim=anim, **opts)


# ============================================================ gộp clip

# Gộp nhiều clip vào một FBX: exporter làm một take cho mỗi NLA strip của
# object được xuất (nó tắt mọi strip, bật từng cái, lấy mẫu đúng đoạn của
# strip đó). Khung game bám rig gốc bằng constraint chứ không có action, nên
# phải BAKE từng action ra keyframe trên chính khung game trước.
#
# Shape key thì exporter không tắt/bật hộ (Key không phải object). Nên các clip
# được XẾP NỐI ĐUÔI trên timeline, cách nhau CLIP_GAP frame, và action shape
# key đặt thành strip NLA của Key đúng đoạn đó: lấy mẫu take nào thì chỉ strip
# shape key của take đó đang chạy.

CLIP_GAP = 10
_LINEAR = 1     # enum Keyframe.interpolation: CONSTANT=0, LINEAR=1, BEZIER=2


def bake_clip(context, arm, game, action, first, last, name):
    """Lấy mẫu khung game (đang bám rig gốc) từng frame -> action mới."""
    compat.assign_action(arm, action)
    sc = context.scene
    bones = list(game.pose.bones)
    rows = {pb.name: [] for pb in bones}
    for f in range(first, last + 1):
        sc.frame_set(f)
        for pb in bones:
            m = game.convert_space(pose_bone=pb, matrix=pb.matrix,
                                   from_space='POSE', to_space='LOCAL')
            rows[pb.name].append(m.decompose())
    act = bpy.data.actions.new(name)
    slot = act.slots.new('OBJECT', game.name)
    bag = compat.action_channelbag(act, slot, create=True)
    frames = list(range(first, last + 1))
    for pb in bones:
        pb.rotation_mode = 'QUATERNION'
        locs, quats, scales, prev = [], [], [], None
        for loc, q, s in rows[pb.name]:
            if prev is not None:
                q.make_compatible(prev)
            prev = q
            locs.append(loc)
            quats.append(q)
            scales.append(s)
        base = 'pose.bones["%s"].' % pb.name
        for path, vals, n in (('location', locs, 3), ('rotation_quaternion', quats, 4),
                              ('scale', scales, 3)):
            for i in range(n):
                fc = bag.fcurves.new(base + path, index=i)
                fc.keyframe_points.add(len(frames))
                co = []
                for f, v in zip(frames, vals):
                    co += (f, v[i])
                fc.keyframe_points.foreach_set('co', co)
                fc.keyframe_points.foreach_set('interpolation', [_LINEAR] * len(frames))
                fc.update()
    return act, slot


def _strip(id_, name, start, action, slot, first, last):
    anim = id_.animation_data or id_.animation_data_create()
    track = anim.nla_tracks.new()
    track.name = name
    st = track.strips.new(name, int(start), action)
    if slot is not None and hasattr(st, 'action_slot'):
        st.action_slot = slot
    st.action_frame_start, st.action_frame_end = first, last
    st.frame_start = start
    st.frame_end = start + (last - first)
    st.extrapolation = 'NOTHING'
    return st


def export_combined(context, arm, game, meshes, acts, path, made):
    """Một FBX: mô hình + mỗi action một take. Trả về danh sách clip."""
    for id_ in [game] + [m.data.shape_keys for m in meshes if m.data.shape_keys]:
        if id_.animation_data:
            for tr in list(id_.animation_data.nla_tracks):
                id_.animation_data.nla_tracks.remove(tr)
    follow(game, True)
    clips, t = [], 1
    for a in acts:
        s, e = (int(round(x)) for x in a.frame_range)
        e = max(e, s + 1)
        baked, slot = bake_clip(context, arm, game, a, s, e, "SRP_" + safe(a.name))
        made.append(baked)
        _strip(game, safe(a.name), t, baked, slot, s, e)
        fa, fs = face_action(a)
        for m in meshes:
            if fa is not None and m.data.shape_keys is not None:
                _strip(m.data.shape_keys, safe(a.name), t, fa, fs, s, e)
        clips.append({'name': safe(a.name), 'loop': bool(getattr(a, 'use_cyclic', False)),
                      'first': s, 'last': e, 'face': fa is not None,
                      'start': t})
        t += (e - s) + CLIP_GAP
    # bone theo NLA chứ không theo rig gốc nữa
    follow(game, False)
    for m in meshes:
        set_key_action(m, None, None)
    # Exporter ghi transform mặc định của node từ frame hiện tại, và script
    # Unity dựng Avatar từ chính transform đó. Frame 0 nằm ngoài mọi strip
    # (strip đầu bắt đầu ở 1, extrapolation NOTHING) nên ở đó là rest pose.
    context.scene.frame_set(0)
    write_fbx(context, path, [game] + meshes, anim=True, nla=True)
    return clips


# ============================================================ Unity

def unity_editor_dir(path):
    """Thư mục Assets/Editor nếu `path` nằm trong một project Unity, không thì None."""
    p = os.path.abspath(path)
    while True:
        head, tail = os.path.split(p)
        if tail == 'Assets' and os.path.isdir(os.path.join(head, 'ProjectSettings')):
            return os.path.join(p, 'Editor', 'RigTamHanh')
        if not tail or head == p:
            return None
        p = head


def write_unity_script(folder):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "RigTamHanhHumanoidImporter.cs")
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(UNITY_CS)
    return path


# ============================================================ xuất

class _State:
    """Chụp lại những gì việc xuất phải đụng, để trả về y nguyên."""

    def __init__(self, context, arm, objs):
        sc = context.scene
        self.frame = (sc.frame_start, sc.frame_end, sc.frame_current)
        self.active = context.view_layer.objects.active
        self.sel = [o for o in context.view_layer.objects if o.select_get()]
        self.mode = context.object.mode if context.object else 'OBJECT'
        anim = arm.animation_data
        self.action = (anim.action, anim.action_slot) if anim else None
        self.nla = [(t, t.mute) for t in anim.nla_tracks] if anim else []
        self.names = {o: o.name for o in objs}

    def restore(self, context, arm):
        sc = context.scene
        for o, n in self.names.items():
            o.name = n
        anim = arm.animation_data
        if self.action is not None:
            anim.action = self.action[0]
            if self.action[0] is not None and self.action[1] is not None:
                anim.action_slot = self.action[1]
        elif anim is not None:
            anim.action = None
        for t, mute in self.nla:
            t.mute = mute
        sc.frame_start, sc.frame_end = self.frame[0], self.frame[1]
        sc.frame_set(self.frame[2])
        for o in context.view_layer.objects:
            o.select_set(o in self.sel)
        context.view_layer.objects.active = self.active
        if self.active is not None and self.mode != 'OBJECT':
            try:
                with _with(context, self.active):
                    bpy.ops.object.mode_set(mode=self.mode)
            except RuntimeError:
                pass


def _cleanup(coll, made_data):
    for o in list(coll.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    bpy.data.collections.remove(coll)
    for d in made_data:
        if d.users == 0:
            if isinstance(d, bpy.types.Mesh):
                bpy.data.meshes.remove(d)
            elif isinstance(d, bpy.types.Armature):
                bpy.data.armatures.remove(d)
            elif isinstance(d, bpy.types.Action):
                bpy.data.actions.remove(d)
    for k in [k for k in bpy.data.shape_keys if k.users == 0]:
        try:
            bpy.data.batch_remove([k])
        except Exception:
            pass


def clip_plan(acts, which, combine):
    """[(tên file clip hoặc None = file nhân vật, [action])] theo cách xuất."""
    if which == 'SETS':
        return [(safe(st.name), a) for st, a in acts]
    if combine and acts:
        return [(None, acts)]
    return [(safe(a.name), [a]) for a in acts]


def clip_info(plan, which, combine):
    """Bảng clip cho json -- tính TRƯỚC khi ghi FBX để ghi được json trước."""
    clips = []
    for file, acts in plan:
        multi = which == 'SETS' or (combine and file is None)
        t = 1
        for a in acts:
            s, e = (int(round(x)) for x in a.frame_range)
            e = max(e, s + 1)
            c = {'name': safe(a.name), 'loop': bool(getattr(a, 'use_cyclic', False)),
                 'first': s, 'last': e, 'face': face_action(a)[0] is not None}
            if multi:
                c['start'] = t
                t += (e - s) + CLIP_GAP
            if which == 'SETS':
                c['file'] = file
            clips.append(c)
    return clips


def export(context, arm, folder, name, which='ALL', face_z=True, combine=False,
           only_human=True, tpose=True, scope='RIG', scope_coll=None):
    """Xuất. Trả về (danh sách file, dòng log).

    combine=True: mọi clip nằm trong chính `<tên>.fbx` (mỗi action một take),
    không ra file `<tên>@<action>.fbx` nào.
    which='SETS': mỗi bộ action một file `<tên>@<bộ>.fbx`, mỗi action một take.
    scope: mesh nào được xuất (SCOPES).
    """
    turn = FACE_Z if face_z else Matrix()
    errors, warns, notes, hmap = check(arm)
    if errors:
        raise ValueError("; ".join(errors))
    skinned, attached = scoped_meshes(context, arm, scope, scope_coll)
    if not skinned and not attached:
        raise ValueError("Không có mesh nào của %s trong phạm vi xuất (%s)"
                         % (arm.name, dict((k, n) for k, n, _d in SCOPES)[scope]))
    if which == 'SETS':
        acts = action_sets(arm)
        if not acts:
            raise ValueError("Chưa có bộ action nào được tích (hoặc bộ nào cũng trống)")
        combine = False
    else:
        acts = picked_actions(arm)
        if which == 'NONE':
            acts = []
        elif which == 'ACTIVE':
            cur = arm.animation_data.action if arm.animation_data else None
            acts = [cur] if cur is not None else []
    os.makedirs(folder, exist_ok=True)
    plan = clip_plan(acts, which, combine)

    state = _State(context, arm, skinned + attached)
    if context.object is not None and context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    # bản sao phải mang đúng tên gốc (Unity tìm blendshape theo đường dẫn tên)
    rename = dict(state.names)
    for o in skinned + attached:
        o.name = o.name + "__srp_src"

    coll = bpy.data.collections.new("SRP_UnityExport")
    context.scene.collection.children.link(coll)
    files, lines = [], list(notes) + ["CẢNH BÁO: " + w for w in warns]
    made = []
    try:
        game = build_skeleton(context, arm, hmap, name, coll, turn, only_human)
        made.append(game.data)
        merge = None
        if only_human:
            torso = {hmap[h] for h in TORSO if h in hmap}
            merge = merge_map(arm, {b.name for b in game.data.bones}, torso)
        meshes = prep_meshes(context, arm, game, coll, rename, made, turn, merge,
                             (skinned, attached))
        objs = [game] + meshes
        anim = arm.animation_data or arm.animation_data_create()
        for t in anim.nla_tracks:
            t.mute = True

        base = os.path.join(folder, safe(name) + ".fbx")
        sc = context.scene
        combined = bool(combine and plan and plan[0][0] is None)
        clips = clip_info(plan, which, combine)
        # json ghi TRƯỚC FBX: Unity đang mở mà nạp FBX lúc json chưa có thì vẫn
        # nhận ra (script Unity cũng tự import lại FBX khi json tới sau)
        mapping = {
            'version': 1, 'character': safe(name), 'keep_extra': not only_human,
            'keep_rest_pose': not tpose,
            'combined': combined,
            'fps': sc.render.fps / sc.render.fps_base,
            'human': [{'human': h, 'bone': hmap[h]} for h in HUMAN_ORDER if h in hmap],
            'clips': clips,
            'sets': [f for f, _a in plan] if which == 'SETS' else [],
        }
        js = os.path.join(folder, safe(name) + ".humanoid.json")
        with open(js, 'w', encoding='utf-8') as f:
            json.dump(mapping, f, ensure_ascii=False, indent=1)

        if combined:
            export_combined(context, arm, game, meshes, plan[0][1], base, made)
            files.append(base)
        else:
            # mô hình: rest pose, không animation
            anim.action = None
            follow(game, False)
            write_fbx(context, base, objs, anim=False)
            files.append(base)
            follow(game, True)
        for file, group in ([] if combined else plan):
            p = os.path.join(folder, "%s@%s.fbx" % (safe(name), file))
            if which == 'SETS':
                export_combined(context, arm, game, meshes, group, p, made)
                files.append(p)
                continue
            a = group[0]
            compat.assign_action(arm, a)
            fa, fs = face_action(a)
            for m in meshes:
                set_key_action(m, fa, fs)
            s0, e0 = (int(round(x)) for x in a.frame_range)
            sc.frame_start, sc.frame_end = s0, max(e0, s0 + 1)
            sc.frame_set(s0)
            write_fbx(context, p, objs, anim=True)
            files.append(p)
        sc.frame_set(state.frame[2])
        files.append(js)
        ed = unity_editor_dir(folder)
        files.append(write_unity_script(ed or folder))
        lines.append("%d bone trong khung game, %d bone Humanoid, %d mesh, %d clip%s%s"
                     % (len(game.data.bones), len(hmap), len(meshes), len(clips),
                        " trong %d bộ" % len(plan) if which == 'SETS' else "",
                        " | dồn trọng số %d bone bỏ đi" % len(merge) if merge else ""))
    finally:
        _cleanup(coll, made)
        state.restore(context, arm)
    for ln in lines:
        prefs.log("[Unity] " + ln)
    return files, lines


# ============================================================ UI / operator

def _rig(context):
    st = context.scene.srp_unity
    if st.rig is not None and st.rig.type == 'ARMATURE':
        return st.rig
    ob = context.object
    if ob is not None and ob.type == 'ARMATURE':
        return ob
    if ob is not None and ob.type == 'MESH':
        a = ob.find_armature()
        if a is not None:
            return a
    rig = rigdef.active_rig(context)
    return rig


def default_name(arm):
    return re.sub(r'\.\d{3}$', '', arm.name) if arm else "Character"


class SRP_ActionRef(PropertyGroup):
    action: PointerProperty(type=bpy.types.Action, name="Action")


class SRP_ActionSet(PropertyGroup):
    """Một bộ action (action collection): xuất thành một file <tên>@<bộ>.fbx,
    mỗi action một take. Lưu trên chính rig."""
    name: StringProperty(name="Tên bộ", default="Bo")
    use: BoolProperty(name="Xuất", default=True,
                      description="Tích: bộ này được xuất khi chọn 'Theo bộ action'")
    actions: CollectionProperty(type=SRP_ActionRef)
    index: IntProperty(default=0)


class SRP_UnitySettings(PropertyGroup):
    rig: PointerProperty(type=bpy.types.Object, name="Rig",
                         poll=lambda self, o: o.type == 'ARMATURE')
    folder: StringProperty(name="Thư mục", subtype='DIR_PATH', default="//Unity/",
                           description="Chọn thẳng một thư mục trong Assets/ của "
                                       "project Unity thì script import tự vào "
                                       "Assets/Editor/RigTamHanh")
    name: StringProperty(name="Tên nhân vật", default="",
                         description="Để trống thì lấy theo tên rig")
    which: EnumProperty(
        name="Animation",
        items=(('ALL', "Các clip được tích",
                "Chỉ xuất các clip được tích trong danh sách bên dưới -- mỗi clip ra "
                "một file <tên>@<clip>.fbx (hoặc một take nếu gộp)"),
               ('ACTIVE', "Chỉ action đang gán", ""),
               ('SETS', "Theo bộ action",
                "Mỗi bộ action được tích ra một file <tên>@<bộ>.fbx, trong đó mỗi "
                "action một take (giống action collection)"),
               ('NONE', "Không xuất animation", "Chỉ mô hình + Avatar")),
        default='ALL')
    scope: EnumProperty(name="Mesh xuất", items=SCOPES, default='RIG',
                        description="Xuất những mesh nào của rig. Khung xương luôn đủ")
    scope_coll: PointerProperty(type=bpy.types.Collection, name="Collection",
                                description="Chỉ xuất mesh của rig nằm trong collection này")
    only_human: BoolProperty(
        name="Chỉ xương Humanoid", default=True,
        description="Bật: FBX chỉ có các xương Unity Humanoid cần (Hips làm gốc). "
                    "Trọng số của xương mặt, tai, Palm, đốt sống thừa... dồn sang "
                    "xương Humanoid gần nhất; biểu cảm mặt đi qua blendshape. "
                    "Tắt: xuất mọi xương deform (giữ được animation xương mặt)")
    combine: BoolProperty(
        name="Gộp animation vào file nhân vật", default=False,
        description="Bật: một file <tên>.fbx chứa cả nhân vật lẫn mọi clip "
                    "(mỗi action một take). Tắt: mỗi action một file "
                    "<tên>@<action>.fbx riêng")
    tpose: BoolProperty(
        name="Avatar theo T-pose", default=True,
        description="Như nút Enforce T-Pose của Unity: Avatar lấy tư thế tham "
                    "chiếu là T-pose (tay ngang, ngón thẳng, chân thẳng đứng) "
                    "thay vì tư thế nghỉ trong Blender. Tư thế nghỉ hơi chữ A / "
                    "gối hơi gập mà làm tham chiếu thì animation retarget sang "
                    "lệch một góc cố định. Mô hình không bị đổi dáng")
    face_z: BoolProperty(
        name="Nhìn về +Z trong Unity", default=True,
        description="Xoay bản xuất 180° để nhân vật nhìn đúng transform.forward "
                    "của Unity. Tắt thì nhân vật nhìn -Z (quay lưng với forward)")


class SRP_OT_unity_check(Operator):
    bl_idname = "srp.unity_check"
    bl_label = "Kiểm tra Humanoid"
    bl_description = "Kiểm tra rig có dựng được Avatar Humanoid trong Unity không. Không sửa gì"

    def execute(self, context):
        arm = _rig(context)
        if arm is None:
            self.report({'ERROR'}, "Chưa chọn rig")
            return {'CANCELLED'}
        errors, warns, notes, m = check(arm)
        out = ["KIỂM TRA HUMANOID -- %s" % arm.name, ""]
        out += ["LỖI: " + e for e in errors] or ["Lỗi: không có"]
        out += ["CẢNH BÁO: " + w for w in warns] or ["Cảnh báo: không có"]
        out += [""] + notes + ["", "ÁNH XẠ (sửa trong text block %s):" % MAP_TEXT]
        out += ["  %-26s %s" % (h, m[h]) for h in HUMAN_ORDER if h in m]
        t = bpy.data.texts.get("SRP_Unity_Check") or bpy.data.texts.new("SRP_Unity_Check")
        t.clear()
        t.write("\n".join(out))
        if errors:
            self.report({'ERROR'}, "%d lỗi -- xem text block SRP_Unity_Check" % len(errors))
        else:
            self.report({'WARNING' if warns else 'INFO'},
                        "Dựng được Humanoid: %d bone, %d cảnh báo -- xem SRP_Unity_Check"
                        % (len(m), len(warns)))
        return {'FINISHED'}


class SRP_OT_unity_map_edit(Operator):
    bl_idname = "srp.unity_map_edit"
    bl_label = "Sửa tay bảng ghép xương Humanoid"
    bl_description = ("Ghi bảng ánh xạ hiện tại vào text block %s để sửa tay. "
                      "Dòng 'LeftHand = TênBone'; để trống sau dấu = là bỏ bone đó" % MAP_TEXT)

    def execute(self, context):
        arm = _rig(context)
        if arm is None:
            self.report({'ERROR'}, "Chưa chọn rig")
            return {'CANCELLED'}
        m = humanoid_map(arm)
        t = bpy.data.texts.get(MAP_TEXT) or bpy.data.texts.new(MAP_TEXT)
        t.clear()
        t.write("# Sửa tên bone bên phải dấu =, xoá trống để bỏ. Dòng # là chú thích.\n")
        for h in HUMAN_ORDER:
            t.write("%s = %s\n" % (h, m.get(h, "")))
        self.report({'INFO'}, "Đã ghi %s -- mở ở Text Editor để sửa" % MAP_TEXT)
        return {'FINISHED'}


class SRP_OT_unity_export(Operator):
    bl_idname = "srp.unity_export"
    bl_label = "Xuất FBX cho Unity"
    bl_description = ("Xuất nhân vật + rig + animation thành FBX Humanoid cho Unity, "
                      "kèm bảng ánh xạ và script import. File .blend không bị đổi")
    bl_options = {'REGISTER'}

    def execute(self, context):
        st = context.scene.srp_unity
        arm = _rig(context)
        if arm is None:
            self.report({'ERROR'}, "Chưa chọn rig")
            return {'CANCELLED'}
        folder = bpy.path.abspath(st.folder)
        if not folder or (st.folder.startswith('//') and not bpy.data.filepath):
            self.report({'ERROR'}, "Lưu file .blend trước, hoặc chọn thư mục tuyệt đối")
            return {'CANCELLED'}
        name = st.name.strip() or default_name(arm)
        try:
            files, lines = export(context, arm, folder, name, st.which, st.face_z,
                                  st.combine and st.which not in ('NONE', 'SETS'),
                                  st.only_human, st.tpose, st.scope, st.scope_coll)
        except ValueError as e:
            self.report({'ERROR'}, "Không xuất được: %s" % e)
            return {'CANCELLED'}
        cs = files[-1]
        msg = "Đã xuất %d file vào %s" % (len(files) - 2, folder)
        if unity_editor_dir(folder):
            msg += " | script import đã vào Assets/Editor/RigTamHanh"
        else:
            msg += " | chép %s vào Assets/Editor của project" % os.path.basename(cs)
        self.report({'INFO'}, msg)
        return {'FINISHED'}


class SRP_OT_unity_clips(Operator):
    """Tích / bỏ tích mọi clip của rig trong danh sách xuất"""
    bl_idname = "srp.unity_clips"
    bl_label = "Chọn clip"
    bl_options = {'REGISTER', 'UNDO'}

    value: BoolProperty(default=True)

    def execute(self, context):
        arm = _rig(context)
        if arm is None:
            return {'CANCELLED'}
        for a in rig_actions(arm):
            a.srp_unity_export = self.value
        return {'FINISHED'}


class SRP_UL_action_sets(UIList):
    bl_idname = "SRP_UL_action_sets"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index=0):
        row = layout.row(align=True)
        row.prop(item, "use", text="")
        row.prop(item, "name", text="", emboss=False)
        n = sum(1 for r in item.actions if r.action is not None)
        row.label(text="%d clip" % n)


class SRP_UL_set_actions(UIList):
    bl_idname = "SRP_UL_set_actions"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index=0):
        if item.action is None:
            layout.label(text="(action đã xoá)", icon='ERROR')
            return
        row = layout.row(align=True)
        row.label(text=item.action.name, icon='ACTION')
        f0, f1 = (int(round(x)) for x in item.action.frame_range)
        sub = row.row()
        sub.alignment = 'RIGHT'
        sub.label(text="%d–%d" % (f0, f1))


def _set_items(self, context):
    arm = _rig(context)
    return [(a.name, a.name, "") for a in (rig_actions(arm) if arm else [])] or [("", "(rig chưa có action)", "")]


class SRP_OT_action_set(Operator):
    """Thêm / xoá bộ action, thêm / bỏ action trong bộ"""
    bl_idname = "srp.action_set"
    bl_label = "Bộ action"
    bl_options = {'REGISTER', 'UNDO'}
    bl_property = "pick"

    op: EnumProperty(items=(('ADD_SET', "Thêm bộ", ""), ('DEL_SET', "Xoá bộ", ""),
                            ('ADD', "Thêm action", ""), ('ADD_CHECKED', "Thêm các clip đang tích", ""),
                            ('DEL', "Bỏ action", ""), ('UP', "Lên", ""), ('DOWN', "Xuống", "")))
    pick: EnumProperty(items=_set_items, name="Action")

    @classmethod
    def description(cls, context, props):
        return {'ADD_SET': "Thêm một bộ action mới",
                'DEL_SET': "Xoá bộ đang chọn (action không bị xoá)",
                'ADD': "Thêm một action của rig vào bộ đang chọn",
                'ADD_CHECKED': "Thêm mọi clip đang tích trong danh sách clip vào bộ đang chọn",
                'DEL': "Bỏ action đang chọn ra khỏi bộ (action không bị xoá)",
                'UP': "Đưa action lên trên", 'DOWN': "Đưa action xuống dưới"}[props.op]

    def invoke(self, context, event):
        if self.op == 'ADD':
            context.window_manager.invoke_search_popup(self)
            return {'RUNNING_MODAL'}
        return self.execute(context)

    def execute(self, context):
        arm = _rig(context)
        if arm is None:
            self.report({'ERROR'}, "Chưa chọn rig")
            return {'CANCELLED'}
        sets = arm.srp_action_sets
        if self.op == 'ADD_SET':
            st = sets.add()
            st.name = "Bo_%d" % len(sets)
            arm.srp_action_sets_index = len(sets) - 1
            return {'FINISHED'}
        if not len(sets):
            self.report({'ERROR'}, "Chưa có bộ action nào")
            return {'CANCELLED'}
        i = min(arm.srp_action_sets_index, len(sets) - 1)
        st = sets[i]
        if self.op == 'DEL_SET':
            sets.remove(i)
            arm.srp_action_sets_index = max(0, i - 1)
            return {'FINISHED'}
        have = {r.action for r in st.actions}
        if self.op in ('ADD', 'ADD_CHECKED'):
            new = ([bpy.data.actions.get(self.pick)] if self.op == 'ADD' else picked_actions(arm))
            n = 0
            for a in new:
                if a is not None and a not in have:
                    st.actions.add().action = a
                    have.add(a)
                    n += 1
            st.index = len(st.actions) - 1
            self.report({'INFO'}, "Thêm %d action vào %s" % (n, st.name))
            return {'FINISHED'}
        j = st.index
        if not (0 <= j < len(st.actions)):
            return {'CANCELLED'}
        if self.op == 'DEL':
            st.actions.remove(j)
            st.index = max(0, j - 1)
        elif self.op == 'UP' and j > 0:
            st.actions.move(j, j - 1)
            st.index = j - 1
        elif self.op == 'DOWN' and j < len(st.actions) - 1:
            st.actions.move(j, j + 1)
            st.index = j + 1
        return {'FINISHED'}


def draw_sets(L, arm):
    box = L.box()
    box.label(text="Bộ action của %s -- mỗi bộ một file <tên>@<bộ>.fbx" % arm.name, icon='NLA')
    row = box.row()
    row.template_list("SRP_UL_action_sets", "", arm, "srp_action_sets", arm, "srp_action_sets_index", rows=3)
    col = row.column(align=True)
    col.operator("srp.action_set", text="", icon='ADD').op = 'ADD_SET'
    col.operator("srp.action_set", text="", icon='REMOVE').op = 'DEL_SET'
    sets = arm.srp_action_sets
    if not len(sets):
        return
    st = sets[min(arm.srp_action_sets_index, len(sets) - 1)]
    row = box.row()
    row.template_list("SRP_UL_set_actions", "", st, "actions", st, "index", rows=4)
    col = row.column(align=True)
    col.operator("srp.action_set", text="", icon='ADD').op = 'ADD'
    col.operator("srp.action_set", text="", icon='REMOVE').op = 'DEL'
    col.separator()
    col.operator("srp.action_set", text="", icon='TRIA_UP').op = 'UP'
    col.operator("srp.action_set", text="", icon='TRIA_DOWN').op = 'DOWN'
    box.operator("srp.action_set", text="Thêm các clip đang tích", icon='CHECKBOX_HLT').op = 'ADD_CHECKED'


def draw_clips(L, arm):
    clips = rig_clips(arm)
    box = L.box()
    if not clips:
        box.label(text="Không có clip nào có slot cho %s" % arm.name, icon='INFO')
        return
    n = sum(1 for a, _s in clips if a.srp_unity_export)
    head = box.row(align=True)
    head.label(text="Clip của %s: xuất %d / %d" % (arm.name, n, len(clips)), icon='ACTION')
    head.operator("srp.unity_clips", text="", icon='CHECKBOX_HLT').value = True
    head.operator("srp.unity_clips", text="", icon='CHECKBOX_DEHLT').value = False
    cur = arm.animation_data.action if arm.animation_data else None
    col = box.column(align=True)
    for a, s in clips:
        row = col.row(align=True)
        row.prop(a, "srp_unity_export", text=a.name)
        sub = row.row(align=True)
        sub.alignment = 'RIGHT'
        f0, f1 = (int(round(x)) for x in a.frame_range)
        info = "%d–%d" % (f0, f1)
        if s.name_display != arm.name:
            info += " · slot %s" % s.name_display
        sub.label(text=info, icon='PLAY' if a is cur else 'BLANK1')


def draw_unity(L, context):
    st = context.scene.srp_unity
    arm = _rig(context)
    L.prop(st, "rig")
    if st.rig is None and arm is not None:
        note = L.column(align=True)
        note.scale_y = 0.8
        note.label(text="Để trống → dùng %r" % arm.name, icon='DOT')
    L.prop(st, "folder")
    L.prop(st, "name")
    if not st.name.strip() and arm is not None:
        note = L.column(align=True)
        note.scale_y = 0.8
        note.label(text="Để trống → tên %r" % default_name(arm), icon='DOT')
    L.prop(st, "scope")
    if st.scope == 'COLLECTION':
        L.prop(st, "scope_coll")
    if arm is not None:
        sk, at = scoped_meshes(context, arm, st.scope, st.scope_coll)
        note = L.column(align=True)
        note.scale_y = 0.8
        names = [o.name for o in sk + at]
        note.label(text="%d mesh: %s" % (len(names), ", ".join(names[:4]) + (" …" if len(names) > 4 else "")),
                   icon='DOT' if names else 'ERROR')
    L.prop(st, "only_human")
    L.prop(st, "which", text="")
    if st.which == 'ALL' and arm is not None:
        draw_clips(L, arm)
    if st.which == 'SETS' and arm is not None:
        draw_sets(L, arm)
    row = L.row()
    row.enabled = st.which not in ('NONE', 'SETS')
    row.prop(st, "combine")
    L.prop(st, "face_z")
    L.prop(st, "tpose")
    row = L.row(align=True)
    row.operator("srp.unity_check", icon='VIEWZOOM')
    row.operator("srp.unity_map_edit", text="", icon='TEXT')
    r = L.row()
    r.scale_y = 1.4
    r.enabled = arm is not None
    r.operator("srp.unity_export", icon='EXPORT')


CLASSES = (SRP_ActionRef, SRP_ActionSet, SRP_UnitySettings, SRP_OT_unity_check,
           SRP_OT_unity_map_edit, SRP_OT_unity_export, SRP_OT_unity_clips,
           SRP_UL_action_sets, SRP_UL_set_actions, SRP_OT_action_set)


def register_extra():
    bpy.types.Scene.srp_unity = PointerProperty(type=SRP_UnitySettings)
    bpy.types.Object.srp_action_sets = CollectionProperty(type=SRP_ActionSet)
    bpy.types.Object.srp_action_sets_index = IntProperty(default=0)
    # Lưu trên chính action: mở lại file vẫn nhớ clip nào bỏ ra
    bpy.types.Action.srp_unity_export = BoolProperty(
        name="Xuất sang Unity", default=True,
        description="Tích: clip này được xuất khi chọn 'Các clip được tích'")


def unregister_extra():
    for owner, attr in ((bpy.types.Scene, "srp_unity"), (bpy.types.Action, "srp_unity_export"),
                        (bpy.types.Object, "srp_action_sets"), (bpy.types.Object, "srp_action_sets_index")):
        try:
            delattr(owner, attr)
        except AttributeError:
            pass


# ============================================================ script Unity

UNITY_CS = r'''// Sinh bởi Rig Tẩm Hành (Blender). Đặt trong một thư mục Editor của project.
//
// Mỗi file FBX có file <tên>.humanoid.json nằm cạnh được import thành Humanoid
// với đúng bảng ánh xạ bone trong json -- không dùng auto-map.
//   <tên>.fbx          -> mô hình, tự dựng Avatar
//   <tên>@<clip>.fbx   -> một animation, dùng lại Avatar của <tên>.fbx
//   <tên>@<bộ>.fbx     -> một bộ action: mỗi action một take
//
// Avatar dựng SAU khi Unity import xong cả đợt (OnPostprocessAllAssets), từ
// chính mô hình vừa import, rồi import lại FBX đó một lần. Nhờ vậy:
// - json tới sau FBX (Blender đang ghi dở, chép từng file) vẫn được xử lý:
//   json tới là FBX cùng nhóm được import lại;
// - file animation đợi mô hình dựng xong Avatar rồi mới chép Avatar đó, không
//   tự dựng Avatar từ frame đầu của clip;
// - không phụ thuộc thứ tự import.
// Avatar không hợp lệ thì Console báo lỗi. Làm lại tay: chọn FBX, menu
// Assets > Rig Tẩm Hành > Dựng lại Avatar Humanoid.
//
// Avatar dựng từ T-POSE (như nút Enforce T-Pose của Unity): tay ngang, cẳng
// tay, bàn tay và bốn ngón thẳng theo tay, chân thẳng đứng. Mô hình không bị
// đổi dáng: chỉ tư thế tham chiếu của Avatar. Json có "keep_rest_pose": true
// thì bỏ qua.
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;

public class RigTamHanhHumanoidImporter : AssetPostprocessor
{
    // v3: dựng Avatar sau khi import xong cả đợt -- file import bằng bản cũ tự dựng lại.
    const string Marker = "RigTamHanhHumanoid:v3:";
    public override uint GetVersion() { return 3; }

    [System.Serializable] public class Pair { public string human; public string bone; }
    [System.Serializable] public class Clip { public string name; public bool loop; public int first; public int last; public bool face; public int start; public string file; }
    [System.Serializable] public class Map
    {
        public int version; public string character; public bool keep_extra; public bool combined; public float fps;
        public bool keep_rest_pose;
        public Pair[] human; public Clip[] clips; public string[] sets;
    }

    // ------------------------------------------------------------ tiện ích

    static bool IsFbx(string p) { return p != null && p.ToLower().EndsWith(".fbx"); }

    static string JsonFor(string assetPath, out string baseFbx, out string clip)
    {
        string dir = Path.GetDirectoryName(assetPath).Replace('\\', '/');
        string file = Path.GetFileNameWithoutExtension(assetPath);
        string ch = file;
        clip = null;
        int at = file.IndexOf('@');
        if (at > 0) { ch = file.Substring(0, at); clip = file.Substring(at + 1); }
        baseFbx = dir + "/" + ch + ".fbx";
        return dir + "/" + ch + ".humanoid.json";
    }

    static Map Load(string path)
    {
        try { return File.Exists(path) ? JsonUtility.FromJson<Map>(File.ReadAllText(path)) : null; }
        catch (System.Exception e) { Debug.LogError("[RigTamHanh] Không đọc được " + path + ": " + e.Message); return null; }
    }

    static string Stamp(string json)
    {
        return Marker + File.GetLastWriteTimeUtc(json).Ticks;
    }

    // Script import Humanoid khác (bản cũ còn sót) cùng xử lý FBX thì hai bên
    // ghi đè Avatar của nhau: FBX ra Generic hoặc mất T-pose. Có thì dừng, hỏi xoá.
    static string OtherImporter()
    {
        var other = TypeCache.GetTypesDerivedFrom<AssetPostprocessor>()
            .FirstOrDefault(t => t != typeof(RigTamHanhHumanoidImporter) && t.Name.EndsWith("HumanoidImporter"));
        return other == null ? null : other.Name;
    }

    static void WarnOther(string other, string assetPath)
    {
        string path = AssetDatabase.FindAssets(other + " t:MonoScript").Select(AssetDatabase.GUIDToAssetPath)
            .FirstOrDefault(p => Path.GetFileNameWithoutExtension(p) == other);
        Debug.LogError("[RigTamHanh] Project còn script " + other + (path != null ? " (" + path + ")" : "")
            + " cũng dựng Avatar Humanoid -- " + assetPath + " chưa được xử lý. Xoá script đó rồi chọn FBX, "
            + "Assets > Rig Tẩm Hành > Dựng lại Avatar Humanoid.");
        if (path == null || Application.isBatchMode || SessionState.GetBool("RigTamHanh.AskedOther", false)) return;
        SessionState.SetBool("RigTamHanh.AskedOther", true);
        EditorApplication.delayCall += () =>
        {
            if (EditorUtility.DisplayDialog("Rig Tẩm Hành",
                    "Project còn script import Humanoid khác:\n" + path +
                    "\n\nHai script cùng dựng Avatar sẽ ghi đè nhau (FBX ra Generic, T-pose sai). Xoá script này?",
                    "Xoá", "Để nguyên"))
                AssetDatabase.DeleteAsset(path);
        };
    }

    static void Align(Transform bone, Transform child, Vector3 dir)
    {
        if (bone == null || child == null) return;
        Vector3 cur = child.position - bone.position;
        if (cur.sqrMagnitude < 1e-12f) return;
        bone.rotation = Quaternion.FromToRotation(cur, dir) * bone.rotation;
    }

    // Đưa cây transform về T-pose: chỉ xoay quanh đầu xương, theo thứ tự cha
    // trước con, nên chiều dài xương và mọi thứ khác giữ nguyên.
    static void EnforceTPose(Dictionary<string, Transform> H)
    {
        System.Func<string, Transform> T = n => H.TryGetValue(n, out var t) ? t : null;
        Transform lu = T("LeftUpperArm"), ru = T("RightUpperArm");
        Vector3 right = (lu != null && ru != null) ? ru.position - lu.position : Vector3.right;
        right.y = 0f;
        right = right.sqrMagnitude > 1e-8f ? right.normalized : Vector3.right;
        foreach (var side in new[] { "Left", "Right" })
        {
            Vector3 dir = side == "Left" ? -right : right;
            Align(T(side + "UpperArm"), T(side + "LowerArm"), dir);
            Align(T(side + "LowerArm"), T(side + "Hand"), dir);
            Align(T(side + "Hand"), T(side + " Middle Proximal") ?? T(side + " Index Proximal"), dir);
            foreach (var f in new[] { "Index", "Middle", "Ring", "Little" })
            {
                Align(T(side + " " + f + " Proximal"), T(side + " " + f + " Intermediate"), dir);
                Align(T(side + " " + f + " Intermediate"), T(side + " " + f + " Distal"), dir);
            }
            Align(T(side + "UpperLeg"), T(side + "LowerLeg"), Vector3.down);
            Align(T(side + "LowerLeg"), T(side + "Foot"), Vector3.down);
        }
    }

    // HumanDescription từ chính mô hình đã import (bản sao tạm, không đụng asset).
    static bool Describe(string fbx, Map map, out HumanDescription desc)
    {
        desc = new HumanDescription();
        var model = AssetDatabase.LoadAssetAtPath<GameObject>(fbx);
        if (model == null) { Debug.LogError("[RigTamHanh] " + fbx + ": chưa nạp được mô hình"); return false; }
        var go = Object.Instantiate(model);
        go.name = model.name;
        go.hideFlags = HideFlags.HideAndDontSave;
        try
        {
            var all = go.GetComponentsInChildren<Transform>(true);
            // trùng tên (mesh tên giống bone): ưu tiên transform không có Renderer
            var byName = new Dictionary<string, Transform>();
            foreach (var t in all)
                if (!byName.TryGetValue(t.name, out var old) || old.GetComponent<Renderer>() != null)
                    byName[t.name] = t;
            var dup = all.Where(t => t.GetComponent<Renderer>() == null).GroupBy(t => t.name)
                         .Where(x => x.Count() > 1).Select(x => x.Key).ToList();
            if (dup.Count > 0)
            {
                Debug.LogError("[RigTamHanh] " + fbx + ": nhiều transform trùng tên (" + string.Join(", ", dup)
                    + ") -- Avatar sẽ khớp nhầm, T-pose sai. Xuất lại bằng Rig Tẩm Hành 1.30 trở lên "
                    + "(node armature tên <tên>_Armature, không trùng tên file).");
                return false;
            }
            var human = new List<HumanBone>();
            var H = new Dictionary<string, Transform>();
            foreach (var p in map.human)
            {
                if (!byName.TryGetValue(p.bone, out var t)) { Debug.LogError("[RigTamHanh] " + fbx + ": không có bone " + p.bone + " cho " + p.human); continue; }
                var hb = new HumanBone { humanName = p.human, boneName = p.bone };
                hb.limit.useDefaultValues = true;
                human.Add(hb);
                H[p.human] = t;
            }
            if (!map.keep_rest_pose) EnforceTPose(H);
            var skeleton = all.Select(t => new SkeletonBone
            {
                name = t.name, position = t.localPosition, rotation = t.localRotation, scale = t.localScale
            }).ToArray();
            desc = new HumanDescription
            {
                human = human.ToArray(), skeleton = skeleton,
                upperArmTwist = .5f, lowerArmTwist = .5f, upperLegTwist = .5f, lowerLegTwist = .5f,
                armStretch = .05f, legStretch = .05f, feetSpacing = 0f, hasTranslationDoF = false,
            };
            return true;
        }
        finally { Object.DestroyImmediate(go); }
    }

    static void SetupClips(ModelImporter mi, Map map, string fbx, string clip, bool isSet)
    {
        var model = AssetDatabase.LoadAssetAtPath<GameObject>(fbx);
        var paths = model == null ? new List<string>() : model.GetComponentsInChildren<Transform>(true)
            .Where(t => t != model.transform)
            .Select(t => AnimationUtility.CalculateTransformPath(t, model.transform)).ToList();
        var clips = mi.defaultClipAnimations;
        foreach (var c in clips)
        {
            // take nhiều clip: tên "<armature>|<action>", lấy phần sau '|'
            string take = c.takeName.Substring(c.takeName.LastIndexOf('|') + 1);
            c.name = (clip != null && !isSet) ? clip : take;
            var info = map.clips == null ? null : map.clips.FirstOrDefault(x => x.name == c.name && (!isSet || x.file == clip))
                       ?? map.clips.FirstOrDefault(x => x.name == c.name);
            c.loopTime = info != null && info.loop;
            if (map.keep_extra)
            {
                // Humanoid chỉ giữ đường cong của bone Humanoid; mask này giữ
                // luôn bone mặt / tai / Palm.
                var mask = new AvatarMask();
                mask.transformCount = paths.Count;
                for (int i = 0; i < paths.Count; i++)
                {
                    mask.SetTransformPath(i, paths[i]);
                    mask.SetTransformActive(i, true);
                }
                c.maskType = ClipAnimationMaskType.CreateFromThisModel;
                c.ConfigureClipFromMask(mask);
            }
        }
        mi.clipAnimations = clips;
    }

    static void Reimport(ModelImporter mi, bool anim)
    {
        mi.bakeAxisConversion = true;
        mi.importBlendShapes = true;
        mi.importAnimation = anim;
        mi.SaveAndReimport();
    }

    static Avatar BaseAvatar(string baseFbx, string stamp)
    {
        var bi = AssetImporter.GetAtPath(baseFbx) as ModelImporter;
        if (bi == null || bi.userData != stamp) return null;
        return AssetDatabase.LoadAllAssetsAtPath(baseFbx).OfType<Avatar>().FirstOrDefault(a => a.isHuman && a.isValid);
    }

    // ------------------------------------------------------------ import

    // Không giữ trạng thái gì từ OnPreprocessModel / OnPostprocessModel: khi
    // Unity import song song (AssetImportWorker), hai hàm đó chạy ở TIẾN TRÌNH
    // KHÁC -- biến tĩnh, delayCall đặt ở đó không về tới editor chính (bản v2
    // dựa vào delayCall trong OnPostprocessModel nên có lúc FBX ra Generic).
    static readonly HashSet<string> pending = new HashSet<string>();
    static bool scheduled;

    void OnPreprocessModel()
    {
        if (!IsFbx(assetPath)) return;
        string json = JsonFor(assetPath, out _, out string clip);
        Map map = Load(json);
        if (map == null) return;
        var imp = (ModelImporter)assetImporter;
        imp.bakeAxisConversion = true;
        imp.importBlendShapes = true;
        imp.importAnimation = clip != null || map.combined;
    }

    static void OnPostprocessAllAssets(string[] imported, string[] deleted, string[] moved, string[] movedFrom)
    {
        foreach (var p in imported.Concat(moved))
        {
            if (p.ToLower().EndsWith(".humanoid.json"))
            {
                string dir = Path.GetDirectoryName(p).Replace('\\', '/');
                string file = Path.GetFileName(p);
                string ch = file.Substring(0, file.Length - ".humanoid.json".Length);
                if (File.Exists(dir + "/" + ch + ".fbx")) pending.Add(dir + "/" + ch + ".fbx");
                foreach (var f in Directory.GetFiles(dir, ch + "@*.fbx")) pending.Add(f.Replace('\\', '/'));
            }
            else if (IsFbx(p) && File.Exists(JsonFor(p, out _, out _)))
                pending.Add(p);
        }
        if (pending.Count > 0 && !scheduled)
        {
            scheduled = true;
            EditorApplication.delayCall += Flush;
        }
    }

    static void Flush()
    {
        scheduled = false;
        var list = pending.ToList();
        pending.Clear();
        // mô hình trước, animation sau
        foreach (var p in list.OrderBy(p => Path.GetFileName(p).Contains("@") ? 1 : 0))
        {
            try { Process(p); }
            catch (System.Exception e) { Debug.LogException(e); }
        }
    }

    static void Process(string fbx)
    {
        string json = JsonFor(fbx, out string baseFbx, out string clip);
        Map map = Load(json);
        var mi = AssetImporter.GetAtPath(fbx) as ModelImporter;
        if (map == null || mi == null) return;
        string stamp = Stamp(json);
        bool anim = clip != null || map.combined;
        bool isSet = clip != null && map.sets != null && map.sets.Contains(clip);
        bool human = mi.animationType == ModelImporterAnimationType.Human;

        if (clip == null)
        {
            if (mi.userData == stamp && human) { Check(fbx); ShareAvatar(fbx, json); return; }
        }
        else
        {
            Avatar src0 = BaseAvatar(baseFbx, stamp);
            if (mi.userData == stamp && human && (src0 == null || mi.sourceAvatar == src0)) return;
            // mô hình còn đang dựng Avatar: đợi, ShareAvatar sẽ gọi lại
            if (src0 == null && File.Exists(baseFbx)) return;
        }
        string other = OtherImporter();
        if (other != null) { WarnOther(other, fbx); return; }
        // thiết lập trục / blendshape / animation chưa lưu (json tới sau, hoặc
        // mới chỉ đặt tạm trong OnPreprocessModel): lưu và import lại rồi mới dựng
        if (!mi.bakeAxisConversion || !mi.importBlendShapes || mi.importAnimation != anim) { Reimport(mi, anim); return; }

        Avatar src = clip == null ? null : BaseAvatar(baseFbx, stamp);
        mi.animationType = ModelImporterAnimationType.Human;
        if (src != null)
        {
            mi.avatarSetup = ModelImporterAvatarSetup.CopyFromOther;
            mi.sourceAvatar = src;
        }
        else
        {
            if (!Describe(fbx, map, out var desc)) return;
            mi.avatarSetup = ModelImporterAvatarSetup.CreateFromThisModel;
            mi.humanDescription = desc;
        }
        if (anim) SetupClips(mi, map, fbx, clip, isSet);
        mi.bakeAxisConversion = true;
        mi.importBlendShapes = true;
        mi.importAnimation = anim;
        mi.userData = stamp;
        mi.SaveAndReimport();
    }

    static void Check(string fbx)
    {
        var av = AssetDatabase.LoadAllAssetsAtPath(fbx).OfType<Avatar>().FirstOrDefault();
        if (av == null || !av.isHuman || !av.isValid)
            Debug.LogError("[RigTamHanh] " + fbx + ": Avatar Humanoid KHÔNG hợp lệ -- xem cảnh báo của Avatar trong Inspector, "
                + "sửa rồi chọn FBX, Assets > Rig Tẩm Hành > Dựng lại Avatar Humanoid.");
    }

    // Mô hình dựng xong Avatar: các file animation cùng nhóm chép Avatar đó.
    static void ShareAvatar(string baseFbx, string json)
    {
        string dir = Path.GetDirectoryName(baseFbx).Replace('\\', '/');
        string ch = Path.GetFileNameWithoutExtension(baseFbx);
        foreach (var f in Directory.GetFiles(dir, ch + "@*.fbx"))
            Process(f.Replace('\\', '/'));
    }

    [MenuItem("Assets/Rig Tẩm Hành/Dựng lại Avatar Humanoid")]
    static void Rebuild()
    {
        var picked = Selection.objects.Select(AssetDatabase.GetAssetPath).Where(IsFbx).ToList();
        foreach (var p in picked.OrderBy(p => Path.GetFileName(p).Contains("@") ? 1 : 0))
        {
            string json = JsonFor(p, out _, out string clip);
            Map map = Load(json);
            var mi = AssetImporter.GetAtPath(p) as ModelImporter;
            if (map == null || mi == null)
            {
                Debug.LogWarning("[RigTamHanh] " + p + ": không có " + json + " nằm cạnh");
                continue;
            }
            mi.userData = "";
            Reimport(mi, clip != null || map.combined);
        }
    }

    [MenuItem("Assets/Rig Tẩm Hành/Dựng lại Avatar Humanoid", true)]
    static bool RebuildValid()
    {
        return Selection.objects.Any(o => IsFbx(AssetDatabase.GetAssetPath(o)));
    }
}
'''
