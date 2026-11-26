# Rig Tẩm Hành — nhật ký thay đổi

Mỗi mục ghi **đổi gì**, **vì sao**, và **số đo** chứng minh. Số đo quan trọng
ngang với mô tả: chỗ nào không có số là chỗ chưa kiểm chứng.

Bài test nằm trong `tests/` của repo (không đi kèm file zip phát hành); xem
`tests/README.md`. Các mục cũ nhắc tên bài test thời trước khi có bộ test
chung -- một số bài đó đã gộp vào `tests/cases/`.

## 1.39.0 — 2026-11-26

**Sửa weight một nút** (`weightauto.py`, `srp.weights_auto`).
- Nút **Sửa weight** ở Sửa › Trọng số skin chạy mọi bước sửa weight thân: khu trú, rào vùng,
  sửa hông / gối / khuỷu, tự làm mượt các khớp, rào lại, lấp chỗ thiếu, dọn (bỏ weight
  < 0.01, tối đa 4 xương, normalize -- bước mới). Menu từng bước cũ vẫn ở mũi tên bên cạnh.
- Sửa hông / gối / khuỷu và tự làm mượt là bước *thử*: làm xong khám ~40 tư thế
  (`weightfence.check_poses`); số tư thế có lỗi không giảm (hoà thì độ giãn trung bình không
  giảm) thì trả lại weight trước bước đó. Lý do: trên Hotdog, sửa hông làm giãn khi giơ đùi
  x3.13 -> x5.14 -- dải chuyển weight đo trên người.
- Mọi bước chạy trong `keep_hand`: vertex vẽ tay y nguyên kể cả bước không tự giữ (lấp chỗ
  thiếu từng đổi vertex vẽ tay của Adult). Có quần áo thì cập nhật theo thân rồi dọn thân lại
  (da theo áo chép weight vụn của áo).
- Số đo:
  - Hotdog (`Hotdog_Rig_v3`, 2974 vertex): tư thế có lỗi 18/40 -> 4/40, giãn trung bình
    x2.50 -> x1.82, lớn nhất x4.48 -> x3.13 (giơ đùi 90°: ống chân mảnh cắm vào thân to),
    weight vụn 50 -> 0; giữ tự làm mượt + dọn, bỏ sửa hông. 3 giây.
  - Adult cấy lỗi: tư thế có lỗi 15 -> 1, hết lấn vùng ở chỗ cấy, 644 vertex vẽ tay y nguyên.
- Test mới `weight_auto` (13 mục, có trường hợp bước thử làm hỏng bị trả lại); cả bộ 31/31.

## 1.38.2 — 2026-11-25

