"""Bo xuong THAM CHIEU — thay han he marker kieu Auto-Rig Pro.

Vi sao bo marker: mot empty hinh cau chi noi duoc MOT diem. No khong noi duoc
doan xuong chay tu dau toi dau (phai doan bang cach noi hai marker lien tiep),
va tuyet nhien khong noi duoc ROLL — phuong xoay quanh truc xuong. Ma roll moi
la thu quyet dinh "gap khuyu" la gap ve huong nao, va `pole_angle` bang bao
nhieu. Voi marker, roll do `_align_roll()` doan lay theo huong xuong; nguoi
dung khong nhin thay va khong sua duoc.

Bo ref o day lam giong Rigify: mot armature that, moi doan xuong ref la mot
xuong that co head/tail/roll, keo trong Edit Mode. Nhin la thay khop nam dau,
bat Axes la thay roll. Khac Rigify mot diem, dung nhu yeu cau: KHONG do ra ca
bo metarig mot luc. Tung bo phan mot, va moi lan them mot bo phan thi CHON
xuong cha cho no. Nho vay nhan vat bon tay sau chan chi la bam them vai lan,
khong phai sua ban ve.

Cay phan cap cua bo ref CHINH LA cay phan cap cua rig se sinh ra — ten xuong
ref trung ten xuong deform tuong ung. Khong co bang tra thu hai de lech nhau.
"""

import bpy
from bpy.props import (BoolProperty, EnumProperty, IntProperty, StringProperty)
from mathutils import Matrix, Vector

from . import rigdef

REF_SUFFIX = "_Ref"

# Bon nhan ghi thang len xuong ref. KHONG suy tu ten: bo phan "mat" khong co
# ben, nhung ben trong no co `Eye.L` va `Eye.R`. Doc ben tu duoi ten thi hai
# con mat bi tach thanh hai "bo phan" rieng, va bo phan mat that thi con moi
# xuong ham. Nhan la du lieu, ten la thu de nguoi doc — khong tron hai thu.
TAG_PART = "srp_part"      # loai: HIPS / SPINE / ARM / LEG / FACE / CHAIN
TAG_INST = "srp_inst"      # so thu tu chi cung loai cung ben
TAG_SIDE = "srp_side"      # 'L' / 'R' / '' (bo phan nam giua)
TAG_BASE = "srp_base"      # ten trong ban ve, de ben sinh rig tra cuu
# Anh chup bo ref LUC RIG KHOP VOI NO (dung rig xong, hoac vua cap nhat rig).
# Nam tren armature data cua bo ref. `refsync` lay hieu so "bo ref bay gio"
# tru "anh chup nay" de biet nguoi dung vua keo xuong nao — xem `refsync`.
TAG_BASELINE = "srp_baseline"
TAG_LEG = "srp_leg"        # kieu chan, ghi tren xuong ref va xuong dui cua rig

# Ty le theo CHIEU CAO bounding box cua mesh muc tieu, pose chu T. Chi la diem
# xuat phat — toan bo y nghia cua buoc nay la nguoi dung keo lai cho khop nhan
# vat that.
#
# BO MAC DINH = `Kid_Rig.001` (project Dentis): moi con so ben duoi do thang tu
# rig do, chia cho bounding box cua mesh `body` (cao 1,519, day 0,004, tam Y
# -0,004). Doi bo mac dinh thi do lai cung cach, dung sua tay tung so.
#
# Moi dong: (ten, head, tail, cha trong cung bo phan, noi lien, doi xung[, z])
#   `cha trong cung bo phan` = None nghia la xuong goc cua bo phan, no se noi
#   vao socket ma nguoi dung chon.
#   `doi xung` = True nghia la xuong nay sinh ra ca .L lan .R (dung cho mat,
#   bo phan nam giua nhung co chi tiet hai ben). Toa do ghi cho ben L (+X).
#   `z` (tuy chon) = truc Z cuc bo mong muon, ghi cho ben L — chep dung roll
#   cua bo mac dinh thay vi de `_default_roll` doan. Ben R tu lat guong.

UP = (0.0, 0.0, 1.0)

# Bo mat cua Kid_Rig, chia theo VUNG de them le tung phan (nhan vat khong
# luoi, robot chi co mat...). "Khuon mat (du bo)" la tong cua tat ca.
#
# Cha co the nam o VUNG KHAC: luoi, rang duoi, moi duoi theo `Jaw`. `add_part`
# tim cha ngoai vung tren bo ref; chua co (them Luoi truoc Ham) thi noi tam vao
# socket, roi luc them Ham no tu nhan lai con — xem `_adopt`.
FACE_GROUPS = (
    ('JAW', "Mặt · Hàm",
     "Hàm dưới. ĐẦU ở bản lề, ĐUÔI ở chóp cằm. Lưỡi, răng dưới, môi dưới "
     "bám theo xương này.",
     (("Jaw", (0.0, -0.0068, 0.7407), (0.0, -0.1211, 0.7041), None, False, False, (0.0, -0.305, 0.952)),)),
    ('TEETH', "Mặt · Răng",
     "Hai hàm răng: Teeth_Upper theo đầu, Teeth_Lower theo hàm. Mesh răng "
     "chọn ở mục 1 sẽ gắn cứng vào hai xương này.",
     (("Teeth_Upper", (0.0, -0.1305, 0.7701), (0.0, -0.1303, 0.7595), None, False, False, (0.0, 1.0, 0.017)),
      ("Teeth_Lower", (0.0, -0.1289, 0.7362), (0.0, -0.1289, 0.7458), "Jaw", False, False, (0.0, 1.0, 0.0)))),
    ('TONGUE', "Mặt · Lưỡi",
     "4 đốt lưỡi nối liền, từ cuống ra chóp, theo hàm.",
     (("Tongue",     (0.0, 0.0159, 0.7429), (0.0, -0.0126, 0.7475), "Jaw", False, False, (0.0, 0.160, 0.987)),
      ("Tongue.001", (0.0, -0.0126, 0.7475), (0.0, -0.0500, 0.7450), "Tongue", True, False, (0.0, -0.067, 0.998)),
      ("Tongue.002", (0.0, -0.0500, 0.7450), (0.0, -0.0849, 0.7379), "Tongue.001", True, False, (0.0, -0.199, 0.980)),
      ("Tongue.003", (0.0, -0.0849, 0.7379), (0.0, -0.1027, 0.7327), "Tongue.002", True, False, (0.0, -0.280, 0.960)))),
    ('LIPS', "Mặt · Môi",
     "7 môi trên theo đầu, 7 môi dưới theo hàm.",
     (("Lip_Upper_Mid", (0.0, -0.1472, 0.7628), (0.0, -0.1647, 0.7628), None, False, False, UP),
      ("Lip_Upper",     (0.0644, -0.1231, 0.7565), (0.0644, -0.1406, 0.7565), None, False, True, UP),
      ("Lip_Upper.001", (0.0426, -0.1349, 0.7632), (0.0426, -0.1525, 0.7632), None, False, True, UP),
      ("Lip_Upper.002", (0.0222, -0.1426, 0.7635), (0.0222, -0.1601, 0.7635), None, False, True, UP),
      ("Lip_Lower_Mid", (0.0, -0.1434, 0.7379), (0.0, -0.1610, 0.7379), "Jaw", False, False, UP),
      ("Lip_Lower",     (0.0623, -0.1231, 0.7489), (0.0623, -0.1406, 0.7489), "Jaw", False, True, UP),
      ("Lip_Lower.001", (0.0403, -0.1315, 0.7426), (0.0403, -0.1490, 0.7426), "Jaw", False, True, UP),
      ("Lip_Lower.002", (0.0214, -0.1395, 0.7399), (0.0214, -0.1571, 0.7399), "Jaw", False, True, UP))),
    ('NOSE', "Mặt · Mũi", "Một xương mũi.",
     (("Nose", (0.0, -0.1389, 0.7838), (0.0, -0.1597, 0.7869), None, False, False, (0.0, 0.148, 0.989)),)),
    ('EYE', "Mặt · Mắt (cặp)",
     "Một CẶP mắt. Thêm lần nữa là ra cặp thứ hai (Eye_2.L/R) — nhân vật bốn "
     "mắt, sáu mắt. ĐẦU ở tâm quay nhãn cầu, ĐUÔI chỉ hướng nhìn.",
     (("Eye", (0.0550, -0.0790, 0.8293), (0.0550, -0.1240, 0.8293), None, False, True, UP),)),
    ('EYELID', "Mặt · Mí mắt",
     "7 xương mỗi bên: khoé trong, 2 mí trên, khoé ngoài, 3 mí dưới.",
     (("Eyelid_Inner",     (0.0287, -0.1187, 0.8336), (0.0287, -0.1363, 0.8336), None, False, True, UP),
      ("Eyelid_Upper",     (0.0472, -0.1154, 0.8611), (0.0472, -0.1371, 0.8611), None, False, True, UP),
      ("Eyelid_Upper.001", (0.0783, -0.1048, 0.8600), (0.0783, -0.1223, 0.8600), None, False, True, UP),
      ("Eyelid_Outer",     (0.0970, -0.0925, 0.8356), (0.0970, -0.1101, 0.8356), None, False, True, UP),
      ("Eyelid_Lower",     (0.0395, -0.1177, 0.8031), (0.0395, -0.1411, 0.8031), None, False, True, UP),
      ("Eyelid_Lower.001", (0.0717, -0.1112, 0.7963), (0.0717, -0.1346, 0.7963), None, False, True, UP),
      ("Eyelid_Lower.002", (0.0941, -0.0972, 0.8113), (0.0941, -0.1206, 0.8113), None, False, True, UP))),
    ('BROW', "Mặt · Lông mày",
     "4 xương mỗi bên, từ đuôi mày vào giữa trán. Mesh lông mày chọn ở mục "
     "1 sẽ chỉ skin vào các xương này.",
     (("Eyebrow",     (0.1069, -0.1005, 0.8737), (0.1069, -0.1259, 0.8737), None, False, True, UP),
      ("Eyebrow.001", (0.0815, -0.1182, 0.8857), (0.0815, -0.1432, 0.8857), None, False, True, UP),
      ("Eyebrow.002", (0.0494, -0.1298, 0.8861), (0.0494, -0.1545, 0.8861), None, False, True, UP),
      ("Eyebrow.003", (0.0201, -0.1362, 0.8804), (0.0201, -0.1592, 0.8804), None, False, True, UP))),
    ('EAR', "Mặt · Tai", "Một xương mỗi tai.",
     (("Ear", (0.1219, -0.0001, 0.7892), (0.1587, 0.0568, 0.8216), None, False, True, (-0.234, -0.362, 0.902)),)),
)
FACE_KINDS = ('FACE',) + tuple(g[0] for g in FACE_GROUPS)

