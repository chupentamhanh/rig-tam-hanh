"""Mesh phụ bám da: lông mày Adult đi theo MỌI shape key của thân. Fixture adult_final.blend."""
import bpy
import addon_utils
from mathutils.bvhtree import BVHTree

addon_utils.enable("rig_tam_hanh", default_set=False)
from rig_tam_hanh import face as F, followkeys

ctx = bpy.context
body = bpy.data.objects["Adult_body"]
brow = bpy.data.objects["Adult_eyebrow"]
bk = body.data.shape_keys.key_blocks
results = []


def rep(name, ok, detail=""):
    results.append(ok)
    print("[%s] %s %s" % ("ĐẠT" if ok else "HỎNG", name, detail))


def ev(o):
    d = ctx.evaluated_depsgraph_get(); oe = o.evaluated_get(d); me = oe.to_mesh()
    vs = [o.matrix_world @ v.co for v in me.vertices]; me.calc_loop_triangles()
    tr = [tuple(t.vertices) for t in me.loop_triangles]; oe.to_mesh_clear(); return vs, tr


def gaps():
    bv, bt = ev(body); tree = BVHTree.FromPolygons(bv, bt)
    return [tree.find_nearest(p)[3] for p in ev(brow)[0]]


def set_keys(vals):
    for k in bk:
        k.value = vals.get(k.name, 0.0)
    ctx.view_layer.update()


def worst(cases):
    set_keys({}); g0 = gaps()
    out = {}
    for name, vals in cases.items():
        set_keys(vals); g = gaps()
        out[name] = max(abs(a - b) for a, b in zip(g, g0)) * 1000.0
    set_keys({})
    return out


single = {k.name: {k.name: 1.0} for k in list(bk)[1:]}
presets = {n: v for n, v in F.EXPR_PRESETS.items() if v}
before = worst(single); before_p = worst(presets)
b_name = max(before, key=before.get)

for o in list(ctx.selected_objects):
    o.select_set(False)
ctx.view_layer.objects.active = body
r = bpy.ops.face_shapes.follow_skin()
rep("chạy xong", r == {'FINISHED'})
names = {k.name for k in brow.data.shape_keys.key_blocks}
moving = [n for n in before if before[n] > 0.5]
rep("lông mày có key cho mọi key làm da dưới nó dịch", all(n in names for n in moving), "%d key" % len(moving))
drv = {fc.data_path for fc in brow.data.shape_keys.animation_data.drivers}
rep("mọi key của lông mày có driver theo thân",
    all('key_blocks["%s"].value' % n in drv for n in names if n != "Basis" and n in bk))

after = worst(single); after_p = worst(presets)
a_name = max(after, key=after.get)
rep("từng key: lông mày không tách / lún khỏi da (< 1 mm)", after[a_name] < 1.0,
    "trước: tệ nhất %s %.2f mm -> sau: %s %.2f mm" % (b_name, before[b_name], a_name, after[a_name]))
bp = max(before_p, key=before_p.get); ap = max(after_p, key=after_p.get)
rep("biểu cảm mẫu: lông mày bám da (< 1 mm)", after_p[ap] < 1.0,
    "trước: %s %.2f mm -> sau: %s %.2f mm" % (bp, before_p[bp], ap, after_p[ap]))
r2 = bpy.ops.face_shapes.follow_skin()
rep("chạy lần hai không đổi số key", len(brow.data.shape_keys.key_blocks) == len(names))
print("TỔNG %d/%d" % (sum(results), len(results)))
