"""Weight tools on the finished Adult (fixture adult_final.blend: body has hand-painted marks).
Checks: hand-paint guard (hip_weights / cloth_bind), paint-session tracking, sync from body,
Delta Mush bake. argv: -- outdir"""
import bpy, sys
import addon_utils

addon_utils.enable("rig_tam_hanh", default_set=False)
from rig_tam_hanh import cloth

ctx = bpy.context
rig = bpy.data.objects["Adult_Rig"]
body = bpy.data.objects["Adult_body"]
sweater = bpy.data.objects["Adult_SWEATER"]
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
rep("fixture có vertex vẽ tay", len(marks) > 0, "%d" % len(marks))

# ---- guard: full hip/knee/elbow repair + cloth bind keep painted vertices
b0 = rows(body)
select_rig()
bpy.ops.srp.hip_weights()
b1 = rows(body)
rep("hip_weights giữ vertex vẽ tay", all(b0[i] == b1[i] for i in marks))
rep("hip_weights vẫn sửa vertex khác", any(b0[i] != b1[i] for i in range(len(b0)) if i not in marks))
key = body.get(cloth.SKIN_KEY) or {}
rep("da-theo-áo không giữ bản gốc cho vertex vẽ tay", not (marks & {int(k) for k in key.keys()}))
bpy.ops.srp.cloth_bind()
rep("cloth_bind giữ vertex vẽ tay", all(b0[i] == rows(body)[i] for i in marks))

# ---- paint session tracking
cloth.register_extra()
free = [i for i in range(len(body.data.vertices)) if i not in marks][:5]
ctx.view_layer.objects.active = body
bpy.ops.object.mode_set(mode='WEIGHT_PAINT'); ctx.view_layer.update(); cloth._watch_modes(ctx.scene)
body.vertex_groups["Thigh.L"].add(free, 0.123, 'REPLACE')
bpy.ops.object.mode_set(mode='OBJECT'); ctx.view_layer.update(); cloth._watch_modes(ctx.scene)
now = cloth.hand_painted(body)
rep("phiên vẽ đánh dấu vertex mới", set(free) <= now and marks <= now, "%d -> %d" % (len(marks), len(now)))
rep("thân vẽ lại -> báo quần áo chưa cập nhật", cloth.sync_stale(body))
bpy.ops.object.mode_set(mode='WEIGHT_PAINT'); ctx.view_layer.update(); cloth._watch_modes(ctx.scene)
bpy.ops.object.mode_set(mode='OBJECT'); ctx.view_layer.update(); cloth._watch_modes(ctx.scene)
rep("vào/ra không vẽ -> không thêm", cloth.hand_painted(body) == now)

# ---- sync from body
sweater[cloth.HAND_KEY] = [0]
sw0 = rows(sweater)[0]
hair0 = rows(bpy.data.objects["Adult_HAIR"])
b0 = rows(body)
select_rig()
bpy.ops.srp.sync_from_body()
rep("sync: thân không đổi", rows(body) == b0)
rep("sync: vertex vẽ tay trên áo giữ nguyên", rows(sweater)[0] == sw0)
rep("sync: tóc mặc định không đụng", rows(bpy.data.objects["Adult_HAIR"]) == hair0)
rep("sync: hết báo chưa cập nhật", not cloth.sync_stale(body))
for n in ("Adult_SWEATER", "Adult_pants", "Adult_shoes_L", "Adult_eyebrow"):
    o = bpy.data.objects[n]
    rep("sync: %s đủ trọng số" % n, cloth.count_low(o, rig) == 0)
select_rig()
bpy.ops.srp.sync_from_body(hair=True)
hb = cloth._used_bones(bpy.data.objects["Adult_HAIR"], rig)
rep("sync + tóc: tóc vẫn theo đầu", hb and hb <= {"Head", "Neck"}, sorted(hb))

# ---- Delta Mush bake
marks = cloth.hand_painted(body)
b0 = rows(body)
select_rig()
r = bpy.ops.srp.bake_weights()
b1 = rows(body)
rep("bake chạy xong", r == {'FINISHED'})
rep("bake giữ vertex vẽ tay", all(b0[i] == b1[i] for i in marks))
changed = [i for i in range(len(b0)) if b0[i] != b1[i]]
rep("bake đổi vertex khác", len(changed) > 100, "%d" % len(changed))
deform = {b.name for b in rig.data.bones if b.use_deform}
over = [i for i in changed if sum(1 for n, w in b1[i].items() if n in deform and w > 1e-4) > 4]
rep("bake: tối đa 4 xương", not over, "%d vertex quá 4" % len(over))
bad_sum = [i for i in changed if abs(sum(w for n, w in b1[i].items() if n in deform) - 1) > 1e-3]
rep("bake: tổng weight = 1", not bad_sum, "%d vertex lệch" % len(bad_sum))
rep("bake: không sót mesh tạm", not [o for o in bpy.data.objects if o.name.startswith("SRP_bake_tmp")])
rep("bake: báo quần áo cần cập nhật", cloth.sync_stale(body))

print("TỔNG %d/%d" % (sum(results), len(results)))