# Cap mat thu hai tro di: thap hon cap dau mot chut de khong de len nhau.
EYE_EXTRA = (("Eye", (0.0550, -0.0790, 0.7900), (0.0550, -0.1240, 0.7900), None, False, True, UP),)

PARTS = (
    dict(
        kind='HIPS',
        label="Hông (gốc)",
        sided=False,
        once=True,
        socket=None,
        note="Xương gốc của cả bộ. Đặt ở tâm chậu hông, đuôi chỉ XUỐNG như "
             "Kid_Rig.",
        bones=(
            ("Hips", (0.0, 0.0054, 0.4128), (0.0, 0.0054, 0.3678), None, False, False, (0.0, 1.0, 0.0)),
        ),
    ),
    dict(
        kind='SPINE',
        label="Cột sống + cổ + đầu",
        sided=False,
        once=True,
        socket="Hips",
        note="Sáu đốt: 4 lưng, 1 cổ, 1 đầu. Đuôi của Head là ĐỈNH đầu.",
        bones=(
            ("Spine",     (0.0, 0.0054, 0.4128), (0.0, -0.0045, 0.4675), None, False, False, (0.0, 0.984, 0.177)),
            ("Spine.001", (0.0, -0.0045, 0.4675), (0.0, -0.0093, 0.5286), "Spine", True, False, (0.0, 0.997, 0.079)),
            ("Spine.002", (0.0, -0.0093, 0.5286), (0.0, -0.0066, 0.5970), "Spine.001", True, False, (0.0, 0.999, -0.040)),
            ("Spine.003", (0.0, -0.0066, 0.5970), (0.0, 0.0098, 0.6712), "Spine.002", True, False, (0.0, 0.976, -0.216)),
            ("Neck",      (0.0, 0.0098, 0.6712), (0.0, -0.0061, 0.7164), "Spine.003", True, False, (0.0, 0.943, 0.332)),
            ("Head",      (0.0, -0.0061, 0.7164), (0.0, -0.0061, 0.8919), "Neck", True, False, (0.0, 1.0, 0.0)),
        ),
    ),
    dict(
        kind='ARM',
        label="Tay",
        sided=True,
        once=False,
        socket="Spine.003",
        note="Khuỷu để chồi ra SAU một chút — thẳng tuyệt đối thì IK không biết "
             "gập về hướng nào.",
        bones=(
            ("Shoulder",    (0.0003, 0.0066, 0.6597), (0.0771, 0.0066, 0.6595), None, False, False, (0.003, 0.0, 1.0)),
            ("Bicep",       (0.0903, 0.0066, 0.6266), (0.1863, 0.0186, 0.6266), "Shoulder", False, False, (-0.124, 0.992, 0.0)),
            ("Forearm",     (0.1863, 0.0186, 0.6266), (0.3079, 0.0134, 0.6235), "Bicep", True, False, (0.043, 0.999, -0.001)),
            ("Hand_Master", (0.3079, 0.0134, 0.6235), (0.4359, 0.0134, 0.6235), "Forearm", True, False, UP),
        ),
    ),
    dict(
        kind='HAND',
        label="Bàn tay (ngón)",
        sided=True,
        once=False,
        socket="Hand_Master",
        note="Mỗi ngón 1 xương bàn + 3 đốt, chọn được 1-5 ngón, xếp theo hình học "
             "xương bàn tay đang có. Bỏ qua nếu nhân vật không có ngón tay (móng, vuốt, găng "
             "cứng).",
        bones=(),                       # sinh dong, xem `_hand_spec`
    ),
    dict(
        kind='LEG',
        label="Chân",
        sided=True,
        once=False,
        socket="Hips",
        note="Gối để chồi ra TRƯỚC một chút. `Heel` là mốc gót chân cho foot "
             "roll — chỉ lấy VỊ TRÍ ĐẦU, hướng và độ dài không dùng tới.",
        bones=(
            ("Thigh", (0.0543, 0.0000, 0.3735), (0.0543, 0.0032, 0.2256), None, False, False, (0.0, -1.0, -0.021)),
            ("Shin",  (0.0543, 0.0032, 0.2256), (0.0543, 0.0197, 0.0483), "Thigh", True, False, (0.0, -0.996, -0.093)),
            ("Foot",  (0.0543, 0.0197, 0.0483), (0.0543, -0.0462, 0.0005), "Shin", True, False, (0.0, -0.587, 0.810)),
            ("Toe",   (0.0543, -0.0462, 0.0005), (0.0543, -0.0962, 0.0005), "Foot", True, False, UP),
            ("Heel",  (0.0543, 0.0452, 0.0017), (0.0543, -0.0043, 0.0010), "Foot", False, False, UP),
        ),
    ),
    dict(
        kind='FACE',
        label="Khuôn mặt (đủ bộ)",
        sided=False,
        once=True,
        socket="Head",
        note="Đủ bộ mặt của Kid_Rig một lần: hàm, răng, lưỡi, môi, mũi, mắt, "
             "mí, lông mày, tai. Muốn chọn lẻ từng phần thì dùng các mục "
             "'Mặt · ...' bên dưới thay cho mục này.",
        bones=(),                       # ghep tu FACE_GROUPS, xem duoi bang
    ),
) + tuple(
    dict(kind=kind, label=label, sided=False, once=kind != 'EYE',
         socket="Head", note=note, bones=rows)
    for kind, label, note, rows in FACE_GROUPS
)

