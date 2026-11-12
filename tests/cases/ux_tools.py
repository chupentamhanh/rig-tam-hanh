"""Nút gộp và thanh "Bước tiếp theo". Fixture adult_final.blend."""
import bpy
import addon_utils
from mathutils import Vector

addon_utils.enable("rig_tam_hanh", default_set=False)
from rig_tam_hanh import cloth, ux, posekey, generate, face

ctx = bpy.context
rig = bpy.data.objects["Adult_Rig"]; body = bpy.data.objects["Adult_body"]
brow = bpy.data.objects["Adult_eyebrow"]
st = ctx.scene.srp_generate
results = []


def rep(name, ok, detail=""):
    results.append(ok)
    print("[%s] %s %s" % ("ĐẠT" if ok else "HỎNG", name, detail))


def rows(o):
    return cloth._rows_of(o, exact=True)


def select_rig():
    if ctx.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for o in list(ctx.selected_objects):
        o.select_set(False)
    ctx.view_layer.objects.active = rig
    rig.select_set(True)


marks = cloth.hand_painted(body)
# ---- Sửa weight…: một toán tử, bốn việc
select_rig()
b0 = rows(body)
r = bpy.ops.srp.weights_fix(task='LEGS')
rep("Sửa weight… / hông và gối chạy xong", r == {'FINISHED'})
b1 = rows(body)
rep("vertex vẽ tay giữ nguyên", all(b0[i] == b1[i] for i in marks), "%d vertex" % len(marks))
r = bpy.ops.srp.weights_fix(task='FILL')
rep("Sửa weight… / lấp chỗ thiếu chạy xong", r == {'FINISHED'})

# ---- Cập nhật quần áo: bind món mới, thân không đổi khi tắt "sửa da"
bpy.ops.mesh.primitive_cube_add(size=0.05, location=rig.matrix_world @ rig.data.bones["Head"].head_local + Vector((0, -0.12, 0.05)))
badge = ctx.active_object; badge.name = "Test_Badge"
e = st.cloth_meshes.add(); e.mesh, e.mode = badge, 'TRANSFER'
st.skin_follow = False
select_rig()
b0 = rows(body)
r = bpy.ops.srp.cloth_update()
rep("Cập nhật quần áo chạy xong", r == {'FINISHED'})
rep("món mới được bind", cloth.deformed_by(badge, rig))
rep("tắt 'sửa da' -> thân không đổi", rows(body) == b0)
rep("quần áo đủ weight", all(cloth.count_low(x.mesh, rig) == 0 for x in st.cloth_meshes
                              if x.mesh is not None and x.mode == 'TRANSFER'))
st.skin_follow = True
b0 = rows(body)
r = bpy.ops.srp.cloth_update()
b1 = rows(body)
changed = [i for i in range(len(b0)) if b0[i] != b1[i]]
rep("bật 'sửa da' -> da dưới áo đổi, vertex vẽ tay giữ", r == {'FINISHED'} and changed
    and all(b0[i] == b1[i] for i in marks), "%d vertex đổi" % len(changed))
rep("không còn báo quần áo chưa cập nhật", not cloth.sync_stale(body))

# ---- Thanh "Bước tiếp theo"
body[cloth.STAMP_KEY] = body.get(cloth.STAMP_KEY, 0) + 1
nxt = ux.next_step(ctx)
rep("thân sửa weight -> gợi ý cập nhật quần áo", nxt is not None and nxt[2] == "srp.cloth_update", str(nxt and nxt[0]))
body[cloth.SYNC_KEY] = body[cloth.STAMP_KEY]

# ---- Pose -> Shape key: lông mày rời tự bám da
bpy.ops.object.mode_set(mode='POSE') if ctx.mode != 'POSE' else None
P = rig.pose.bones
brows = [pb.name for pb in P if pb.name.startswith("Eyebrow")]
for n in brows:
    P[n].location = Vector((0, 0, 0.004))
ctx.view_layer.update()
for pb in P:
    pb.select = pb.name in brows
r = bpy.ops.face_shapes.pose_to_key(mode='NEW', key_name="UX_Brow", follow_skin=True)
rep("Pose -> Shape key chạy xong", r == {'FINISHED'})
rep("lông mày có key mới", "UX_Brow" in brow.data.shape_keys.key_blocks)
rep("lông mày không còn bị báo chưa bám da", not ux.follow_stale(ctx, body))
rep("hộp xác nhận có trên các nút ghi đè",
    all(hasattr(c, "invoke") for c in (generate.SRP_OT_bind, face.FACESHAPES_OT_build,
                                        ux.SRP_OT_weights_fix, ux.SRP_OT_cloth_update)))
print("TỔNG %d/%d" % (sum(results), len(results)))
