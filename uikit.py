"""Khung điều hướng của N-panel: thanh chọn khu, wizard dựng rig, nút "?".

Trước đây một tab chứa ~25 panel của ba việc khác hẳn nhau (dựng rig, diễn
xuất, sửa lỗi), mỗi panel kèm 2-5 dòng chữ xám giải thích. Giờ:

- Thanh chọn khu ở đầu tab, xếp theo đúng luồng làm việc:
  Dựng -> Mặt -> Diễn -> Xuất, rồi Sửa (công cụ, dùng lúc cần). Chỉ panel
  của khu đang chọn được vẽ.
- Khu Dựng chỉ mở MỘT bước: bước đầu tiên chưa xong, hoặc bước người dùng
  bấm vào trong danh sách.
- Chữ giải thích chuyển vào HELP, mở bằng nút "?" trên đầu panel.

Trạng thái khu nằm trong Python chứ không trong property: `poll()` và
`draw()` không được ghi vào ID, mà khu phải tự đổi khi vào Pose Mode. Mất
khi khởi động lại Blender cũng chẳng sao -- lúc đó nó tự chọn lại.
"""

import bpy
from bpy.props import IntProperty, StringProperty

# Thứ tự = luồng làm việc. Sửa để cuối: không phải một bước, là hộp đồ nghề.
ZONES = (
    ('BUILD', "Dựng", 'ARMATURE_DATA', "Dựng rig từ bộ xương ref rồi bind skin"),
    ('FACE', "Mặt", 'SHAPEKEY_DATA', "Shape key khuôn mặt, face rig bằng bendy bone, pose thành shape key, đối xứng L/R"),
    ('ANIM', "Diễn", 'POSE_HLT', "Picker, FK/IK, công cụ animate, onion skin"),
    ('EXPORT', "Xuất", 'EXPORT', "Xuất nhân vật + animation sang Unity Humanoid"),
    ('FIX', "Sửa", 'TOOL_SETTINGS', "Quét lỗi rig, dựng lại driver, khám rig, đổi tên xương"),
)

_state = {'zone': None, 'mode': None, 'focus': None, 'manual': False}


def _redraw(context):
    for area in context.screen.areas if context.screen else ():
        if area.type == 'VIEW_3D':
            area.tag_redraw()


def zone(context):
    """Khu đang mở. Vào Pose Mode thì tự sang Diễn."""
    mode = context.mode
    if mode != _state['mode']:
        if _state['mode'] is not None and mode == 'POSE':
            _state['zone'] = 'ANIM'
        _state['mode'] = mode
    if _state['zone'] is None:
        from . import rigdef
        if mode == 'POSE':
            _state['zone'] = 'ANIM'
        elif rigdef.active_rig(context) is None:
            _state['zone'] = 'BUILD'
        else:
            _state['zone'] = 'ANIM'
    return _state['zone']


# ============================================================ wizard

REQUIRED_STEPS = (1, 2, 3, 4, 6)


def focus(context, progress=None):
    """Bước đang mở trong khu Dựng (1..6), hoặc None = chỉ hiện danh sách."""
    if _state['manual']:
        return _state['focus']
    if progress is None:
        from . import generate
        progress = generate.build_progress(context)
    for i in REQUIRED_STEPS:
        if not progress[i - 1][1]:
            return i
    return None


def draw_steps(layout, context):
    """Danh sách bước, bấm để mở. Trả về bước đang mở."""
    from . import generate
    steps = generate.build_progress(context)
    done = [ok for _n, ok, _h in steps]
    cur = focus(context, steps)
    col = layout.column(align=True)
    for i, (name, ok, hint) in enumerate(steps, start=1):
        row = col.row(align=True)
        open_ = generate.step_visible(context, i, done)
        row.enabled = open_
        if ok:
            icon = 'CHECKMARK'
        elif not open_:
            icon = 'LOCKED'
        elif i in generate.OPTIONAL_STEPS:
            icon = 'DOT'
        else:
            icon = 'RADIOBUT_OFF'
        text = "%d · %s" % (i, name)
        if not ok and open_ and i == cur:
            text += "  — " + hint
        op = row.operator("srp.step_focus", text=text, icon=icon, depress=(i == cur))
        op.step = i
    return cur