# Bo mat rieng cua tung vung, de buoc bind biet xuong nao cong mesh nao. Ten
# GOC (chua co ben) — `face_role_bones()` cua generate ghep ben vao.
FACE_TEETH = ("Teeth_Upper", "Teeth_Lower")
FACE_TONGUE_PREFIX = "Tongue"
FACE_BROW_PREFIX = "Eyebrow"

PART_BY_KIND = {p['kind']: p for p in PARTS}

# Chan di bang ngon / mong. Cung nam xuong voi chan nguoi: `Foot` la doan ban dai
# tu co chan sau (hock) xuong, `Toe` la ban chan / mong cham dat, `Heel` la mep
# sau cho cham dat. Gap chu Z: goi ra truoc, hock ra sau.
_F, _Z = (0.0, -1.0, 0.0), (0.0, -0.6, 0.8)
LEG_LAYOUTS = {
    'PAW': (
        ("Thigh", (0.0543, 0.0000, 0.3735), (0.0543, -0.0300, 0.2500), None, False, False, _F),
        ("Shin",  (0.0543, -0.0300, 0.2500), (0.0543, 0.0450, 0.1250), "Thigh", True, False, _F),
        ("Foot",  (0.0543, 0.0450, 0.1250), (0.0543, 0.0150, 0.0180), "Shin", True, False, _F),
        ("Toe",   (0.0543, 0.0150, 0.0180), (0.0543, -0.0500, 0.0005), "Foot", True, False, UP),
        ("Heel",  (0.0543, 0.0350, 0.0005), (0.0543, -0.0100, 0.0005), "Foot", False, False, UP),
    ),
    'HOOF': (
        ("Thigh", (0.0543, 0.0000, 0.3735), (0.0543, -0.0250, 0.2550), None, False, False, _F),
        ("Shin",  (0.0543, -0.0250, 0.2550), (0.0543, 0.0400, 0.1450), "Thigh", True, False, _F),
        ("Foot",  (0.0543, 0.0400, 0.1450), (0.0543, 0.0180, 0.0450), "Shin", True, False, _F),
        ("Toe",   (0.0543, 0.0180, 0.0450), (0.0543, -0.0120, 0.0005), "Foot", True, False, _Z),
        ("Heel",  (0.0543, 0.0220, 0.0005), (0.0543, -0.0100, 0.0005), "Foot", False, False, UP),
    ),
}
PART_BY_KIND['FACE']['bones'] = tuple(row for g in FACE_GROUPS for row in g[3])

# {ten goc: ten goc cua cha} cho moi xuong mat — de tim cha o vung khac.
FACE_PARENT = {row[0]: row[3] for row in PART_BY_KIND['FACE']['bones']}

# Bo phan bat buoc phai co truoc khi dung rig. FACE va CHAIN deu tuy chon:
# robot, thu, dao cu khong co mat; khong phai nhan vat nao cung co duoi.
CORE_KINDS = ('HIPS', 'SPINE', 'ARM', 'LEG')

# Xuong ref co huong/do dai khong dung toi — chi lay vi tri DAU. Bao cho nguoi
# dung biet de ho khong mat cong can chinh.
POINT_ONLY = ("Heel",)


# ------------------------------------------------------------------ ten

# Ten xuong ref TRUNG ten xuong deform tuong ung, ke ca phan danh so chi. Goi
# thang ham cua `rigdef` chu khong chep lai: hai ban sao lech nhau mot ky tu la
# bo ref tro toi mot cai ten khong co trong rig, va khong cho nao bao loi.
#
# Goi LUC DUNG chu khong gan lai lam bien module (`bone_name = rigdef.bone_name`
# o dau file). Khi bat lai addon trong mot Blender dang chay, `__init__` import
# het module roi moi `importlib.reload` tung cai — nen module MOI doc thuoc tinh
# cua module CU va no nem AttributeError ngay luc import, truoc khi kip reload.


def inst_name(base, inst):
    return rigdef.inst_name(base, inst)


def bone_name(base, inst=1, side=None):
    return rigdef.bone_name(base, inst, side)


# Bo phan xep theo hinh hoc xuong CHA dang co, toa do von da o he cuc bo.
LOCAL_KINDS = ('CHAIN', 'HAND')


def _digit_name(base, inst, side):
    """`Palm.001` ben L -> `Palm.L.001`, tay thu hai -> `Palm_2.L.001`.

    Hau to so phai nam SAU hau to ben. Ghep thang `bone_name("Palm.001", …)`
    ra `Palm.001.L`, khac he ten cua rig goc (`Palm.L.001`) — va do la thu
    picker cung nhu bang quy tac widget dang do theo tien to.
    """
    stem, digit = base, ""
    if len(base) > 4 and base[-4] == "." and base[-3:].isdigit():
        stem, digit = base[:-4], base[-4:]
    return bone_name(stem, inst, side) + digit


def ref_object_name(rig_name="SRP_Rig"):
    return rig_name + REF_SUFFIX


def find_ref(context):
    """Bo ref dang lam viec: object active, roi selected, roi cai dau tien."""
    for obj in ([context.object] + list(context.selected_objects)
                + list(context.scene.objects)):
        if obj is not None and obj.type == 'ARMATURE' and is_ref(obj):
            return obj
    return None


def is_ref(obj):
    if obj is None or obj.type != 'ARMATURE':
        return False
    return any(TAG_PART in b.keys() for b in obj.data.bones)


# ------------------------------------------------------------ doc bo ref

def part_of(bone):
    """(kind, inst, side) cua mot xuong ref, hoac None neu no khong thuoc bo nao."""
    kind = bone.get(TAG_PART)
    if not kind:
        return None
    return kind, int(bone.get(TAG_INST, 1)), (bone.get(TAG_SIDE) or None)


def parts_in(ref):
    """{(kind, inst, side): {ten trong ban ve: bone}} — cac bo phan tren bo ref.

    Khoa trong dung ten BAN VE (`Bicep`, `Eye.L`) chu khong phai ten day du
    (`Bicep_2.L`), de ben sinh rig tra cuu theo ban ve ma khong phai ghep chuoi
    lai moi lan.
    """
    found = {}
    if ref is None:
        return found
    for bone in ref.data.bones:
        tag = part_of(bone)
        if tag is None:
            continue
        found.setdefault(tag, {})[bone.get(TAG_BASE) or bone.name] = bone
    return found


def store_baseline(ref):
    """Chup lai bo ref o trang thai rig dang khop voi no.

    Moi xuong: head, tail, truc Z — he cuc bo cua bo ref. Ghi de anh cu.
    """
    data = {}
    for bone in ref.data.bones:
        z = bone.matrix_local.to_3x3() @ Vector((0.0, 0.0, 1.0))
        data[bone.name] = [*bone.head_local, *bone.tail_local, *z]
    ref.data[TAG_BASELINE] = data


def part_sort_key(key):
    """Sap xep on dinh cho khoa bo phan — `side` co the la None."""
    kind, inst, side = key
    return kind, inst, side or ""


def part_label(kind, inst, side):
    spec = PART_BY_KIND.get(kind)
    label = spec['label'] if spec else kind
    if side:
        label += " " + ("trái" if side == 'L' else "phải")
    if inst > 1:
        label += " #%d" % inst
    return label


def missing_core(ref):
    """Cac bo phan bat buoc con thieu, theo dung thu tu phai lam."""
    have = {k for k, _i, _s in parts_in(ref)}
    return [k for k in CORE_KINDS if k not in have]


