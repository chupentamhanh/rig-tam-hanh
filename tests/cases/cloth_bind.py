"""Bind quần áo / tóc của Kid bằng addon rồi đo. argv: -- <outdir>"""
import bpy, math, os, sys
import addon_utils
from mathutils import Euler, Vector
from mathutils.bvhtree import BVHTree
from mathutils.interpolate import poly_3d_calc

OUT = sys.argv[sys.argv.index("--") + 1]
os.makedirs(OUT, exist_ok=True)
addon_utils.enable("rig_tam_hanh", default_set=False)
from rig_tam_hanh import cloth, rigdef, compat, unityexport, health

ctx = bpy.context
rig = bpy.data.objects["Kid_Rig.001"]
body = bpy.data.objects["body"]
st = ctx.scene.srp_generate
st.target_mesh = body
for o in ctx.selected_objects:
    o.select_set(False)
ctx.view_layer.objects.active = rig
res = []
def rep(n, p, d=""):
    res.append(p); print("[%s] %s %s" % ("ĐẠT" if p else "HỎNG", n, d))

r = bpy.ops.srp.cloth_find()
found = [(e.mesh.name, e.mode, e.bone) for e in st.cloth_meshes]
rep("tìm quần áo chưa bind", r == {'FINISHED'} and len(found) == 4, str(found))

r = bpy.ops.srp.cloth_bind()
cl = [e.mesh for e in st.cloth_meshes]
deform = {b.name for b in rig.data.bones if b.use_deform}
for o in cl:
    idx = {g.index: g.name for g in o.vertex_groups}
    bare = sum(1 for v in o.data.vertices if not any(idx[g.group] in deform and g.weight > 1e-4 for g in v.groups))
    mx = max(sum(1 for g in v.groups if idx[g.group] in deform and g.weight > 1e-4) for v in o.data.vertices)
    mods = [m.type for m in o.modifiers]
    rep("bind %s" % o.name, cloth.deformed_by(o, rig) and bare == 0 and mx <= 4 and mods.count('ARMATURE') == 1
        and o.parent is rig and o.parent_type == 'OBJECT',
        "%d nhóm, %d vertex trống, tối đa %d xương/vertex, modifier %s" % (len(o.vertex_groups), bare, mx, mods))

# ---- đo khi pose: quần áo đi theo da, không đâm xuyên
P = rig.pose.bones
prop = P[rigdef.PROP_BONE]
def body_surface():
    dg = ctx.evaluated_depsgraph_get()
    me = body.evaluated_get(dg).data
    vs = [body.matrix_world @ v.co for v in me.vertices]
    me.calc_loop_triangles()
    tris = [tuple(t.vertices) for t in me.loop_triangles]
    return vs, tris
def eval_world(o):
    dg = ctx.evaluated_depsgraph_get()
    return [o.matrix_world @ v.co for v in o.evaluated_get(dg).data.vertices]
def pose(on):
    bpy.ops.object.mode_set(mode='POSE') if ctx.mode != 'POSE' else None
    if not on:
        bpy.ops.srp.reset(whole_rig=True)
        return
    for limb in rigdef.limbs_for(rig):
        if limb.kind == 'ARM':
            prop[limb.prop] = rigdef.FK_VALUE
    compat.refresh(ctx, rig)
    for n, e in (("BicepFK.L", (0, 0, 70)), ("ForearmFK.L", (0, 0, 60)), ("BicepFK.R", (40, 0, -50)),
                 ("ThighFK.L", (60, 0, 0)), ("ShinFK.L", (-80, 0, 0)), ("Spine.002", (25, 0, 15)), ("Head", (0, 30, 0))):
        if n in P:
            P[n].rotation_mode = 'XYZ'
            P[n].rotation_euler = Euler([math.radians(x) for x in e])
    for limb in rigdef.limbs_for(rig):
        if limb.kind == 'LEG' and limb.side == 'L':
            prop[limb.prop] = rigdef.FK_VALUE
    compat.refresh(ctx, rig)
    ctx.view_layer.update()

