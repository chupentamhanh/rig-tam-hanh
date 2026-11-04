"""Kiểm tra tổng thể addon trên bản sao file Kid (factory startup)."""
import bpy, math, sys, traceback
import addon_utils
from mathutils import Matrix, Euler

ok = []
def rep(name, passed, detail=""):
    ok.append((name, passed))
    print("[%s] %s %s" % ("ĐẠT" if passed else "HỎNG", name, detail))

def safe_op(op, *a, **k):
    try:
        return op(*a, **k)
    except Exception as e:
        return "EXC " + str(e)[:120]

# --- A. bật/tắt addon nhiều vòng
try:
    for i in range(3):
        addon_utils.enable("rig_tam_hanh", default_set=False)
        addon_utils.disable("rig_tam_hanh")
    addon_utils.enable("rig_tam_hanh", default_set=False)
    import rig_tam_hanh as SRP
    rep("bật/tắt addon 3 vòng", True, "v%s, %d class" % (SRP.bl_info["version"], len(SRP._CLASSES)))
except Exception:
    traceback.print_exc()
    rep("bật/tắt addon 3 vòng", False)
    raise SystemExit(1)
from rig_tam_hanh import build, rigdef, compat, health, unityexport, uikit, facerig

ctx = bpy.context
rig = bpy.data.objects["Kid_Rig.001"]
body = bpy.data.objects["body"]
ctx.view_layer.objects.active = rig
for o in ctx.selected_objects:
    o.select_set(False)
rig.select_set(True)

# --- B. khám rig + kiểm tra hệ FK/IK
r = safe_op(bpy.ops.srp.quick_scan)
rep("quét nhanh", r == {'FINISHED'}, "rig hỏng: %s" % health.broken_rigs())
r = safe_op(bpy.ops.srp.health)
t = bpy.data.texts.get(health.TEXT_NAME)
body_txt = t.as_string() if t else ""
errs, warns = body_txt.count("[LOI ]"), body_txt.count("[canh]")
rep("khám rig đầy đủ", r == {'FINISHED'} and errs == 0, "%d lỗi, %d cảnh báo" % (errs, warns))
if errs or warns:
    for line in body_txt.splitlines():
        if "[LOI ]" in line or "[canh]" in line:
            print("    ", line[:150])
v = build.verify_switching(ctx, rig)
rep("công tắc FK/IK của mọi chi", not v, v or "")

# --- C. snap IK <-> FK: pose một bên, snap bên kia, gạt công tắc, bàn tay/chân không được nhảy
bpy.ops.object.mode_set(mode='POSE')
P = rig.pose.bones
prop = P[rigdef.PROP_BONE]
def hand_world(name):
    ctx.view_layer.update()
    return (rig.matrix_world @ P[name].matrix).copy()
def setsw(limb, v):
    prop[limb.prop] = v
    compat.refresh(ctx, rig)
for limb in rigdef.limbs_for(rig):
    end = limb.deform[-1]
    saved = {pb.name: pb.matrix_basis.copy() for pb in P}
    # pose FK, snap IK theo FK, gạt sang IK
    setsw(limb, rigdef.FK_VALUE)
    for n in limb.fk[:2]:
        P[n].rotation_mode = 'XYZ'
        P[n].rotation_euler = Euler((math.radians(25), math.radians(10), math.radians(35)))
    before = hand_world(end)
    safe_op(bpy.ops.srp.snap, direction='TO_IK', scope='ONE', limb_name=limb.name)
    setsw(limb, rigdef.IK_VALUE)
    after = hand_world(end)
    d1 = (after.translation - before.translation).length * 1000
    a1 = math.degrees(before.to_quaternion().rotation_difference(after.to_quaternion()).angle)
    # ngược lại: snap FK theo IK, gạt về FK
    before = hand_world(end)
    safe_op(bpy.ops.srp.snap, direction='TO_FK', scope='ONE', limb_name=limb.name)
    setsw(limb, rigdef.FK_VALUE)
    after = hand_world(end)
    d2 = (after.translation - before.translation).length * 1000
    a2 = math.degrees(before.to_quaternion().rotation_difference(after.to_quaternion()).angle)
    rep("snap %s" % limb.label, max(d1, d2) < 1.0 and max(a1, a2) < 1.0,
        "FK→IK lệch %.3f mm %.2f° | IK→FK lệch %.3f mm %.2f°" % (d1, a1, d2, a2))
    for n, m in saved.items():
        P[n].matrix_basis = m
    setsw(limb, limb.default_switch if hasattr(limb, 'default_switch') else rigdef.FK_VALUE)

# --- D. lật pose: xoay BicepFK.L, lật, BicepFK.R phải là ảnh gương
for pb in P:
    pb.select = False
P["BicepFK.L"].rotation_mode = 'XYZ'
P["BicepFK.L"].rotation_euler = Euler((0.3, 0.2, 0.5))
P["BicepFK.L"].select = True
ctx.view_layer.update()
r = safe_op(bpy.ops.srp.mirror_pose)
ctx.view_layer.update()
ml = rig.matrix_world @ P["BicepFK.L"].matrix
mr = rig.matrix_world @ P["BicepFK.R"].matrix
flip = Matrix.Diagonal((-1, 1, 1, 1))
dirl = (ml.to_3x3() @ __import__('mathutils').Vector((0, 1, 0)))
dirr = (mr.to_3x3() @ __import__('mathutils').Vector((0, 1, 0)))
dirl.x = -dirl.x
rep("lật pose", r == {'FINISHED'} and dirl.angle(dirr) < math.radians(0.5),
    "%s, lệch hướng %.3f°" % (r, math.degrees(dirl.angle(dirr))))
r = safe_op(bpy.ops.srp.reset, whole_rig=True)
ident = all(pb.matrix_basis == Matrix() for pb in P if not pb.name.startswith(("Pole", "ElbowPole")))
rep("reset cả rig", r == {'FINISHED'} and ident, str(r))

# --- E. mặt + Unity
bpy.ops.object.mode_set(mode='OBJECT')
st = ctx.scene.face_shapes
st.face, st.rig = body, rig
r = safe_op(bpy.ops.face_shapes.qc)
qc = bpy.data.texts["FaceShapes_QC"].as_string() if "FaceShapes_QC" in bpy.data.texts else ""
rep("kiểm định shape key", r == {'FINISHED'}, qc.split("CẢNH BÁO")[-1].strip()[:120].replace("\n", " | "))
r = safe_op(bpy.ops.face_shapes.test_expr, expr="Vui")
rep("thử biểu cảm", r == {'FINISHED'})
e, w, n, m = unityexport.check(rig)
rep("kiểm tra Humanoid", not e, "%d bone, lỗi %s, cảnh báo %s" % (len(m), e, w))
# operator nào cũng phải poll được mà không nổ
bad = []
for mod in (bpy.ops.srp, bpy.ops.face_shapes):
    for name in dir(mod):
        try:
            getattr(mod, name).poll()
        except Exception as ex:
            bad.append((name, str(ex)[:60]))
rep("poll mọi operator", not bad, str(bad))
uikit._state['zone'] = None
rep("chọn khu tự động", uikit.zone(ctx) in {z for z, *_ in uikit.ZONES}, uikit.zone(ctx))

print("\nTỔNG: %d/%d đạt" % (sum(p for _n, p in ok), len(ok)))