def next_inst(ref, kind, side):
    """So thu tu con trong cho mot bo phan moi cung loai, cung ben."""
    used = {i for k, i, s in parts_in(ref) if k == kind and s == side}
    inst = 1
    while inst in used:
        inst += 1
    return inst


def eye_inst(ref):
    """Số thứ tự còn trống cho một cặp mắt mới.

    Đếm theo XƯƠNG `Eye*` đang có chứ không theo thẻ bộ phận: cặp mắt thứ nhất
    do bộ phận `FACE` đẻ ra nên nó mang thẻ FACE. Đếm theo thẻ thì cặp mới lại
    nhận số 1 và đè thẳng lên cặp cũ.
    """
    inst = 1
    while any(_digit_name("Eye", inst, side) in ref.data.bones
              for side in rigdef.SIDES):
        inst += 1
    return inst


def socket_items(self, context):
    """Moi xuong ref hien co — de chon lam cha cho bo phan sap tao."""
    ref = find_ref(context)
    if ref is None:
        return [('NONE', "chưa có bộ ref", "")]
    names = sorted(b.name for b in ref.data.bones)
    return [(n, n, "") for n in names] or [('NONE', "chưa có xương nào", "")]


# --------------------------------------------------------------- dung ref

def mesh_fit(mesh_object):
    """(chieu cao, tam X-Y, day chan) cua mesh muc tieu."""
    if mesh_object is None:
        return 1.7, Vector((0.0, 0.0)), 0.0
    corners = [mesh_object.matrix_world @ Vector(c) for c in mesh_object.bound_box]
    lowest = min(c.z for c in corners)
    highest = max(c.z for c in corners)
    centre = Vector((sum(c.x for c in corners) / 8.0,
                     sum(c.y for c in corners) / 8.0))
    return max(highest - lowest, 1e-3), centre, lowest


def _place(ratio, height, centre, floor, flip):
    x = ratio[0] * (-1.0 if flip else 1.0)
    return Vector((centre.x + x * height,
                   centre.y + ratio[1] * height,
                   floor + ratio[2] * height))


def ensure_ref(context, name, mesh_object=None):
    """Lay (hoac tao) armature ref. Khong dung bo phan nao ca."""
    obj = bpy.data.objects.get(name)
    if obj is not None and obj.type != 'ARMATURE':
        obj = None
    if obj is None:
        armature = bpy.data.armatures.new(name)
        obj = bpy.data.objects.new(name, armature)
        # Octahedral + Axes: nhin mot cai la thay ca vi tri khop lan roll. Day
        # dung la thu he marker khong lam duoc.
        armature.display_type = 'OCTAHEDRAL'
        armature.show_axes = True
        obj.show_in_front = True
    if obj.name not in context.scene.collection.objects:
        for existing in list(obj.users_collection):
            existing.objects.unlink(obj)
        context.scene.collection.objects.link(obj)
    if mesh_object is not None:
        obj.matrix_world = mesh_object.matrix_world.copy()
    return obj


def add_part(context, ref, kind, side=None, inst=None, socket=None,
             mesh_object=None, chain_name=None, chain_count=4,
             leg_type='HUMAN', fingers=5, thumb=True):
    """Dung xuong ref cho MOT bo phan. Tra ve danh sach ten xuong vua tao."""
    spec = PART_BY_KIND.get(kind)
    if spec is None and kind != 'CHAIN':
        return []
    height, centre, floor = mesh_fit(mesh_object)
    # Ban tay theo so thu tu cua CANH TAY no bam vao, khong tu dem rieng: ngon
    # cua tay thu hai phai la `Index_2.L` de khop voi `Hand_Master_2.L`.
    socket_bone = ref.data.bones.get(socket) if socket else None
    if kind == 'HAND' and socket_bone is not None:
        inst = int(socket_bone.get(TAG_INST, 1))
    if kind == 'EYE':
        inst = eye_inst(ref)
    if inst is None:
        inst = next_inst(ref, kind, side)
    flip = side == 'R'

    if kind == 'CHAIN':
        specs = _chain_spec(ref, socket, chain_name, chain_count, height)
    elif kind == 'HAND':
        specs = _hand_spec(ref, socket, side, fingers, thumb)
    elif kind == 'EYE' and inst > 1:
        specs = EYE_EXTRA
    elif kind == 'LEG' and leg_type in LEG_LAYOUTS:
        specs = LEG_LAYOUTS[leg_type]
    else:
        specs = spec['bones']

    # Xuong mat cua VUNG KHAC dang cho cha thuoc vung nay (luoi them truoc ham
    # thi dang tam noi vao Head). Doc the TRUOC khi vao Edit Mode — edit bone
    # khong mang custom property.
    orphans = _face_orphans(ref, specs) if kind in FACE_KINDS else {}

    made = []                   # [(ten day du, ten ban ve)]
    context.view_layer.objects.active = ref
    ref.select_set(True)
    if context.mode != 'EDIT_ARMATURE':
        bpy.ops.object.mode_set(mode='EDIT')
    try:
        edit = ref.data.edit_bones
        inv = ref.matrix_world.inverted()
        local = {}
        for base, head, tail, parent, connect, mirror, *extra in specs:
            sides = (side,) if not mirror else rigdef.SIDES
            for this in sides:
                this_flip = flip if not mirror else this == 'R'
                full = _digit_name(base, inst, this)
                bone = edit.get(full) or edit.new(full)
                # Chuoi bo tro va ban tay xep theo xuong CHA dang co, nen toa do
                # cua chung von da o he cuc bo. Cac bo phan con lai dat theo ty
                # le co the nen phai doi tu he the gioi vao.
                if kind in LOCAL_KINDS:
                    bone.head, bone.tail = Vector(head), Vector(tail)
                else:
                    bone.head = inv @ _place(head, height, centre, floor, this_flip)
                    bone.tail = inv @ _place(tail, height, centre, floor, this_flip)
                bone.use_deform = False
                z = extra[0] if extra else None
                if z is not None and kind not in LOCAL_KINDS:
                    # Ban ve ghi Z o he THE GIOI cho ben L. Lat guong qua mat
                    # phang X: thanh phan x doi dau, dung nhu `symmetrize` doi
                    # dau roll. Roi moi doi vao he cuc bo cua bo ref.
                    z = Vector((-z[0] if this_flip else z[0], z[1], z[2]))
                    z = inv.to_3x3() @ z
                _default_roll(bone, kind, base, z, inv.to_3x3())
                local[(base, this)] = bone
                # Xuong doi xung nam trong bo phan KHONG co ben (hai con mat
                # trong bo phan mat): ten ban ve phai giu ca hau to ben, khong
                # thi `Eye.L` va `Eye.R` de len nhau trong cung mot bo phan.
                made.append((full, base + "." + this if mirror else base))

        # Noi cay: cha trong cung bo phan truoc, roi xuong goc vao socket.
        for base, _h, _t, parent, connect, mirror, *_extra in specs:
            sides = (side,) if not mirror else rigdef.SIDES
            for this in sides:
                bone = local[(base, this)]
                up = None
                if parent is not None:
                    up = (local.get((parent, this)) or local.get((parent, side))
                          or _outside(edit, parent, inst, this))
                if up is not None:
                    bone.parent = up
                    bone.use_connect = connect and up.name in {b.name for b in local.values()}
                elif socket:
                    bone.parent = edit.get(socket)
                    bone.use_connect = False
        # Nhan lai con dang mo coi o vung khac.
        for child, (parent, this) in orphans.items():
            up = local.get((parent, this)) or local.get((parent, None))
            if up is not None and child in edit:
                edit[child].parent = up
                edit[child].use_connect = False
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')

    for full, base in made:
        bone = ref.data.bones.get(full)
        if bone is not None:
            bone[TAG_PART] = kind
            bone[TAG_INST] = inst
            bone[TAG_SIDE] = side or ""
            bone[TAG_BASE] = base
            if kind == 'LEG':
                bone[TAG_LEG] = leg_type
    return [full for full, _base in made]