**Mọi pie menu dùng được trong chế độ đặt marker.**
- Lúc vào chế độ marker, add-on đọc keymap người dùng (3D View, Object Mode) và cho mọi phím
  gọi `wm.call_menu_pie` đi qua: mặc định là ` (View), Shift+S (Snap), . (Pivot),
  , (Orientation), Shift+O (Proportional Falloff), cùng pie của add-on khác hoặc phím đã đổi.
  Khớp đúng modifier (kể cả "Any").
- Menu thường (Shift+A, M, Ctrl+A, Ctrl+L...) vẫn bị chặn vì sửa dữ liệu. Phím riêng của chế
  độ marker (Enter, Esc, chuột trái / phải, Ctrl+Z) không nhường cho pie nào.
- Số đo: bài test `markers` thêm 6 mục; trên Blender đang mở `pie_keys` tìm đủ 6 pie mặc định.

## 1.38.1 — 2026-11-25

**Phím Z dùng được trong chế độ đặt marker.**
- Chế độ marker chỉ cho một danh sách phím cố định đi qua Blender và nuốt phần còn lại, nên Z
  (pie menu shading), Shift+Z (wireframe), Alt+Z / Shift+Alt+Z (X-ray) không có tác dụng. Giờ
  mọi tổ hợp Z không có Ctrl đi qua; Ctrl+Z vẫn là lùi một bước đặt marker. Các phím khác
  (A, G, X, Delete...) vẫn bị chặn như trước.
- Danh sách phím đi qua gom vào hàm `passes_to_blender` để test được.
- Số đo: bài test `markers` thêm 4 mục (100/100), cả bộ 30/30.

## 1.38.0 — 2026-11-25

**Snapping của Blender trong chế độ đặt marker.**
- Trước đây chế độ marker nuốt mọi click trên header (không bật được nam châm, không mở được
  Snap To) và kéo marker chỉ trượt trên mặt phẳng nhìn. Giờ header, Shift+Tab, Shift+Ctrl+Tab
  đi qua bình thường; đổi mode từ header thì chế độ marker tạm dừng, marker giữ nguyên.
- `snapping.py` làm lại snapping theo đúng cài đặt của scene trên các mesh đang hiện:
  Increment, Grid, Vertex, Edge, Face (Project), Volume, Edge Center, Edge Perpendicular,
  Face Center, Face Nearest, cùng Absolute Grid Snap, Backface Culling, Include
  Non-Selectable, Snap Peel Object, số bước Face Nearest.
- Kéo marker: giữ Ctrl đảo bật / tắt snap như khi G, Shift bước Increment mịn 10 lần; bước
  lưới theo zoom (ortho). Ctrl+click và vẽ chuỗi cũng rơi vào điểm snap; vẽ chuỗi có vòng
  xem trước. Solid: không bắt đỉnh / cạnh bị che; điểm trước / sau trùng nhau trên màn hình
  thì lấy điểm gần mắt.
- Số đo: bài test `snapping` 28/28, thử chuột mô phỏng 10/10 (kéo rơi đúng đỉnh, Ctrl không
  bắt, vẽ chuỗi bắt cạnh trước, tắt snap kéo tự do như cũ). Trên Mothman (2.200 đỉnh): dựng
  dữ liệu 8 ms, mỗi lần bắt dưới 8 ms.

## 1.37.1 — 2026-11-25

**Sửa foot roll chân người.**
- Thêm xương `ToeMch` giữ ngón bám đất (như chân thú): ở IK, nhấc gót bằng `Ball` thì ngón
  nằm phẳng; ở FK ngón vẫn theo bàn chân. Đo trên Mothman: trước đó ngón cắm 107 mm, giờ mũi
  chân đứng yên 0 mm.
- `Ball` cùng chiều `ToeTip`: xoay dương ở cả hai là nhấc gót (trước đây Ball phải xoay âm).
- Nút *Nâng cấp foot roll* (Sửa & kiểm tra → Driver & rig logic) cho rig dựng từ bản cũ: thêm
  `ToeMch`, đảo `Ball`, đổi dấu key cũ của Ball để chuyển động giữ nguyên (đo: lệch 0 mm).
- Khu trú weight: đáy bàn chân người chỉ thuộc `Foot` (bỏ `Shin`). Mothman: đáy gót 36% Shin
  -> 0, lăn gót thì da gót nhấc 28 mm -> 0.
- Còn lại: nhấc gót bằng Ball, da ngay trước ức bàn chân lún khoảng 36 mm do weight `Foot`.
- Test `limb_types` thêm 9 mục (45).

## 1.37.0 — 2026-11-25

**Khu trú weight và tự dọn marker.**
- Bước *Khu trú weight* tự chạy sau Bind (tắt được ở tuỳ chọn Bind), kèm nút riêng ở mục Vùng
  weight & khám. Đảo lưới rời được xét theo hình học: chỉ thuộc chuỗi phụ khi nằm dọc theo
  xương chuỗi. Chuỗi đã có lưới riêng không ăn sang lưới khác; trái không ăn phải; hai chân chỉ
  trộn ở háng. Chỉ đụng vertex có xương sai chỗ, vertex vẽ tay giữ nguyên.
- Đo trên bản sao Mothman, bind lại từ đầu: mắt dính xương râu 83% -> 0; `Ear.L` chung vertex
  với đầu 217 -> 0, với `Ear.R` 82 -> 0; weight sai bên 70 -> 2; xoay râu không kéo mắt / thân;
  giãn cạnh khi gập bắp tay x2.07 -> x1.31, đùi x1.89 -> x1.54; cánh dưới x1.62 -> x1.72.
  Trên Kid, Adult (weight vẽ tốt): đổi 2% vertex, không xương nào mất weight.
- Dựng rig + widget thành công thì xoá hết marker và collection của chúng; marker chưa ghi được
  ghi vào bộ ref trước khi dựng, dựng lỗi thì giữ marker. Bind xoá bộ ref thì marker mồ côi
  cũng bị xoá. Mở lại marker từ bộ ref giữ đúng vị trí và roll.
- Test mới `weight_localize` (10 mục); `markers` 96 mục. Chưa thử trên animation thật.

## 1.36.1 — 2026-11-23

**Sửa chuỗi đối xứng và khớp rẽ nhánh.**
- Chuỗi mọc từ giữa người rồi toả sang một bên (cánh) giờ tạo đủ hai bên; trước đây chỉ xét
  điểm gốc nên ra một bên. Đuôi vẫn là chuỗi đơn dù cong sang một bên.
- Nút *Tạo bên đối xứng* cho chuỗi đơn đã vẽ, giữ nguyên dáng và xương cha.
- Khớp rẽ nhánh: panel cho chọn từng nhánh hoặc tất cả nhánh. Xoay, căn thịt, trục gập, đổi
  cha, xoá chỉ tác động lên lựa chọn đó; trước đây chỉ tới được nhánh đầu tiên.
- Khớp cột sống có chuỗi mọc vào vẫn được ghim vào trục đối xứng.
- Đổi cha một nhánh tách khớp chung thành hai marker đúng chỗ, không mất đầu xương.
- Test `markers` 86 mục; 7 thao tác chọn nhánh bằng chuột mô phỏng đạt. Chưa thử bằng chuột thật.

## 1.36.0 — 2026-11-23

**Vẽ chuỗi xương phụ ngay trong chế độ marker.**
- Tai, Đuôi, Cánh, Tóc, Áo, Khác: click từ gốc ra ngọn, Enter để tạo. Chỉ click gốc và ngọn
  thì chia đều theo số đốt. Chuột phải bỏ khớp vừa vẽ, Esc huỷ chuỗi.
- Xương cha tự chọn: tai, đuôi, cánh, tóc bám vào thân; áo và Khác bám xương gần nhất. Đổi
  cha hoặc xoá chuỗi ở panel (cả bên đối xứng).
- Gốc lệch tâm tự tạo cả hai bên. Click đầu trúng marker có sẵn thì chuỗi rẽ nhánh từ đó.
- Trục gập tính theo dáng chuỗi vừa vẽ. Chuỗi đơn không bị ghim vào trục đối xứng.
- Unity: chế độ *Chỉ xương Humanoid* giữ lại xương chuỗi phụ (chưa đo clip animation của chúng). Đo trên bản
  sao Mothman, Unity 2022.3: Humanoid hợp lệ, 46 xương map, xương cánh giữ đúng cha, có weight.
- Sửa: vùng nút điều hướng viewport nuốt click ở góc trên bên phải.
- Test `markers` 66 mục; 11 thao tác chuột mô phỏng đạt. Chưa thử bằng chuột thật.

## 1.35.0 — 2026-11-23

**Đơn giản hoá thao tác đặt marker.**
- Một chế độ duy nhất: click chọn khớp, giữ và kéo để dời, Ctrl+click đưa khớp đang chọn
  tới chỗ click (Ctrl+Shift: trên da), chuột phải lùi, Enter ghi, Esc tạm dừng. Khớp không
  tự nhảy; panel có danh sách khớp theo bộ phận.
- Không chọn nhầm: marker nằm trong collection tắt, viewport chỉ nhận marker, panel khác ẩn
  trong lúc chỉnh.
- Chỉ cần đặt khớp chính (22 khớp với bộ người 4 ngón). Đốt sống, đốt ngón, đuôi xương đòn,
  đuôi bàn tay tự nội suy và vẫn kéo được từng đốt.
- Bộ phận nghiêng: *Căn cả chuỗi vào giữa thịt* (giới hạn độ dịch, xa quá thì giữ nguyên) và
  *Trục gập theo chuỗi*; xoay roll cả chuỗi ±5°, ±15°, ±90°.
- File lưu marker bản 1.34 tự chuyển khi mở chế độ chỉnh. Đo trên bản sao Mothman: 75 marker
  còn 67, vị trí lệch 0 mm.
- Sửa: gốc ngón và đuôi xương bàn bị tách đôi trên mesh có ma trận xoay / scale; đặt xương
  đòn kéo lệch cột sống và tay bên kia.
- Test `markers` 48 mục; 14 thao tác chuột mô phỏng đạt. Chưa thử bằng chuột thật.

## 1.34.0 — 2026-11-23

**Đặt marker theo từng khớp.**
- Module `markers`: mỗi khớp là một marker, nằm trên bộ ref. "Áp dụng" ghi vị trí và
  roll vào bộ ref, nên dựng rig, FK/IK, weight, xuất Unity đi đường cũ.
- Đặt lần lượt: click trên model, marker vào giữa khối thịt (Shift: trên da). Khớp chưa
  đặt đi theo khớp cha bằng phép đồng dạng. Đối xứng L/R khi đặt và khi kéo.
- Roll tự tính theo quy ước cố định (Y dọc xương, X là trục gập, R là ảnh gương của L),
  hiện trục trên viewport, chỉnh riêng từng xương.
- Thêm chuỗi đơn hoặc đôi L/R cho tai, tóc, đuôi, quần áo.
- Đo: bộ người 74 marker, 41 lượt đặt khi đối xứng; roll hai bên lệch 0.00000; roll tay
  30° ra 30.00°. Mô phỏng click trên bản sao Mothman, bind, import Unity 2022.3: Humanoid
  hợp lệ, 46 xương. Chưa thử bằng chuột thật.
- Test mới: `markers` (28 mục).

## 1.33.0 — 2026-11-23

**Kiểu chân (Người / Chó / Dê) và số ngón tay.**
- Chân thú giữ ba tên Thigh-Shin-Foot + Toe: `Foot` là đoạn bàn từ cổ chân sau,
  `Toe` là bàn chân / móng. Nhờ vậy FK/IK, weight, retarget, Humanoid đi chung
  đường với chân người; rig chân người không đổi.
- Control `LegIK` đặt ở chỗ chạm đất. Xương đệm `ToeMch` giữ bàn chân / móng yên
  khi xoay `Ball` để nhấc cổ chân sau (đo: móng xoay < 0.5°, dịch < 1 mm).
- Snap IK theo FK cho chân thú: đặt cả ma trận control theo `FootFK` (lệch < 1 mm,
  < 1°). Dựng lại ref từ rig giữ kiểu chân.
- Retarget: chân thú chép độ xoay, không nắn theo chân người, nên giữ dáng chữ Z;
  tỉ lệ hông đo tới chỗ chạm đất.
- Unity: không duỗi thẳng chân thú trong T-pose của Avatar (`keep_leg_rest`). Script
  import v4. Đo trên Krampus, Rake, Unity 2022.3 và 6000.3: Humanoid hợp lệ, dáng
  chân lệch 0.00°, tay vẫn ngang.
- Bàn tay 1-5 ngón, có / không ngón cái; ngón còn lại giãn đều. Picker ẩn hàng ngón
  không có.
- Test mới: `limb_types` (36 mục).

## 1.32.0 — 2026-11-18

**Retarget animation** (`retarget.py`, panel *Retarget animation* ở khu Diễn).
- Nguồn: armature bất kỳ -- Mixamo FBX, BVH, FBX khác, rig Rig Tẩm Hành khác.
  Nút *Nhập file animation* gọi importer FBX / BVH; bộ xương nhập vào mà
  hông -> đầu không chỉ lên (file Z-up / sai trục) thì tự xoay dựng đứng.
- Ghép xương: bảng Humanoid (`unityexport.auto_map`) cho cả hai bên; sửa tay ở
  text block `SRP_Retarget_Map`.
- Mỗi frame: R_đích = Δ_nguồn · A · R_nghỉ_đích (hệ thế giới), Δ_nguồn là độ
  xoay của bone nguồn so với lúc nghỉ. A nắn hướng xương lúc nghỉ CHỈ cho tay /
  chân / ngón (A-pose ↔ T-pose); thân, cổ, đầu, hàm A = 1 -- xương gốc mỗi rig
  đặt một kiểu: nắn Hips của Cat_Rig (nằm ngang) theo Hips Mixamo (dựng đứng)
  làm đường hông xoay 90° (đo được, đã bỏ). Hai bên nhìn khác hướng thì xoay
  nguồn quanh trục đứng trước. Hông dịch × (độ cao hông đích / nguồn).
- Bake: tính ma trận pose cả cây xương bằng tay (không update depsgraph mỗi
  bone), key thân / cổ / đầu / ngón / mũi chân và chuỗi FK; chi để IK thì từng
  frame `snap.snap_ik_to_fk` + key control IK, pole, chuỗi lăn chân. Action mới
  `<animation>_<rig>` có slot cho rig.
- Đo (test `retarget`, 14 mục, nguồn kiểu Mixamo dựng tại chỗ: T-pose, cm,
  scale 0.01): Mixamo / BVH / FBX -> Kid và Adult -> Kid: lệch hướng xương chi
  ≤ 0.16°, đường vai / đường hông 0.0°; chân để IK lệch 0.14°; hông dịch đúng tỉ
  lệ (0.615); đứng tại chỗ: hông đi ngang 0.
- Trên bản sao Cat.blend (chibi, tỉ lệ hông 0.51): lệch hướng chi 0.0°, đường
  vai / hông 0.0°, khớp cổ chân không thấp hơn lúc nghỉ (0.045 / 0.046 m).

## 1.31.0 — 2026-11-18

**Rào weight theo vùng + Khám weight** (`weightfence.py`). Automatic weights và
Delta Mush chỉ nhìn khoảng cách và độ mượt nên không chặn được lỗi "dính sai
vùng" -- gặp trên con mèo: vai ăn lên má, hàm ăn ra sau gáy / xuống ngực, đùi
bên này ăn sang chân bên kia.
- Vùng của xương theo cấu trúc rig (đầu = xương đầu + con cháu; chi = chuỗi
  `rigdef.limbs_for` + xương gốc chi leo lên tới chỗ nhánh có chi khác / đầu;
  cổ = leo lên từ đầu tới chỗ có chi; còn lại là thân). Cầu nối: cổ vào đầu;
  vai, đùi, xương gốc chi, đầu vào thân; 2 xương deform thân gần chỗ chi bám
  vào chi (Hips / Hip_Master không deform chỉ là chỗ đi qua); đầu vào tay; hai
  chân trộn trong dải giữa háng (0.25 khoảng cách hai khớp háng); vai / tay /
  xương thân chỗ bám được ăn vertex đầu sát xương vai (dưới 1.0 lần khoảng
  cách vai -> khớp đầu; đo: cổ mèo 0.5–0.9, má mèo ≥ 1.3, má Adult ≥ 1.56).
  Hàm: theo khớp hàm, bớt dần từ 0.3 tới 0.45 chiều dài hàm phía sau khớp, từ
  0.3 tới 0.65 phía trên, từ 0.6 tới 1.0 phía dưới; phần thừa về xương cha.
- Vùng của vertex: vùng có tổng weight lớn nhất, attribute INT `srp_region`,
  tự tính cuối Bind; gán / chọn vùng trong Edit Mode.
- **Rào weight theo vùng** (mục mới trong *Sửa weight…*): chỉ sửa vertex phạm
  luật (vertex vẽ tay giữ), làm mượt quanh chỗ gỡ đi ≥ 0.05, tối đa 4 xương,
  normalize các vertex đã sửa. Đo:
  - Adult sạch (đã vẽ tay): 4 vertex đổi, lệch tối đa < 0.02 (vụn 0.001 của hàm ở vai);
  - Con mèo đã sửa tay (bản sao Cat.blend): 0 vertex đổi;
  - cấy lại lỗi của con mèo vào bản sao: nhún vai má bị kéo 3.9 cm -> 0,
    há miệng sau gáy 5.7 cm -> 0, ngực 6.9 cm -> 0 (184 vertex sửa);
  - Adult cấy lỗi (vai lên má, hàm ra sau gáy, đùi trái sang chân phải): khám
    tĩnh và khám tư thế đều thấy; rào xong nhún vai / há miệng: 0.00 mm.
- **Khám weight** (hộp *Vùng weight & khám*): kiểm tĩnh + ~40 tư thế của
  `bakeweights.training_poses` cộng há miệng (tính skin bằng ma trận, không
  đụng pose rig, ~1 s trên Adult). Báo cáo ở text block `SRP_Weight_Check`.
- Test mới: `weight_fence` (19 mục).

## 1.30.0 — 2026-11-16

**Unity: sửa lỗi FBX ra Generic và T-pose sai.** Script import viết lại (v3).
- T-pose hỏng: node armature trong FBX mang đúng tên nhân vật -- trùng tên node
  gốc Unity đặt theo tên file. Unity khớp transform theo tên nên lấy nhầm node
  gốc, tư thế tham chiếu của Avatar bị xoay (đo, Unity 2022.3: hướng đùi y = 0,
  tức chân nằm ngang). Nay node armature tên `<tên>_Armature`; script Unity gặp
  file cũ còn trùng tên thì báo lỗi, không dựng Avatar sai.
- Generic: bản cũ dựng Avatar bằng `delayCall` đặt trong `OnPostprocessModel`.
  Unity import song song (AssetImportWorker -- có trong project thật) thì hàm đó
  chạy ở tiến trình phụ, `delayCall` không về editor chính. Nay dựng trong
  `OnPostprocessAllAssets` (luôn ở editor chính), từ mô hình đã import xong.
- json tới sau FBX (Unity đang mở lúc Blender ghi, hoặc chép từng file): json
  tới là FBX cùng nhóm được import lại. Blender cũng ghi json TRƯỚC FBX.
- File animation không tự dựng Avatar từ frame đầu của clip khi import trước mô
  hình nữa: đợi mô hình dựng xong rồi chép Avatar đó.
- Còn script import Humanoid khác: hỏi xoá (không hỏi trong batchmode).
- Menu *Assets → Rig Tẩm Hành → Dựng lại Avatar Humanoid*; Avatar không hợp lệ
  thì Console báo.

**Mesh xuất** (`scope`): mọi mesh của rig / mesh đang chọn / mesh đang hiện /
mesh trong một collection. Mesh có key chạy bằng driver mà mesh nó bám không
được xuất thì xuất riêng (key đứng yên).

**Bộ action** (giống action collection): bộ có tên, lưu trên rig, mỗi bộ một
file `<tên>@<bộ>.fbx` mỗi action một take; json ghi `sets` và `file` của từng
clip để Unity đặt tên clip theo take.

Test: `unity_sets` (15 mục). Kiểm trong Unity 2022.3.62 và 6000.3.9 (project
nháp, batchmode), cả hai giống nhau:
- chép cả nhóm (mỗi clip một file / theo bộ / gộp): mô hình Human, Avatar hợp
  lệ; file clip / bộ CopyFromOther đúng Avatar mô hình; take đặt tên đúng action;
- import ở tiến trình phụ (OutOfProcessPerQueue): như trên;
- json tới sau FBX: trước Generic, json tới -> Human;
- tư thế tham chiếu Avatar: hướng cánh tay / cẳng tay / ngón y = 0.00, đùi /
  cẳng chân y = -1.00 (bản 1.29 trên cùng file: đùi y = 0.00);
- còn script import cũ: FBX để Generic, Console chỉ đúng file script; xoá xong,
  menu Dựng lại -> Human.

## 1.29.0 — 2026-11-13

**Face rig bằng bendy bone** (`facebendy.py`, nút trong khu *Mặt*): điều khiển
biểu cảm hoàn toàn bằng xương, không shape key, vẫn xuất được sang game engine.
- Mày (3 control), mí trên / mí dưới (3 control, góc mí dùng chung), môi trên /
  môi dưới (5 control, khoé dùng chung) thành chuỗi bendy bone 8 đoạn, handle
  ABSOLUTE nối các đoạn liền nhau. Xương deform mặt gắn vào khớp nối
  (`FSk_*`, Copy Transforms + Follow B-Bone) đặt đúng điểm đường cong lúc nghỉ.
- Môi dưới theo Jaw, khoé miệng theo Jaw 50% (đo: hàm 15° -> khoé đi ~43% môi dưới).
- Mí: xương mí treo dưới cần xoay từ tâm nhãn cầu (`FMch_LidAim_*`, Damped Track
  vào đường cong) và cần đẩy ra (`FMch_LidPush_*`, driver theo góc quay, 0.2 bán
  kính / radian). Đo trên Adult, nhắm mắt hết khe: kéo thẳng như các đường khác
  thì da mí cắt qua nhãn cầu; chỉ xoay (không đẩy) còn 8 vertex lọt vào mắt
  sâu > 1 mm; xoay + đẩy: 0–2. Đã thử và bỏ: Shrinkwrap lên mesh mắt (mesh mắt
  nhiều lớp, bám nhầm lớp trong), Limit Distance (chỉ dời xương, da vẫn cắt).
- Tư thế nghỉ lệch 0.0002 mm, weight không đổi vertex nào.
- Xuất FBX (tắt *Chỉ xương Humanoid*): xương mặt là con của Head, mở lại FBX
  thấy Lip_Upper_Mid đi 2.90 mm khi control kéo 3 mm; không có xương `FCtl_` /
  `FBB_` / `FSk_` / `FMch_` trong file.
- Gỡ: xương mặt về cha cũ, xoá control / đoạn / khớp nối / driver; khám rig 0
  lỗi cả khi có và khi đã gỡ lớp bendy.
- Test mới: `face_bendy` (12 mục, gồm nhắm mắt), `face_bendy_remove` (5 mục).

## 1.28.0 — 2026-11-12

**Dễ dùng hơn: gom nút, hỏi lại trước khi ghi đè, thanh "Bước tiếp theo"**
(`ux.py`). Các toán tử cũ vẫn còn (script / bài test gọi thẳng), chỉ không bày
trên panel.
- **Sửa weight…** (`srp.weights_fix`): một menu thay 5 nút -- Tự làm mượt weight
  các khớp (Delta Mush), Sửa hông / gối / khuỷu, Sửa hông và gối, Lấp chỗ thiếu.
- **Cập nhật quần áo** (`srp.cloth_update`): thay "Bind quần áo" + "Cập nhật
  weight từ thân". Bind món mới / gắn cứng / automatic, chép weight thân (đúng
  như đang có) sang món chép-từ-thân và lông mày; "Sửa da dưới áo theo áo" nằm
  trong hộp thoại, ghi rõ là đổi weight thân (vertex vẽ tay giữ). Không còn dải
  hông / gối riêng trên quần áo (đo trước đây: chép thẳng ít đâm xuyên hơn).
- Lông mày / râu rời tự bám da sau **Dựng bộ shape key** và **Pose → Shape key**
  (tuỳ chọn, mặc định bật); mesh phụ ghi lại bộ key đã bám (`srp_follow_keys`).
- Hỏi lại trước khi ghi đè: Bind mesh thân (khi đã bind: báo mất weight + số
  vertex vẽ tay), Dựng bộ shape key (khi đã có: số key của addon bị dựng lại /
  key làm tay được giữ), các mục tính lại weight của "Sửa weight…".
- Thanh **Bước tiếp theo** dưới thanh khu: bước dựng còn thiếu -> quần áo chưa
  bind -> thân sửa weight, quần áo chưa cập nhật -> lông mày chưa bám key mặt
  mới -> (tuỳ chọn) dựng shape key mặt -> sẵn sàng xuất. Bấm là mở đúng chỗ / làm.
- Đổi tên cho dễ hiểu: Tự làm mượt weight các khớp, Lông mày / râu rời bám da,
  Đánh dấu vùng mặt, Đo khuôn mặt (tự động), Bind mesh thân, Chỉnh lại vị trí
  xương của rig, Tìm animation trỏ vào xương đã mất, Sửa animation theo bảng đổi
  tên, Sửa tay bảng ghép xương Humanoid. Viết lại hướng dẫn "?" của quần áo và
  trọng số.
Bài `ux` (14/14): Sửa weight… giữ 644 vertex vẽ tay; Cập nhật quần áo bind món
mới, thân không đổi khi tắt sửa da, bật thì 275 vertex da đổi và vertex vẽ tay
giữ; thanh gợi ý đúng việc; Pose -> Shape key xong lông mày hết bị báo.

## 1.27.0 — 2026-11-07

**Xuất Unity: chọn clip nào xuất** (`unityexport.rig_clips`, `srp.unity_clips`).
- Mục animation "Các clip được tích" (thay "Mọi action của rig") hiện danh sách
  clip của rig kèm ô tích, khoảng frame, dấu ▶ ở clip đang gán, nút tích hết /
  bỏ hết, và "xuất N / M".
- Danh sách đọc theo SLOT của action: slot rig đang / đã dùng (`slot.users()`),
  slot trùng tên rig, hoặc slot OBJECT có từ một nửa kênh trỏ vào bone có thật
  của rig. Action chỉ có slot shape key, hay slot của object khác, không hiện.
  Trước đây chỉ đoán theo tên bone trong toàn action.
- Ô tích là thuộc tính của chính action (`Action.srp_unity_export`, mặc định
  bật) -- lưu trong file, mở lại vẫn nhớ; file cũ xuất y như trước.
- `compat.action_slot_for` ưu tiên slot mà chính rig đang dùng, nên lúc xuất
  gán đúng slot đã hiện trong danh sách.
- "Kiểm tra Humanoid" ghi số clip xuất / tổng và tên clip bị bỏ.
Bài `unity_clips` (10/10): 4 action (slot đang dùng, slot trùng tên, slot lạ có
kênh bone, slot object khác) -> danh sách đúng 3; bỏ tích 1 -> file riêng chỉ
ra 2 clip, json và chế độ gộp cũng 2; bỏ hết -> chỉ mô hình; rig được trả lại
đúng action + slot đang gán.

## 1.26.0 — 2026-11-07

**Mesh phụ bám da** (`followkeys.py`, nút "Mesh phụ bám da" ở khu Mặt).
- Lỗi: "Thử biểu cảm" chỉ đặt slider trên mesh mặt; lông mày rời đi theo bằng
  driver nhưng chỉ có 8 key BRW_* (chép từ Kid). Adult: EYE_Blink kéo da dưới
  lông mày 16-22 mm, EYE_Squint 9.7 mm, EYE_Wide 4.8 mm -- lông mày đứng yên,
  tách / lún khỏi da; 8 key BRW_* cũng lệch da 3.9-8.7 mm.
- Neo từng vertex mesh phụ vào điểm da gần nhất (tam giác + trọng tâm) kèm
  khoảng hở trong khung tam giác; mỗi key của mặt: dời theo điểm neo, khoảng hở
  xoay theo da. Key thiếu thì tạo kèm driver, key có thì ghi lại theo da. Chỉ
  dùng dữ liệu shape key, không pose rig. Mesh phụ = mesh đang chọn, không chọn
  thì lông mày (vai trò BROW / mesh phụ khớp theo mẫu).
- Tuỳ chọn "Làm mượt" (mặc định 0). Da giãn thì lông mày giãn theo: nhắm mắt
  dày x1.25, nhướng mày x1.34. Làm mượt bớt giãn nhưng hở khỏi da: nhắm mắt 4
  lượt x1.21 / hở 2.0 mm, 25 lượt x1.10 / 3.8 mm.
Đo (bài `follow_skin`, khoảng cách lông mày tới da so với lúc nghỉ, tệ nhất
qua 56 key / 15 biểu cảm mẫu): trước 6.29 mm (EYE_BlinkL, "Nhắm mắt") -> sau
0.70 mm. File Kid_Base_1: lông mày Adult 8 -> 16 key (thêm EYE_Blink / Squint /
Wide, MTH_Smile; ghi lại 8 BRW_*).

## 1.25.0 — 2026-11-07

**Pose → Shape key: "Chỉ xương đang chọn"** (`posekey.py`).
- Chỉ lấy pose của các xương đang chọn; xương mặt khác (kể cả đang pose) tạm
  về rest lúc đo. Tách key trái / phải: pose cả hai bên, chọn bên trái nướng
  key trái, chọn bên phải nướng key phải. Nướng xong CHỈ xương đã dùng về rest,
  bên còn lại giữ pose. Hộp thoại ghi lấy bao nhiêu / bỏ qua xương nào; tự bật
  khi đang chọn một phần các xương đã pose. Không chọn gì thì báo lỗi.
- Đọc chọn qua `context.selected_pose_bones`, ngoài Pose Mode thì `PoseBone.select`
  (Blender 5.2 bỏ `Bone.select`).
- Vùng một bên = vertex có weight của xương bên đó. Xương mày trong cùng có weight
  lan qua giữa trán thì key bên đó cũng kéo phần giữa trán ấy -- đúng như weight.
Đo trên Kid (bài `posekey_split`, 4 xương mày mỗi bên): key trái động 8.15 mm ở
vùng mày trái, ngoài vùng 0.00000 mm; key phải 8.26 mm / 0.00000 mm; trái +
phải lệch 0.0003 mm so với nướng cả hai; tắt tuỳ chọn: y hệt trước (0.00000 mm).

## 1.24.0 — 2026-11-07

**Avatar Unity dựng từ T-pose** (script `RigTamHanhHumanoidImporter.cs`, tuỳ
chọn xuất "Avatar theo T-pose", mặc định bật).
- Avatar Humanoid trước đây lấy tư thế nghỉ trong Blender làm tư thế tham chiếu.
  Tư thế đó hơi chữ A, gối hơi gập, ngón hơi cong -- Unity coi đó là "T-pose",
  nên mọi animation retarget sang lệch một góc cố định (giống khi bỏ qua nút
  Enforce T-Pose của Unity).
- Script giờ tự đưa khung xương tham chiếu về T-pose trước khi dựng Avatar:
  bắp tay, cẳng tay, bàn tay, bốn ngón (trừ ngón cái) thẳng ngang theo hướng
  vai; đùi, cẳng chân thẳng đứng. Chỉ xoay quanh đầu xương, cha trước con;
  cây transform trả lại ngay -- mô hình import ra vẫn đúng dáng Blender.
- Dấu import lên `v2`: FBX đã import bằng script trước tự dựng lại Avatar một
  lần khi có script mới. Bỏ nhận dấu của script bản cũ; thay vào đó, project
  còn một script `*HumanoidImporter` khác thì script mới báo lỗi và không xử lý
  (hai script đóng dấu khác nhau sẽ import lại nhau vô tận).
- Json: `keep_rest_pose` = true thì giữ cách cũ.
Đo trong Unity 2022.3.62f2 (batchmode, project thử riêng): tư thế tham chiếu
lệch khỏi T-pose -- cũ: bắp tay 5.8° (Kid 7.1°), cẳng tay 3.9°, bàn tay 9.6°,
ngón 16.9°, cẳng chân 4.9°; mới: 0.0° mọi đoạn, cả Adult lẫn Kid. Animation
Wave của Kid chạy trên Adult so với chính Kid, góc lệch lớn nhất: cũ 1.4°
(bắp tay), mới 0.0° (6 đoạn tay/chân). Dáng mô hình import ra như nhau ở hai
cách. Có script import thứ hai: báo lỗi 1 lần, không import lại.

## 1.23.0 — 2026-11-04

**Đổi tên: Rig Tẩm Hành.** Tác giả: Chú Pen Tẩm Hành.
- Thư mục / module addon: `rig_tam_hanh`. Cài từ zip mới rồi bật lại trong
  Preferences; tuỳ chọn trong Preferences của addon về mặc định.
- Tab N-panel, tên khối text (`RigTamHanh_KhamRig`, `RigTamHanh_Remap`), log.
- Script Unity: `RigTamHanhHumanoidImporter.cs`, vào `Assets/Editor/RigTamHanh`.
  Project Unity đã có script import bản cũ thì xoá file cũ đi; script mới vẫn
  nhận dấu import của bản cũ nên không import lại vô tận nếu lỡ còn cả hai.
- KHÔNG đổi: định danh nội bộ lưu trong file .blend (`srp_generate`, các thuộc
  tính `srp_*`, toán tử `bpy.ops.srp.*`) -- đổi là file đã rig mất thiết lập
  và dấu vẽ tay.
- README: giới thiệu + hướng dẫn kèm ảnh chụp màn hình (`docs/images/`).

## 1.22.0 — 2026-11-04

**Tối ưu weight (Delta Mush)** -- `bakeweights.py`, `srp.bake_weights`, nút
trong panel Sửa > Trọng số skin. Tuỳ chọn, không tự chạy.
- Cho rig qua 39 tư thế (tay, chân hai bên, lưng, cổ) tính thẳng bằng ma trận
  -- không pose rig, không đụng constraint. Lấy hình Delta Mush (Corrective
  Smooth 20 vòng, qua shape key + ORCO trên mesh tạm) của weight hiện có, rồi
  mỗi vertex giải NNLS: weight không âm, tổng 1, tối đa 4 xương (tuỳ chọn 8),
  kéo nhẹ về weight cũ / trung bình hàng xóm (3 lượt). Đích bị Delta Mush tự
  gập (co giãn lớn) tính nhẹ đi; xương chi ở xa bị loại; gập gối/khuỷu trong
  tập học tối đa 100°.
- Làm mượt cục bộ quanh GỐI sau khi nướng: nướng làm vùng Thigh -> Shin quá
  gắt (vertex cách khớp 1.6 cm đã 97% một xương), gập 130° khoeo bật ra một
  mẩu lưới. Không làm ở khuỷu: lưới méo khuỷu 19% -> 30%.
- Vertex vẽ tay giữ nguyên; xong thì báo quần áo cần "Cập nhật weight từ thân".
Đo trên Adult, bắt đầu từ weight tự động của addon, so với weight người dùng
vẽ tay (8 tư thế thử tay/chân trái): lệch vai/nách 10.4 -> 7.9 mm, hông/mông
19.2 -> 15.3 mm (p95 100 -> 51 mm), vùng người dùng đã sửa 6.4 -> 5.1 mm, gối
0.9 -> 1.4 mm; tam giác gập ngược khi gập gối 130°: 7 -> 6. Còn: lòng khuỷu
gập 130° 11 tam giác gập ngược (tay vẽ 12, addon 8). 3 giây trên 3381 vertex.
Đã thử 13 biến thể trong phòng thử; đây là bản chọn. Hồi quy: 22/22, 15/15,
9/10 (bài áo Kid vẫn lỗi cũ 7 vs 5).

## 1.21.0 — 2026-11-04

**Cập nhật weight từ thân** (`srp.sync_from_body`, `cloth.sync_from_body`).
- Thân là nguồn chuẩn, KHÔNG bị sửa: không da-theo-áo, không dải hông/gối
  trên đồ. Áo, quần, giày (Chép từ thân) chép lại như bind; lông mày (vai trò
  BROW, hay mesh phụ khớp theo mẫu) chép từ da trán, chỉ trên xương nó vốn
  dùng, không làm mượt, tối đa 8 xương; tóc gắn cứng chỉ chép khi bấm "+ Tóc"
  (xương mặt dồn về Head). Mắt, răng, lưỡi bỏ qua. Vertex vẽ tay trên đồ giữ.
- `transfer(current=True)`: đọc weight thân đang có. Trước đây chép từ thân
  luôn thay 266 vertex da dưới áo bằng bản "da gốc" cũ -- người dùng vẽ lại
  thân xong, bind quần áo vẫn lấy weight cũ ở đó. Sync xong bỏ bản "da gốc".
- Mỗi phiên vẽ có đổi tăng `srp_wstamp`; sync ghi `srp_synced`. Khác nhau thì
  panel quần áo và panel sửa weight báo "<thân> đã sửa weight, quần áo chưa
  cập nhật". "Bind mesh" đánh dấu là đã đồng bộ.
Adult: thân không đổi 1 vertex (644 vertex vẽ tay giữ), áo 454/624, quần
156/236, giày 138/138 x2, lông mày 106/106 vertex đổi; khe lông mày-da khi
dời xương mày 5.44 -> 5.46 mm. Da đâm xuyên đồ qua 8 tư thế: 431 (chép theo
"da gốc" cũ: 425; bind cũ có dải: 440). Kiểm: 13/14 (mục hỏng là kỳ vọng sai:
tóc ngắn chép từ thân ra đúng 100% Head). Hồi quy: 22/22, 15/15, 9/10 (bài
áo Kid vẫn lỗi cũ 7 vs 5).

## 1.20.0 — 2026-11-04

**Giữ weight vẽ tay** (`cloth.HAND_KEY`, `keep_hand`, `_watch_modes`).
- Vào Weight Paint / Edit Mode của mesh skin vào rig: chụp weight; ra: vertex
  nào đổi được đánh dấu "vẽ tay" (lưu trên object, `srp_handpaint`). Đổi số
  vertex (tách/xoá) thì bỏ đánh dấu -- chỉ số cũ vô nghĩa.
- "Sửa weight hông, gối, khuỷu" (cả hai chế độ) và "Bind quần áo" ghi lại
  nguyên giá trị cũ cho vertex vẽ tay sau khi chạy, và bỏ chúng khỏi bản "da
  gốc" để da-theo-áo về sau không khôi phục đè lên. Quần áo vẫn bind lại, chép
  từ thân -- tức là chép luôn weight vẽ tay của thân (áo len Adult đổi 578
  vertex theo nách/khuỷu mới).
- "Bind mesh" (bind lại từ đầu) bỏ hết đánh dấu: weight cũ không còn.
- Panel sửa weight: hiện số vertex đang giữ, nút "Thôi giữ weight vẽ tay".
- Adult: đánh dấu sẵn 464 vertex người dùng đã vẽ (nách, khuỷu, cổ, bàn tay),
  tìm bằng cách dựng lại kết quả 1.19.4 rồi so với file.
Kiểm: hip_weights(ALL) đổi 128 vertex khác, 464 vertex vẽ tay giữ y hệt;
cloth_bind giữ y hệt; phiên vẽ 5 vertex -> đánh dấu 469; vào/ra không vẽ ->
không thêm. Hồi quy: 22/22, 15/15, 9/10 (bài áo Kid vẫn lỗi cũ 7 vs 5).

## 1.19.5 — 2026-11-03

**Khoeo chân, mông mềm hơn; sửa chân không đè weight tay tự vẽ.**
- Gối (`JOINT_IN/OUT/SMOOTH_R` 2/3/3% -> 5/5/6%): gập 90-130° khoeo Adult là
  khía chữ V sắc, Kid là nếp tròn. Đã thử 3/4/4.5%, 4/4.5/5.5%, 5/5/6%: 5/5/6%
  khoeo cong mềm, gối tròn khi ngồi xổm, bắp chân không móp.
- Mông (`HIP_BACK` (0.05, 0.07) -> (0.06, 0.09)): giơ chân 90° nếp mông-đùi bớt
  gãy, mông tròn như Kid; lùi chân 35° không đổi.
- `srp.hip_weights(part='LEGS')` -- nút "Chỉ hông và gối (giữ weight tay)":
  không chạm khuỷu, chỉ bind lại quần áo ở chân (quần, giày), da-theo-áo chỉ
  làm lại ở vùng chân (`skin_follow(zone=)`). Adult sau khi người dùng tự vẽ
  nách/khuỷu (464 vertex): 227 vertex thân đổi, 0 vertex dính xương tay/cổ,
  áo len giữ nguyên.
- `hip_band` / `joint_band` chỉ bỏ bản "da gốc" của vertex vừa đặt lại
  (`_forget_skin`), không xoá cả bản: trước đây lần bind sau khôi phục/đè mất
  weight ở chỗ khác.
Hồi quy: 22/22, 15/15, 9/10 (bài áo Kid vẫn lỗi cũ 7 vs 5).

## 1.19.4 — 2026-11-03

**Khớp vai theo gốc tay, không theo nách** (`fitref._arm_root`, `ROOT_SLOPE`).
1.19.3 vẫn để vai Adult ở 0.177: hạ tay 84°, cánh tay hở khỏi thân, đỉnh vai
gãy góc -- Kid thì tay ôm sát, vai tròn. Nách Adult là một sườn dốc ~45° dài
4 cm; neo theo nách (hay theo chỗ dốc 45°: ra 0.181) đều trôi ra ngoài. Giờ dò
chỗ mặt dưới tay hết dựng đứng (dốc < 2:1) và tâm/độ dày ống tay; đặt đầu
Bicep so với mốc đó như ở mẫu, co giãn theo độ dày ống tay. Kid: mốc 0.133,
khớp 0.137. Adult: Bicep 0.177 -> 0.155, z 1.362 -> 1.365. Đã thử tay 0.177 /
0.163 / 0.150 / 0.150 hạ 1.2 cm: 0.150-0.155 giống Kid nhất. Hồi quy 22/22.

## 1.19.3 — 2026-11-03

**Khớp vai bám nách** (`fitref._armpit`, `place_ref`). Adult: đầu Bicep đặt ở
x = 0.208, cách nách 6.5 cm. Kid chỉ cách 1.4 cm, nên vai Adult gập lệch ra
ngoài khi hạ tay. Giờ dò nách bằng tia dọc từ dưới cánh tay lên, dùng nó làm
mốc ở lượt khớp 2 (knot x/z + landmark L/R), rồi đặt đầu Bicep theo khoảng cách
nách của mẫu, co giãn theo đoạn nách -> khuỷu. Adult: Bicep 0.208 -> 0.177
(nách 0.144). Hạ tay 75°, giơ 60°, đưa trước 70°: vai tròn, không gãy. Fit
trung bình 1.01 mm. Hồi quy: 15/15, 9/10 (bài áo vẫn lỗi cũ 7 vs 5), 22/22.

## 1.19.2 — 2026-11-03

**Khuỷu tay mềm hơn gối** (`ARM_IN`, `ARM_OUT`, `ARM_SMOOTH_R`). Dải chung với
gối (trong 2%) làm lòng khuỷu áo len Adult thành một bậc gắt khi gập 90°. Khuỷu
giờ có dải riêng: trong 5%, ngoài 4%, làm mượt cục bộ trong 6% chiều cao. Đã thử
3.5% / 4.5%: còn gợn. Gập 90° và 130°: lòng khuỷu thành đường cong trơn. Gối
giữ nguyên. Hồi quy: 15/15, 9/10, 22/22.

## 1.19.1 — 2026-11-03

**Làm mượt cục bộ nếp khoeo / lòng khuỷu** (`joint_band`). Dải gắt ở mặt
trong đổi gần hết 0 -> 1 qua một vòng vertex trên lưới thưa: nếp gối răng cưa,
có ô quần gập ngược. Giờ sau khi đặt dải, tỉ lệ xương trên/dưới được trộn với
hàng xóm 6 lượt -- CHỈ ở mặt trong, trong 3% chiều cao quanh khớp, chỉ qua cạnh
ngắn, mép vùng trộn một nửa. Không nới dải (nới thì khoeo móp lại). Adult gập
gối 130°: 3 lượt còn ô gập, 6 lượt hết, bắp chân vẫn đầy; ngồi xổm, khuỷu mượt.
Hồi quy: 15/15, 9/10, 22/22.

## 1.19.0 — 2026-11-03

**Khoeo / lòng khuỷu không móp khi gập sâu** (`cloth.joint_band`).
- Ngồi xổm, gập gối 130° trên Adult: khoeo móp hẳn vào, bắp chân teo. Weight
  gối chép từ Kid trộn đều quanh cả vòng khớp và rộng quá mức: cách gối 10 cm,
  bắp chân vẫn 28% Thigh. Vertex khoeo 50/50 rơi vào giữa dây cung khi gập.
- Dải xương trên <-> xương dưới ở gối và khuỷu: mặt TRONG (khoeo, lòng khuỷu)
  nửa rộng 2% chiều cao, mặt NGOÀI (bánh chè, khuỷu) 3%. Mặt trong lấy ngược
  hướng pole -- dùng chung cho chân và tay. Ngoài 9% quanh khớp tắt dần.
- Đã thử trong 0.6% / ngoài 3.5%: lưới quần thưa (vòng cách 2-4 cm) gập ngược
  thành lỗ ở nếp gối. Trong 2%: còn một ô quần gập nhỏ đúng nếp gối khi gập
  sâu (vải ép vào nhau).
- Bind quần áo tự áp dải này cho quần áo; nút "Sửa weight hông, gối, khuỷu"
  (đổi tên từ "hông & mông") áp cho thân. Adult: 232 vertex thân, quần 74,
  áo len 100. Hồi quy: test_overall 15/15, test_cloth 9/10, test_adult 22/22.

## 1.18.2 — 2026-11-03

**Cẳng quần teo dưới gối khi giơ chân** (`cloth.limb_cull`, `smooth`).
- Gập gối 118° (IK): cẳng quần Adult thắt lại ngay dưới gối. Vòng vertex giữa
  cẳng quần mang 73% Shin + 15% Thigh + 12% Foot. Nguồn: chép từ da = nội suy
  trong tam giác da, mà cẳng chân thân Adult gần như chỉ có vòng gối (Thigh
  0.43) và vòng cổ chân (Foot 0.3) -- da không sao (giữa hai vòng không có
  vertex), quần có vòng giữa thì nhận weight trộn.
- `limb_cull`: sau khi chép, xương CHI (Thigh/Shin/Foot, Bicep/Forearm/Hand) chỉ
  giữ weight nếu đoạn xương không xa hơn đoạn gần nhất quá 2-6% chiều cao. Giữa
  cẳng: Thigh cách 22 cm, Shin 7 cm -> bỏ Thigh/Foot, còn Shin 1.0. Vòng gối,
  cổ chân vẫn trộn. Xương thân không đụng (dải hông của hip_band giữ nguyên).
- `smooth` trộn hàng xóm theo khoảng cách: cạnh dài hơn 4% chiều cao không
  trộn (lưới quần thưa nối thẳng vòng gối với vòng cổ chân).
- Hồi quy: test_overall 15/15, test_cloth 9/10, test_adult 22/22; hông giữ nguyên.
- Còn: gập gối sâu, da ngay dưới khớp hẹp còn ~90% bề ngang (hao hụt thể tích
  của skin tuyến tính, nằm dưới quần).

## 1.18.1 — 2026-11-03

**Quần / quần short theo đùi khi giơ chân cao** (`cloth.pants_top`,
`hip_band(top=...)`, gọi trong `bind_all`).
- Quần short Kid giơ chân 60-90°: đùi xuyên ra trước quần. Ống quần đã 100%
  Thigh; thủ phạm là mảng quần trước bụng CAO HƠN khớp -- chép từ da háng nên
  đi theo Pelvis, mặt trên đùi quét lên đúng chỗ đó. Nới dải của da (3 bản
  thử) không đổi gì.
- Bind quần áo giờ nhận ra món nào là quần (weight Thigh > 0.5 ở >= 5% vertex,
  cạp cao hơn khớp đùi < 25% chiều cao) và đặt dải Thigh <-> hông theo CHÍNH
  cái quần: tâm 40%, nửa rộng 30% quãng khớp -> cạp -- mép trên luôn dưới cạp.
  Dải cố định theo chiều cao thì với tới cạp: hở da ở cạp; cạp quần Adult chỉ
  cao hơn khớp 10 cm.
- Chỉ THÊM weight Thigh, không bớt: bớt là phía sau quần Adult (đã chép weight
  da mông theo đùi) đứng lại, mông đâm qua, hở da dưới gấu áo len.
- Giữ chuẩn 4 xương / vertex cho quần áo (bản đầu ra 5, test_cloth bắt được).
- Chạy trước "da dưới áo đi theo áo", nên da dưới quần lấy weight mới.
- Kid (short, 297 vertex), Adult (pants, 97 vertex). Hồi quy: test_overall
  15/15, test_cloth 9/10, test_adult 22/22.
- Còn: Kid giơ chân 90° hở một chấm da nhỏ ở mép cạp phía trước.

## 1.18.0 — 2026-11-03

**Nút "Sửa weight hông & mông"** (khu Sửa › Trọng số skin, `cloth.hip_band`).
Giơ chân cao trên Adult: háng trước gập thành khe, mông gãy thành gờ có góc
nhọn, quần gãy theo. Weight hông chép từ Kid: mông chỉ 20-45% Thigh -- nửa sau
đứng yên khi đùi quay. (Thêm: lưới quần thưa, cạnh 6-19 cm, làm mượt loang
Pelvis xuống giữa đùi, da dưới quần nhận lại chính weight đó.)
- Đặt lại dải chuyển Thigh <-> hông quanh mỗi khớp đùi theo chiều cao nhân
  vật: trước tâm +0.5%, nửa rộng 2.5% (hẹp, ngay nếp háng); sau tâm +5%, nửa
  rộng 7% (rộng, lệch lên -- mông quay một phần theo đùi). Phần không thuộc
  Thigh chia lại cho Pelvis/Hips/Spine theo tỉ lệ cũ; ra xa khớp thì tắt dần.
- Bỏ qua vertex mang weight chi khác (chân kia, cẳng chân, tay) hay của đầu.
  Xoá bản lưu da-gốc, tự bind lại quần áo. Ctrl+Z hoàn tác.
- Adult: 141 vertex; Kid: 131. Giơ chân 90° / 60° co gối: háng trơn, mông tròn
  cả hai nhân vật; ngồi xổm, bước đi, cúi, đá ra sau không đổi. Hồi quy:
  test_overall 15/15, test_cloth 9/10 như trước.
- Còn biết (có sẵn, không do nút này): quần short Kid giơ chân 60-90° thì đùi
  xuyên ra trước -- mảng quần trước háng lấy weight Pelvis của da háng, ống
  quần xoè rộng; ống quần đã 100% Thigh.

## 1.17.4 — 2026-11-03

**Khớp theo mẫu: Hips quá thấp, gối choãi** (`fitref`).
- Thân cũng là ống trơn như chân: Hips Adult chỉ cao hơn đáy quần 1.8 cm (Kid
  6.4 cm = 14% quãng đáy quần -> cổ). Giờ khớp HAI LƯỢT: lượt 1 tìm khớp được
  hình dạng neo chắc (Head; vai, cổ tay của tay trái), lượt 2 khởi đầu bằng co
  giãn từng đoạn qua các mốc đó theo cả chiều cao lẫn chiều ngang. Adult: Hips
  0.863 -> 0.944; Hips/Spine.001/.002/.003 ở 14/30/47/65% quãng (Kid 12/28/46/65%).
  Chậm gấp đôi (~40 s).
- Lượt 2 dời đầu đùi vào trong 1 cm, gối lệch ra ngoài 5 mm so với đường hông
  -> cổ chân: mặt phẳng gập nghỉ xoay 42°, pole IK hiệu chỉnh theo đó -> ngồi
  xổm hai gối choãi. `place_ref` giờ đặt khớp giữa của mỗi chi (gối, khuỷu) với
  hướng lệch khỏi đường gốc -> ngọn lấy theo MẪU, chỉ vị trí dọc chi theo phép
  khớp. Hướng gối gập khi ngồi xổm: x 0.65 -> 0.01 (thẳng ra trước).
- Adult_Rig trong file đã cập nhật tại chỗ (ref_apply + chép lại weight + bind
  lại quần áo), shape key không đụng. Khám rig 0 lỗi, FK/IK đạt.

## 1.17.3 — 2026-11-03

**Khớp theo mẫu: hông, gối đặt sai** (`fitref.solve`). Người dùng thấy trên
Adult_Rig: hông tụt hẳn xuống, gối gập sai chỗ, gối mesh đâm qua quần.
- Chân là ống trơn: bề mặt không nói được khớp nằm đâu dọc ống, nên khớp chân
  giữ nguyên vị trí khởi đầu -- mà khởi đầu co giãn đều cả người theo chiều
  cao. Tỉ lệ chân/thân Adult khác Kid: đầu đùi 0.760 (dưới đáy quần 0.845 tới
  8.5 cm), gối 0.452 (theo tỉ lệ Kid phải ~0.51).
- Giờ dò mốc ĐÁY QUẦN trên cả hai lưới (tia bắn lên ở đường giữa), khởi đầu co
  giãn chiều cao TỪNG ĐOẠN qua mốc đó, và giữ mốc suốt quá trình khớp.
- Adult: đầu đùi 0.817, gối 0.519, Hips 0.863; lệch bề mặt TB 1.3 -> 1.0 mm,
  max 27 -> 16 mm. Ngồi xổm sâu không còn da gối thò qua quần -- kết luận ở
  1.17.0 ("quần quá thưa") là SAI, thủ phạm là khớp gối.
- Sửa Adult_Rig đang có (không dựng lại): ref từ chính rig, kéo xương theo phép
  khớp mới, "Cập nhật rig từ ref"; chép lại weight thân + lông mày, bind lại
  quần áo. Shape key không đụng.
- Lưu ý: `ref_apply` lấy bộ ref ĐẦU TIÊN tìm thấy -- file còn sót một bộ ref cũ
  thì nó áp nhầm bộ đó ("không đổi gì"). Xoá ref thừa trước khi áp.

## 1.17.2 — 2026-11-03

**Đối xứng shape key trên lưới không đối xứng** (`mirrorkey`). Người dùng sửa
EYE_BlinkL của Adult rồi lật sang R: mí phải rách thành mảng.
- Thủ phạm chính: lúc sửa key đã lỡ sửa vào Basis -- 126 vertex quanh mắt trái
  dời tới 17.6 mm so với lưới import (lưới gốc lệch hai bên tối đa 4.8 mm).
  Lật ĐỘ DỜI cộng vào Basis bên phải vốn chưa sửa thì ra hình khác hẳn.
  Giờ mặc định lật THEO HÌNH ở bên đích (ô "Lật theo hình"): bật key R thì mắt
  phải đúng ảnh gương mắt trái khi bật L -- đo: lệch 0.00 mm. Bên nguồn và đường
  giữa vẫn lật độ dời (key L làm động 23 vertex bên phải; lật hình chúng thì bật
  R là mắt trái rách). Báo cảnh báo khi Basis hai bên lệch > 6 mm ở vùng key.
- Cặp vertex: ghép theo cấu trúc lưới (`topo_twins`, như Topology Mirror của
  Blender) thay cho vertex gần điểm gương nhất -- 124 vertex Adult không có cặp
  trùng chỗ, giờ 0. Không lần ra cặp thì nội suy bề mặt tại điểm gương.
- Còn: nhắm nửa chừng hai mắt vẫn hơi khác nhau, vì hình nghỉ hai mắt khác
  nhau -- chỉ hết khi Basis đối xứng lại.

## 1.17.1 — 2026-11-03

**Sửa bộ dựng shape key nhắm mắt theo face rig** (`facerig.Lids`). Dựng lại
trên chính Kid ra mép mí răng cưa, hở hai khoé. Bốn nguyên nhân, đo trên Kid
(so với key EYE_BlinkL làm đẹp sẵn trong file) và Adult:
- Đường gặp quá thấp (`MEET_PREF` .15): mắt to kiểu hoạt hình thì mí trên
  phải quay hơn 80°, da gấp nếp dọc thành răng cưa. Giờ .4; hiệu chỉnh coi
  hoà mọi mức lòi nhãn cầu trong 1 điểm % (0.15% với 0.6% mắt không phân biệt
  được), trước là 0.3 nên Adult vẫn rơi về .15.
- Dải mép mí dưới góc xương mí quay nguyên khối nên trượt QUÁ đường gặp
  25-30° (Kid v1805 tới -34°, key đẹp dừng -8°): mí trên chồng lên mí dưới.
  Giờ gập vào sát đường gặp (`LID_TUCK` 0.3).
- Vùng mí dưới đo theo weight lan tới -131° (phủ gò má): mí dưới nhích lên là
  má phồng. Chốt 50° dưới mép xương mí dưới (`LID_LO_SPAN`).
- Khoé (Eyelid_Inner/Outer) chỉ đi 25% quãng: hở hai khoé. `LID_CORNER` 1.0.
- Mép mí và độ thuộc-về-mí của từng vertex được làm mượt dọc cạnh lưới
  (`LID_SMOOTH` 6 lượt): weight tô tay mỗi vertex một tỉ lệ, hàng xóm quay
  lệch nhau ra nếp chữ W. Làm mượt GÓC QUAY thay vào thì trơn nhưng mép bị da
  phía trên kéo lại, nhắm còn hở -- bỏ.

Đã thử và bỏ: dò viền khe mắt từ vòng cạnh biên của lỗ mắt -- trên Kid/Adult
vòng biên nằm sâu trong hốc (da mí cuộn vào), rộng 5 cm trong khi khe mắt
nhìn thấy rộng ~10 cm; lấy nó làm mép mí thì má rách tới khoé miệng.

Kết quả (`blink_build_render.py`, `test_facerig.py`): nhắm mắt lòi nhãn cầu
0.00% trên cả Kid và Adult, hết răng cưa, khoé khép kín; nheo/mở to/nửa nhắm
sạch. Còn: Adult chụp cận còn một nếp chữ V mềm giữa mí khi nhắm, và nửa
nhắm có một chấm nhãn cầu nhỏ lòi qua da phía trên mí. Hồi quy: test_overall
15/15, test_facerig như trước.

Adult trong file giữ bộ key chép từ Kid (1.17.0) -- vẫn sạch hơn bản dựng.

## 1.17.0 — 2026-11-03

**Dựng nhân vật mới theo nhân vật mẫu đã rig** (`fitref.py`, bước 2 ·
"Hoặc lấy từ nhân vật mẫu đã rig"). Chọn rig mẫu + mesh thân mẫu, bấm
"Dựng ref theo nhân vật mẫu":
- Lưới mẫu được uốn bằng chính rig mẫu (mỗi xương một affine, LBS bằng weight
  mẫu) cho áp lên lưới mới: ICP hai chiều + ràng buộc khớp cha/con, mỗi vòng là
  một bình phương tối thiểu tuyến tính. Xương mặt đi theo Head, trừ Jaw.
- Bộ ref dựng từ rig mẫu (`refsync.ref_from_rig`) rồi dời theo phép khớp: đầu
  xương = trung bình phép của xương và xương cha, roll = trục Z qua phần tuyến
  tính; ép đối xứng L/R theo đúng quy ước roll của mẫu. Xong luôn bước 2-3.
- Tự điền nhãn cầu (mắt mẫu đưa qua phép khớp, tìm mesh trùng tâm), bỏ mắt /
  quần áo của nhân vật mẫu khỏi danh sách, ghép mesh phụ cùng hình (lông mày).
- Lúc Bind (ô "Bind: chép weight + shape key từ mẫu", mặc định bật): weight thân
  và mesh phụ chép từ mẫu thay automatic weights, tối đa 8 xương / vertex; chép
  luôn bộ shape key của mẫu, driver lông mày trỏ sang key thân mới.
- Trước khi chép: `refine` nắn lưới mẫu đã uốn bằng trường dịch chuyển mượt cho
  áp sát từng vertex. Thiếu bước này mí mắt chép sai 150/334 vertex dù hai cái
  đầu trùng nhau tới 0.4 mm (uốn bằng xương còn lệch ~4 mm ở mặt), nhắm mắt ra
  mép mí răng cưa. Có nó: còn 22 vertex khác > 0.3, phần lớn do giới hạn xương.
- Đã thử cho mỗi xương mí/môi tự khớp: lệch TB tăng 1.3 -> 2.4 mm, chậm gấp
  đôi, mí vẫn sai -- bỏ.
- Shape key mới tạo phải đặt `value = 0` tường minh: trong Blender có giao diện
  key mới mang giá trị 1.0 (chạy nền thì 0) -- 56 biểu cảm cộng dồn thành một
  cái mỏ dài tới ngực, chỉ thấy khi nhìn viewport thật.

Sửa kèm: `cloth.candidates` bỏ qua mesh phụ đã ghép với mẫu; `cloth._write`
nhận `limit`.

Số đo: Kid -> Adult (cao 1.52 -> 1.98 m, cùng đầu) trên bản sao file thật,
`test_adult.py`: 22/22 đạt
| | |
|---|---|
| khớp lưới | lệch bề mặt TB 1.3 mm, max 27 mm (đáy quần khác hình), 20 s |
| rig | 155 xương, khám rig 0 lỗi 0 cảnh báo, FK↔IK đã kiểm, snap 4 chi < 0.02 mm |
| weight | thân 110 nhóm, mọi mesh 0 vertex thiếu; áo/quần/giày chép từ thân, tóc gắn cứng; 705 vertex da theo áo |
| shape key | 56 key thân + 8 key lông mày có driver; nhắm mắt lệch TB 0.14 mm so với Kid |
| Unity 2022.3 | avatar Humanoid hợp lệ, 55 xương, 8 mesh, 56 blendshape; clip Wave của Kid chạy trên Adult lệch hướng tay 1-2° |
| hồi quy | test_overall 15/15, test_cloth 9/10 như trước |

Còn biết: ngồi xổm sâu (gối ~110°) da gối thò qua quần -- từng đổ cho quần
236 vertex; sai, do khớp gối đặt thấp 5.5 cm, sửa ở 1.17.3. `face_shapes.build` (theo face rig) dựng lại trên chính Kid cũng ra mí răng
cưa -- lỗi của bộ dựng key nhắm mắt, sửa ở 1.17.1.

## 1.16.0 — 2026-11-03

**Xuất Unity: chỉ xương Humanoid** (ô "Chỉ xương Humanoid", MẶC ĐỊNH BẬT).
Khung game chỉ còn các bone trong bảng ánh xạ Humanoid -- trên Kid 55 thay vì
114; Hips là gốc, không Root, không bone mặt / tai / Palm / Pelvis / Spine.001.

Trọng số lưới trên bone bị bỏ dồn sang bone giữ lại (`merge_map`):
- Bone giữa chuỗi THÂN mà cử động được (có widget/constraint): chia đôi bone
  trên / dưới -- Spine.001 -> nửa Spine nửa Chest.
- Còn lại: về bone giữ lại gần nhất phía trên -- môi dưới, răng, lưỡi -> Jaw;
  môi trên, mí, mày, tai -> Head; Palm -> Hand; Pelvis.L -> Hips.
  (Bản đầu chia Pelvis.L nửa cho đùi: hông lệch tới 8 mm khi nhấc chân --
  Pelvis.L không widget, không constraint, nó cứng theo Hips.)
- json `keep_extra: false` (không còn bone phụ để giữ đường cong).
- Tắt ô này thì xuất như cũ (mọi bone deform, giữ animation xương mặt).

Số đo trên bản sao file Kid đang mở (đã bind quần áo), action Wave/Idle:
| | |
|---|---|
| bone trong FBX | 55 (Blender import ngược và Unity đều đếm 55) |
| Unity | Avatar Human hợp lệ, prefab 64 transform, 7 mesh, 56 blendshape, clip Humanoid 0 đường cong bone phụ |
| chuyển động bone (import ngược) | lệch 1.1e-6 m |
| lưới body frame 12 so với rig gốc | TB 0.16 mm; chỉ vùng miệng z 1.15-1.21 lệch > 2 mm -- do bài test key xương môi `Lip_Upper.L`, xương đó cố ý không xuất |
| Unity retarget so với Blender | ≤ 2.9 mm |
| gộp clip + chỉ Humanoid | 55 bone, 2 take, lệch 1.1e-6 m, shape key 0.000 |

## 1.15.2 — 2026-11-03

Khung quần áo nằm trong bước 6 · Bind skin, mà wizard khu Dựng chỉ mở bước
đang làm -- rig đã bind xong thì bước 6 đóng và khung quần áo biến mất, người
dùng không tìm ra (chụp N-panel thật xác nhận). Giờ là panel riêng "Quần áo,
tóc, phụ kiện" LUÔN hiện trong khu Dựng khi đã có rig, dưới danh sách bước;
tiêu đề có dấu ⚠ và dòng "Chưa bind: ..." khi còn mesh quanh nhân vật chưa gắn
rig; nút "Lấp trọng số thiếu" có ở cả đây lẫn khu Sửa › Trọng số skin.

## 1.15.1 — 2026-11-03

QC bằng mắt trên viewport file Kid đang mở (6 tư thế × 3 góc + chụp cận:
T-pose, tay xuôi, giơ tay, ngồi xổm, bước đi, cúi + quay đầu), mỗi lỗi thấy được
đều đo lại bằng số rồi mới sửa:

| thấy trên viewport | nguyên nhân đo được | sửa |
|---|---|---|
| (trước khi nhìn) cổ áo nhận Jaw 1.0, môi, mí; cổ tay áo nhận Palm.* | chép thẳng da cằm/bàn tay | xương dưới Head -> Head's cha, ngón/lòng bàn tay -> bàn tay (`remap_bones`, theo cây) |
| mũ hoodie rách thành "vây" khi quay đầu | chân mũ chép Head 1.0 từ da gáy | Head cũng dồn về Neck; đồ theo đầu dùng Gắn cứng |
| mảnh nhọn thò sau tai khi cúi | 25 vertex body tổng trọng số < 0.95 (Jaw 0.08...), cạnh giãn 18x | `fill_weights`: phần thiếu -> tổ tiên không-mặt (Head), vertex trống lấy trung bình kề; tự chạy sau Bind, nút ở khu Sửa › Trọng số skin |
| cạnh áo giãn 3.5x ở chân mũ/vai | vertex kề nhau, một Neck 1.0, một Bicep 0.6 | làm mượt chỉ chỗ có bậc, không trộn trái/phải, số lượt TỰ CHỌN theo đo LBS trên bộ tư thế tổng hợp: hoodie 8 lượt (67->23), short 0 (5 vs 20/26) |
| da nếp nách sau đâm qua lưng áo khi tay xuôi | ẩn body thì hết -> là da | `skin_follow`: da bị áo che (ray theo pháp tuyến ≤ 4.5% chiều cao) lấy trọng số áo ngay trên nó; bỏ qua đầu/mặt/bàn tay; mép trộn nửa; ô "Da dưới áo đi theo áo" |
| bind lần 2 trọng số trôi (hoodie 17 -> 15 nhóm) | chép lại da đã bị đổi theo áo | lưu trọng số da gốc `srp_skin_orig` trên body; `srp.bind` xoá khi bind lại thân |

Đo sau cùng (rig thật, 5 tư thế): cạnh body giãn > 2x: 0 (trước: 4, tối đa
18.7x); hoodie cạnh giãn > 1.6x & > 4 mm: 44 (trước 127); short 15; body 0 vertex
thiếu trọng số. Còn lại: vệt da cỡ một cạnh lưới ở nách sau khi cúi + tay buông
80°, chỉ thấy khi chụp sát 0.75 m.

`test_cloth.py` 9/10 (bind lại ổn định, Head giữ 123 vertex da đầu, xuất Unity 7
mesh); mục "chép từ thân hơn automatic" không còn so được vì `skin_follow` áp
cho cả hai cách (đâm xuyên 7 vs 5). `test_overall.py` 15/15.

## 1.15.0 — 2026-11-03

**Bind quần áo, tóc, phụ kiện rời** (`cloth.py`, bước 6 · Bind skin). Danh
sách mesh + cách bind từng cái; "Tìm quần áo chưa bind" tự gom mọi mesh quanh
nhân vật chưa gắn vào rig nào và đoán cách bind theo tên (hair/hat/mũ/kính...
-> gắn cứng Head). "Bind mesh" bind luôn danh sách sau thân; "Bind quần áo"
chạy riêng phần này, chạy lại được.

- **Chép từ thân** (mặc định): mỗi vertex lấy trọng số của điểm gần nhất trên
  bề mặt thân (BVH + nội suy trong tam giác), giữ 4 xương, chuẩn hoá. Đo ở rest
  pose của rig. Điểm xa thân > 8 cm thì báo gợi ý dùng Automatic.
- **Automatic**: automatic weights, giấu xương mặt như bind thân.
- **Gắn cứng**: 100% vào một xương bằng SKIN (Armature modifier), không
  parent-bone -- `mount_bones` coi xương có object gắn-bone là xương đỡ phụ kiện
  và loại nó khỏi automatic weights, nên gắn tóc vào Head kiểu đó thì lần bind
  thân sau Head mất da đầu.
- Mỗi lần bind gỡ sạch modifier/nhóm/parent cũ của mesh đó trước.

Số đo, `test_cloth.py` trên bản sao Kid (hair, hoodie, shoes, short trước đó
không gắn gì), pose tay 70°/60°, đùi 60°, gối -80°, lưng 25°, đầu 30°:
| mesh | cách bind | lệch so với da (TB / p95) | đâm xuyên |
|---|---|---|---|
| hoodie | chép từ thân | 15.6 / 41.1 mm | 0/711 |
| hoodie | automatic | 25.2 / 62.4 mm | 24/711 |
| short | chép từ thân | 7.5 / 36.2 mm | 1/309 |
| shoes | chép từ thân | 2.3 / 8.3 mm | 0/276 |
| hair | gắn cứng Head | (cứng, không theo da) | 0/313 |

0 vertex không trọng số, ≤4 xương/vertex, 1 Armature modifier mỗi mesh; bind
lại 2 lần không nhân đôi; bind lại cả thân thì Head vẫn giữ 115 vertex da đầu;
khám rig 0 lỗi; xuất Unity ra 7 mesh (trước là 3).

## Kiểm tra tổng thể — 2026-11-03 (không đổi code)

Bài test: `test_overall.py`, `test_proportions.py`, `test_roll.py`,
script kiểm tra trong Unity 2022.3.62f2 (batchmode), chạy trên bản sao
`Kid_Base_1.blend`.

**Tổng thể trên Kid: 15/15 đạt** -- bật/tắt addon 3 vòng, quét nhanh, khám rig
(0 lỗi 0 cảnh báo), công tắc FK/IK, snap IK<->FK cả 4 chi (lệch ≤0.009 mm,
0.00°), lật pose (0.000°), reset, QC shape key, thử biểu cảm, Humanoid (55
bone), poll mọi operator, chọn khu.

**Nhân vật tỉ lệ khác, dựng bằng đúng quy trình addon** (ref -> dựng -> bind
-> shape key mặt -> xuất), mỗi cái 13/13 đạt:
| | Tall | Stocky |
|---|---|---|
| chiều cao | 1.92 m | 1.43 m (chân x0.75, thân x1.45, đầu x1.15) |
| rig / chi | 155 bone / 4 | 155 bone / 4 |
| khám rig | 0 lỗi | 0 lỗi |
| vertex không trọng số | 0/2937 | 0/2937 |
| snap 4 chi | ≤0.014 mm | ≤0.006 mm |
| shape key mặt | 51 body + 20 lưỡi + 15 răng + 8 mày, QC sạch | như Tall |
| Humanoid | 55 bone, hợp lệ trong Unity | như Tall |

**Dùng chung animation qua Unity Humanoid:** clip Wave của Kid trên Tall /
Stocky -- hướng đoạn xương lệch 0.6-5° (phần lớn là khác tư thế nghỉ: 1.4-3.9°
ngay ở frame 1); bàn chân lệch 12-15° nhưng KHÔNG đổi qua các frame = dốc bàn
chân lúc nghỉ khác nhau. Nhấc chân 0.14-0.18 lần chiều dài chân ở cả ba, hông
1.27-1.28 lần chân -- Unity co giãn đúng theo tỉ lệ.

**Bone roll:** KidRoll = Kid với roll +70° trên cả 112 bone deform, chuyển
động world y hệt (lưới trùng Kid 3e-6 m). Trong Unity, mọi tổ hợp avatar Kid /
KidRoll × clip Wave / WaveRoll lệch **0.00 mm**. Roll KHÔNG ảnh hưởng file
Humanoid: Unity đổi sang không gian cơ (muscle) theo vị trí khớp lúc T-pose.
Roll vẫn quan trọng ở hai chỗ không đo ở đây: Rig Type Generic, và dùng chung
action giữa hai rig NGAY TRONG Blender (action lưu xoay cục bộ). Addon đã đặt
roll theo bộ mẫu (`refrig._default_roll`) và lật đối xứng chép cả roll.

**Phát hiện trên file Kid:** `hair`, `hoodie`, `shoes`, `short` không gắn vào
rig (không Armature modifier, không parent) -- animate thì đứng yên, xuất Unity
thì không có. `srp.bind` hiện chỉ bind mesh thân + mắt + răng/lưỡi/mày, chưa
có chỗ cho quần áo / tóc rời.

## 1.14.1 — 2026-11-03

**Gộp animation vào file nhân vật** (khu Xuất, ô "Gộp animation vào file nhân
vật"). Bật thì chỉ ra một `<tên>.fbx` chứa nhân vật + mọi clip, mỗi action một
take; json mang `combined: true` và script Unity tách take thành clip, đặt tên
theo action (bỏ tiền tố `<armature>|`), loop theo `use_cyclic`.

- Khung game không có action (bám rig gốc bằng constraint), nên mỗi action
  được BAKE ra keyframe trên khung game (`bake_clip`, POSE -> LOCAL từng frame,
  quaternion nối liền), đặt thành một NLA strip; exporter ra mỗi strip một take.
- Exporter không tắt/bật NLA của Key, nên các clip xếp nối đuôi trên timeline
  (cách nhau 10 frame), action shape key thành strip NLA của Key đúng đoạn đó,
  extrapolation NOTHING.
- Xuất ở frame 0 (ngoài mọi strip) để transform mặc định của node là rest pose
  -- script Unity dựng Avatar từ chính transform đó.
- Exporter đưa mỗi take về bắt đầu ở frame 0.

Số đo trên bản sao Kid (Wave + Idle, Unity 2022.3 batchmode):
| | |
|---|---|
| file ra | chỉ Kid.fbx (+ json, .cs); .blend không đổi |
| import ngược Blender | 2 take Kid|Idle, Kid|Wave, 0..23; bone lệch 1.2e-6 m; smile lệch 0.000 |
| Unity | Avatar Human hợp lệ; clip Idle (loop) và Wave, humanMotion |
| Unity: shape key không lẫn clip | MTH_SmileL max 100 ở Wave, 0 ở Idle |
| Unity: retarget so với Blender | lệch tối đa 2.9 mm (như bản tách file) |

## 1.14.0 — 2026-11-03

**Giao diện xếp lại theo khu** (`uikit.py` mới, `ui.py` viết lại). Không đổi
operator, `bl_idname` hay setting nào -- chỉ phần vẽ.

- Thanh chọn khu ở đầu tab Rig Tẩm Hành, theo luồng làm việc:
  **Dựng → Mặt → Diễn → Xuất → Sửa**. Mỗi lúc chỉ vẽ panel của một khu.
  Vào Pose Mode thì tự sang Diễn. Rig thiếu driver/constraint thì nút Sửa đỏ
  lên ở mọi khu.
- Khu Dựng thành wizard: danh sách 7 bước (✓ xong, khoá, tuỳ chọn), chỉ MỞ
  bước đầu tiên chưa xong hoặc bước vừa bấm. Bấm bước 7 sang khu Mặt.
- Shape key khuôn mặt (trước là bước 7 trong Dựng) thành khu Mặt; Xuất Unity
  (trước là bước 8) thành khu Xuất.
- FK/IK thành bảng một dòng mỗi chi: tên | thanh trượt | →FK →IK.
- Chữ giải thích nằm sẵn trên panel (26 khối `scale_y = 0.8`) chuyển vào nút
  "?" trên đầu panel (`uikit.HELP`, cũng hiện làm tooltip). Giữ lại dòng trạng
  thái và cảnh báo.
- Chữ không dấu sửa thành có dấu (picker, FK/IK, Sửa, onion, remap, bind...).
- Nút Pose → Shape key không còn lặp nguyên khối ở picker Mặt, chỉ một nút tắt.
- Dòng "Rig ...: thiếu N bone" (bảng bone họ rig cũ) không hiện cho face rig
  Rig Tẩm Hành nữa.

Kiểm chứng: nạp lại trong Blender đang mở, chụp N-panel từng khu
(`ui_shots/`), cả wizard lúc mọi bước xong và lúc mở bước 6. Không lỗi vẽ.

## 1.13.0 — 2026-11-03

**Xuất sang Unity, Rig Type Humanoid** (`unityexport.py`, panel "8 · Xuất sang
Unity"). Ba nút: Kiểm tra Humanoid (chỉ đọc, báo vào text block
`SRP_Unity_Check`), Tạo bảng sửa ánh xạ (text block `SRP_Humanoid_Map`), Xuất FBX.

Ra: `<tên>.fbx` (mô hình, rest pose), `<tên>@<action>.fbx` mỗi action,
`<tên>.humanoid.json` (bảng ánh xạ + clip), `RigTamHanhHumanoidImporter.cs`. Chọn
thẳng một thư mục trong `Assets/` thì script tự vào `Assets/Editor/RigTamHanh`.

- Khung xương game tạm: bone deform + bone Humanoid + Root, cha = tổ tiên gần
  nhất có trong khung. Hips của Rig Tẩm Hành không deform nên xuất thẳng thì mất.
  Copy Transforms trong không gian POSE theo rig gốc, nên exporter lấy mẫu ra
  đúng chuyển động đã qua IK/FK.
- Ánh xạ: quy ước Rig Tẩm Hành (rigdef) trước, rồi đoán theo tên (Mixamo, Rigify
  DEF-, tên thường). Cột sống theo HÌNH: đoạn giữa Hips và Neck; 4 đốt thì
  Spine / bỏ / Chest / UpperChest.
- Mesh bản sao: apply xoay/scale, gộp eyebrow (key chạy driver) vào body, skin
  nhãn cầu gắn-bone 100% vào Eye.L/R, giữ 4 bone/vertex, bỏ nhóm trỏ vào bone
  control.
- Shape key theo action: slot KEY trong chính action, hoặc action `<tên>_Face`.
- Xoay bản xuất 180° quanh Z (tắt được): nhân vật Blender nhìn -Y sang Unity
  thành nhìn -Z, transform.forward chỉ sau lưng. `axis_forward` KHÔNG sửa được
  việc này -- Unity đọc hệ trục trong FBX rồi bù lại, '-Z' hay 'Z' ra như nhau.
- Script Unity dựng Avatar từ json (không auto-map), file `@` dùng
  CopyFromOther Avatar của mô hình, mask giữ đường cong bone ngoài Humanoid.

Số đo trên bản sao Kid với 2 action thử (Wave có shape key `MTH_SmileL` qua
`Wave_Face`, Idle cyclic), `test_unity_export.py` / `test_unity_import.py` /
script kiểm tra trong Unity 2022.3.62f2 (batchmode):
| | |
|---|---|
| file .blend sau khi xuất | không đổi (object, mesh, action, collection, mode, action đang gán) |
| import ngược vào Blender: rest pose | lệch 1.2e-6 m |
| import ngược: vị trí bone qua từng frame | lệch 1.0e-6 m; đường cong smile lệch 0.000 |
| khung game | 114 bone, 55 bone Humanoid, 3 mesh, tối đa 4 bone/vertex |
| Unity: Avatar | Human, isValid, 55 bone; file @ CopyFromOther KidAvatar |
| Unity: clip | humanMotion, Idle loop, 57 đường cong blendshape, Lip_Upper.L giữ 10 đường cong |
| Unity: retarget Humanoid so với Blender | lệch tối đa 2.9 mm (hông bị Unity chuẩn hoá trọng tâm) |
| Unity: hướng | nhìn +Z, tay trái ở -X |

Chưa thử: Unity 6 (API dùng có đủ ở 6), rig không phải Rig Tẩm Hành.

## 1.12.0 — 2026-11-03

**Đối xứng shape key L ↔ R** (`mirrorkey.py`, operator `face_shapes.mirror_key`).

- **Lật sang bên kia:** key nguồn → key bên kia, tên tự đổi (`EYE_BlinkL` →
  `EYE_BlinkR`, `Smile.L` → `Smile.R`, `Brow_L.001`, `lip_left_up`...). Tên chưa
  có thì gợi ý Tạo mới, có rồi thì tự chọn Ghi đè. `VIS_L` không bị coi là bên
  trái.
- **Đối xứng trong key:** giữ nửa L (hoặc R), chép gương sang nửa kia. Vertex
  trên đường giữa bỏ phần dời ngang.
- Pose → Shape key có thêm ô **Tạo luôn bản đối xứng**: một lần bấm ra cả hai
  bên.
- Mặt phẳng gương lấy trong không gian armature, tâm ở bone Head, không theo
  object (body của Kid xoay -90° X). Cặp vertex tìm bằng KDTree trên Basis. Có
  quá 5% vertex lệch cặp thì báo mesh lệch hai bên.
- Mesh phụ (eyebrow) được lật theo bản đồ riêng của nó, key mới có driver.

Số đo, chạy `test_mirrorkey.py` trên bản sao Kid:
| | |
|---|---|
| cặp vertex lệch quá ngưỡng (0.1% kích thước) | body 6/3387, eyebrow 0/106 |
| đối xứng trong key rồi lật lại | lệch 0.00000 |
| Sneer.L + tạo luôn bản đối xứng | có Sneer.R trên body và eyebrow, kèm driver |
| lật MTH_SmileL so với MTH_SmileR addon dựng | lệch 1.79 trên 3.93 |

Dòng cuối không phải lỗi lật: trục X cho sai số nhỏ nhất (Y 4.67, Z 7.53), xương
hai bên đối xứng tuyệt đối, nhưng **skin weight của Kid lệch hai bên** tới 0.47
(Lip_Lower.L.001 so với .R, 15 vertex chênh quá 0.05). Key R do rig dựng mang
theo độ lệch đó; bản lật mới là gương thật.

## 1.11.0 — 2026-11-03

**Pose → Shape key** (`posekey.py`, operator `face_shapes.pose_to_key`). Người
dùng pose xương mặt trong Pose Mode, bấm một nút, chọn **Tạo mới** (đặt tên,
gợi ý sẵn `Pose_001`...) hoặc **Ghi đè** (chọn từ danh sách shape key của mesh
mặt). Nút nằm ở 7 · Shape key khuôn mặt › Pose → Shape key và ở Diễn xuất ›
Picker › Mặt.

- Chỉ lấy pose các con cháu của bone Head. Head, cổ, tay đang pose dở thì được
  đưa về rest lúc đo, xong trả lại nguyên.
- Mọi shape key khác tắt trong lúc đo (KeyScope), nên giá trị đang bật của chúng
  không lọt vào key mới.
- Mesh phụ do rig làm biến dạng (lông mày Kid) cũng nhận key cùng tên, kèm
  driver theo mesh mặt. Khi ghi đè, key cùng tên trên mesh phụ cũng được ghi lại.
- Key tạo mới không ghi vào bản kê khai `srp_face`, nên "Dựng bộ shape key" lần
  sau không xoá nó. Nếu ghi đè lên key của addon thì có cảnh báo là dựng lại sẽ
  thay lại key đó.
- Tên trùng khi Tạo mới thì bị từ chối. Không có xương mặt nào đang pose thì
  cũng bị từ chối.

Số đo, chạy `test_posekey.py` trên bản sao Kid: pose Jaw 12°, Lip_Upper.L,
Eyebrow.L.001, cộng thêm Head 20° và Forearm.L.
| | |
|---|---|
| key = 1 so với pose chỉ có xương mặt | lệch tối đa 2.3e-5 |
| vertex dưới z = 1.0 m bị dời | 0 (không lọt Head/tay) |
| key trên eyebrow + driver | có |
| xương mặt sau khi convert | về rest; Head/Forearm giữ nguyên pose |
| ghi đè JAW_Open | đổi hình, tổng số key giữ nguyên |

---

## 1.10.0 — 2026-11-03

### Shape key khuôn mặt từ face rig Rig Tẩm Hành (module mới `facerig.py`)

Đường "theo face rig" cũ chỉ nhận bộ bone của một họ rig khác (`Jaw_Base`,
`UpperLip_Ctrl.L`...). Trên Kid_Rig và mọi rig dựng từ mục 3, nó báo thiếu bone
rồi rơi về chế độ vùng. Module mới đọc đúng tên trong `refrig.FACE_GROUPS`.

- Mục 7, cách dựng "Tự chọn":
  - Rig có xương mặt Rig Tẩm Hành (Jaw, Lip_Upper/Lower_Mid, Lip_Upper/Lower.L/R)
    thì đi theo rig trước.
  - Thiếu mí / mày / mũi / lưỡi thì chỉ thiếu key của nhóm đó.
- Tư thế được tính thẳng ra `matrix_basis`, cha trước con sau, không chờ
  depsgraph.
- Há hàm kéo hai khoé về trung điểm, nên khoé không toác. Trần hàm đo bằng độ
  giãn cạnh quanh khoé, chặn ở 24°.
- **Mí không nướng qua xương.**
  - Với góc 85°, skin tuyến tính đưa da theo dây cung và cắt vào nhãn cầu.
  - Thay vào đó, mỗi vertex quay quanh tâm nhãn cầu. Mép mí đi trọn tới đường
    gặp, da phía trên nén dần, và đứng yên ở rìa vùng mí.
  - Rìa vùng mí đo từ trọng số skin và bị chặn dưới xương mày.
  - Đường gặp mí đo bằng ray cast lên nhãn cầu rời.
- Mesh phụ do rig làm biến dạng ở gần mặt (lông mày rời) được nướng cùng và có
  driver theo slider của mesh mặt. Công thức mí không áp lên chúng.
- Key mới: `JAW_Open/Forward/Left/Right`, `TNG_Out/Up/Down/Left/Right`,
  `NOS_Wrinkle`. Thêm biểu cảm mẫu "Lè lưỡi" và "Há hốc".
- Sửa nút **Kiểm định**: trước đây nó so z object với vùng mặt. Body của Kid
  xoay −90° X, scale 0.01, nên z object của nó là chiều sâu, và nút báo bake sai
  trên cả 56 key.

**Đo trên bản sao Kid_Base_1** (body 3387 vertex, cường điệu 150%):

| | |
|---|---|
| Số key | body 56, eyebrow 8 (8 driver) |
| Tư thế rig sau khi dựng | trả lại nguyên vẹn (kể cả tay đang pose) |
| Key làm tay `MyHandKey` | giữ nguyên, kể cả giá trị 0.7 |
| Key lan xuống dưới đầu | 0 (thấp nhất z 1.01 m, da dưới cằm) |
| Giãn cạnh khoé: JAW_Open / VIS_AA / VIS_OH / SmileL | 1.94 / 2.23 / 2.17 / 2.30 (trần 2.3) |
| Nhãn cầu lòi khi nhắm (ray cast) | 25.31% → 0.31% |
| Vertex da trong nhãn cầu: nghỉ / nhắm / nheo / mở to | 24 / 24 / 24 / 24 |
| Dựng lại lần hai | đúng 56 key, không nhân đôi |
| Kiểm định | 0 cảnh báo của addon |

**Còn thô:** mí khép trên Kid trông như một tấm vạt, vì giữa mép lỗ mắt và lông
mày chỉ có 2–3 vòng lưới, phải trải ra 85°. Thêm 2–3 edge loop quanh lỗ mắt thì
mí khép tròn hơn; công thức không cần đổi.

---

## 1.9.0 — 2026-11-02

### Sửa bộ ref sau khi đã bind skin (module mới `refsync.py`)

Trước đây bộ ref bị xoá lúc bind. Muốn sửa thì chỉ còn cách dựng một rig MỚI,
và như thế là mất skin, mất weight tô tay, mất animation, mất driver.

- **`srp.ref_from_rig` — "Dựng lại bộ ref từ rig"**, mục 2, chỉ hiện khi chưa
  có bộ ref.
  - Chép head/tail/roll của rig đang có. Gắn thẻ bộ phận theo bản vẽ của
    `refrig`, không đoán từ tên.
  - Xương deform ngoài bản vẽ thì gắn thành chuỗi bổ trợ.
  - Dùng được cả với rig làm tay.
- **`srp.ref_apply` — "Cập nhật rig từ ref"**, mục 4.
  - Sửa rest pose của rig ngay tại chỗ: không xoá xương, không đổi tên.
  - Vertex group, constraint, driver và action giữ nguyên.
  - Xương nào dời thì đo lại pole của chi chứa nó, rồi kiểm FK↔IK.
  - Object parent kiểu BONE (nhãn cầu, mũ) giữ nguyên vị trí thế giới.
  - Bộ ref có thêm bộ phận mới thì rig được thêm xương, chạy `apply_logic` và
    gán widget.
  - Tuỳ chọn "Bind lại weight", mặc định TẮT vì bind lại sẽ ghi đè weight tô tay.
- **Dời theo HIỆU SỐ so với ảnh chụp bộ ref** (`refrig.TAG_BASELINE`), không
  theo toạ độ tuyệt đối.
  - Ảnh chụp được lưu lúc `srp.generate`, `srp.ref_from_rig` và sau mỗi lần
    cập nhật.
  - Xương không ai đụng tới thì đứng yên tuyệt đối, kể cả control mà rig làm
    tay đặt lệch bản vẽ.

Số đo trên bản sao Kid_Base_1 (bài `test_refsync.py`, `test_refsync_add.py`
trong scratchpad của phiên):

| Kiểm tra | Kết quả |
|---|---|
| Dựng ref từ Kid_Rig.001 | 113 xương, đủ bộ phận bắt buộc. Bản vẽ dựng lại khớp rig 0,00 mm |
| Cập nhật khi chưa sửa gì | 0 xương dời |
| Khuỷu L lùi 2 cm, Eye.L dời 3 mm, Jaw xoay roll | Dời đúng 9 xương: chuỗi deform/FK/IK của tay L, ElbowPole.L, Eye.L, Jaw. `Bicep.L` tail vẫn trùng `Forearm.L` head. Roll Jaw khớp ref (dot 1,0) |
| Mesh `body` ở rest pose | lệch tối đa 0,0002 mm |
| Nhãn cầu, weight, driver, FK↔IK | đứng yên / không đổi / không đổi / OK |
| Cập nhật lần 2 | 0 xương dời |
| Kéo khuỷu về chỗ cũ | mọi xương tay L về đúng toạ độ ban đầu |
| Thêm chuỗi 3 xương vào Head | rig thêm 3 xương deform có widget. Bật "Bind lại weight" thì mesh có vertex group của chúng |

### Thêm lẻ từng phần khuôn mặt

- **Menu "Thêm bộ phận" có thêm 9 mục:** `Mặt · Hàm / Răng / Lưỡi / Môi /
  Mũi / Mắt (cặp) / Mí mắt / Lông mày / Tai`.
  - "Khuôn mặt (đủ bộ)" vẫn còn và bằng đúng tổng của 9 mục này. Bảng tọa độ
    chỉ có một nơi duy nhất là `refrig.FACE_GROUPS`.
- **Cha chéo vùng:** lưỡi, răng dưới và môi dưới theo `Jaw`.
  - Thêm chúng trước Hàm thì chúng nối tạm vào `Head`.
  - Lúc thêm Hàm, Hàm tự nhận lại chúng làm con (`_face_orphans`).
- **Chặn thêm trùng xương.** `add_part` lấy lại xương trùng tên và gắn thẻ mới
  lên nó, nên thêm "Lưỡi" khi đã có "đủ bộ" sẽ lặng lẽ cướp 4 xương lưỡi. Giờ
  thao tác đó bị từ chối, kèm tên các xương bị trùng.
- **`srp.ref_from_rig`** gắn thẻ mặt theo từng vùng, nên dựng lại xong vẫn xoá
  lẻ được, ví dụ chỉ bỏ lưỡi.
- **Cặp mắt đầu tiên** giờ thêm được bằng `Mặt · Mắt`. Từ cặp thứ hai trở đi
  ra `Eye_2.L/R` như trước.

Số đo (`test_face_parts.py`):

| Kiểm tra | Kết quả |
|---|---|
| Thêm lẻ 9 vùng, Hàm thêm SAU CÙNG, so với "đủ bộ" | 0 khác biệt về vị trí, cha, connect, roll |
| Thêm Lưỡi khi đã có / thêm "đủ bộ" khi đã có vùng lẻ | đều bị từ chối |
| Xoá vùng Lưỡi | hết xương Tongue |
| Dựng từ ref theo vùng của Kid | 155/155 xương, lệch 0,000 mm, cha khớp hết |

## 1.8.0 — 2026-11-02

### Bộ rig mặc định = `Kid_Rig.001` (project Dentis)

Bộ ref (`refrig.PARTS`, `HAND_LAYOUT`) giờ đo thẳng từ `Kid_Rig.001`, chia theo
bounding box của mesh `body` (cao 1,519). Mọi xương mang luôn trục Z của Kid
(cột thứ 7 trong bản vẽ), không còn để `_default_roll` đoán.

* Cột sống còn **một** `Neck` như Kid (bỏ `Neck.001/.002` khỏi bản vẽ; rig cũ
  có chúng vẫn dựng được). `Hips` đuôi chỉ xuống.
* Bàn tay: 20 xương theo đúng bố cục ngón của Kid, kể cả roll ngón cái.
* Bộ phận **Khuôn mặt** (trước là "Hàm & mắt") có đủ 63 xương mặt của Kid:
  `Jaw`, `Tongue` ×4, `Teeth_Upper/Lower`, môi trên ×7 (theo đầu), môi dưới ×7
  (theo hàm), `Eye`, `Eyebrow` ×4, `Eyelid_*` ×7 mỗi bên, `Nose`, `Ear`.
  `generate` dựng cả bộ nguyên si từ bộ ref (`_ref_chain`), giữ cây cha con.

**Tên chuẩn hoá** so với Kid để lật trái/phải được: `Eyebrow.L_5` →
`Eyebrow.L`, `Eyebrow_001.R` → `Eyebrow.R.001`, `Lip_Upper_L.001` →
`Lip_Upper.L.001`, `Nose_6` → `Nose`. Ba xương `Lip_Lower_R*` của Kid có Z chỉ
xuống (ngược mọi xương môi khác) — bản vẽ để Z lên cho cả hai bên.

Số đo (`test_generate.py`, trên bản sao `Kid_Base_1.blend`, xoá Kid_Rig rồi dựng
lại bằng addon): 154/154 xương khớp tên, cha, deform; lệch head/tail tối đa
**0,21 mm**; roll khớp (z·z ≥ 0,99) trừ ba xương môi nói trên; FK↔IK kiểm chứng.

### Lỗi có từ trước: bộ ref trên mesh FBX bị xoay

Bộ ref chép `matrix_world` của mesh. `body` của Kid xoay 90° quanh X, nên "Z cục
bộ" của bộ ref không phải là "lên trên". `_hand_spec` và `_default_roll` lại
lấy Z cục bộ → cả bàn tay quay 90° quanh cổ tay (ngón cái lệch **123 mm**),
roll thân/tay/chân lật 180°. Giờ mọi hướng thế giới đổi qua `to_local` trước.
Sau sửa: ngón cái lệch 0,1 mm.

### Mesh mặt rời: răng, lưỡi, lông mày

Bước 1 có thêm danh sách "Răng, lưỡi, lông mày rời", cùng kiểu với nhãn cầu
(`srp_generate.face_meshes`). Bind:

* **Răng** — mỗi đảo lưới gắn cứng 1,0 vào `Teeth_Upper`/`Teeth_Lower` gần tâm
  đảo nhất; một mesh chứa cả hai hàm vẫn tự tách. Kid: 175 + 175 vertex.
* **Lưỡi** — automatic weights CHỈ trên chuỗi `Tongue` (tắt tạm `use_deform`
  các xương khác). Kid: 4 nhóm, 100 vertex.
* **Lông mày** — automatic weights CHỈ trên `Eyebrow*` + `Head`.
* Có mesh răng/lưỡi rời thì xương răng/lưỡi bị giấu khỏi automatic weights của
  mesh thân (như xương mắt). Xương lông mày thì KHÔNG — trên Kid chúng vẫn giữ da
  trán.

Picker mặt nhận thêm tên bộ Kid: `Eyelid_*`, `Lip_Upper*`, `Lip_Lower*`,
`Teeth_*`, `Tongue*`, `Ear.L/R`.

### Sửa lỗi

* `health._scan_after_load`: `prefs.log()` gọi trước `prefs = _preferences()` →
  `UnboundLocalError` bị `except` nuốt, tự sửa khi mở file chưa từng chạy.
* `widgets.auto_offset` chia khoảng đẩy cho độ dài xương (translation là MÉT).
* `widgets.drawn_points` trả toạ độ thế giới trong khi BVH ở toạ độ rig.
* `snap`: IK←FK bỏ qua foot roll → lệch gối 56 mm, cổ chân 47 mm khi gót/mũi
  đang xoay; giờ `reset_roll()` trước khi snap (lệch 0,015 mm). `key_ik` key
  thêm xương roll, `key_fk` key thêm location cho xương không nối cha.
* `face._weigh_jaw`: răng trên chỉ bị gỡ khỏi `Jaw`, không trả về xương cha.
* `remap.apply_plan`: chạy thật không đếm driver; bỏ sót `bone_target` và
  driver trên armature data.
* `refrig.draw_parts`: sort khoá bộ phận có `side=None` → TypeError.

---

## 1.7.1 — 2026-08-22 (khuya, sau khi Blender tắt đột ngột)

### Bỏ `to_mesh()` trong vòng lặp

Blender của anh Art tắt đột ngột. **Không có bằng chứng nào chỉ vào addon này**:
không có `.crash.txt` nào được ghi, và log của addon khác trong file cho thấy
một chuỗi tắt CÓ TRẬT TỰ (`Stopping WebSocket server` → `Event loop closed`), tức
Blender đi qua đường thoát bình thường chứ không phải sập. Nên mục này không
phải "đã sửa lỗi crash" — nó là dọn đúng một chỗ mà chính dự án này đã ghi lại
là nguy hiểm, nhân lúc nhìn lại.

Ghi chú ngày 2026-08-21: *"Đừng gọi `to_mesh()`/`to_mesh_clear()` lặp trên
object evaluated -- vòng lặp kiểu đó làm Blender chết mất tiến trình. Dùng thẳng
`obj.evaluated_get(dg).data`."* Rồi chính `eyeball_shields()` lại làm đúng thế:
lặp qua từng nhãn cầu, mỗi vòng dựng một lưới tạm rồi xoá. Và nó được gọi **ba
lần mỗi lượt dựng** (`region_shapes`, `solve_lid_angles`, `eye_contract`) → 12
chu kỳ tạo/xoá lưới tạm cho một lần bấm nút, trên nhân vật bốn mắt.

Thêm `eval_mesh(obj)`: object kiểu MESH thì đọc thẳng `evaluated_get(dg).data`
-- đúng lưới ấy, không có bản tạm nào để quên dọn, không có hai bản sống chồng
lên nhau. Chỉ curve/text/metaball mới thật sự cần `to_mesh()`, và ở đó vẫn trả
object về cho chỗ gọi dọn. Áp cho cả ba chỗ: `eval_coords`, `eyeball_exposure`,
`eyeball_shields`. Cả file giờ còn đúng một lời gọi `to_mesh()`, nằm trong nhánh
không-phải-MESH của chính hàm ấy.

Không đổi một con số nào ở đầu ra: 20/20 bộ test xanh, `test_hole` 28/28.

### Cứu trạng thái chưa lưu

`quit.blend` (34 MB, 17:29) giữ nguyên phiên làm việc lúc tắt, tức có cả bộ 56
shape key vừa dựng bằng 1.7.0. Đã chép sang
một bản lưu riêng (`quit_2026-08-22_1729_truoc_khi_crash.blend`) trước khi mở
lại Blender -- `quit.blend` bị ghi đè ở lần thoát kế tiếp.

---

## 1.7.0 — 2026-08-22 (khuya)

### ĐẶT ĐÍCH RỒI GIẢI, thôi viết công thức

Anh Art: *"hãy phát triển một công thức giúp cho face shape key được tạo ra
chính xác hơn đi, tình trạng này vẫn lỗi nhiều lắm"*. Đúng, và chỗ sai không
nằm ở công thức nào cụ thể — nằm ở chuyện **có công thức**.

Bảy bản liên tiếp tôi sửa mí bằng cách viết một công thức hình học mới, và lần
nào cũng có một nhân vật làm hỏng giả định của nó: có lỗ / không lỗ, nhãn cầu
trong da / ngoài da, khe ngang / khe xiên, mép lỗ cuộn vào / không cuộn, lưới
thưa / lưới dày, trọng số đều / trọng số dốc. Đó là một quỹ đạo sai chứ không
phải một chuỗi lỗi rời rạc.

**Kiến trúc cũ** — công thức tính đường đi → tắt dần theo một hàm tự chọn → làm
mượt → chốt giãn cạnh → chốt chặn nhãn cầu. Năm bước nối tiếp, mỗi bước phá bảo
đảm của bước trước, và cái duy nhất đúng nghĩa — *"mắt phải nhắm"* — thì không
bước nào phát biểu ra được.

**Kiến trúc mới** — chỉ nói **ĐÍCH**, rồi để một phép giải tìm chỗ đứng cho da:

| ràng buộc | vì sao |
|---|---|
| mép lỗ mắt → tới đường khe | khép cái lỗ |
| vành da đang ôm mặt cầu → **trượt trên mặt cầu** tới khe | che con ngươi |
| viền ngoài mảng → đứng yên | không kéo cả khuôn mặt |
| không vertex nào **lại gần nhãn cầu hơn lúc nghỉ** | không để cầu ló ra |

`biharmonic_field()` cực tiểu hoá `|L·d|²` — năng lượng uốn của trường độ dịch —
với các đích trên làm ràng buộc cứng. Nói nôm na: *"cho tôi cách trải đều nhất
có thể, biết mấy chỗ này phải tới đúng đây"*. Đó chính là thứ mà mọi hàm tắt dần
tự chế xưa nay đang xấp xỉ một cách vụng về.

| `Mesh_0.001`, nhắm hết cỡ | con ngươi hở | khẩu độ hở | gập ngược |
|---|---|---|---|
| lúc mở | 24% / 19% | 100% | 0% |
| 1.4.0 chỉ quay | 2% | **100%** | 0% |
| 1.5.0 chỉ khép | **24%** | 10% | 0% |
| 1.6.0 hai công thức | 5% / **11%** | 8% / 10% | 0% |
| **1.7.0 phép giải** | **3% / 0%** | **0%** | **0%** |

Hợp đồng: **16/16 ĐẠT**, lần đầu không còn dòng cảnh báo nào. Và đường cong theo
slider ra đúng `100 → 75 → 50 → 25 → 0%` — tuyến tính hoàn hảo, dấu hiệu của một
trường tuyến tính thật chứ không phải một công thức được vặn cho vừa.

### Ba thứ trước phải cài tay, giờ TỰ RA

* **Tắt dần** — nghiệm biharmonic tự trải theo hình lưới thật, nên lưới dày hay
  thưa đều đúng. Xoá `LID_SPREAD`, `LID_RINGS` khỏi đường mới; trước đây phải đo
  `LID_SPREAD` và nó sai ngay khi đổi mật độ lưới.
* **Khoé mắt đứng yên** — ở khoé, đường khe đi qua đúng chỗ vertex đang đứng nên
  độ dịch ĐÍCH tự bằng 0. Xoá `LID_TAPER_P`; trước đây phải nhân thêm `taper()`,
  và thiếu nó thì một đa giác gập ngược làm bộ dò chết cứng ở 0,09 rad.
* **Bộ dò** — không còn tham số nào để dò. Hai chặng quét 36 phép đo mỗi con mắt
  biến mất; giờ chỉ giải một lần, **3,1 ms mỗi mắt**.

### Chỗ hỏng mà chỉ phép giải mới lộ ra

Bản giải đầu tiên khép lỗ 0% nhưng che phủ lại **tệ hơn** (24% → 19%), và nhìn
ảnh thì có hai cục u tròn ngay trên mí. Không vertex nào lún vào nhãn cầu cả —
phép giải kéo da trượt vào trong vài mm, mà da mí ở đây chỉ cách mặt cầu
**0,4–11 mm**, nên quả cầu ló ra. Đo được: `v103` đi từ −1,12 mm ra −0,47 mm,
đúng chỗ cục u hiện lên.

Luật *"không chui vào nhãn cầu"* cho qua ca đó. Luật đúng là **"không lại gần
nhãn cầu hơn lúc nghỉ"** — chặt hơn, và nó nằm trong vòng lặp của chính phép
giải (giải → đẩy ra → **ghim lại** → giải lại), chứ không phải một bước hạ nguồn
phá công của bước trên. Sau khi sửa: che phủ 24% → **3%**, cục u biến mất.

Làm mượt hạ nguồn cũng phải miễn **cả mảng giải** chứ không chỉ nhóm mí đã tô:
phép giải trải rộng hơn nhóm (nhóm + 2 vòng), và phần trải đó chính là phần chịu
biến dạng.

### Ai đi đường nào

Cần **có lỗ mắt** và **có mesh nhãn cầu** thì mới đủ dữ kiện đặt đích. Quét file
của anh Art: `Mesh_0.001` (4 mắt), `Male`, `pig_body` → đi đường giải;
`My_Body` (hốc mắt liền da) → giữ đường công thức cũ. Robot, đạo cụ, nhân vật
mắt vẽ trên texture cũng rơi vào đường cũ, và đó là chuyện bình thường.

### Bài test

`test_hole.py` **28/28**, thêm hai ca:

* **mắt có lỗ + có nhãn cầu thì KHÔNG được sinh tham số nào** — nếu bộ dò lại
  trả về một con số để vặn thì nghĩa là đã lén quay về lối cũ.
* **đường cong theo slider phải tuyến tính** — đặc trưng của trường tuyến tính;
  một công thức được vặn cho khớp hai đầu sẽ cong ở giữa.

Giữ nguyên hai ca một-nửa làm đối chứng, vì mỗi nửa đều từng là một bản phát
hành và đều hỏng theo một kiểu: chỉ-khép cho lỗ 10% mà con ngươi 45% → 33%;
chỉ-quay cho con ngươi 45% → 0% mà lỗ còn 70%. Phép giải: **0% và 0%**.

Toàn bộ 20 bộ xanh.

---

## 1.6.0 — 2026-08-22 (tối)

### Nhắm mắt là HAI chuyển động, không phải một

Anh Art bấm nút "Nhắm mắt" và mắt mở trân trân — ngay sau khi tôi báo đã sửa
xong và đóng gói bản 1.5.0. Hai bản liên tiếp tôi làm **đúng một nửa việc**, mỗi
lần một nửa khác nhau:

| bản | làm được | hỏng ở đâu |
|---|---|---|
| 1.4.0 | quay tấm mí qua trước nhãn cầu — **che** được | cái lỗ vẫn mở toang, giấu con ngươi đi là thấy |
| 1.5.0 | mép lỗ tiến vào khe — **khép** được cái lỗ | khép ở sau mặt cầu, người xem không thấy gì đổi |

Đây là hai việc khác nhau, tác dụng lên hai nhóm vertex khác nhau, và **thiếu
cái nào cũng ra một bộ key nhìn hỏng**. Giờ `lid_arc` làm cả hai:

* **`swing`** — cả tấm mí quay quanh tâm nhãn cầu một góc chung. Đây là thứ làm
  mắt TRÔNG NHƯ nhắm.
* **`conv`** — mép lỗ tiến vào đường khe. Đây là thứ KHÉP CÁI LỖ.

Đo trên `Mesh_0.001`: mép lỗ cách tâm nhãn cầu 5,3–18,8 mm còn da mí ngoài thì
23 mm, nên quay 30° đưa da ngoài đi 12 mm mà mép lỗ chỉ 2,6 mm. **Quay không
khép nổi lỗ, khép lỗ không che nổi cầu.**

| `Mesh_0.001`, nhắm hết cỡ | con ngươi hở | khẩu độ hở |
|---|---|---|
| lúc mở | 24% | 100% |
| 1.4.0 (chỉ quay) | 2% | **100%** |
| 1.5.0 (chỉ khép) | **24%** | 10% |
| bản này | **5%** | **8%** |

Mắt nhỏ khép được 19% → 11% che phủ, hợp đồng báo CẢNH BÁO — thật, và đó là
thông tin đúng chứ không phải lỗi cần giấu.

### Hình học thật của cái hốc mắt, đo ra rồi mới hiểu

Ba lần tôi đoán sai vì chưa đo cái này:

| | |
|---|---|
| bán kính nhãn cầu | 23,4 |
| tâm nhãn cầu so với mặt phẳng mép lỗ | **+4,6 — ở PHÍA TRƯỚC** |
| cực trước nhãn cầu so với mép lỗ | +28,0 |
| vành da sát mép lỗ | nằm **NGOÀI** mặt cầu 0,4–11 |
| mép lỗ | nằm **TRONG** mặt cầu 4,5–18,3 |

Hốc mắt là một cái **phễu**: vành ngoài ôm sát mặt cầu, mép lỗ cuộn vào phía sau
nó. Nhãn cầu là quả cầu to nằm gọn trong đầu, cái lỗ chỉ là một cửa sổ nhỏ nhìn
vào nó. Muốn kéo mép lỗ ra TRƯỚC quả cầu thì phải vọt lên 19–34 mm — bằng cả
đường kính quả cầu. Không đời nào, và đó là lý do mép lỗ phải khép ở phía sau
(đúng chỗ của nó) còn phần che là việc của vành da ngoài.

### Ba chỗ hỏng trong phép quay, mỗi chỗ một phép đo

**1. Chiều quay lấy theo dấu của `gap` thì lật ngay tại đường khe.** Một vertex
cách khe 0,1 mm về phía dưới quay ngược hẳn với hàng xóm cách khe 0,1 mm về phía
trên. Đo được: đúng **một** đa giác gập ngược, và nó là đa giác duy nhất có một
đỉnh lọt sang bên kia khe — 1/12 = 8%, vừa đủ vượt trần 6% và làm bộ dò từ chối
mọi góc quay có ích (chốt ở 0,09 rad, che phủ 24% → 16%). Giờ chiều lấy theo
**nhóm vertex thuộc về**. Sau khi sửa: 0% gập ngược ở mọi góc tới 0,60 rad.

**2. Khoé mắt là điểm neo.** Hai nửa mí dính liền nhau ở hai khoé nên ở đó chúng
không được đi ngược chiều. Phép khép không bị vì nó nhân với `gap` vốn tự về 0 ở
khoé; phép quay phải mượn đúng ý đó — nhân thêm `taper()` như môi. Đo được: giãn
cạnh ở góc 0,20 rad từ **3,91 xuống 1,48**.

**3. Phép khép phải đo từ chỗ vertex ĐÃ ĐỨNG SAU KHI QUAY.** Quay đã dời mép lỗ
rồi, khép theo số nghỉ là khép hụt chỗ này thừa chỗ kia. Đo trên mắt .L — khép
theo số nghỉ chạm đáy ở khẩu độ **19%** rồi hở trở lại; đo từ chỗ đã quay thì
xuống thẳng **0%** ở `conv = 1.00`, tuyến tính, 0% gập ngược suốt.

### Bộ dò hai chặng

Hai tham số, hai mục tiêu, nên dò tuần tự: chặng 1 quét `swing` chấm bằng che
phủ, chặng 2 quét `conv` chấm bằng khẩu độ với góc quay đã chốt. Không quét lưới
2 chiều vì hai tham số gần như độc lập — cùng kết quả với 1/13 số phép đo.

### Hợp đồng chấm CẢ HAI thước

Thêm phép chấm che phủ nhãn cầu bên cạnh khẩu độ. Hai thước, hai chuyện; thiếu
thước nào cũng lọt một bộ key nhìn hỏng — và cả hai lần lọt vừa rồi đều do thiếu
đúng một trong hai. Che phủ chấm theo **tỉ lệ so với lúc mở** (`GOAL_SEEN = 0.5`)
chứ không theo số tuyệt đối: với nhãn cầu to nằm gọn trong đầu, con số lúc mở đã
là 24%, đòi 10% tuyệt đối là đòi một thứ vô nghĩa.

Cũng sửa một chỗ nhỏ mà đắt: hợp đồng đọc lại nhóm THÔ rồi chấm trong khi bộ
dựng làm việc trên nhóm ĐÃ VUỐT MỀM — hai hệ trục khác nhau, cùng một con mắt ra
9% hay 15% tuỳ chọn hệ nào.

`Mesh_0.001`: **14 dòng ĐẠT, 2 CẢNH BÁO** (mắt nhỏ che phủ 19% → 11%).

### Bài test

`test_hole.py` **26/26**. Canh cầu dựng lại cho đúng hình học thật: tâm nhãn cầu
lùi vào sao cho cực trước chạm mặt da (quả cầu nằm trong đầu, chỉ lộ cái chóp
qua lỗ), và **mép lỗ được kéo cuộn vào trong** thành phễu. Canh cũ đặt quả cầu
nhô ra ngoài da — che phủ 85% và không phép quay nào hạ được, tức nó không tái
hiện được ca hỏng nào cả.

Ba ca quyết định, giữ cả ba để chứng minh từng nửa là không đủ:

| ca | khẩu độ | con ngươi |
|---|---|---|
| CHỈ khép lỗ | 13% ✓ | 45% → 33% ✗ *(người xem thấy mắt mở)* |
| CHỈ quay | 70% ✗ | 45% → 0% ✓ |
| **cả hai** | **9% ✓** | **45% → 16% ✓** |

Và ca chốt chặn chấm bằng **quãng đường bị đẩy** thay vì khẩu độ: luật cũ đẩy
mép lỗ ngược ra 11,78 mm, luật mới 0,00 mm. Độ lớn hiệu ứng phụ thuộc phễu sâu
bao nhiêu nên khẩu độ đổi ít trên canh tổng hợp; quãng đường thì đo được ở cả
hai.

Toàn bộ 20 bộ: `test_all` 32 chức năng, `test_ref` 32, `test_hole` 26,
`test_multieye` 24, `test_picker` 21, `test_foureyes` 18, `test_order` 17,
`test_eyeball` 16, `test_dropref` 15, `test_lidcover` 15, `test_regress` 14,
`test_mount` 14, `test_names` 14, `test_manylimbs` 13, `test_soften` 11, cùng
`test_sym`, `test_hand`, `test_roll`, `test_fkwidget`, `test_widget2` — **xanh
hết**.

---

## 1.5.0 — 2026-08-22

### MẮT KHOÉT LỖ: nhắm mắt là KHÉP CÁI LỖ, không phải che nhãn cầu

Anh Art tắt con ngươi đi rồi nhìn, và thấy cái mà không phép đo nào của tôi
thấy: **ở trạng thái nhắm, hai mắt vẫn không khép hẳn**. Trong khi đó bảng điểm
báo con ngươi hở 24%% → 2%% và hợp đồng báo ĐẠT hết.

Cả hai đều đúng, và cả hai đều vô nghĩa. `Mesh_0.001` **khoét hẳn một cái lỗ ở
mỗi mắt** — bốn vòng biên hở, mỗi vòng 7 vertex. Mảng da mí trượt ra TRƯỚC nhãn
cầu nên che nó rất giỏi, còn cái lỗ thì nguyên vẹn: nhìn xuyên thẳng vào trong
đầu. Đây là lần thứ hai **cùng một kiểu sai** — đo bằng một thước không phải
công năng — và nó xảy ra NGAY SAU khi cả một hệ thống hợp đồng được dựng lên để
chặn đúng kiểu đó. Hợp đồng chỉ chặn được thứ nó biết đo.

Thước mới: **bề rộng cái lỗ**, đo bằng chính mép lỗ, không dính gì đến nhãn cầu.
Đo được cả khi giấu con ngươi — tức đo đúng cái anh Art nhìn.

| `Mesh_0.001`, nhắm hết cỡ | khẩu độ còn lại |
|---|---|
| bản 1.4.0 (mô hình cung) | **100%%** — không khép chút nào |
| bản này | **9–11%%** |

Đường cong theo slider: `100 → 77 → 55 → 32 → 10%%`, đơn điệu, 0%% đa giác gập
ngược, giãn cạnh p99 1,45.

### Năm chỗ hỏng, tìm ra bằng năm phép đo

**1. Vertex thuộc CẢ hai nhóm mí thì hai phép dịch triệt tiêu nhau.** v1298 và
v1301 nằm trong cả `FS_LidUpper.L` lẫn `FS_LidLower.L`; vòng lặp cộng hai vector
ngược chiều lên cùng một vertex. Đo được: mép lỗ trọng số 1.0 mà dịch đúng
**0,00 mm**. Đúng bài học đã ghi cho xương hàm — thuộc cả hai phía thì phải
QUYẾT, không chia đôi.

**2. Trục quay lấy riêng từng vertex bỏ sót đúng mép lỗ.** Trục cũ là
`u × tang`; vertex nằm thẳng trên/dưới tâm mắt có `tang ≈ 0` nên bị `continue`.
Đó chính là những vertex phải đi xa nhất.

**3. `eyeball_guard` lôi ngược mép lỗ ra.** Luật cũ — *không sâu hơn lúc nghỉ* —
nghe chặt hơn nhưng SAI. Đo trên `Mesh_0.001`:

| | |
|---|---|
| bán kính nhãn cầu | 23,4 mm |
| mép lỗ so với TÂM nhãn cầu, theo trục `out` | −3,5 … −5,8 mm (nằm **sau** tâm) |
| mép lỗ lún trong nhãn cầu **lúc nghỉ** | 4,6 … 14,4 mm |
| pháp tuyến mặt cầu chấm với `out` | −0,22 … −0,76 (hướng **ra sau**) |

Nhãn cầu không lồi qua cái lỗ — **nó nuốt trọn mép lỗ**, đúng như vành mắt thật
cuộn vào sau con ngươi. Khép mí đẩy mép sâu thêm 2–4 mm, luật cũ lôi ngược ra,
và khẩu độ bật từ 10%% lên **26%%**. Lôi ra chẳng được gì: quả cầu đục, vertex nằm
sau mặt cầu thì đi sâu thêm bao nhiêu cũng vẫn khuất.

Luật mới: **vertex NGOÀI nhãn cầu lúc nghỉ thì không được chui vào.** Đó mới là
lúc nhãn cầu thò qua da — thứ duy nhất người xem thấy. `test_multieye` giữ nguyên
ca đối chứng: tắt chốt chặn vẫn 59 lượt đâm, bật thì 0.

**4. Mép lỗ nằm ngoài nhóm mí thì không ai kéo nó.** Trên canh cầu 96×48 có 4/12
vertex mép rơi ngoài nhóm tô, và chúng ghim khẩu độ ở **64%%** dù mọi ràng buộc
lưới còn thừa chỗ. Mép lỗ **là** mép mí theo định nghĩa; giờ vành tắt dần được
dựng từ HÌNH HỌC quanh lỗ chứ không từ phần nghệ sĩ đã tô. `region_invariants`
vẫn báo CẢNH BÁO để nghệ sĩ biết mà tô lại.

**5. Khe NGHIÊNG thì tự nó đã có bề rộng.** Thước đầu tiên đo độ trải của mép lỗ
theo trục `close`. Với mắt xiên 24°, mép lỗ khép đúng vào khe vẫn cho ra một
dải — canh cầu báo hở **25%%** ở trạng thái khép hết cỡ, và bộ dò tưởng mình đã
hết cách. Giờ đo **so với đường khe**. Trên mặt người khe gần ngang nên chênh
lệch không lộ ra; đó là lý do nó nấp được.

### Hai hình học, hai đường đi

Cùng một tham số `k`, nhưng đường đi khác nhau vì thứ phải đạt khác nhau:

* **có khoét lỗ** — mép lỗ đi THẲNG tới đường khe, da xung quanh tắt dần theo
  KHOẢNG CÁCH TRÊN LƯỚI (mét, không phải số vòng — đếm vòng thì con số trôi theo
  mật độ lưới). Vành trải rộng `LID_SPREAD = 1,6` lần quãng mép đi XA NHẤT; lấy
  trung bình thì vành hụt đúng ở chỗ đi xa nhất (giãn 2,63 → rách, so với 2,17).
* **liền da** — không có lỗ nào để khép, việc của mí là CHE QUẢ CẦU, nên cả tấm
  mí QUAY quanh tâm nhãn cầu MỘT GÓC CHUNG (gần như cứng).

Ép chung một đơn vị đã thử và hỏng: quy góc về "phần đường tới khe" biến phép
quay thành phép kéo từng vertex về khe, tức cả tấm mí sập xuống một đường. Canh
tổng hợp — ngay ở `k=0,1` đã giãn cạnh 2,27, tới `k=0,5` thì 26%% đa giác gập
ngược và giãn 7,46.

### ĐÃ THỬ VÀ BỎ — đẩy đích mí ra trước nhãn cầu

Lý lẽ nghe rất đúng: mí thật khép ở trước giác mạc chứ không ở đáy hốc mắt. Dựng
xong, đo: **không ra tay một lần nào**, cả bảy vertex mép đều đẩy thêm 0,00 mm —
vì mép lỗ nằm SAU tâm nhãn cầu (bảng ở mục 3), đường thoát gần nhất chạy ngược
ra sau. Code đã bỏ, số đo giữ lại trong `face.py`.

### Hợp đồng chấm bằng khẩu độ, và chấm trên đúng bộ vùng đã dựng

`eye_contract` tự chuyển sang khẩu độ khi mesh có lỗ, và dòng báo cáo nói rõ
đang đo `khẩu độ` hay `con ngươi`. Thêm một chỗ sửa nhỏ mà đắt: hợp đồng đọc lại
nhóm THÔ rồi chấm, trong khi bộ dựng làm việc trên nhóm ĐÃ VUỐT MỀM — hai hệ
trục khác nhau, cùng một con mắt ra 9%% hay 15%% tuỳ chọn hệ nào. Giờ chấm trên
đúng bộ vùng bộ dựng đã dùng.

Bất biến mới: **lỗ mắt phải có chủ**. Mesh có lỗ ở đúng chỗ con mắt mà nhóm mí
không phủ tới mép thì cả bộ lặng lẽ tụt về đo che phủ và cái lỗ không bao giờ
khép — đúng kiểu hỏng đắt nhất, không ai báo gì cả. Giờ nó báo HỎNG.

`Mesh_0.001`: **12 dòng ĐẠT, 0 cảnh báo**, chạy 0,24 s.

### Bài test

`test_hole.py` (mới, **22/22**) — canh cầu 96×48 khoét hai lỗ, tỉ lệ lấy từ
`Mesh_0.001` (bán kính nhãn cầu gấp 1,6 lần bán kính lỗ, tâm nhãn cầu gần như
nằm trên mặt da, nên mép lỗ nằm sẵn 3,0–12,8 mm bên trong quả cầu). Bài này kiểm
cả tiền đề đó, vì nếu nó sai thì mọi kết luận phía sau vô nghĩa.

Ca quyết định trong bài, tái hiện đúng chuyện đã xảy ra: quét hết khoảng góc của
mô hình cung, lấy góc CHE NHÃN CẦU TỐT NHẤT — che phủ 85%% → 73%%, cải thiện thật,
một bộ dò chấm bằng che phủ sẽ tin — **mà cấu hình nó chọn để cái lỗ hở 74%%**.
Mô hình mới trên cùng canh ấy: 10%%.

Và ca đối chứng cho luật chốt chặn: cùng một trường độ dịch, luật cũ banh khẩu
độ từ 10%% lên 46%%, luật mới giữ nguyên 10%%.

Toàn bộ: `test_all` 32 chức năng, `test_ref` 32, `test_multieye` 24, `test_hole`
22, `test_picker` 21, `test_foureyes` 18, `test_order` 17, `test_eyeball` 16,
`test_dropref` 15, `test_lidcover` 14, `test_regress` 14, `test_mount` 14,
`test_names` 14, `test_manylimbs` 13, `test_soften` 11, cùng `test_sym`,
`test_hand`, `test_roll`, `test_fkwidget`, `test_widget2` — **tất cả xanh**.

---

## 1.4.0 — 2026-08-21 (tối)

### HỢP ĐỒNG: vùng phải thoả gì, shape key phải làm được gì

Bốn lỗi nặng của hai ngày 20–21/08 đều là **cùng một kiểu sai**, lặp lại bốn
lần. Cái đắt không phải từng lỗi mà là cái kiểu:

| | kiểu sai | nó đã gây ra gì |
|---|---|---|
| 1 | **Đo bằng thước nội bộ của công thức** | `_pair_gap` đo khoảng cách hai *nhóm vertex* — đúng cái công thức được thiết kế để giảm. Chấm "khép 54%, ĐẠT" trong khi con ngươi hở 26% |
| 2 | **Bất biến đúng nhưng không liên quan** | `eyeball_guard` cấm da nằm *trong* nhãn cầu, báo 0 lượt — thật. Nhưng mí trượt *ra sau* nhãn cầu: không đâm lần nào mà vẫn hở |
| 3 | **Tối ưu một số, làm hỏng số khác** | 1.3.0 hạ che phủ xuống 6% và làm 17% đa giác mí gập ngược |
| 4 | **Bảo đảm thượng nguồn bị hạ nguồn xoá** | `smooth_field` ăn mất công của mí (5% → 15%) |

Và **vùng** thì chưa hề có hợp đồng nào: `FS_LidUpper.L` chỉ là một tập vertex,
không gì buộc nó liên quan tới con mắt nào — nên nó ôm trọn hai con mắt cả
tháng.

Bốn nguyên tắc ngược lại, cài thành code:

* **`region_invariants()`** — vùng được định nghĩa bởi *vật nó phải trượt lên*.
  Bất biến chính: **mọi vertex trong vùng mí của mắt N phải có mắt N là nhãn cầu
  gần nhất**. Chạy 0,37 s, và một mình nó bắt được lỗi bốn-mắt ngay ngày đầu.
* **`eye_contract()`** — mỗi key mắt phải thoả **cùng lúc**: che phủ ≤ 10%, đơn
  điệu theo slider (0 → 0.25 → 0.5 → 0.75 → 1), nheo không được hở thêm, lưới
  ≤ 6% gập ngược và ≤ 2,4 giãn p99, và **tổ hợp** 14 mẫu biểu cảm không được đâm
  nhãn cầu quá 5% bán kính.
* **Chấm ở CUỐI chuỗi**, sau làm mượt / chốt giãn cạnh / chốt chặn — tức đúng
  thứ được ghi vào file. Chấm sớm hơn là chấm một thứ không phải thứ sẽ dùng.
* **Không chặn dựng** (anh Art chốt): vẫn ghi key, nhưng báo TO ở `self.report`
  và ghi từng dòng ra Console.

Chạy hết 1,08 s cho 12 phép đo trên nhân vật bốn mắt.

### Hai chỗ hợp đồng tự chấm sai, đã sửa

* **`EYE_Wide` bị tính là lỗi.** Mở to mắt thì con ngươi *phải* hở thêm — đó là
  công năng. Giờ mẫu nào dùng `EYE_Wide` thì bỏ qua phép "hở thêm".
* **Đếm từng phần mười mm là kêu suốt ngày.** Da mí vốn ôm sát mặt cầu (phân vị
  25 chỉ cách 0,4 mm). `CONTRACT_DEEP = 5%` bán kính mới tính là lún.

Sau khi sửa: `Mesh_0.001` **12 dòng ĐẠT, 0 cảnh báo**.

### Bộ tái hiện tám lỗi cũ

`test_regress.py` (mới, **14/14**). Một hợp đồng chưa bao giờ thấy một ca hỏng
thì chỉ là lời hứa — nên bài này dựng lại đúng từng ca đã xảy ra và đòi bộ kiểm
phải kêu:

| lỗi cũ | bị bắt bởi | bộ kiểm nói gì |
|---|---|---|
| vùng mí gộp hai mắt | bất biến vùng | `45/86 vertex nằm gần một con mắt KHÁC` |
| mí không hề khép | hợp đồng che phủ | `HỎNG 30 → 28 → 27 → 26 → 31%` |
| cấm xuyên nhưng không cấm bị che | che phủ HỎNG trong khi chốt chặn im | chốt chặn chỉ ra tay ở 4 key |
| nhắm nửa chừng hở hơn lúc mở | phép đơn điệu | `KHÔNG đơn điệu ở mức 1.00` |
| nheo banh mắt ra | hợp đồng nheo | `HỎNG 30% → 33%` |
| lưới nhúm ở góc lớn | ràng buộc chất lượng | `18% gập ngược, giãn 3,18` |
| làm mượt hạ nguồn ăn mất công | đo ở cuối chuỗi | `CẢNH BÁO 30 → 30 → 26 → 25 → 19%` |
| tổ hợp đâm nhãn cầu | phép chấm tổ hợp | máy chạy đủ; trên canh tổng hợp không kích hoạt |

Mục cuối nói cho đúng: phép chấm tổ hợp **chạy và không kêu oan**, nhưng canh
tổng hợp không tạo ra được ca đâm. Nó có kích hoạt trên nhân vật thật (`Buồn`
báo 18 vertex trước khi thêm ngưỡng độ sâu). Tức 7/8 tái hiện được, 1/8 mới chỉ
kiểm được phần máy móc.

Và bài có **ca đối chứng**: trên cùng canh ấy, bản dựng ĐÚNG không sinh dòng
HỎNG nào, đơn điệu/nheo/lưới đều ĐẠT, che phủ 30% → 20%. Không có ca này thì
không có gì chứng minh bộ kiểm chỉ kêu khi thật sự hỏng.

`EXPR_PRESETS` nhấc ra khỏi operator lên module để hợp đồng dùng chung.

---

## 1.3.1 — 2026-08-21 (chiều)

### Góc gấp mí phải bị RÀNG BUỘC bởi chất lượng lưới

Bản 1.3.0 tối ưu đúng một con số — độ che phủ — và làm hỏng một con số khác.
Anh Art nhìn ra ngay trong một ảnh: mắt che được nhưng cả vùng mí **nhúm thành
gai**. Bảng điểm có kêu (14/82 đa giác gập ngược, giãn cạnh max 6,03) và tôi đã
coi nhẹ nó.

Quan hệ giữa góc gấp và chất lượng lưới rất dốc — đo trên `Mesh_0.001`, mắt
thứ nhất, quét từng độ:

| góc | con ngươi hở | đa giác gập ngược | giãn cạnh p99 |
|---|---|---|---|
| 10° | 9% | **0%** | 1,80 |
| 15° | **6%** | 4% | 2,24 |
| 20° | 11% | 9% | 2,69 |
| 25° | 16% | 30% | 3,13 |
| 30° | 17% | 43% | 3,58 |

Quá 20° là hai mí **đâm xuyên nhau** (mỗi bên đi trọn góc từ phía mình). Và
che nhiều hơn không phải lúc nào cũng tốt hơn: quá đà thì mí lộn qua bên kia con
ngươi và hở **trở lại** (25° hở 16%, tệ hơn 15°).

`solve_lid_angles()` giờ là bài tối ưu **có ràng buộc**: che ít nhất trong số
các góc giữ được `LID_FLIP_MAX = 6%` đa giác gập ngược và `LID_STRETCH_MAX = 2.4`
giãn cạnh p99. Quét 13 điểm thô rồi 5 điểm tinh.

### Hai đường đã thử và bỏ trên đường tới đó

Cả hai đều nghe hợp lý và đều hỏng, mỗi cái một kiểu — số đo trên `Mesh_0.001`:

1. **Mỗi vertex chỉ quay tới đường khe của riêng nó**, để hai mí khỏi cắt nhau.
   Lưới sạch tuyệt đối (0% gập, giãn 1,08) nhưng **không che gì cả** (hở 24% →
   26%). Kẹp ở khe làm *mọi* vertex dừng đúng tại khe, tức cả tấm mí co về một
   vạch góc thay vì trải ra trên mặt cầu.
2. **Quay cả tấm nhưng kẹp ở khe** (`min` giữa hai cái trên). Cùng kết quả:
   phần lớn vertex vẫn bị kẹp về khe, hở 24%.

Kết luận rút ra: **che được là nhờ tấm mí TRẢI RA trên mặt cầu, không phải nhờ
nó đi tới đâu.** Nên giữ phép quay đều, và chống đâm xuyên bằng cách giới hạn
GÓC chứ không bằng cách kẹp từng vertex.

Một chi tiết hình học đã trả giá: lần thử 1 lấy **góc của điểm khe nhìn từ tâm
nhãn cầu**. Sai, vì đường khe chạy gần ngay tâm nên góc đó gần bằng không và mí
không nhúc nhích. Muốn nói "hạ mí xuống ngang mức khe" thì phải giải
`asin(mức khe / bán kính)`, không phải lấy góc của điểm khe.

### Kết quả trên `Mesh_0.001`

| | 1.3.0 | 1.3.1 |
|---|---|---|
| đa giác mí gập ngược | 14/82 (**17%**) | **0/49 (0%)** |
| giãn cạnh mí p99 / max | 3,39 / 6,03 | **1,46 / 2,32** |
| con ngươi hở khi nhắm 1.0 | 6% | 10% |
| nhắm 0.25 / 0.50 / 0.75 | 19 / 17 / 7% | 18 / 15 / 13% |
| nheo 1.0 | 6% | 13% |

Đổi 4 điểm che phủ lấy một cái lưới sạch. Nhìn bằng mắt thì đây mới là bộ dùng
được — bản 1.3.0 che kín hơn nhưng gãy nát.

---

## 1.3.0 — 2026-08-21

### Mí mắt CHƯA BAO GIỜ khép — và một thước đo sai đã giấu chuyện đó

Đây là lỗi nặng nhất từ đầu dự án, và nó nấp được vì **mọi phép đo đều đúng
nhưng đo nhầm thứ**.

Bản cũ đẩy vertex mí theo **đường thẳng** về đường khe. Đường khe nằm giữa hai
nhóm mí — mà chỗ đó lại nằm **phía sau** mặt trước nhãn cầu. Nên mí trượt vòng
ra sau con ngươi thay vì phủ qua trước nó. Kết quả: không lần nào "đâm xuyên"
(`eyeball_guard` báo đúng 0 lượt), `_pair_gap` cũng báo "khép 54%" (đúng nốt,
hai nhóm có xích lại gần nhau thật) — trong khi con ngươi lồ lộ.

Đo trên `Mesh_0.001`, tắt trò co nhãn cầu để xem **một mình cái mí** làm được gì
(% mặt nhãn cầu hướng về người xem còn nhìn thấy):

| nhắm | con ngươi còn hở |
|---|---|
| 0.00 (mở mắt) | 21% |
| 0.50 | 23% |
| **1.00** | **26%** |

Nhắm hết cỡ còn hở **hơn** lúc mở. Cái "mắt nhắm" xưa nay hoàn toàn do **nhãn
cầu tự co còn 80% và thụt vào 6 mm** để trốn. Driver co ấy lại có ngưỡng 0.6,
nên mọi giá trị lưng chừng và **toàn bộ `EYE_Squint`** (không có driver) đều lòi
con ngươi ra ngoài da.

**Bài học chung, đắt hơn cả cái lỗi:** một bất biến đúng (`không đâm xuyên`) vẫn
có thể hoàn toàn không liên quan tới thứ cần bảo đảm (`bị che khuất`). Trước khi
tin một thước đo, phải hỏi nó có đo đúng **công năng** không.

### Mí trượt QUA TRƯỚC nhãn cầu, biên độ dò bằng ĐO

* `lid_arc()` — vertex mí **quay quanh tâm nhãn cầu** thay vì đi thẳng. Khoảng
  cách tới tâm không đổi nên mí luôn nằm trên mặt cầu, tức luôn ở phía trước
  con ngươi. Ràng buộc nằm trong hình học, không phải trong một chốt chặn vá sau.
* `solve_lid_angles()` — **dò góc bằng cách đo che phủ**, từng con mắt một. Không
  công thức nào ra được con số đó: nó phụ thuộc hình mí, cỡ nhãn cầu và độ lồi
  của mặt cùng lúc. Trên `Mesh_0.001` bốn mắt ra hai góc khác nhau (15,9° cho
  cặp mắt to, 13,6° cho cặp mắt nhỏ). Chạy hết **1,4 giây**.
* Mục tiêu là **góc NHỎ NHẤT che kín**, không phải góc che kín nhất. Khi mí đã
  phủ hết thì cả một dải góc cùng cho 0%, và "chọn cái tốt nhất" thì trôi tới
  tận trần — đo được: mắt trái chốt 55,9° còn mắt phải cùng hình dạng trôi lên
  74,5° (chạm trần) dù cả hai đều 0%.
* `eyeball_uncovered()` — thước đo mới: bắn tia từ vertex nhãn cầu ra phía người
  xem, **chỉ bắn vào mesh mặt** (mũ/kính/mặt nạ không tính là che, bài học từ
  `eyeball_exposure`).
* Đường thẳng cũ vẫn còn, làm **đường lui** cho mesh không có nhãn cầu nào chỉ
  tới (robot, đạo cụ, mắt vẽ trên texture).

### Mí được MIỄN làm mượt

Cùng lý do với răng nhưng nghiêm trọng hơn: quãng đi của mí do phép **đo** quyết
định, mà `smooth_field` lấy trung bình với láng giềng **ngoài** vùng mí — những
vertex đứng yên — nên nó kéo cái mí vừa khép quay về phía mở.

| cùng một góc | con ngươi hở |
|---|---|
| không làm mượt | 5% |
| có làm mượt | 15% |
| bảo bộ dò tự bù bằng cách đo trên số đã mượt | 11% |

Làm mượt đặt một **trần cứng** lên mức khép — tăng góc bao nhiêu cũng không
vượt. Viền không bị gãy vì `soften_regions()` đã vuốt **trọng số** nhóm rồi, tức
chính biên độ đã tắt dần ở rìa mí; đó mới là chỗ chữa đúng.

### Bỏ trò co nhãn cầu (anh Art chốt)

`eye_shrink_on` mặc định **TẮT**. Nhắm mắt giờ là mí che thật. Hết luôn cú nhảy
bậc ở ngưỡng 0.6.

### Bảng điểm chấm bằng CHE PHỦ

`GOAL_COVER = 0.10` — nhắm hết cỡ, con ngươi chỉ được hở tới ngần này.
`GOAL_BLINK` (khoảng cách hai nhóm mí) tụt xuống làm **đường lui** cho mesh
không có nhãn cầu, và dòng báo cáo nói rõ là "chỉ đo được gián tiếp".

### Kết quả trên `Mesh_0.001` (bốn mắt, cường điệu 150%)

| | trước | sau |
|---|---|---|
| mở mắt (nền) | 21% | 21% |
| nhắm 0.50 | 23% | 17% |
| **nhắm 1.00** | **26%** *(chỉ 0% nhờ nhãn cầu tự co)* | **6%** — mí che thật |
| **nheo 1.00** | **24%** | **6%** |
| nheo + nhìn lên 25° | 25% | 7% |
| nhắm + liếc 25° | — | 5% |
| nhắm + nhìn xuống 25° | — | 2% |

Dựng cả bộ 56 key mất 1,6 giây (kể cả 1,4 giây dò góc).

### Kiểm tra

`test_lidcover.py` (mới, **13/13**) — thước đo duy nhất được phép kết luận là
bắn tia, và mọi phép đo đều có **đối chứng đường thẳng cũ**: đo được thẳng để
lại 54–55% con ngươi hở còn cung để lại 0–1%. Có cả ca ngược: bảng điểm phải
chấm **HỎNG** khi cho nó số đo "che 0%".

Chạy lại toàn bộ 17 bộ, 0 hỏng.

---

### Đã thử và bỏ — dùng mesh con ngươi để CHẶN TỪ ĐẦU thay vì sửa sau

Anh Art hỏi đúng câu đáng hỏi: sao không lấy chính mesh con ngươi đã chọn ở
bước 1 mà định hình biên độ mí, để không bao giờ có gì phải cứu? Đã dựng và đo
**cả hai cách hiểu** của câu đó:

1. **Trượt trên mặt cầu** — vertex mí quay quanh tâm nhãn cầu thay vì đi thẳng,
   giữ nguyên độ dài quãng đường. Về lý thì khoảng cách tới tâm không đổi nên
   "không thể lún vào".
2. **Kẹp quãng đường** — giữ nguyên hướng đã hiệu chỉnh, chỉ cắt ngắn quãng đi
   ở đúng chỗ vertex chạm mặt nhãn cầu (`clamp_travel`, lấy mẫu 12 điểm dọc
   đoạn — độ lún dọc một đoạn cắt qua khối lồi là hàm **lõm**, chia đôi tìm
   nghiệm không có gì bảo đảm).

`Mesh_0.001`, cường điệu 150%, nhóm vùng **thô** (tắt vuốt mềm viền) để sáu
lượt so được với nhau. Cột "đâm vào" đếm trên cả 56 shape key × 4 nhãn cầu:

| | khép mí | đâm vào | giãn cạnh mí p99/max |
|---|---|---|---|
| đi thẳng, không chốt chặn | 60,3 / 59,7 | 30 lượt | 1,66 / 1,87 |
| **đi thẳng + chốt chặn** | **59,5 / 58,7** | **0 lượt** | **1,66 / 1,87** |
| (1) trượt, không chốt chặn | 55,7 / 53,6 | 34 lượt | 1,66 / **2,29** |
| (2) kẹp, không chốt chặn | 50,2 / 47,7 | 38 lượt | 1,66 / 1,88 |
| (2) kẹp + chốt chặn | 47,9 / 47,6 | 0 lượt | 1,66 / 1,88 |

Cả hai đều **thua trên mọi cột**, và — điều quyết định — **cả hai vẫn đâm vào
nhãn cầu**, đúng thứ chúng sinh ra để chặn.

**Lý do nằm ở THỨ TỰ.** Sau `lid()` còn `smooth_field()` (lấy trung bình với
láng giềng) rồi `cap_stretch()` (nhân đều cả trường độ dịch). Hai bước đó dời
vertex lần nữa, nên mọi bảo đảm hình học dựng trong `lid()` đều bị phá ở hạ
nguồn. Trong một chuỗi như thế, **chỗ duy nhất bảo đảm được là chỗ cuối cùng**
— và đó chính là `eyeball_guard`.

Cái giá thì ngược với trực giác: chốt chặn tốn **0,8 điểm** khép mí, không đổi
độ giãn, ra tay đúng 36 lượt trên cả 56 key. Chặn từ đầu tốn **4,6 điểm**
(trượt) tới **11,7 điểm** (kẹp) — nó cắt ngắn quãng đi của đúng những vertex
làm nhiệm vụ che, rồi làm mượt đem phần hụt lan sang hàng xóm.

Code đã gỡ, số đo giữ lại thành khối ghi chú ngay trên `eyeball_guard`. Muốn
chặn từ đầu thật thì phải đổi kiến trúc: làm mượt và chốt giãn cạnh phải biết
về nhãn cầu, hoặc lặp cả ba bước tới khi hội tụ. Chưa đáng, vì chốt chặn hiện
tại đã cho 0 lượt đâm.

Giữ lại một phần: `eyeball_shields()` tách khỏi `eyeball_guard` thành hàm
riêng, dựng BVH của nhãn cầu **một lần** cho cả bộ key.

---

## 1.2.1 — 2026-08-20 (chiều)

### Nhân vật NHIỀU MẮT một bên: mỗi con mắt một vùng riêng

`face.py`. Bộ vùng `FS_*` xưa nay chỉ có **một** cặp nhóm mí mỗi bên
(`FS_LidUpper.L` / `FS_LidLower.L`). Nhân vật bốn mắt (hai cặp chồng nhau mỗi
bên) rơi hết vào cùng một nhóm, và đó là chỗ **hỏng** chứ không phải chỗ thiếu
tính năng.

Đo trên `Mesh_0.001` (bốn mắt, bốn tay):

| | |
|---|---|
| `FS_LidUpper.L` | 33 vertex — **17 gần mắt to, 16 gần mắt nhỏ** |
| `FS_LidLower.L` | 38 vertex — 19 / 19 |
| hai tâm nhãn cầu cách nhau | 37,4 mm trên bán kính 23,4 mm (1,60 lần) |

Một nhóm gộp thì `PairFrame` + `seam_line()` khớp **một** đường khe cho cả hai
con mắt, và đường đó rơi đúng khoảng giữa: tâm mắt to cách khe **+8,6 mm**, tâm
mắt nhỏ **−14,5 mm**. Gấp mí về đường ấy kéo da của cả hai mắt vào giữa.

* Hậu tố theo đúng quy ước xương của `rigdef.inst_name`: mắt thứ nhất giữ
  nguyên `.L`, mắt thứ hai là `_2.L` — khớp tên xương `Eye_2.L`. Rig hai mắt cũ
  **không đổi một chữ nào** (`region_table` đúng bằng `REGIONS`: 16/16).
* `split_eye_regions()` tự tách nhóm gộp, chạy trong `make_regions`. Chia theo
  khoảng cách tới **mặt cầu** (`|p−c| − r`) chứ không tới tâm: hai mắt cùng bên
  hay khác cỡ, đo tới tâm thì luôn thiên vị quả to. Không vứt vertex nào —
  kiểm bằng phép cộng lại đúng số cũ.
* `lid()` và `eyeball()` chạy **từng con mắt một**, mỗi con dùng hệ trục và
  đường khe của riêng nó rồi mới cộng lại.
* Bảng điểm chấm **từng mắt**. Gộp hai mắt vào một phép đo thì mắt không nhắm
  được mắt kia gánh điểm hộ — đúng cái bẫy đã cho bộ key bốn mắt "đạt" trong
  khi không con mắt nào khép.
* `seam_partner` ghép theo **tiền tố** thay vì bảng tên đầy đủ; `is_sharp()`
  thay `SHARP_REGIONS`; `jaw_block_names()` thay bảng `JAW_BLOCK` cứng. Bảng
  tên cứng thì cứ thêm một con mắt là quên một tên.

Kết quả trên nhân vật thật (`Mesh_0.001`, cường điệu 150%):

| | trước | sau |
|---|---|---|
| mắt 1 trái khép | 48,5% | **54,1%** |
| mắt 2 trái khép | 50,4% | **54,2%** |
| mắt 1 phải / mắt 2 phải | 48,5% / 50,4% | **54,2% / 53,7%** |

Nhìn thì cả bốn mắt nhắm kín, không còn thấy tròng.

### Chốt chặn: da không được lún vào nhãn cầu sâu hơn lúc nghỉ

`eyeball_guard()` trong `face.py`, chạy **sau** chốt chặn giãn cạnh (chốt chặn
nhân đều cả trường độ dịch nên nó kéo được một vertex vừa cứu chui vào lại).

Khép mí là da **trượt trên** mặt cầu, còn shape key chỉ là trường vector tuyến
tính: nó đi thẳng, nhãn cầu thì cong. Đo trên bộ key cũ — lúc nghỉ đã có 7
vertex mí nằm trong mỗi nhãn cầu (da cuộn vào sau vành mắt, hoàn toàn đúng),
rồi `EYE_BlinkL` đẩy **thêm 10 vertex** vào, sâu nhất **12,71 mm** trên bán
kính 23,4 mm. Đó chính là con ngươi lòi qua mí.

* Bất biến: **không vertex nào lún sâu hơn lúc nghỉ**. Nói "đẩy hết ra ngoài"
  là sai — 7 vertex kia vốn đã ở trong, kéo ra là banh hốc mắt.
* Hình chặn lấy từ **chính lưới nhãn cầu** qua BVH, không phải mặt cầu: nhãn
  cầu tạo hình có giác mạc lồi, chặn bằng mặt cầu thì hoặc lọt giác mạc hoặc
  phình ra khỏi tròng. Nhãn cầu nằm trong mesh mặt thì co theo `eyeball()` nên
  hình chặn lấy vị trí **đã dịch** của chính nó.
* Phải **lặp** (`EYE_PASSES = 6`): hai nhãn cầu cùng bên gần như chạm nhau, đẩy
  ra khỏi quả này là đẩy vào quả kia. Một lượt duy nhất chỉ hạ 125 lượt đâm
  xuống 6; lặp thì về 0.

| | tắt chốt chặn | bật |
|---|---|---|
| bộ thử bốn mắt, cả bộ key | 125 lượt đâm, sâu nhất 10,94 mm | **0 lượt** |
| `Mesh_0.001`, cả **56** key × 4 nhãn cầu | 10 lượt (12,71 mm) ở riêng `EYE_BlinkL` | **0 lượt** |
| biên độ lớn nhất | 0,0388 m | 0,0413 m (+6%) |

Biểu cảm **cộng dồn** (14 mẫu trong bảng "Thử biểu cảm") đo lại trên nhân vật
thật: 9/10 mẫu **không thêm vertex nào** vào nhãn cầu so với lúc nghỉ. Riêng
"Buồn" thêm 2 vertex — nằm sau vành mí, nhìn không thấy. Shape key là **cộng
tuyến tính**, nên chốt chặn từng key không thể bảo đảm cho mọi tổ hợp; đây là
giới hạn của cách làm, không phải lỗi cài đặt.

### Danh sách nhãn cầu là của CẢ SCENE — phải lọc theo mesh

`eye_meshes_for()`. `srp_generate.eyes` không thuộc về một mesh nào cả. File
`Ver3_work.blend` có `Male` (người, hai mắt) và `Mesh_0.001` (bốn mắt) dùng
**chung** một danh sách, nên đọc thẳng danh sách ấy là gán bốn con mắt của nhân
vật này cho khuôn mặt của nhân vật kia rồi tách đôi nhóm mí của người ta.

Thước đo là bán kính **của chính nhãn cầu** (`EYE_HOME = 4.0`): mắt nằm đúng
hốc thì da mí ôm quanh nó, cách chưa tới một bán kính; nhân vật khác thì cách
hàng mét. Kiểm trên scene thật: `Mesh_0.001` nhận đúng 4 nhãn cầu, `Male` nhận
**0** và không bị tách nhóm nào.

### Kiểm tra

`test_multieye.py` (mới, **23/23**) — dựng đầu hình cầu 64×32 với hai cặp mắt
xếp chồng đúng tỉ lệ nhân vật thật (tâm cách nhau 1,60 lần bán kính).

Đầu **không** dùng cube kéo dài: cube 0,25 × 0,15 × 0,9 chia đều cho ô lưới
lệch 3,6 lần (10 mm ngang, 37 mm dọc), mà hai mắt cùng bên chỉ cách nhau 26 mm
— gần hơn một ô lưới. Fixture như thế đo chính nó chứ không đo addon.

Mỗi phép đo đều có **đối chứng tắt tính năng**: một chốt chặn im lặng vẫn làm
mọi phép đo "đạt", nên phải đo cả trường hợp không có nó.

Chạy lại toàn bộ: `test_all` 32 chức năng, `test_ref` 32/32, `test_picker`
21/21, `test_order` 17/17, `test_eyeball` 16/16, `test_soften` 11/11,
`test_dropref` 15/15, `test_mount` 14/14, `test_names` 14/14, `test_foureyes`
18/18, `test_manylimbs` 13/13, `test_multieye` 23/23, cùng `test_sym`,
`test_hand`, `test_roll`, `test_fkwidget`. **0 hỏng.**

`test_clip.py` / `test_split.py` / `test_split2.py` / `test_sweep.py` cần một
file có `Male` **và** `3.0_Rig` với nhãn cầu **còn nằm trong mesh mặt`. Nhãn
cầu của nhân vật đó đã tách ra thành object riêng từ phiên trước, nên tiền đề
của bốn bài này không còn — `test_sweep` vẫn chạy, ba bài kia dừng ở bước
`split_eyeballs`. Không phải lỗi mới.

