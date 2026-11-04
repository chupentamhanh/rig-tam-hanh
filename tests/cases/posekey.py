import bpy, math
import addon_utils
from mathutils import Matrix, Quaternion, Vector

addon_utils.enable("rig_tam_hanh", default_set=False)
from rig_tam_hanh import posekey, facerig

ctx = bpy.context
body = bpy.data.objects["body"]
brow = bpy.data.objects["eyebrow"]
kid = bpy.data.objects["Kid_Rig.001"]
st = ctx.scene.face_shapes
st.face, st.rig = body, kid
ctx.view_layer.objects.active = kid
kb = body.data.shape_keys.key_blocks
print("keys before", len(kb) - 1, "| face bones", len(posekey.face_bones(kid)))

def op(*a, **k):
    try:
        return bpy.ops.face_shapes.pose_to_key(*a, **k)
    except RuntimeError as e:
        return 'ERR ' + str(e)[:80]
print("no pose ->", op('EXEC_DEFAULT', mode='NEW', key_name='X'))

def pose():
    P = kid.pose.bones
    P["Jaw"].rotation_mode = 'XYZ'
    P["Jaw"].rotation_euler = (math.radians(12), 0, 0)
    P["Lip_Upper.L"].location = (0, 0.01, 0)
    P["Eyebrow.L.001"].location = (0, 0.01, 0)
    P["Head"].rotation_mode = 'XYZ'
    P["Head"].rotation_euler = (0, 0, math.radians(20))
    P["Forearm.L"].rotation_quaternion = (0.9, 0.3, 0, 0)
    ctx.view_layer.update()

pose()
# reference: face-only pose evaluated, no keys
for k in kb: k.value = 0
P = kid.pose.bones
saved = {pb.name: pb.matrix_basis.copy() for pb in P}
for n in ("Head", "Forearm.L"):
    P[n].matrix_basis = Matrix()
ctx.view_layer.update()
ref = facerig.eval_co(body)
for n, m in saved.items():
    P[n].matrix_basis = m
ctx.view_layer.update()

r = op('EXEC_DEFAULT', mode='NEW', key_name='MyPose')
print("new ->", r, "| has key", "MyPose" in kb,
      "| eyebrow key", "MyPose" in brow.data.shape_keys.key_blocks)
print("face bones reset:", all(P[n].matrix_basis == Matrix() for n in ("Jaw", "Lip_Upper.L", "Eyebrow.L.001")),
      "| Head/Forearm kept:", P["Head"].matrix_basis != Matrix() and P["Forearm.L"].matrix_basis != Matrix())
drv = [f.data_path for f in brow.data.shape_keys.animation_data.drivers if 'MyPose' in f.data_path]
print("eyebrow driver:", drv)

# key at 1 with face rest must reproduce the face-only pose
P["Head"].matrix_basis = Matrix(); P["Forearm.L"].matrix_basis = Matrix()
for k in kb: k.value = 0
kb["MyPose"].value = 1
ctx.view_layer.update()
got = facerig.eval_co(body)
err = max((a - b).length for a, b in zip(got, ref))
basis = kb["Basis"]
mx = max((kb["MyPose"].data[i].co - basis.data[i].co).length for i in range(len(basis.data)))
print("reproduce err %.2e (max delta %.4f)" % (err, mx))
low = [i for i in range(len(basis.data))
       if (kb["MyPose"].data[i].co - basis.data[i].co).length > 1e-5
       and (body.matrix_world @ basis.data[i].co).z < 1.0]
print("moved verts below z=1.0 (arm/body leak):", len(low))
print("own flag?", "MyPose" in (body.data.shape_keys.get("srp_face") or []))
kb["MyPose"].value = 0

pose()
print("dup name ->", op('EXEC_DEFAULT', mode='NEW', key_name='MyPose'))
old = [kb["JAW_Open"].data[i].co.copy() for i in range(len(basis.data))]
r = op('EXEC_DEFAULT', mode='OVERWRITE', target='JAW_Open')
ch = max((kb["JAW_Open"].data[i].co - old[i]).length for i in range(len(old)))
print("overwrite ->", r, "| changed %.4f" % ch, "| key count", len(kb) - 1)
r = op('EXEC_DEFAULT', mode='OVERWRITE', target='MyPose', reset_pose=False)
print("overwrite own key ->", r, "| pose kept", P["Jaw"].matrix_basis != Matrix())