def measure(o):
    """(lệch trung bình mm, p95 mm, số vertex đâm xuyên) của quần áo so với da."""
    pose(False)
    bv, bt = body_surface()
    tree = BVHTree.FromPolygons(bv, bt)
    cv = eval_world(o)
    bind = []
    for p in cv:
        loc, nor, ti, d = tree.find_nearest(p)
        tri = bt[ti]
        w = poly_3d_calc([bv[k] for k in tri], loc)
        bind.append((tri, w, (p - loc).dot(nor)))
    pose(True)
    bv2, _ = body_surface()
    cv2 = eval_world(o)
    errs, pen = [], 0
    for (tri, w, off0), p0, p1 in zip(bind, cv, cv2):
        s0 = sum((bv[k] * f for k, f in zip(tri, w)), Vector())
        s1 = sum((bv2[k] * f for k, f in zip(tri, w)), Vector())
        errs.append(((p1 - p0) - (s1 - s0)).length)
        n1 = (bv2[tri[1]] - bv2[tri[0]]).cross(bv2[tri[2]] - bv2[tri[0]]).normalized()
        if off0 > 0.001 and (p1 - s1).dot(n1) < -0.001:
            pen += 1
    pose(False)
    errs.sort()
    return sum(errs) / len(errs) * 1000, errs[int(len(errs) * .95)] * 1000, pen

for o in cl:
    mean, p95, pen = measure(o)
    e = next(x for x in st.cloth_meshes if x.mesh is o)
    print("   %-7s %-8s đi theo da: lệch TB %.1f mm, p95 %.1f mm | đâm xuyên %d/%d vertex"
          % (o.name, e.mode, mean, p95, pen, len(o.data.vertices)))
    if o.name == "hoodie":
        hood = (mean, p95, pen)

# so với automatic weights trên chính cái áo
bpy.ops.object.mode_set(mode='OBJECT')
eh = next(x for x in st.cloth_meshes if x.mesh.name == "hoodie")
eh.mode = 'AUTO'
bpy.ops.srp.cloth_bind()
amean, ap95, apen = measure(eh.mesh)
print("   hoodie  AUTO     đi theo da: lệch TB %.1f mm, p95 %.1f mm | đâm xuyên %d" % (amean, ap95, apen))
rep("áo: chép từ thân tốt hơn automatic", hood[2] <= apen and hood[0] <= amean,
    "đâm xuyên %d vs %d, lệch TB %.1f vs %.1f mm" % (hood[2], apen, hood[0], amean))
bpy.ops.object.mode_set(mode='OBJECT')
eh.mode = 'TRANSFER'

# ---- bind lại: không nhân đôi
bpy.ops.srp.cloth_bind()
before = {o.name: (len(o.vertex_groups), len(o.modifiers)) for o in cl}
bpy.ops.srp.cloth_bind(); bpy.ops.srp.cloth_bind()
after = {o.name: (len(o.vertex_groups), len(o.modifiers)) for o in cl}
rep("bind lại 2 lần không nhân đôi", before == after, str(after))

# ---- bind lại cả thân: tóc gắn cứng KHÔNG được làm Head mất da đầu
ctx.view_layer.objects.active = rig
r = bpy.ops.srp.bind(drop_ref=False)
hg = body.vertex_groups.get("Head")
n_head = sum(1 for v in body.data.vertices for g in v.groups if hg and g.group == hg.index and g.weight > .5)
rep("bind lại thân: Head vẫn giữ da đầu", r == {'FINISHED'} and n_head > 100, "%d vertex Head>0.5" % n_head)
bpy.ops.srp.health()
t = bpy.data.texts[health.TEXT_NAME].as_string()
rep("khám rig sau khi bind", t.count("[LOI ]") == 0, "%d lỗi %d cảnh báo" % (t.count("[LOI ]"), t.count("[canh]")))

# ---- Unity
files, lines = unityexport.export(ctx, rig, OUT, "KidCloth", which='NONE')
print("   ", [l for l in lines if "mesh" in l])
rep("xuất Unity có quần áo", any("7 mesh" in l or "8 mesh" in l for l in lines), lines[-1])

# ---- ảnh pose
pose(True)
bpy.ops.object.mode_set(mode='OBJECT')
sc = ctx.scene
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); sc.collection.objects.link(cam)
cam.data.type = 'ORTHO'; cam.data.ortho_scale = 1.7
cam.location = (0.9, -5, 0.75); cam.rotation_euler = (math.radians(90), 0, math.radians(10))
sc.camera = cam
sc.render.engine = 'BLENDER_WORKBENCH'
sc.render.resolution_x, sc.render.resolution_y = 560, 640
sc.render.filepath = os.path.join(OUT, "kid_cloth_pose.png")
rig.hide_render = True
bpy.ops.render.render(write_still=True)
print("\nTỔNG: %d/%d đạt" % (sum(res), len(res)))