### Phải bấm lại

Bộ shape key đang có được dựng bằng luật cũ và **không tự cập nhật**. Vào mục 7
→ **"1 · Tạo nhóm vùng FS_*"** (để tách nhóm mí) rồi **"2 · Dựng bộ shape
key"**.


## 1.2.0 — 2026-08-20

### Bộ sinh rig từ BỘ XƯƠNG REF, bỏ hẳn kiểu đặt marker

`refrig.py` (mới) + `generate.py` viết lại. Marker kiểu Auto Rig Pro không thể
hiện được vị trí khớp lẫn phương xoay của bone; giờ là một armature ref thật,
nắn từng bộ phận một, mỗi bộ phận **tự chọn xương cha** — nên nhân vật nhiều
tay nhiều chân đều dựng được.

* Thẻ (`TAG_PART` / `TAG_INST` / `TAG_SIDE` / `TAG_BASE`) ghi thẳng lên xương
  ref, không suy từ tên. Suy từ tên thì `FACE` bị tách làm ba khoá.
* Tối đa 8 chi mỗi loại mỗi bên (`rigdef.MAX_INSTANCE`). Chi thứ nhất giữ
  nguyên tên cũ nên rig làm từ trước vẫn khớp.
* Bàn tay 20 xương nằm **trong bộ ref** để chỉnh từ ref, không phải sửa tay
  trong rig đã dựng (sửa xong dựng lại là mất).
