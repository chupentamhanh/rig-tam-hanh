"""Dựng rồi gỡ face rig bendy bone: rig về đúng như cũ. Fixture adult_final.blend."""
import bpy
import addon_utils
addon_utils.enable("rig_tam_hanh", default_set=False)
from rig_tam_hanh import facebendy as FB
ctx = bpy.context
arm = bpy.data.objects["Adult_Rig"]
results = []
def rep(name, ok, detail=""):
    results.append(ok); print("[%s] %s %s" % ("ĐẠT" if ok else "HỎNG", name, detail))
before = {b.name: (b.parent.name if b.parent else None, b.matrix_local.copy()) for b in arm.data.bones}
FB.build(ctx, arm); FB.build(ctx, arm)
rep("dựng hai lần không nhân đôi", sum(1 for b in arm.data.bones if b.name.startswith(FB.CTRL)) ==
    len({c for _n, pts, _b, _p in FB.curves(arm) for c, _q in pts}))
FB.remove(ctx, arm)
after = {b.name: (b.parent.name if b.parent else None, b.matrix_local.copy()) for b in arm.data.bones}
rep("gỡ: đúng bộ xương cũ", set(after) == set(before))
rep("gỡ: cha + tư thế nghỉ như cũ", all(after[n][0] == before[n][0] and
    max(abs(a - b) for ra, rb in zip(after[n][1], before[n][1]) for a, b in zip(ra, rb)) < 1e-6 for n in before))
r = bpy.ops.srp.health()
txt = bpy.data.texts.get("RigTamHanh_KhamRig")
rep("khám rig sau khi gỡ: 0 lỗi", txt is not None and txt.as_string().count("[LOI ]") == 0)
FB.build(ctx, arm)
r = bpy.ops.srp.health()
txt = bpy.data.texts.get("RigTamHanh_KhamRig")
rep("khám rig khi có bendy: 0 lỗi", txt is not None and txt.as_string().count("[LOI ]") == 0,
    "%d lỗi" % (txt.as_string().count("[LOI ]") if txt else -1))
print("TỔNG %d/%d" % (sum(results), len(results)))