class SRP_OT_zone(bpy.types.Operator):
    bl_idname = "srp.zone"
    bl_label = "Chọn khu"
    bl_options = {'INTERNAL'}

    zone: StringProperty()

    @classmethod
    def description(cls, context, props):
        return next((d for z, _l, _i, d in ZONES if z == props.zone), "")

    def execute(self, context):
        _state['zone'] = self.zone
        _redraw(context)
        return {'FINISHED'}


class SRP_OT_step_focus(bpy.types.Operator):
    bl_idname = "srp.step_focus"
    bl_label = "Mở bước"
    bl_description = "Mở bước này. Bấm lại để thu gọn"
    bl_options = {'INTERNAL'}

    step: IntProperty()

    def execute(self, context):
        if self.step == 7:          # shape key mặt nằm ở khu Mặt
            _state['zone'] = 'FACE'
        elif _state['manual'] and _state['focus'] == self.step:
            _state['focus'] = None
        else:
            _state['manual'], _state['focus'] = True, self.step
        _redraw(context)
        return {'FINISHED'}


def draw_zone_bar(layout, context):
    from . import health
    cur = zone(context)
    row = layout.row(align=True)
    row.scale_y = 1.3
    broken = bool(health.broken_rigs())
    for key, label, icon, _desc in ZONES:
        cell = row.row(align=True)
        if key == 'FIX' and broken:
            cell.alert = True
            icon = 'ERROR'
        cell.operator("srp.zone", text=label, icon=icon, depress=(key == cur)).zone = key


# ============================================================ nút "?"