* Xương ngón đánh số **sau** hậu tố bên: `Palm.L.001`, không phải `Palm.001.L`.

Kiểm chứng: 32/32 (`test_ref.py`). Dựng trực tiếp == dựng trái rồi đối xứng:
57/57 xương, lệch 0,0000 mm / 0,0000°.

### Tay phải là ẢNH GƯƠNG, không phải tay trái xoay 180°

`refrig._hand_spec`. `direction.cross(Z)` tự đổi dấu theo bên, nên trục ngang
bàn tay quay ngược: ngón trỏ nằm sau lưng còn ngón cái chìa ra trước. Nhân
`flip` vào **cả** `across` lẫn `down` mới thành phép gương thật.

Kiểm chứng: lệch 0,0000 mm so với ảnh gương lý thuyết.

### Widget: hướng, kích thước, hình

* **Vòng tròn quanh xương phải nằm trong mặt phẳng XZ.** Trong hệ custom
  shape, **Y chạy dọc xương**; `_circle(axis='Z')` nằm trong mặt phẳng chứa
  trục xương nên 17/28 widget quay sai 90°.
* **`custom_shape_translation` là MÉT THÔ**, không theo chiều dài xương — chỉ
  `custom_shape_scale_xyz` mới nhân với chiều dài. Đặt `0.5` làm cả bộ widget
  bàn tay bay ra xa nửa mét. Muốn dịch theo tỉ lệ thì tự nhân `bone.length`.