def _outside(edit, parent, inst, side):
    """Xuong cha nam o bo phan KHAC tren bo ref (vd `Jaw` cho luoi), hoac None."""
    for name in (_digit_name(parent, inst, side), _digit_name(parent, inst, None),
                 parent):
        if name in edit:
            return edit[name]
    return None


def _face_orphans(ref, specs):
    """{ten xuong co san: (ten goc cua cha, ben)} — con o vung khac ma cha
    theo ban ve lai thuoc `specs` sap dung."""
    mine = {row[0] for row in specs}
    out = {}
    for bone in ref.data.bones:
        if bone.get(TAG_PART) not in FACE_KINDS:
            continue
        base = bone.get(TAG_BASE) or bone.name
        side = None
        if base[-2:] in (".L", ".R"):
            base, side = base[:-2], base[-1]
        parent = FACE_PARENT.get(base)
        if parent in mine and base not in mine:
            out[bone.name] = (parent, side)
    return out


def part_bone_names(kind, inst=1, side=None):
    """Ten day du moi xuong mot bo phan SE dung (tru ban tay, chuoi)."""
    spec = PART_BY_KIND.get(kind)
    if spec is None:
        return []
    rows = EYE_EXTRA if kind == 'EYE' and inst > 1 else spec['bones']
    out = []
    for base, _h, _t, _p, _c, mirror, *_z in rows:
        for this in (rigdef.SIDES if mirror else (side,)):
            out.append(_digit_name(base, inst, this))
    return out


# Ban tay cua Kid_Rig.001 (ben L). Moi dong: (ten, head, tail, cha, noi lien),
# head/tail la he so theo khung ban tay (doc xuong, ngang, xuong duoi) nhan voi
# CHIEU DAI `Hand_Master`, tinh tu co tay. Do thang tu rig — xem
# `_hand_spec` cho khung. Van chi la CHO DUNG BAN DAU: ngon tay la xuong ref
# nhu moi bo phan khac, keo lai trong Edit Mode cua bo ref.
#
# Cot cuoi la truc Z cuc bo cua xuong, cung khung do — chep dung roll cua Kid
# (ngon cai xoay gan 45 do so voi ngon khac, doan theo luat chung la lech).
HAND_LAYOUT = (
    ("Palm",       (0.0, 0.0, 0.0), (0.5687, -0.1745, -0.0019), None, False, (0.003, -0.001, 1.000)),
    ("Pinky",      (0.5687, -0.1745, -0.0019), (0.6783, -0.1969, -0.0160), "Palm", False, (0.122, -0.025, 0.992)),
    ("Pinky.001",  (0.6783, -0.1969, -0.0160), (0.7742, -0.2176, -0.0287), "Pinky", True, (0.126, -0.027, 0.992)),
    ("Pinky.002",  (0.7742, -0.2176, -0.0287), (0.8560, -0.2342, -0.0529), "Pinky.001", True, (0.273, -0.055, 0.960)),
    ("Palm.001",   (0.0, 0.0, 0.0), (0.5934, -0.0349, -0.0011), None, False, (0.002, 0.0, 1.000)),
    ("Ring",       (0.5934, -0.0349, -0.0011), (0.7300, -0.0465, -0.0198), "Palm.001", False, (0.134, -0.011, 0.991)),
    ("Ring.001",   (0.7300, -0.0465, -0.0198), (0.8319, -0.0586, -0.0351), "Ring", True, (0.146, -0.017, 0.989)),
    ("Ring.002",   (0.8319, -0.0586, -0.0351), (0.9331, -0.0697, -0.0744), "Ring.001", True, (0.358, -0.039, 0.933)),
    ("Palm.002",   (0.0, 0.0, 0.0), (0.6025, 0.1038, 0.0044), None, False, (-0.007, -0.001, 1.000)),
    ("Middle",     (0.6025, 0.1038, 0.0044), (0.7404, 0.1066, -0.0258), "Palm.002", False, (0.214, 0.004, 0.977)),
    ("Middle.001", (0.7404, 0.1066, -0.0258), (0.8575, 0.1103, -0.0595), "Middle", True, (0.276, 0.009, 0.961)),
    ("Middle.002", (0.8575, 0.1103, -0.0595), (0.9608, 0.1141, -0.0982), "Middle.001", True, (0.351, 0.013, 0.936)),
    ("Palm.003",   (0.0, 0.0, 0.0), (0.5871, 0.2422, -0.0062), None, False, (0.009, 0.004, 1.000)),
    ("Index",      (0.5871, 0.2422, -0.0062), (0.6785, 0.2563, -0.0266), "Palm.003", False, (0.213, 0.033, 0.977)),
    ("Index.001",  (0.6785, 0.2563, -0.0266), (0.7781, 0.2697, -0.0520), "Index", True, (0.243, 0.033, 0.970)),
    ("Index.002",  (0.7781, 0.2697, -0.0520), (0.8861, 0.2924, -0.0852), "Index.001", True, (0.282, 0.059, 0.958)),
    ("Palm.004",   (0.0, 0.0, 0.0), (0.3686, 0.3570, -0.0134), None, False, (-0.695, 0.719, 0.025)),
    ("Thumb",      (0.3686, 0.3570, -0.0134), (0.4266, 0.4040, -0.0165), "Palm.004", False, (-0.628, 0.777, 0.033)),
    ("Thumb.001",  (0.4266, 0.4040, -0.0165), (0.4941, 0.4375, -0.0188), "Thumb", True, (-0.445, 0.896, 0.015)),
    ("Thumb.002",  (0.4941, 0.4375, -0.0188), (0.5475, 0.4474, -0.0197), "Thumb.001", True, (-0.182, 0.983, 0.003)),
)


# Thu tu bo ngon: 4 ngon la bo ut, 3 ngon bo them ngon nhan... Ten giu nguyen
# (`Index`, `Middle`) nen Humanoid va picker nhan dung.
FINGER_ORDER = ("Index", "Middle", "Ring", "Pinky")
_FINGER_PALM = {"Pinky": "Palm", "Ring": "Palm.001", "Middle": "Palm.002",
                "Index": "Palm.003", "Thumb": "Palm.004"}


def hand_layout(fingers=5, thumb=True):
    """HAND_LAYOUT voi `fingers` ngon (tinh ca ngon cai neu `thumb`).

    Ngon con lai duoc gian deu lai tren be ngang ban tay, de ban tay 3 ngon
    khong bi hong mot ben cho ngon vua bo.
    """
    fingers = max(1, min(5, int(fingers)))
    thumb = bool(thumb) and fingers >= 2    # mot ngon thi la ngon thuong
    rest = fingers - 1 if thumb else min(fingers, 4)
    keep = list(FINGER_ORDER[:rest])
    rows = {r[0]: r for r in HAND_LAYOUT}
    first, last = rows["Palm.003"][2][1], rows["Palm"][2][1]    # ngang: tro .. ut
    if len(keep) == 1:
        slots = [(first + last) * 0.5]
    else:
        slots = [first + (last - first) * i / (len(keep) - 1) for i in range(len(keep))]
    shift = {}
    for digit, slot in zip(keep, slots):
        palm = _FINGER_PALM[digit]
        delta = slot - rows[palm][2][1] if len(keep) < 4 else 0.0
        shift[palm] = shift[digit] = shift[digit + ".001"] = shift[digit + ".002"] = delta
    if thumb:
        for n in ("Palm.004", "Thumb", "Thumb.001", "Thumb.002"):
            shift[n] = 0.0
    out = []
    for name, head, tail, parent, connect, z in HAND_LAYOUT:
        if name not in shift:
            continue
        d = shift[name]
        h = head if name.startswith("Palm") else (head[0], head[1] + d, head[2])
        out.append((name, h, (tail[0], tail[1] + d, tail[2]), parent, connect, z))
    return out


