"""Face sub-parts: add piecemeal (tongue before jaw), compare with full FACE, generate."""
import bpy
import addon_utils

addon_utils.enable("rig_tam_hanh", default_set=False)
from rig_tam_hanh import refrig, generate, refsync, rigdef

ctx = bpy.context
body = bpy.data.objects["body"]
kid = bpy.data.objects["Kid_Rig.001"]
st = ctx.scene.srp_generate
st.target_mesh = body
st.eyes.clear()

print("menu:", [i.identifier for i in ctx.scene.srp_ref.bl_rna.properties["kind"].enum_items])


def fresh(name):
    st.rig_name = name
    for o in [o for o in bpy.data.objects if refrig.is_ref(o)]:
        bpy.data.objects.remove(o)
    bpy.ops.srp.ref_start()
    return refrig.find_ref(ctx)


def snap(ref):
    return {b.name: (b.head_local.copy(), b.tail_local.copy(), b.parent and b.parent.name,
                     b.use_connect, round(b.roll if False else 0, 3)) for b in ref.data.bones}


# A: full face
ref = fresh("A")
for k in ('SPINE', 'FACE'):
    bpy.ops.srp.ref_add(kind=k, socket="")
full = {b.name: (b.head_local.copy(), b.tail_local.copy(), b.parent and b.parent.name, b.use_connect,
                 b.matrix_local.to_3x3().col[2].copy()) for b in ref.data.bones}

# B: piecemeal, tongue/teeth/lips BEFORE jaw
ref = fresh("B")
bpy.ops.srp.ref_add(kind='SPINE', socket="")
for k in ('TONGUE', 'TEETH', 'LIPS', 'NOSE', 'EYE', 'EYELID', 'BROW', 'EAR', 'JAW'):
    r = bpy.ops.srp.ref_add(kind=k, socket="")
    print("  add", k, r)
for k in ('TONGUE', 'FACE'):
    try:
        print("dup", k, bpy.ops.srp.ref_add(kind=k, socket=""))
    except RuntimeError as e:
        print("dup", k, "refused:", str(e).strip())
print("extra eye pair:", bpy.ops.srp.ref_add(kind='EYE', socket=""), "Eye_2.L" in ref.data.bones)
piece = {b.name: (b.head_local.copy(), b.tail_local.copy(), b.parent and b.parent.name, b.use_connect,
                  b.matrix_local.to_3x3().col[2].copy()) for b in ref.data.bones}
bad = []
for n, v in full.items():
    p = piece.get(n)
    if p is None:
        bad.append((n, "missing"))
    elif (v[0] - p[0]).length > 1e-6 or (v[1] - p[1]).length > 1e-6 or v[2] != p[2] or v[3] != p[3] or (v[4] - p[4]).length > 1e-4:
        bad.append((n, v[2], p[2], v[3], p[3]))
print("piecemeal vs full differences:", bad)
print("parts:", sorted((k[0], len(g)) for k, g in refrig.parts_in(ref).items()))
print("drop tongue:", bpy.ops.srp.ref_drop(kind='TONGUE', inst=1, side=""),
      [n for n in ref.data.bones.keys() if n.startswith("Tongue")])

# C: ref_from_rig tags by region
for o in [o for o in bpy.data.objects if refrig.is_ref(o)]:
    bpy.data.objects.remove(o)
ctx.view_layer.objects.active = kid
bpy.ops.srp.ref_from_rig()
r = refrig.find_ref(ctx)
print("from Kid parts:", sorted((k[0], k[2], len(g)) for k, g in refrig.parts_in(r).items()))

# D: generate from region-tagged ref matches Kid
bpy.ops.srp.ref_from_rig if False else None
ctx.view_layer.objects.active = r
st.rig_name = "Gen"
print("generate:", bpy.ops.srp.generate())
g = bpy.data.objects["Gen"]
off = max(max((g.matrix_world @ g.data.bones[n].head_local - kid.matrix_world @ kid.data.bones[n].head_local).length,
              (g.matrix_world @ g.data.bones[n].tail_local - kid.matrix_world @ kid.data.bones[n].tail_local).length)
          for n in g.data.bones.keys() if n in kid.data.bones)
par = [n for n in g.data.bones.keys() if n in kid.data.bones and
       (g.data.bones[n].parent and g.data.bones[n].parent.name) != (kid.data.bones[n].parent and kid.data.bones[n].parent.name)]
print("gen vs Kid: bones", len(g.data.bones), "/", len(kid.data.bones), "| max off mm %.3f" % (off * 1000), "| parent diff", par,
      "| missing", sorted(set(kid.data.bones.keys()) - set(g.data.bones.keys())))