* Hình chạy dọc (`Slab`, `Bar`, `Horseshoe`) bị loại khỏi `auto_fit`: bọc theo
  da phóng widget vai lên 5,53× (344 mm trên xương 109 mm, chạm tới khuỷu).
* `fit_meshes()` ba tầng: mesh chỉ định → mesh đã skin → **mesh nhân vật chọn
  ở bước 1**. Nhờ tầng ba, nút widget dùng được trước khi bind.

### FK/IK: bàn tay và bàn chân bám theo control

`build.ensure_tip_follow()` + `rigdef.CON_TIP`. Constraint IK chỉ giải hai
đoạn đầu (`chain_count=2`), đoạn thứ ba không ai điều khiển — xoay control thì
bàn tay đổi hướng do chuỗi giải lại chứ không do ý người kéo (lệch 31,7° ở
tay, 18,5° ở chân).

Copy Rotation `LOCAL_OWNER_ORIENT` / `LOCAL_WITH_PARENT` / `REPLACE`, trỏ vào
**`limb.ctrl`** chứ không phải `limb.ik_target()`: với chân, đích là `AnkleIK`
— xương đó không bao giờ có góc xoay cục bộ của riêng nó, nên chân ra 0,0°.
Foot roll thêm ba constraint `ADD` từ Heel/ToeTip/Ball.