def _hand_spec(ref, socket, side, fingers=5, thumb=True):
    """Xuong ref cho mot ban tay, xep theo hinh hoc xuong `Hand_Master`.

    Toa do o he CUC BO cua bo ref (giong `_chain_spec`), vi `add_part` chi doi
    he cho nhung bo phan dat theo ty le co the.
    """
    parent = ref.data.bones.get(socket) if socket else None
    if parent is None:
        return []
    wrist = parent.head_local.copy()
    hand = parent.tail_local - parent.head_local
    length = hand.length
    if length < 1e-6:
        return []
    direction = hand.normalized()

    # Ban tay phai la ANH GUONG cua ban tay trai qua mat phang X, KHONG phai
    # ban tay trai quay 180 do quanh Z. Hai phep bien doi nay chi khac nhau o
    # dau cua Y: anh guong doi dau x, quay 180 do doi dau CA x lan y.
    #
    # `direction` da tu doi dau theo ben (canh tay phai chi ve -X), nen tich co
    # huong voi Z cung doi dau theo — va the la truc ngang ban tay quay nguoc,
    # ngon tro sang nam phia sau lung con ngon cai chia ra truoc. Nhan flip vao
    # ca `across` lan `down` la dung lai thanh phep guong that.
    #
    # "Len tren" la Z THE GIOI doi vao he cuc bo cua bo ref, khong phai Z cuc
    # bo: bo ref chep nguyen ma tran cua mesh, ma mesh nhap tu FBX thuong xoay
    # 90 do quanh X (Kid_Rig: `body` dung theo Y cuc bo). Lay Z cuc bo thi ca
    # ban tay quay 90 do quanh co tay — ngon cai lech 12 cm, ca ban up xuong.
    to_local = ref.matrix_world.inverted().to_3x3()
    up = (to_local @ Vector((0.0, 0.0, 1.0))).normalized()
    flip = -1.0 if side == 'R' else 1.0
    across = direction.cross(up) * flip
    if across.length < 1e-4:
        across = (to_local @ Vector((0.0, 1.0, 0.0))).normalized() * flip
    across.normalize()
    down = across.cross(direction).normalized() * flip

    def place(coef):
        return wrist + (direction * coef[0] + across * coef[1]
                        + down * coef[2]) * length

    def axis(coef):
        return (direction * coef[0] + across * coef[1]
                + down * coef[2]).normalized()

    # Truc Z da o he cuc bo cua bo ref (`add_part` khong doi he lan nua cho
    # bo phan LOCAL_KINDS) va da lat guong theo khung ban tay.
    return [(name, place(head), place(tail), parent_name, connect, False,
             axis(z))
            for name, head, tail, parent_name, connect, z in hand_layout(fingers, thumb)]


def _chain_spec(ref, socket, name, count, height):
    """Chuoi bo tro: N doan thang deu nhau, moc tu duoi xuong cha keo ra.

    Cac dot o giua co y de THANG HANG. Hinh dang that (duoi cong, vat ao ru
    xuong) keo tay trong Edit Mode nhanh hon moi cach doan.
    """
    start = Vector((0.0, 0.0, 0.0))
    direction = Vector((0.0, 1.0, 0.0))
    span = height * 0.25
    parent = ref.data.bones.get(socket) if socket else None
    if parent is not None:
        start = parent.tail_local.copy()
        axis = parent.tail_local - parent.head_local
        if axis.length > 1e-6:
            direction = axis.normalized()
        span = max(parent.length * 2.0, height * 0.1)
    out = []
    step = direction * (span / max(count, 1))
    for index in range(count):
        base = name if index == 0 else "%s.%03d" % (name, index)
        prev = None if index == 0 else (name if index == 1
                                        else "%s.%03d" % (name, index - 1))
        out.append((base, start + step * index, start + step * (index + 1),
                    prev, index > 0, False))
    return out


def _default_roll(edit_bone, kind, base, z=None, to_local=None):
    """Roll mac dinh hop ly, roi de nguoi dung tu chinh.

    Ban ve ghi san truc Z (`z`, da o he cuc bo) thi chep dung no — bo Kid_Rig
    co roll rieng tung xuong (ham chui Z ve sau, tai nghieng), doan theo luat
    chung la lech. Khong co thi:
    Mat thi ghim truc X cuc bo vao truc X the gioi — nho vay "quay quanh X"
    luon la ha ham / nhin len xuong bat ke xuong dang chi huong nao. Con lai
    dung quy uoc chung: xuong dung thi Z ra truoc, xuong ngang thi Z len tren.
    Moi huong "the gioi" doi qua `to_local` (he cuc bo cua bo ref) — bo ref xoay
    theo mesh FBX thi Z cuc bo khong con la "len tren".
    """
    axis = edit_bone.tail - edit_bone.head
    if axis.length < 1e-6:
        return
    axis.normalize()
    if z is not None and z.length > 1e-6:
        edit_bone.align_roll(z)
        return
    if to_local is None:
        to_local = Matrix.Identity(3)
    world_axis = (to_local.inverted() @ axis).normalized()
    if kind in FACE_KINDS:
        z = (to_local @ Vector((1.0, 0.0, 0.0))).cross(axis)
        if z.length > 1e-6:
            edit_bone.align_roll(z)
        return
    reference = (Vector((0.0, -1.0, 0.0)) if abs(world_axis.z) > 0.7
                 else Vector((0.0, 0.0, 1.0)))
    edit_bone.align_roll(to_local @ reference)


def drop_part(ref, kind, inst, side):
    """Xoa het xuong ref cua mot bo phan. Con cua chung bi mo coi thi go cha."""
    doomed = [b.name for b in ref.data.bones
              if part_of(b) == (kind, inst, side)]
    if not doomed:
        return 0
    mode = bpy.context.mode
    if mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.context.view_layer.objects.active = ref
    bpy.ops.object.mode_set(mode='EDIT')
    try:
        edit = ref.data.edit_bones
        for name in doomed:
            bone = edit.get(name)
            if bone is None:
                continue
            for child in list(bone.children):
                if child.name not in doomed:
                    child.parent = bone.parent
                    child.use_connect = False
            edit.remove(bone)
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')
    return len(doomed)


def flip_side(name, from_side, other):
    """`Bicep.L` -> `Bicep.R`, `Palm.L.001` -> `Palm.R.001`. None neu khong khop.

    Hau to ben KHONG phai luon nam cuoi ten: he ten ngon tay dat so o sau ben
    (`Palm.L.001`), dung nhu rig goc. Cach cu chi hoi `endswith(".L")` nen no bo
    qua sach 14 xuong ngon co danh so — chieu sang ben kia xong ban tay phai
    thieu mat hai dot cuoi cua moi ngon, ma khong cho nao bao loi.
    """
    stem, digit = name, ""
    if len(name) > 4 and name[-4] == "." and name[-3:].isdigit():
        stem, digit = name[:-4], name[-4:]
    if not stem.endswith("." + from_side):
        return None
    return stem[:-len(from_side)] + other + digit