HELP = {
    'build': ("Dựng rig", (
        "Làm một lần cho mỗi nhân vật.",
        "Bấm vào một bước trong danh sách để mở bước đó, bấm lại để thu gọn.",
        "Bước đã xong có dấu ✓, bước bị khoá cần làm xong bước trước.",
        "Bind skin xong thì mọi bước đều mở để sửa lại khi cần.",
    )),
    'target': ("1 · Chọn mesh", (
        "Nhãn cầu rời: để trống nếu nhãn cầu nằm trong mesh thân.",
        "Bind skin sẽ gắn CỨNG nhãn cầu vào xương mặt.",
        "Nhiều hơn một cặp mắt: thêm bộ phận 'Mắt' ở bước 3.",
        "Răng: mỗi đảo lưới gắn cứng vào Teeth_Upper/Lower.",
        "Lưỡi: weight chỉ trên chuỗi Tongue.",
        "Lông mày: weight chỉ trên Eyebrow + Head.",
    )),
    'ref_start': ("2 · Xương Hips", (
        "Tạo một armature ref thật -- kéo trong Edit Mode,",
        "nhìn được cả khớp lẫn roll.",
        "Rig đã dựng (bộ ref đã xoá lúc bind): dùng 'Chỉnh lại vị trí xương của rig'.",
        "Nhân vật mẫu: chọn một nhân vật đã rig + mesh thân của nó, bấm",
        "'Dựng ref theo nhân vật mẫu' -- lưới mẫu được uốn áp lên lưới mới,",
        "khớp xương, roll đi theo; xong luôn cả bước 3. Lúc Bind, weight",
        "(cả lông mày cùng hình) chép từ mẫu thay cho automatic weights.",
        "Mắt trùng hình mẫu tự vào danh sách nhãn cầu ở bước 1.",
    )),
    'markers': ("Đặt marker từng khớp", (
        "Chọn kiểu chân, số ngón, bấm 'Bắt đầu đặt marker'.",
        "Click một marker, hoặc chọn khớp trong danh sách ở panel. Khớp không tự nhảy.",
        "Giữ và kéo: dời khớp. Ctrl+click: đưa khớp đang chọn tới đó, vào giữa thịt.",
        "Ctrl+Shift+click: đưa tới đó nhưng nằm trên da. Chuột phải: lùi một bước.",
        "Shift+click: chọn thêm khớp (khớp click sau cùng là active). Kéo, G, Snap, Ctrl+click",
        "dời cả nhóm, giữ khoảng cách. Panel: Căn thẳng X / Y / Z theo khớp active.",
        "Snapping của Blender dùng được: nút nam châm, menu Snap To trên header, Shift+Tab.",
        "G: dời khớp đang chọn theo chuột như G của Blender (click / Enter chốt, Esc huỷ).",
        "Đang dời (G hay giữ kéo): X / Y / Z khoá theo trục, Shift+X / Y / Z khoá mặt phẳng,",
        "bấm lại để bỏ khoá. Giữ Ctrl để đảo bật / tắt snap, Shift cho bước Increment mịn hơn.",
        "Đặt các khớp chính là đủ, các đốt giữa tự chia và vẫn kéo lại được.",
        "Enter: ghi vào bộ ref và thoát. Esc: tạm dừng, lần sau chỉnh tiếp.",
        "Xoay, zoom viewport như bình thường. Trong lúc này không chọn được object khác.",
        "Z / Shift+Z / Alt+Z và mọi pie menu (`, . , ,) dùng như thường.",
        "Shift+S (pie Snap): Selection to Cursor / Grid đưa KHỚP đang chọn tới đó, Cursor to",
        "Selected đưa cursor tới khớp. Menu Object > Snap cũng có các mục này ở đầu.",
        "Chọn khớp để xem trục (đỏ X là trục gập, xanh Z) và chỉnh roll ở panel.",
        "Tai, đuôi, cánh, tóc, áo: bấm nút ở mục Thêm chuỗi, click từ gốc ra ngọn, Enter.",
        "Chỉ click gốc và ngọn thì chia đều theo Số đốt. Click nhiều khớp: mỗi click một khớp.",
        "Xương cha tự chọn: tai, đuôi, cánh, tóc bám vào thân; áo bám xương gần nhất.",
        "Gốc lệch tâm thì tự tạo cả hai bên. Chọn khớp của chuỗi để đổi cha hoặc xoá.",
        "Click đầu trúng marker có sẵn: chuỗi rẽ nhánh từ đó (nan cánh, nhánh tóc).",
        "Chọn khớp rẽ nhánh: panel hỏi chỉnh nhánh nào, hoặc tất cả nhánh.",
    )),
    'ref_parts': ("3 · Các bộ phận", (
        "Kéo xương ref cho khớp nhân vật trước khi dựng rig.",
        "Ô xương cha để trống thì nối vào chỗ mặc định của bộ phận.",
        "L → R / R → L: chép đối xứng vị trí xương ref.",
        "`Heel` chỉ lấy VỊ TRÍ ĐẦU, hướng không dùng tới.",
        "Chân: chọn Người / Chó / Dê. Chó, dê: Foot là đoạn từ cổ chân sau xuống,",
        "Toe là bàn chân / móng, control IK ở chỗ chạm đất; xoay Ball để nhấc cổ chân.",
        "Tay / bàn tay: chọn số ngón (1-5) và có ngón cái hay không.",
    )),
    'skeleton': ("4 · Dựng rig + widget", (
        "Dựng xương + control + widget, đấu dây và đo lại pole trong một bước.",
        "Bộ ref được giữ lại (ẩn đi) để còn sửa, đến lúc Bind skin thì tự xoá.",
        "Đã có rig: 'Cập nhật rig từ ref' dời xương của rig theo bộ ref,",
        "giữ nguyên skin, weight, animation, driver.",
    )),
    'regions': ("5 · Nhóm vùng khuôn mặt", (
        "Tuỳ chọn. Nhóm FS_* là đầu vào của trọng số xương hàm/mắt lúc bind",
        "và của bộ shape key theo vùng.",
        "Nút tạo nhóm TẠO sẵn nhóm rỗng; tô bằng Weight Paint.",
        "Mesh đã skin vào rig mặt cũ thì nó đổ sẵn từ đó.",
        "Bỏ qua được: không có vùng thì xương hàm dùng automatic weights.",
    )),
    'bind': ("6 · Bind skin", (
        "Bind xong sẽ xoá bộ ref cho gọn file; bước 2 có nút dựng lại từ rig.",
        "Phụ kiện gắn cứng không cần trọng số; bind lại cũng tự tránh xương đó.",
        "Tô lại trọng số hàm & mắt: chạy lại sau khi sửa nhóm vùng",
        "hoặc dời chỗ xương, khỏi phải bind lại cả người.",
        "Tách nhãn cầu: con ngươi quay bằng chính phép quay của xương.",
        "Quần áo, tóc, phụ kiện rời: panel 'Quần áo, tóc, phụ kiện' bên dưới.",
    )),
    'cloth': ("Quần áo, tóc, phụ kiện", (
        "1. 'Tìm quần áo chưa bind' -- gom mọi mesh quanh nhân vật chưa gắn rig.",
        "2. Chọn cách bind từng dòng:",
        "   Chép từ thân -- trọng số của da ngay dưới (áo, quần, giày)",
        "   Automatic -- như bind thân (đồ rộng, xa thân)",
        "   Gắn cứng -- 100% vào một xương (tóc, mũ, kính -> Head)",
        "3. 'Cập nhật quần áo': bind món mới và chép lại weight thân sang mọi món.",
        "   Bấm lại mỗi khi thêm quần áo hoặc sửa weight thân. Thân không bị đổi,",
        "   trừ khi bật 'Sửa da dưới áo theo áo' trong hộp thoại.",
        "Bind mesh thân ở bước 6 cũng tự bind luôn danh sách này.",
    )),
    'face': ("Shape key khuôn mặt", (
        "1 · Kiểm tra nhân vật mới -- chấm điểm trước khi dựng (chế độ vùng).",
        "2 · Dựng bộ shape key -- dựng lại chỉ thay key của addon,",
        "    key làm tay được giữ nguyên.",
        "3 · Kiểm định -- đo lại sau khi dựng, báo vào text block FaceShapes_QC.",
        "'Ghi tài liệu hướng dẫn' ghi bản đầy đủ vào FaceShapes_HuongDan.",
    )),
    'posekey': ("Pose → Shape key · Đối xứng", (
        "Pose xương mặt trong Pose Mode rồi bấm Pose → Shape key:",
        "tạo key mới (đặt tên) hoặc ghi đè một key có sẵn.",
        "Chỉ lấy pose các xương con của Head; tay, cổ, đầu không bị nướng vào.",
        "Chỉ xương đang chọn: pose cả hai bên, chọn bên trái -> nướng key trái,",
        "chọn bên phải -> nướng key phải. Xương không chọn tạm về rest lúc đo.",
        "'Tạo luôn bản đối xứng' ra cả bên kia trong một lần bấm.",
        "Đối xứng L ↔ R: lật key sang bên kia (tên tự đổi L/R),",
        "hoặc chép nửa này sang nửa kia ngay trong key.",
        "Mesh phụ bám da: lông mày / râu / mi rời đi theo MỌI key của mặt",
        "(key thiếu thì tạo kèm driver). Chọn mesh phụ, không chọn thì lấy lông mày.",
    )),
    'fkik': ("FK / IK", (
        "Thanh trượt: 0 = FK, 1 = IK.",
        "→FK: đặt chuỗi FK trùng tư thế IK hiện tại (rồi chuyển sang FK).",
        "→IK: đặt control IK trùng tư thế FK hiện tại.",
        "Snap chỉ ở frame hiện tại, không ghi key. Bake theo đoạn ở panel con.",
    )),
    'tools': ("Công cụ", (
        "Tween: tạo pose trung gian giữa hai key kề nhau.",
        "Bấm một mức rồi F9 để chỉnh độ.",
    )),
    'unity': ("Xuất sang Unity", (
        "Ra: <tên>.fbx (mô hình), <tên>@<action>.fbx mỗi action,",
        "<tên>.humanoid.json và RigTamHanhHumanoidImporter.cs.",
        "'Chỉ xương Humanoid' (mặc định): FBX chỉ có xương Unity cần, Hips là gốc.",
        "  Trọng số xương mặt/tai/Palm/đốt sống thừa dồn sang xương Humanoid gần",
        "  nhất; biểu cảm mặt đi qua blendshape. Tắt để giữ animation xương mặt.",
        "Bật 'Gộp animation vào file nhân vật': chỉ một <tên>.fbx chứa cả",
        "nhân vật lẫn mọi clip (mỗi action một take, Unity tách thành clip).",
        "Chép .cs vào Assets/Editor; chọn thẳng thư mục trong Assets/ thì",
        "nó tự vào Assets/Editor/RigTamHanh.",
        "Shape key theo action: slot KEY trong action, hoặc action <tên>_Face.",
        "Sửa ánh xạ bone tay: nút bút chì, rồi sửa text block SRP_Humanoid_Map.",
    )),
    'repair': ("Sửa & kiểm tra", (
        "Addon tự quét mỗi lần mở file.",
        "Muốn tự SỬA luôn: bật trong Preferences > Add-ons.",
    )),
    'repair_logic': ("Driver & rig logic", (
        "Dựng lại constraint, driver switch, driver hiện/ẩn collection, custom prop.",
        "An toàn: không đổi kết quả solve.",
    )),
    'retarget': ("Retarget animation", (
        "Chép animation từ bộ xương khác sang rig này, bake ra FK / IK.",
        "1. Nhập file animation (FBX Mixamo, BVH) hoặc chọn armature nguồn có sẵn.",
        "2. Chọn animation; xem số cặp xương ghép được, sai thì sửa bảng ghép.",
        "3. Bù tỉ lệ thân: hông dịch theo tỉ lệ độ cao hông -- nhân vật chân ngắn",
        "   bước ngắn lại. Đứng tại chỗ: bỏ phần hông đi ngang.",
        "4. Retarget: ra action mới <animation>_<rig>, tay / chân theo FK hoặc IK.",
    )),
    'repair_weights': ("Trọng số skin", (
        "Sửa weight: tính lại weight theo lưới nhân vật (mảnh lưới nào chứa xương nào,",
        "  khoảng cách đi dọc bề mặt, không xuyên khe), rồi làm hết các bước dưới đây.",
        "  Bước nào khám tư thế thấy không tốt hơn thì tự bỏ (vd. weight đã vẽ tay tốt).",
        "  Đã chọn Rig mẫu / Mesh mẫu (bước dựng ref): thử thêm chép weight tô tay của",
        "  mẫu kiểu Mixamo -- theo vị trí quanh từng xương, và uốn lưới mẫu (~40 giây).",
        "  Kết quả từng bước in ở console. Dọn luôn weight vụn, tối đa 4 xương.",
        "Mũi tên bên cạnh: chạy riêng từng bước --",
        "  Tự làm mượt weight các khớp: chạy ngay sau Bind, trước khi vẽ tay.",
        "  Sửa hông, gối, khuỷu: háng thành khe, mông gãy, khoeo / khuỷu móp.",
        "  Sửa hông và gối: như trên, không đụng tay.",
        "  Rào weight theo vùng: gỡ xương lấn vùng (vai lên má, hàm ra sau gáy...).",
        "  Lấp chỗ thiếu weight: vertex đứng yên khi pose.",
        "Khám weight: soát lấn vùng, normalize, lệch L/R, rồi thử các tư thế.",
        "Vertex bạn vẽ tay (Weight Paint) luôn được giữ nguyên.",
        "Sửa thân xong: 'Cập nhật quần áo' để quần áo theo thân.",
    )),
}


class SRP_OT_help(bpy.types.Operator):
    bl_idname = "srp.help"
    bl_label = "Hướng dẫn"
    bl_options = {'INTERNAL'}

    topic: StringProperty()

    @classmethod
    def description(cls, context, props):
        title, lines = HELP.get(props.topic, ("", ()))
        return "\n".join(lines) or "Hướng dẫn"

    def execute(self, context):
        title, lines = HELP.get(self.topic, ("Hướng dẫn", ()))

        def draw(menu, _context):
            for line in lines:
                menu.layout.label(text=line)
        context.window_manager.popup_menu(draw, title=title, icon='QUESTION')
        return {'FINISHED'}


def help_button(layout, topic):
    if topic in HELP:
        layout.operator("srp.help", text="", icon='QUESTION', emboss=False).topic = topic


CLASSES = (SRP_OT_zone, SRP_OT_step_focus, SRP_OT_help)