Kiểm chứng: cả 4 chi **40,0°** khớp control; mỗi trục lăn **30,0°**; tư thế
nghỉ chuyển FK↔IK lệch **0,000e+00**. `3.0_Rig` không bị thêm bớt constraint
nào.

### Picker: không còn sót xương

`picker.py` viết lại (`test_picker.py`, 21/21).

* `has_face()` từng dò ba tiền tố gõ cứng (`EyeBrow`/`Eyebrow`/`Jaw_Base`) —
  tên của họ rig gốc. Rig addon sinh ra đặt `Jaw` và `Eye.L/R` nên **cả bảng
  Mặt biến mất** dù ba xương đều bấm được. Giờ hỏi thẳng bảng `FACE_GROUPS`.
* Các hàng tay/chân viết theo **tên gốc**; số thứ tự chi và hậu tố bên do
  `rigdef.bone_name()` chèn vào lúc vẽ → chi thứ 2 trở đi có bảng riêng.
* Bảng **Bàn tay** mới: cả bàn / lòng bàn / 5 ngón / 3 vòng đốt, hai bên.
  Palm nào thuộc ngón nào lấy theo **quan hệ cha con**, không theo chỉ số
  (`_hand_spec` xếp từ ngón út nên `Palm.002` là ngón giữa).