def symmetrize(ref, from_side='L'):
    """Chieu moi bo phan mot ben sang ben kia — ke ca roll.

    Roll DOI DAU khi lat qua mat phang X. Quen dau nay thi hai ben trong giong
    het nhau ma `pole_angle` lech dung 180 do, va khuyu ben phai gap nguoc.
    """
    other = 'R' if from_side == 'L' else 'L'
    todo = [(k, i, s) for k, i, s in parts_in(ref) if s == from_side]
    if not todo:
        return 0, 0
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.context.view_layer.objects.active = ref
    bpy.ops.object.mode_set(mode='EDIT')
    moved = created = 0
    try:
        edit = ref.data.edit_bones
        pairs = []
        for name in [b.name for b in edit]:
            twin = flip_side(name, from_side, other)
            if twin is None:
                continue
            source = edit[name]
            target = edit.get(twin)
            if target is None:
                target = edit.new(twin)
                created += 1
            else:
                moved += 1
            head, tail = source.head.copy(), source.tail.copy()
            head.x, tail.x = -head.x, -tail.x
            target.head, target.tail = head, tail
            target.roll = -source.roll
            target.use_deform = source.use_deform
            pairs.append((source, target))
        for source, target in pairs:
            parent = source.parent
            if parent is None:
                target.parent = None
                continue
            twin = flip_side(parent.name, from_side, other) or parent.name
            target.parent = edit.get(twin) or parent
            target.use_connect = source.use_connect
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')
    for name in [b.name for b in ref.data.bones]:
        twin = flip_side(name, from_side, other)
        if twin is None:
            continue
        source = ref.data.bones[name]
        target = ref.data.bones.get(twin)
        if target is None or TAG_PART not in source.keys():
            continue
        target[TAG_PART] = source[TAG_PART]
        target[TAG_INST] = source.get(TAG_INST, 1)
        # Nhan BEN phai lat theo. Chep nguyen si thi ca hai ben cung mang nhan
        # 'L', tuc chung dem vao cung mot bo phan va ben phai bien mat khoi moi
        # phep dem — rig sinh ra thieu han mot tay ma khong cho nao bao.
        target[TAG_SIDE] = other if source.get(TAG_SIDE) == from_side \
            else (source.get(TAG_SIDE) or "")
        base = source.get(TAG_BASE) or source.name
        target[TAG_BASE] = flip_side(base, from_side, other) or base
        if TAG_LEG in source.keys():
            target[TAG_LEG] = source[TAG_LEG]
    return moved, created


# ------------------------------------------------------------- operators

class SRP_OT_ref_start(bpy.types.Operator):
    "Tạo bộ xương ref và dựng ngay xương Hips — bước đầu tiên"
    bl_idname = "srp.ref_start"
    bl_label = "Tạo bộ ref + xương Hips"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        settings = getattr(context.scene, "srp_generate", None)
        return settings is not None and settings.target_mesh is not None

    def execute(self, context):
        settings = context.scene.srp_generate
        mesh = settings.target_mesh
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        ref = ensure_ref(context, ref_object_name(settings.rig_name), mesh)
        made = add_part(context, ref, 'HIPS', mesh_object=mesh)
        if not made:
            self.report({'ERROR'}, "Không dựng được xương Hips")
            return {'CANCELLED'}
        self.report({'INFO'}, "Đã tạo %s — kéo xương Hips về đúng tâm chậu "
                              "hông, rồi thêm cột sống" % ref.name)
        return {'FINISHED'}


class SRP_OT_ref_add(bpy.types.Operator):
    "Thêm một bộ phận vào bộ ref, nối vào xương cha đã chọn"
    bl_idname = "srp.ref_add"
    bl_label = "Thêm bộ phận"
    bl_options = {'REGISTER', 'UNDO'}

    kind: EnumProperty(
        name="Bộ phận",
        items=[(p['kind'], p['label'], p['note']) for p in PARTS]
        + [('CHAIN', "Chuỗi bổ trợ", "Đuôi, tai thú, vạt áo, áo choàng...")],
        default='SPINE')
    side: EnumProperty(
        name="Bên",
        items=(('L', "Trái", ""), ('R', "Phải", ""),
               ('BOTH', "Cả hai bên", "Dựng bên trái rồi chiếu sang phải")),
        default='BOTH')
    socket: StringProperty(
        name="Nối vào",
        description="Xương ref mà bộ phận này bám vào. Để trống thì dùng mặc "
                    "định của bản vẽ (Tay → Spine.003, Chân → Hips...)")
    chain_name: StringProperty(name="Tên chuỗi", default="Tail")
    chain_count: IntProperty(name="Số xương", default=4, min=1, max=32)
    with_hand: BoolProperty(
        name="Kèm bàn tay", default=True,
        description="Thêm tay thì dựng luôn xương ngón, nối vào Hand_Master "
                    "của chính nó. Tắt nếu nhân vật không có ngón tay")
    leg_type: EnumProperty(name="Kiểu chân", items=rigdef.LEG_TYPES, default='HUMAN')
    fingers: IntProperty(name="Số ngón", default=5, min=1, max=5)
    thumb: BoolProperty(name="Có ngón cái", default=True)

    @classmethod
    def poll(cls, context):
        return find_ref(context) is not None

    def execute(self, context):
        ref = find_ref(context)
        settings = context.scene.srp_generate
        spec = PART_BY_KIND.get(self.kind)
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        if spec is not None and spec['once']:
            if any(k == self.kind for k, _i, _s in parts_in(ref)):
                self.report({'ERROR'}, "%s đã có rồi — mỗi bộ chỉ một cái"
                            % spec['label'])
                return {'CANCELLED'}

        socket = self.socket.strip() or (spec['socket'] if spec else "")
        if socket and socket not in ref.data.bones:
            self.report({'ERROR'}, "Không có xương ref %r để nối vào" % socket)
            return {'CANCELLED'}

        sided = bool(spec and spec['sided'])
        sides = [None]
        if sided:
            sides = ['L', 'R'] if self.side == 'BOTH' else [self.side]

        # `add_part` lay lai xuong trung ten (`edit.get(full) or edit.new`) va
        # gan the moi len no — them "Lưỡi" khi "Khuôn mặt (đủ bộ)" da co la
        # cuop 4 xuong luoi sang bo phan khac ma khong ai hay. Chan tu dau.
        if self.kind in FACE_KINDS:
            clash = [n for side in sides
                     for n in part_bone_names(self.kind, next_inst(ref, self.kind, side), side)
                     if n in ref.data.bones and self.kind != 'EYE']
            if clash:
                self.report({'ERROR'}, "Bộ ref đã có %s%s — xoá bộ phận đang chứa "
                            "chúng trước" % (", ".join(clash[:4]),
                                             "…" if len(clash) > 4 else ""))
                return {'CANCELLED'}

        made, labels = [], []
        for side in sides:
            inst = next_inst(ref, self.kind, side)
            names = add_part(context, ref, self.kind, side=side, inst=inst,
                             socket=socket, mesh_object=settings.target_mesh,
                             chain_name=self.chain_name.strip() or "Tail",
                             chain_count=self.chain_count,
                             leg_type=self.leg_type, fingers=self.fingers, thumb=self.thumb)
            made.extend(names)
            labels.append(part_label(self.kind, inst, side))
            # Ban tay di kem canh tay: no luon bam vao `Hand_Master` cua chinh
            # canh tay vua dung, nen bat nguoi dung bam them mot lan nua chi de
            # chon dung cai socket duy nhat hop ly la vo ich.
            if self.kind == 'ARM' and self.with_hand and names:
                hand = add_part(context, ref, 'HAND', side=side,
                                socket=bone_name("Hand_Master", inst, side),
                                mesh_object=settings.target_mesh,
                                fingers=self.fingers, thumb=self.thumb)
                if hand:
                    made.extend(hand)
                    labels.append(part_label('HAND', inst, side))
        if not made:
            self.report({'ERROR'}, "Không dựng được xương ref nào")
            return {'CANCELLED'}
        self.report({'INFO'}, "%s: %d xương ref, nối vào %s"
                    % (", ".join(labels), len(made), socket or "goc"))
        return {'FINISHED'}


class SRP_OT_ref_drop(bpy.types.Operator):
    "Xoá một bộ phận khỏi bộ ref"
    bl_idname = "srp.ref_drop"
    bl_label = "Xoá bộ phận"
    bl_options = {'REGISTER', 'UNDO'}

    kind: StringProperty()
    inst: IntProperty(default=1)
    side: StringProperty()

    def execute(self, context):
        ref = find_ref(context)
        if ref is None:
            return {'CANCELLED'}
        gone = drop_part(ref, self.kind, self.inst, self.side or None)
        self.report({'INFO'}, "Xoa %s: %d xuong ref"
                    % (part_label(self.kind, self.inst, self.side or None), gone))
        return {'FINISHED'}


