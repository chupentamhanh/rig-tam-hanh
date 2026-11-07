"""Pose -> Shape key, "chỉ xương đang chọn": tách key trái / phải. Fixture kid_facekeys.blend."""
import bpy
import addon_utils
from mathutils import Matrix, Vector

addon_utils.enable("rig_tam_hanh", default_set=False)
from rig_tam_hanh import posekey

ctx = bpy.context
arm = bpy.data.objects["Kid_Rig.001"]
results = []


def rep(name, ok, detail=""):
    results.append(ok)
    print("[%s] %s %s" % ("ĐẠT" if ok else "HỎNG", name, detail))


for o in list(ctx.selected_objects):
    o.select_set(False)
ctx.view_layer.objects.active = arm
arm.select_set(True)
bpy.ops.object.mode_set(mode='POSE')
_a, mesh = posekey.rig_and_mesh(ctx)
P = arm.pose.bones
L = [pb.name for pb in P if pb.name.startswith("Eyebrow") and pb.name.split(".")[1:2] == ["L"]]
R = [pb.name for pb in P if pb.name.startswith("Eyebrow") and pb.name.split(".")[1:2] == ["R"]]
rep("có xương mày hai bên", bool(L) and bool(R), "L %d R %d" % (len(L), len(R)))


def pose_all():
    for n in L + R:
        P[n].location = Vector((0.0, 0.0, 0.006))
        P[n].rotation_mode = 'XYZ'
        P[n].rotation_euler = (0.15, 0.0, 0.0)
    ctx.view_layer.update()


def select(names):
    for pb in P:
        pb.select = pb.name in names


def delta(name):
    kbs = mesh.data.shape_keys.key_blocks
    return [kbs[name].data[i].co - kbs["Basis"].data[i].co for i in range(len(kbs["Basis"].data))]


# vertex do xương mày mỗi bên kéo (có weight > 0) -- key một bên chỉ được
# làm động vùng của bên đó
gi = {g.index: g.name for g in mesh.vertex_groups}
def reach(names):
    return {v.index for v in mesh.data.vertices if any(gi[g.group] in names and g.weight > 0 for g in v.groups)}
inL, inR = reach(set(L)), reach(set(R))
left, right = sorted(inL), sorted(set(range(len(mesh.data.vertices))) - inL)
right_r, left_r = sorted(inR), sorted(set(range(len(mesh.data.vertices))) - inR)
MM = mesh.matrix_world.to_scale().x * 1000.0         # đơn vị mesh -> mm thật

pose_all()
select([])
try:
    r = bpy.ops.face_shapes.pose_to_key(mode='NEW', key_name="X_none", selected_only=True)
    err = ""
except RuntimeError as e:           # toán tử báo ERROR -> ngoại lệ khi gọi từ script
    r, err = {'CANCELLED'}, str(e)
rep("không chọn xương nào -> báo lỗi", r == {'CANCELLED'} and "X_none" not in mesh.data.shape_keys.key_blocks, err)

select(L)
r = bpy.ops.face_shapes.pose_to_key(mode='NEW', key_name="Brow_L", selected_only=True)
rep("nướng bên trái chạy xong", r == {'FINISHED'})
dl = delta("Brow_L")
mL = max(dl[i].length for i in left); mR = max(dl[i].length for i in right)
rep("Brow_L chỉ động vùng xương mày trái", mL * MM > 0.5 and mR * MM < 1e-3,
    "vùng trái %.2f mm, ngoài vùng %.5f mm" % (mL * MM, mR * MM))
rep("xương trái về rest, xương phải giữ pose",
    all(P[n].matrix_basis == Matrix() for n in L) and all(P[n].matrix_basis != Matrix() for n in R))

select(R)
r = bpy.ops.face_shapes.pose_to_key(mode='NEW', key_name="Brow_R", selected_only=True)
dr = delta("Brow_R")
mR = max(dr[i].length for i in right_r); mL = max(dr[i].length for i in left_r)
rep("Brow_R chỉ động vùng xương mày phải", r == {'FINISHED'} and mR * MM > 0.5 and mL * MM < 1e-3,
    "vùng phải %.2f mm, ngoài vùng %.5f mm" % (mR * MM, mL * MM))

pose_all()
select(L + R)
r = bpy.ops.face_shapes.pose_to_key(mode='NEW', key_name="Brow_Both", selected_only=False)
db = delta("Brow_Both")
err = max((db[i] - dl[i] - dr[i]).length for i in range(len(db)))
rep("Brow_L + Brow_R = nướng cả hai bên", err * MM < 1e-3, "lệch %.5f mm" % (err * MM))

pose_all()
select(L)
r = bpy.ops.face_shapes.pose_to_key(mode='NEW', key_name="Brow_All_Off", selected_only=False)
da = delta("Brow_All_Off")
err = max((da[i] - db[i]).length for i in range(len(db)))
rep("tắt tuỳ chọn -> vẫn lấy mọi xương đang pose (như trước)", err * MM < 1e-3, "lệch %.5f mm" % (err * MM))

print("TỔNG %d/%d" % (sum(results), len(results)))