* Bảng **Còn lại** tự sinh: quét control đang hiện, trừ đi cái đã có nút,
  phần dư hiện ra. Sơ đồ gõ cứng không đoán được bộ ref sẽ đẻ ra gì.
* Hàng không bấm được vẽ **nút mờ**, không vẽ chữ trần — chữ trần làm lưới
  nút thủng lỗ, nhìn y hệt picker thiếu xương.

Đo: rig 4 tay + 2 chân + đuôi 5 đốt → **125 control, sót 0**.
`poll()`: `has_face` 0,525 → **0,0034 ms**; bảng bàn tay 0,53 → **0,001 ms**;
phép quét 2,25 ms bỏ hẳn khỏi `poll`.

### Thứ tự các bước: tô vùng mặt TRƯỚC bind

Nhóm `FS_*` là đầu vào của **hai** việc — trọng số hàm/mắt lúc bind, và bộ
shape key. Nó vốn chỉ có ở bước cuối, nên lần bind đầu tiên xương hàm bắt buộc
ăn theo automatic weights rồi phải quay ngược lại tô lại. Panel cũ tự in ra
câu *"bấm 'Tạo nhóm vùng FS_*' ở mục 6 trước"* — quy trình tự thú nhận chạy
ngược.

Giờ **7 bước**, bước 5 là "Nhóm vùng khuôn mặt", chỉ đợi bước 1 (làm trên
mesh, không cần rig). Không sửa một dòng logic nào: `srp.bind` vốn đã hỏi
`has_face_regions()` rồi tự tô kèm nới biên + làm mượt Laplacian.