class SRP_OT_ref_symmetrize(bpy.types.Operator):
    "Chiếu mọi bộ phận một bên sang bên đối diện, kể cả roll"
    bl_idname = "srp.ref_symmetrize"
    bl_label = "Chiếu sang bên kia"
    bl_options = {'REGISTER', 'UNDO'}

    from_side: EnumProperty(
        name="Từ bên", items=(('L', "Trái → Phải", ""), ('R', "Phải → Trái", "")),
        default='L')

    @classmethod
    def poll(cls, context):
        return find_ref(context) is not None

    def execute(self, context):
        ref = find_ref(context)
        moved, created = symmetrize(ref, self.from_side)
        if not moved and not created:
            self.report({'ERROR'}, "Không có bộ phận nào ở bên %s" % self.from_side)
            return {'CANCELLED'}
        self.report({'INFO'}, "Chiếu %d xương (%d tạo mới)" % (moved + created, created))
        return {'FINISHED'}


class SRP_OT_ref_edit(bpy.types.Operator):
    "Mở bộ ref trong Edit Mode để kéo xương"
    bl_idname = "srp.ref_edit"
    bl_label = "Sửa bộ ref"

    @classmethod
    def poll(cls, context):
        return find_ref(context) is not None

    def execute(self, context):
        ref = find_ref(context)
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        for obj in list(context.selected_objects):
            obj.select_set(False)
        ref.select_set(True)
        context.view_layer.objects.active = ref
        bpy.ops.object.mode_set(mode='EDIT')
        return {'FINISHED'}


class SRP_RefSettings(bpy.types.PropertyGroup):
    """Lua chon cho lan them bo phan ke tiep.

    Nam tren Scene chu khong phai tren operator: panel phai VE duoc chung ra
    truoc khi bam nut, con thuoc tinh cua operator thi chi hien sau khi da bam
    (bang F9). Nguoi dung can chon xuong cha TRUOC, khong phai sau.
    """

    kind: EnumProperty(
        name="Bộ phận",
        items=[(p['kind'], p['label'], p['note']) for p in PARTS
               if not p['once'] or p['kind'] != 'HIPS']
        + [('CHAIN', "Chuỗi bổ trợ", "Đuôi, tai thú, vạt áo, áo choàng...")],
        default='SPINE')
    side: EnumProperty(
        name="Bên",
        items=(('BOTH', "Cả hai", "Dựng bên trái rồi chiếu sang phải"),
               ('L', "Trái", ""), ('R', "Phải", "")),
        default='BOTH')
    socket: StringProperty(
        name="Nối vào",
        description="Xương ref mà bộ phận này bám vào. Để trống thì dùng mặc "
                    "định của bản vẽ. Đổi chỗ này là cách dựng nhân vật nhiều "
                    "tay nhiều chân: tay thứ ba nối vào Spine.002 chẳng hạn")
    chain_name: StringProperty(
        name="Tên chuỗi", default="Tail",
        description="Chỉ dùng cho chuỗi bổ trợ. Các đốt sau tự thêm .001, .002")
    chain_count: IntProperty(name="Số xương", default=4, min=1, max=32)
    with_hand: BoolProperty(name="Kèm bàn tay", default=True)
    leg_type: EnumProperty(
        name="Kiểu chân", items=rigdef.LEG_TYPES, default='HUMAN',
        description="Chó / thú và dê / móng guốc: chân gập chữ Z, control IK đặt ở chỗ "
                    "chạm đất. Dựng xong kéo xương ref khớp vào chân thật")
    fingers: IntProperty(
        name="Số ngón", default=5, min=1, max=5,
        description="Tổng số ngón mỗi bàn tay, tính cả ngón cái nếu có")
    thumb: BoolProperty(name="Có ngón cái", default=True,
                        description="Tắt nếu mọi ngón đều nằm cùng một hàng")


def draw_start(layout, context):
    """Buoc 2 — tao bo ref va xuong Hips."""
    ref = find_ref(context)
    if ref is None:
        column = layout.column(align=True)
        column.scale_y = 1.4
        column.operator("srp.ref_start", icon='ARMATURE_DATA')
        # Rig da dung (va co the da bind, bo ref bi xoa luc bind): dung lai bo
        # ref tu chinh rig de con nan tiep. Xem `refsync.ref_from_rig`.
        if rigdef.active_rig(context) is not None:
            layout.operator("srp.ref_from_rig", icon='FILE_REFRESH')
        return
    row = layout.row(align=True)
    row.label(text=ref.name, icon='ARMATURE_DATA')
    row.operator("srp.ref_edit", text="Sửa", icon='EDITMODE_HLT')


def draw_parts(layout, context):
    """Buoc 3 — them tung bo phan, moi cai chon xuong cha rieng."""
    ref = find_ref(context)
    if ref is None:
        layout.label(text="Chưa có bộ ref", icon='ERROR')
        return
    settings = context.scene.srp_ref

    box = layout.box()
    box.label(text="Thêm bộ phận", icon='ADD')
    box.prop(settings, "kind", text="")
    spec = PART_BY_KIND.get(settings.kind)
    if spec is not None and spec['sided']:
        box.row(align=True).prop(settings, "side", expand=True)
    if settings.kind == 'ARM':
        box.prop(settings, "with_hand")
    if settings.kind == 'HAND' or (settings.kind == 'ARM' and settings.with_hand):
        row = box.row(align=True)
        row.prop(settings, "fingers")
        row.prop(settings, "thumb", toggle=True)
    if settings.kind == 'LEG':
        box.row(align=True).prop(settings, "leg_type", expand=True)
    if settings.kind == 'CHAIN':
        row = box.row(align=True)
        row.prop(settings, "chain_name", text="")
        row.prop(settings, "chain_count", text="")
    box.prop_search(settings, "socket", ref.data, "bones", icon='BONE_DATA')
    if spec is not None and not settings.socket.strip():
        sub = box.column(align=True)
        sub.scale_y = 0.8
        sub.label(text="Để trống → nối vào %s" % (spec['socket'] or "gốc"))
    op = box.operator("srp.ref_add", icon='BONE_DATA')
    op.kind = settings.kind
    op.side = settings.side
    op.socket = settings.socket
    op.chain_name = settings.chain_name
    op.chain_count = settings.chain_count
    op.with_hand = settings.with_hand
    op.leg_type = settings.leg_type
    op.fingers = settings.fingers
    op.thumb = settings.thumb

    existing = parts_in(ref)
    if existing:
        box = layout.box()
        box.label(text="Đã có (%d bộ phận)" % len(existing), icon='OUTLINER')
        # `part_sort_key`: `side` la None voi bo phan giua, sorted() tran so
        # None voi 'L' la TypeError — panel vo luon.
        for (kind, inst, side), group in sorted(
                existing.items(), key=lambda item: part_sort_key(item[0])):
            row = box.row(align=True)
            row.label(text="%s — %d xương" % (part_label(kind, inst, side),
                                              len(group)))
            op = row.operator("srp.ref_drop", text="", icon='X', emboss=False)
            op.kind, op.inst, op.side = kind, inst, side or ""

    row = layout.row(align=True)
    op = row.operator("srp.ref_symmetrize", text="L → R")
    op.from_side = 'L'
    op = row.operator("srp.ref_symmetrize", text="R → L")
    op.from_side = 'R'

    missing = missing_core(ref)
    if missing:
        layout.label(text="Còn thiếu: %s"
                     % ", ".join(PART_BY_KIND[k]['label'] for k in missing),
                     icon='ERROR')
    else:
        layout.label(text="Đủ bộ phận bắt buộc", icon='CHECKMARK')


def register_extra():
    bpy.types.Scene.srp_ref = bpy.props.PointerProperty(type=SRP_RefSettings)


def unregister_extra():
    try:
        del bpy.types.Scene.srp_ref
    except AttributeError:
        pass


CLASSES = (SRP_RefSettings, SRP_OT_ref_start, SRP_OT_ref_add, SRP_OT_ref_drop,
           SRP_OT_ref_symmetrize, SRP_OT_ref_edit)