Đo (`test_order.py`, 17/17), cùng bộ hình học, bind hai lần:

| | môi TRÊN dính hàm | nhóm `Jaw` |
|---|---|---|
| chưa tô vùng | 0,306 | 940 vertex |
| tô vùng trước | **0,000** | **174 vertex** |

`has_face_regions()` **không được gọi trong `poll()`**: nó duyệt mọi vertex ×
mọi group, đo được **11,1 ms** trên mesh 2 729 vertex / 150 nhóm, mà
`build_progress()` chạy trong `poll()` của cả 7 panel. Tách làm hai câu hỏi —
`face_region_groups()` hỏi "đã **tạo** chưa" (**0,0025 ms**), `has_face_regions()`
hỏi "đã **tô** chưa" (chỉ gọi lúc bấm nút). Vertex group **không** nằm trong
`mesh.attributes` ở Blender 5.0 nên không có đường đọc hàng loạt ở tầng C.

`BIND_STEP` thành hằng số — trước đó `step_visible` gõ thẳng `done[4]`, chèn
một bước vào giữa là trỏ sai một ô.

### Vuốt mềm viền: chỉ ghim ở KHE thật

Bản đầu ghim mọi vertex giáp **bất kỳ** vùng nào khác. Các vùng trên mặt vốn
nằm sát nhau, nên trên mesh dày vùng nó ghim sạch và cả bước làm mềm thành vô
hiệu. Đo trên nhân vật bốn mắt: `FS_LidUpper.L` bị ghim **33/33 vertex, không
cái nào được vuốt** — mí trông bị bóp bẹt khi nheo mắt.

Giờ chỉ ghim ở khe THẬT (`SEAM_PAIRS`: môi trên↔môi dưới, mí trên↔mí dưới) —
những chỗ mà bậc thang dựng đứng là đúng vì hai mép phải rời nhau được. Giáp
`FS_Brow` hay `FS_Cheek` thì không có khe nào để giữ, cứ vuốt mềm.

| `Mesh_0.001`, số vertex được vuốt | trước | sau |
|---|---|---|
| `FS_LipUpper` | 22/35 | **26/35** |
| `FS_Nose` | 2/18 | **13/18** |
| `FS_Jaw` | 18/42 | **24/42** |
| `FS_Cheek.L` | 0/11 | **10/11** |

Khe môi vẫn giữ trọn ở cả hai mesh (2/2 và 14/14), nên miệng vẫn hé ra được.

Còn lại: `FS_LidUpper.L` trên mesh này vẫn 32/33 bị ghim, vì hai nhóm mí của
nó **đan xen nhau** chứ không giáp nhau theo một đường — chỗ nào cũng chạm
partner. Đây là hạn chế đã biết, chưa xử lý.

### Nhân vật nhiều hơn hai mắt

Bước 1 chỉ có đúng hai ô `eye_L` / `eye_R` nên nhân vật bốn mắt không có cách
nào chỉ tới cặp thứ hai. Sửa cả **hai nửa** — chỉ sửa ô chọn thì cũng không có
xương nào để gắn vào.

**Bộ ref**: thêm bộ phận `EYE` ("Mắt (thêm cặp)"), `once=False` nên thêm được
bao nhiêu cặp tuỳ ý → `Eye_2.L/R`, `Eye_3.L/R`… Cặp thứ nhất vẫn nằm trong
"Hàm & mắt" như cũ, nên quy trình hai mắt không phải bấm thêm lần nào.

Số thứ tự cặp mắt đếm theo **xương `Eye*` đang có**, không theo thẻ bộ phận
(`eye_inst`): cặp thứ nhất do `FACE` đẻ ra nên nó mang thẻ FACE — đếm theo thẻ
thì cặp mới lại nhận số 1 và **đè thẳng lên cặp cũ**.

**Bước 1**: hai ô đổi thành **danh sách** (`CollectionProperty`) — mỗi dòng là
mesh + bên, kèm nút thêm/bỏ. Ghép mesh với xương theo **thứ tự trong danh
sách** (mesh L thứ nhất → `Eye.L`, thứ hai → `Eye_2.L`), nên panel **in thẳng
tên xương ra từng dòng** thay vì bắt người dùng đoán.

Hai ô cũ giữ lại làm đường lui: `eyeball_meshes()` chỉ đọc chúng khi danh sách
còn rỗng, và panel hiện nút "Chuyển sang danh sách". `split_eyeballs` giờ ghi
thẳng vào danh sách.

Kéo theo, những chỗ gõ cứng đúng hai mắt đều phải mở ra:

* `generate.FACE_BONES` (hằng số) → `face_bone_names(rig)` + `eye_bone_names(rig)`
* `face.eyeball_object(context, side)` → thêm tham số `inst`
* `weigh_face_bones(eyes_apart=…)` nhận **tên xương** thay vì tên bên — một chữ
  `'L'` không chỉ rõ được `Eye.L` hay `Eye_2.L`
* `widgets.apply_face_widget` bỏ số thứ tự trước khi tra bảng (`_face_key`), nếu
  không thì cặp mắt thứ hai không có widget và animator không bấm vào đâu để chọn

Kiểm chứng (`test_foureyes.py`, 18/18): ref ra đủ `Eye.L/R` + `Eye_2.L/R` +
`Eye_3.L/R` mà không đè lên nhau, rig có 4 xương mắt **đều có widget**, bind gắn
cứng đúng từng nhãn cầu vào đúng xương của nó, xoay `Eye_2.L` thì nhãn cầu đi
4,33 mm còn da người **0,0000 mm**, và đường lui hai ô cũ vẫn đọc được.

**Bẫy sót lại từ lượt đổi chữ**: hàm `wrap()` cắt chuỗi theo dấu cách nên nó
**nuốt mất dấu cách đầu chuỗi** — 9 câu dạng `" | ..."` thành `"| ..."`, làm báo
cáo dính liền nhau ("Bind Body vao FourEye| chưa có nhóm..."). Đã trả lại.

### Toàn bộ chữ hiển thị chuyển sang tiếng Việt CÓ DẤU

`face.py` vốn là addon FaceShapes viết có dấu, các module mới viết không dấu —
nên panel chỗ có chỗ không. Đo trước khi sửa: **319 / 409 chuỗi UI chưa có dấu
(78%)**.

Thay **theo vị trí cú pháp**, không tìm-thay theo nội dung: tên bone, idname,
data path, khoá từ điển đều là chuỗi, đổi nhầm một cái là hỏng rig mà không chỗ
nào báo lỗi. Máy chỉ sửa đúng những node `Constant` nằm ở chỗ Blender đem ra vẽ,
và sửa từ **cuối file ngược lên** để offset phía trước còn đúng.

Ba lượt, vì mỗi lượt lộ ra một loại bị sót:

1. **397 chuỗi tại chỗ** — `text=`, `name=`, `description=`, `bl_label`,
   `bl_description`, nhãn/mô tả của `EnumProperty`, `self.report(...)`, và
   **docstring của operator** (chính là tooltip khi không có `bl_description`).
2. **96 chuỗi đi vào UI qua BIẾN** — tên bước trong bảng tiến độ, câu báo lỗi
   ghép bằng `%`. Chúng không nằm ở `text=` nên lượt 1 không thấy; bảng tiến độ
   vẫn không dấu trên màn hình là bằng chứng.
3. **Nhãn ngắn trong bảng dữ liệu** — `refrig.PARTS`, tên bước, nhãn chi. Quá
   ngắn nên bộ lọc văn xuôi bỏ qua.

Còn lại **32 chuỗi không dấu, và tất cả đều đúng như vậy**: thuật ngữ (`Action`,
`Basis`, `Mesh`, `Rig`, `Picker`, `Tween`, `FK / IK`, `Snap IK/FK`…) hoặc tiếng
Việt vốn không cần dấu (`Ghi key`, `Xoay`, `Chi`, `Sau`).

**Tách chữ hiển thị khỏi tên dữ liệu.** `rigdef.SIDE_WORD` (`Left`/`Right`) đi
vào **tên custom property và tên bone collection** (`Left Arm FK/IK`) — những
tên đó nằm trong rig và có driver trỏ tới, đổi một chữ là mọi rig cũ đứt driver
mà không chỗ nào báo. Nên thêm `SIDE_LABEL` (`trái`/`phải`) chỉ để hiển thị:
panel FK/IK giờ đọc là "Tay trái", còn prop vẫn là `Left Arm FK/IK`.
`test_names.py` (14/14) ghim đúng chuyện đó lại.

**Bẫy**: `col_offset` của AST tính bằng **byte UTF-8**, không phải ký tự. Dòng
nào đã có dấu (hoặc có dấu gạch dài) là cắt trượt và nuốt mất phần đuôi — ở
`build.py` nó ăn đứt `),` làm cả `EnumProperty` không đóng ngoặc. Chốt
`ast.parse()` sau mỗi file bắt được trước khi kịp ghi ra đĩa.

Hai bài test bám vào tên bước cũ (`"Cac bo phan"`, `"Nhom vung khuon mat"`) nên
chết ngay khi đổi — đã sửa. Đó là cái giá của việc dùng chuỗi hiển thị làm khoá
tra cứu.

### Xương cõng phụ kiện không kéo theo da người

Thêm xương `Hat` cho cái mũ, gắn cứng `pig_hat` vào nó — rồi kéo mũ thì **cả
đầu đi theo**. Đo trên `Test_Pig_Rig`: xương `Hat` (deform, cha là `Head`) ôm
**1006 vertex** vùng đầu, trọng số tới 1,00; xoay 30° làm da heo đi **102,4 mm**.

Nguyên nhân: object gắn bằng **bone parent** đi theo phép quay của xương, không
dùng tới một trọng số nào. Nhưng xương vẫn là deform bone nên `ARMATURE_AUTO`
vẫn chia phần cho nó. Cùng một lỗi đã gặp với nhãn cầu và răng, lần này ở dạng
tổng quát hơn.

**Phòng** — `mount_bones(rig)` trả về xương nào đang cõng object gắn cứng, và
`srp.bind` giấu chúng khỏi automatic weights y như đang làm với xương mặt.
Nhận diện bằng **quan hệ parent** chứ không bằng tên: đặt `Hat`, `Cap`,
`Prop_01` gì cũng được. Xương cõng phụ kiện **skin** (armature modifier) không
nằm trong danh sách — cái đó phải deform thật.

**Chữa** — `srp.free_mounts` cho rig đã bind hỏng từ trước: trả trọng số về
xương cha rồi xoá nhóm (`face.drop_bone_weight`, tách ra từ `_drop_eye` cũ).
Tổng trọng số mỗi vertex giữ nguyên nên tư thế nghỉ không xê dịch. Panel Bind
chỉ hiện nút này **khi thật sự có chuyện**, kèm số vertex đang bị kéo.

Trên `Test_Pig_Rig`: gỡ 1034 vertex, xoay `Hat` 30° → da heo đi **0,0000 mm**.

**Bẫy đo (mắc hai lần trong một phiên)**: lấy mốc từ `mesh.vertices` thô rồi so
với mesh đã qua modifier thì ra **23 mm** ở tư thế nghỉ — mà rig đang rest,
không xương nào có pose. Chênh đó là do rest pose của rig đã đổi sau khi bind
(thêm xương trong Edit Mode). Mốc phải là **mesh đã evaluated với xương cần đo
ở góc 0**, không phải mesh gốc.

**Bẫy fixture**: bản test đầu cộng thẳng `Hat = 0,6` lên trên `Head = 1,0` rồi
đòi Head phải tăng đủ 0,6 — sai, vì `drop_bone_weight` chặn trần ở 1,0 và
automatic weights vốn trả về tổng = 1 trên mỗi vertex. Phải dựng lại đúng trình
tự thật (bind trước, gắn phụ kiện sau) thì fixture mới đo cái người dùng gặp.
(`test_mount.py`, 14/14)

### Bind xong thì bộ xương ref tự xoá

`srp.bind` có thêm tuỳ chọn **Xoá bộ xương ref** (mặc định BẬT). Bind xong là
bộ ref hết việc — rig đã dựng, đã skin — nên để lại chỉ nặng file.

* Xoá **cả object lẫn armature data**. Bỏ mỗi object thì data thành mồ côi và
  vẫn chiếm chỗ trên đĩa cho tới lần mở file sau.
* Xoá **hết** bộ ref trong file chứ không chỉ cái `find_ref()` trả về đầu
  tiên: dựng rig cho hai nhân vật thì file có hai bộ, mà người dùng bấm Bind
  một lần rồi tưởng đã dọn sạch.
* Không có gì trỏ tới bộ ref (`find_ref` dò bằng **thẻ trên xương**, không
  bằng con trỏ) nên xoá không làm gãy liên kết nào.
* `build_progress()` phải sửa theo: rig dựng xong rồi thì hai bước nắn bộ ref
  coi như xong, kể cả khi bộ ref không còn. Thiếu cái này thì bảng tiến độ
  **tụt ngược** về "chưa có bộ ref" ngay sau một lần bind thành công.

Tắt tuỳ chọn (bảng F9) nếu còn muốn nắn lại bộ ref rồi dựng rig lần nữa —
dựng lại **cần** bộ ref, không có thì phải nắn lại từ đầu. Panel Bind có ghi
sẵn dòng nhắc.

Kiểm chứng (`test_dropref.py`, 15/15): bộ ref biến mất cả object lẫn data,
bảng tiến độ không tụt bước nào, và rig không cần bộ ref để chạy — 4 chi đủ,
`apply_logic` + `verify_switching` không lỗi, picker vẫn phủ 69/69 control.

### Nhãn cầu là mesh riêng

`test_eyeball.py`, 16/16.

* `make_regions` từng tạo nhóm `FS_Eyeball` **rỗng vô điều kiện**. Nhóm rỗng
  tệ hơn không có: `split_eyeballs` và mọi phép dò chỉ hỏi "có nhóm không".
  Giờ bỏ qua (và xoá) khi bên đó đã có mesh riêng, và xoá nhóm nào tự dò
  không ra.
* `split_eyeballs` giờ **tự điền `srp_generate.eye_L/eye_R`**. Thiếu bước này
  thì phần còn lại của quy trình không biết nhãn cầu đã ra riêng.
* Xoá nhóm **không được** làm mất phép đo: `FS_Eyeball` là nguồn của cao độ
  bản lề hàm và quả cầu khớp xương mắt. Thêm `eyeball_points()` — ưu tiên mesh
  riêng, chỉ đọc nhóm khi nhãn cầu còn trong mesh mặt. Bỏ đi mà không thay
  nguồn thì bản lề lệch **256,8 mm**.
* `_drop_eye()` trả trọng số `Eye.<bên>` còn sót về xương cha rồi xoá nhóm.
  Không dùng `_set_eye()` với tập rỗng được: `_only_group()` **tạo** nhóm nếu
  chưa có, tức đẻ ra đúng cái đang muốn xoá. Đo: 20/20 vertex giữ đủ, trung
  bình 0,300 → 0,700.
* `make_regions` lấy mesh của bước 1 qua `region_target()` thay vì rơi xuống
  `context.object` — bấm nút lúc chọn nhầm object là tô nhóm lên mesh khác.

### Vuốt mềm viền nhóm vùng khi dựng shape key

Nhóm tô tay là **nhị phân**. Đo trên `My_Body`: **mọi** nhóm đều có bước trọng
số lớn nhất = 1,000 và bước trung bình ở viền cũng = 1,000 — không lấy một
vertex chuyển tiếp nào. Shape key lấy trọng số làm biên độ, nên bậc thang trong
trường trọng số thành vết gãy trên mesh.

`soften_regions()` hạ trọng số của mấy vành ngoài cùng — **vuốt ngược vào
trong**, không nới nhóm ra vertex mới. Chạy trong `region_context()` nên áp cho
mọi đường dùng vùng, và **không ghi đè nhóm trên mesh**: cái người dùng tô vẫn
nguyên bản sắc nét. Dial: `Hằng số hiệu chỉnh > Vuốt mềm viền nhóm` (mặc định
2, 0 là tắt).

Đã thử **nới ra ngoài** trước và nó sai hướng:

| (`My_Body`, 56 shape key, tắt trần giãn cạnh) | cạnh gãy | biên độ | giãn max | khe môi |
|---|---|---|---|---|
| để nguyên | 1499 | — | 6,80x | — |
| nới RA 2 vòng | 1089 (−27%) | **+37,5%** | **11,52x** | — |
| vuốt VÀO 2, không ghim khe | 1099 (−27%) | −7,9% | 7,33x | **0/14** |
| **vuốt VÀO 2, có ghim khe** | **1318 (−12%)** | **−4,9%** | 7,02x | **14/14** |

Nới ra ngoài giảm gãy chừng ấy nhưng biên độ vọt 37,5% và giãn cạnh gần gấp
đôi — vì mặt nạ không chỉ nói "mạnh bao nhiêu", nó còn nói "mô hình độ dịch
còn đúng tới đâu". Kéo vertex ra ngoài vùng đã tô là bắt profile ngoại suy vào
chỗ nó chưa từng được đo; cái +37,5% là dấu hiệu hỏng chứ không phải lời khen.

Vertex giáp nhóm **khác** được ghim nguyên trọng số. Vành môi mỏng nên phần lớn
vertex của nó chạm **cả** khe lẫn da trần; không ghim thì cả 14 vertex môi trên
giáp khe bị vuốt xuống và miệng không hé ra hết. Ghim lấy mất một nửa phần giảm
gãy (−27% còn −12%) — đổi lại miệng còn mở được. p99 giãn cạnh **tốt lên 2,3%**.

Khối cứng (`SHARP_REGIONS`: hai hàm răng, hai nhãn cầu) không đụng tới.

**Bẫy đo**: lần đầu tôi đo bằng giãn cạnh với `cap` bật, và kết luận là bản vá
làm **xấu đi** (6,80x → 11,5x). Sai: `cap` co từng shape key xuống theo mức
giãn của chính nó, nên nó **giấu** đúng cái đang muốn đo. Phải tắt `cap` và
chuẩn hoá theo đỉnh của từng shape mới so được — lúc đó mới thấy cả hai cách
đều giảm gãy ~27%. (`test_soften.py`, 11/11)

### Trọng số hàm: răng dưới không còn chạy trước da cằm

Hai nửa cái miệng chạy theo hai luật khác nhau:

* **Răng dưới**: `_only_group()` gán cứng 1,0 và gỡ khỏi mọi nhóm khác → đi
  trọn 100%. Đúng, răng là khối cứng.
* **Da quanh nó**: `w_jaw = f * (w_Head + w_Jaw)` — chỉ lấy từ xương **cha**,
  nên **trần của xương hàm chính là trọng số cha đang có**. Đo trên
  `My_Body`: vertex da cằm chỉ giữ 0,826 ở `Head`, 0,174 nằm ở `Neck`. Dù mặt
  nạ gọi f = 1,0 thì cằm cũng chỉ theo được 84%.

100% đối 84% → răng trượt khỏi da và lòi ra ngoài cằm.

`_shift_to_jaw()` lấy theo tỉ lệ từ **mọi xương deform**. Hàm nhận `f * tổng`,
phần còn lại nhận `(1-f) * tổng` chia đúng tỉ lệ cũ → **tổng mỗi vertex không
đổi**, tư thế nghỉ lệch 3,2 µm, chạy 3 lần tổng lệch 1,5e-08.

| `My_Body`, hạ hàm 34,3° | răng | da cằm |
|---|---|---|
| trước | 100% cứng | **84%** |
| sau | 100% cứng | **100%** |

Độ giãn da ở 15° (góc thuật toán được chỉnh theo): max **2,07x**, p99
**1,09x** — bằng hoặc hơn mốc cũ trên `Male` (2,08x / 1,30x).

**Bẫy đo**: quãng đường "nếu gắn cứng" phải tính bằng khoảng cách tới **TRỤC
quay**, không phải tới **ĐIỂM bản lề**. Công thức sai báo răng "chỉ đi 91%"
trong khi nó đi đúng 100%, và báo da cằm 50% trong khi thực tế 84%.

Đã thử hợp thêm trường hình học (góc quanh bản lề) vào mặt nạ đã tô: kết quả
**y hệt** (365 vs 357 vertex). Mặt nạ tô đã phủ đủ hàm dưới; cái thiếu chỉ là
cái trần. Nên ship bản nhỏ hơn. (`test_jawslip.py`, 8/8)

### Trọng số hàm & mắt theo vùng đã tô

* Vertex khoé miệng thuộc **cả hai** vành môi: phía "phải đứng yên" **thắng**,
  không chia đôi. Chia đôi thì hạ hàm 15° kéo môi trên đi 23,4 mm.
* Mặt nạ tô là **nhị phân**, biên của nó là bậc thang dựng đứng — chỗ lưới
  rách. Làm mượt Laplacian là bắt buộc: 3,33x → **2,08x**, p99 1,30x, 8 cạnh
  xấu (đường hình học cũ: 2,26x / 1,33x / 18 cạnh).
* Xương mắt chia theo **ĐẢO lưới**, không cắt từng vertex: `FS_Eyeball.L` có
  71 vertex nhưng chỉ 57 nằm trên đảo nhãn cầu, 14 cái kia là da mí.

### Vặt

* `srp_generate` thêm ô chọn **nhãn cầu trái/phải** ở bước 1.
* Nút "Tô lại trọng số hàm & mắt" thêm ô chọn **rig** — thiếu nó thì file
  nhiều nhân vật chọn nhầm rig, mà rig đó tắt collection là bấm nút chỉ nhận
  một câu báo lỗi.
* `outside_view_layer()` / `report_hidden()`: object nằm trong collection bị
  exclude thì `objects.active =` ném RuntimeError giữa chừng, còn
  `evaluated_get()` lặng lẽ trả ma trận cũ (mọi phép đo ra 0,00 mm).
* Xoá VertexGroup làm Blender đánh số lại cả danh sách → **thu tên trước, xoá
  sau**, không giữ tham chiếu qua nhát xoá.
* `bpy.ops.mesh.separate` đánh số lại vertex còn lại → tính chỉ số **ngay
  trước** mỗi nhát cắt.

---

## 1.1.0 và trước

Nền tảng: `rigdef` làm nguồn sự thật duy nhất, `build.apply_logic()` dựng lại
constraint + driver, khám rig, snap IK/FK theo đoạn, onion skin, gộp addon
FaceShapes vào `face.py`.
