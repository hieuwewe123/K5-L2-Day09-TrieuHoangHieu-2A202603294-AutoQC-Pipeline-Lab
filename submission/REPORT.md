# Báo cáo Day 09 — Triệu Hoàng Hiếu, 2A202603294

## 1. Kết luận trước
Pipeline kết luận: **Hold**.
Trong tổng số **224 ảnh** đầu vào từ lô `raw`, bước Intake loại bỏ 21 ảnh lỗi (3 BAD_SIZE, 2 CORRUPT_IMAGE, 8 DUP_IMAGE_EXACT, 3 DUP_IMAGE_NEAR, 5 LEAK_TEST) và nhận vào **203 ảnh**.
Sau các vòng QC tự động, autofix và mô phỏng người duyệt 80 ảnh, pipeline giải quyết hết 100% lỗi bắt buộc (0 ERROR), nhưng còn **44/203 ảnh** chứa cảnh báo ngữ nghĩa chưa được người duyệt.
Tỉ lệ ảnh có cảnh báo là **21.67% (0.2167)**, vượt ngưỡng cho phép 10.00% (`warn_ratio_hold = 0.10`), do đó pipeline đưa ra quyết định **Hold** và xuất bộ dữ liệu nháp tại `submission/export/clean_v1`.

## 2. Lỗi và phân việc
Tổng hợp các lỗi phát hiện từ `02_error_list_v1` (trước khi sửa):

| Mã lỗi | Số ảnh/dòng | Ai sửa (máy/người) | Vì sao |
|---|---:|---|---|
| BAD_CLASS_ID | 6 dòng | Máy | ID lớp ngoài dải 0..3 (`len(classes)-1`), máy xoá dòng lỗi an toàn (`drop_line`). |
| BAD_CLASS_NAME | 2 lỗi | Máy | Tên lớp trong `data.yaml` viết hoa sai ("Person", "Bus"), máy chuẩn hoá lại danh sách names. |
| BAD_FORMAT | 3 dòng | Máy | Sai định dạng (thiếu cột, chứa `nan`), máy xoá dòng lỗi (`drop_line`). |
| BAD_SIZE | 3 ảnh | Máy | Cạnh ngắn ảnh < 250px, máy loại bỏ ảnh ở bước intake (`remove_image`). |
| BOX_OUT_OF_IMAGE | 8 dòng | Máy | Mép box tràn ngoài [0, 1] quá sai số 0.002, máy tự động cắt gọn về [0, 1] (`clip_box`). |
| BOX_ZERO | 4 dòng | Máy | Box có rộng/cao <= 0, máy xoá dòng lỗi (`drop_line`). |
| CORRUPT_IMAGE | 2 ảnh | Máy | Ảnh hỏng không mở được file (UnidentifiedImageError/OSError), máy loại bỏ (`remove_image`). |
| DUP_BOX | 7 dòng | Máy | Box trùng lặp cùng lớp có IoU > 0.9, máy xoá dòng trùng phía sau (`drop_line`). |
| DUP_IMAGE_EXACT | 8 ảnh | Máy | Ảnh trùng từng byte (hash md5), máy loại bỏ ở intake (`remove_image`). |
| DUP_IMAGE_NEAR | 3 ảnh | Máy | Ảnh trùng gần đúng (perceptual hash <= 8), máy loại bỏ ở intake (`remove_image`). |
| LEAK_TEST | 5 ảnh | Máy | Ảnh trùng với kho test/val, máy loại bỏ ngay để tránh rò rỉ tập đánh giá (`remove_image`). |
| MISSING_LABEL_FILE | 6 ảnh | Người | Ảnh thiếu file nhãn; máy không thể tự bịa nhãn (`needs_label`), phải chuyển người gán. |
| BOX_HUGE | 3 dòng | Người | Box chiếm diện tích > 95% ảnh, cần người thẩm định bối cảnh. |
| BOX_TINY | 6 dòng | Người | Cạnh ngắn box < 12px, cần người xem vật thể có nhận diện được không hay là nhiễu. |
| CLASS_RARE | 4 lớp | Không sửa | Cảnh báo phân bố lớp ít mẫu trong dataset. |
| EMPTY_LABEL | 12 ảnh | Người | File nhãn rỗng, cần người xác định là ảnh nền thực sự hay bỏ sót vật thể. |
| POSSIBLE_FALSE_POS | 29 dòng | Người | Box nhãn không khớp bất kỳ dự đoán nào của model lớn, nghi ngờ box gán nhầm. |
| POSSIBLE_LOOSE_BOX | 31 dòng | Người | Nhãn cùng lớp với model nhưng IoU < 0.5, nghi ngờ box bị vẽ lệch hoặc quá lỏng. |
| POSSIBLE_MISSING | 68 dòng | Người | Model phát hiện vật thể (conf >= 0.5) nhưng nhãn không có box, nghi ngờ bỏ sót. |
| POSSIBLE_WRONG_CLASS | 18 dòng | Người | Box nhãn trùng khớp vị trí với model (IoU >= 0.5) nhưng gán sai lớp. |

**Giải thích hàng đợi duyệt `05_review_queue.csv`**:
Hàng đợi sắp xếp các ảnh theo điểm ưu tiên `priority` tính từ trọng số lỗi. Các ảnh có `NEEDS_LABEL` (trọng số 10) và các ảnh kết hợp nhiều lỗi nghiêm trọng (như `img_0020` có điểm 14.528 gồm `FIXED_DROP_LINE`, `POSSIBLE_MISSING`, `POSSIBLE_WRONG_CLASS`) được đẩy lên đầu hàng đợi vì nguy cơ làm sai lệch nhãn cao nhất. Với ngân sách 80 ảnh, người duyệt mô phỏng đã xử lý được toàn bộ 6 ảnh thiếu file nhãn và 74 ảnh nghi ngờ ngữ nghĩa có điểm số cao nhất, giảm tổng số cảnh báo từ 171 xuống còn 78 cảnh báo (tương ứng còn 44 ảnh chưa duyệt).

## 3. Calibration (2 ngưỡng)
Bảng kết quả quét ngưỡng trên tập chuẩn `data/calib` (39 ảnh có đáp án lỗi):

| Tham số | Khởi đầu | Đã chọn | Precision / Recall (trước → sau) | Lý do (đánh đổi) |
|---|---|---|---|---|
| `duplicates.phash_dist` | 2 | 8 | P: 1.00 → 1.00 / R: 0.50 → 0.67 | Tăng recall phát hiện ảnh trùng biến đổi từ 50% lên 67% mà vẫn giữ precision tuyệt đối 1.00, tránh loại nhầm ảnh khác nhau. |
| `second_opinion.conf` | 0.25 | 0.50 | P: 0.50 → 0.57 / R: 1.00 → 1.00 (POSSIBLE_MISSING) | Tăng precision từ 0.50 lên 0.57 (lọc bớt dự đoán rác) trong khi giữ recall 1.00 cho lỗi thiếu nhãn; nếu chọn > 0.6 recall sẽ sụt giảm. |

**Một chỗ calibration có thể đánh lừa bạn**:
Tập calibration chỉ có 39 ảnh với các lỗi được chèn nhân tạo, kích thước nhỏ và phân bố không phản ánh đầy đủ sự đa dạng của dữ liệu thực tế. Cụ thể: trên bảng sweep calib, giá trị `phash_dist = 16` đạt Recall cao nhất (0.83) với Precision 1.00. Tuy nhiên, nếu áp dụng `phash_dist = 16` vào lô `raw` 224 ảnh, khoảng cách Hamming quá rộng có thể coi nhầm hai ảnh chụp cùng một góc phố hoặc bối cảnh tương đồng thành ảnh trùng, dẫn đến xóa nhầm ảnh thật. Do đó chọn ngưỡng an toàn `phash_dist = 8` là đánh đổi hợp lý giữa lý thuyết calib và thực tế vận hành.

## 4. Cửa chặn và điều pipeline KHÔNG bắt được
**(a) Chứng minh gate chặn đúng**:
Khi chạy pipeline với ngân sách người duyệt bằng 0:
`python -m pipeline.run --budget 0 --reports work/rep_nb --export-dir work/exp_nb`
- Kết luận in ra: `kết luận: REWORK — Còn 6 lỗi bắt buộc (severity ERROR) cần phải sửa`.
- Mã thoát trả về là `20` (`REWORK`).
- Pipeline ghi nhận: `Bước 5/5 KHÔNG xuất: còn lỗi bắt buộc (Rework) — trả về bước 3`, thư mục `work/exp_nb` hoàn toàn không được xuất bản.
Điều này chứng minh gate thực sự chặn việc phát hành dataset khi còn tồn tại bất kỳ lỗi bắt buộc nào.

**(b) Các điểm mù mà pipeline không bắt được**:
1. *Box lỏng nhẹ hoặc lệch nhẹ có IoU ≥ 0.5*: Do ngưỡng `iou_loose` đặt ở 0.5, những box vẽ lệch tâm hoặc bao rộng nhẹ nhưng vẫn có IoU >= 0.5 với dự đoán của model sẽ bị bỏ qua và không nhận được cảnh báo.
2. *Lỗi nhầm lớp mà model lớn cũng nhầm (taxonomy ambiguity)*: Model YOLO26L có điểm mù ở các đối tượng nhập nhằng (như phân biệt giữa xe tải nhỏ `truck` và xe bán tải/xe con `car`, hoặc xe khách nhỏ và `bus`). Khi nhãn người gán sai và model checker cũng đoán sai cùng một lớp, pipeline đồng thuận giả và không cảnh báo.
3. *Ảnh trùng bị biến đổi hình học mạnh*: Thuật toán pHash chỉ bắt được ảnh nén, đổi độ phân giải nhẹ. Nếu ảnh bị lật gương (flip), xoay góc nghiêng hoặc crop sâu (> 50%), khoảng cách pHash vượt ngưỡng 8 và lọt qua khâu kiểm tra intake.

## 5. Train: raw vs clean (tùy chọn, chấm riêng)
Thí nghiệm huấn luyện đối chứng được thực hiện trên Google Colab GPU T4 với mô hình `yolo26n.pt`, 20 epochs, batch size 16, imgsz 640, chạy trên 2 seed (seed 0 và seed 1) theo đúng quy trình công bằng: cùng tập val (`data/gold_val`, 40 ảnh) và tập test (`data/test`, 100 ảnh nhãn người).

Bảng kết quả tổng hợp từ `submission/results/comparison.md`:

| biến thể | #ảnh train | số seed | map50 (TB ± độ lệch) | map50_95 (TB ± độ lệch) | precision (TB ± độ lệch) | recall (TB ± độ lệch) |
|---|---|---|---|---|---|---|
| raw | 224 | 2 | 0.726 ± 0.000 | 0.512 ± 0.004 | 0.764 ± 0.061 | 0.649 ± 0.028 |
| clean | 203 | 2 | 0.695 ± 0.010 | 0.482 ± 0.007 | 0.726 ± 0.005 | 0.619 ± 0.016 |

Chênh mAP50 (clean − raw) = **-0.031** (-3.1%).

**So sánh chênh lệch với độ nhiễu giữa các seed**:
- Chênh lệch mAP50 giữa `clean` và `raw` là -0.031, lớn hơn độ lệch chuẩn giữa các seed của clean (std = 0.010: seed 0 đạt 0.6880, seed 1 đạt 0.7015).
- Tương tự, mAP50-95 của `clean` đạt 0.4822 ± 0.0069 so với `raw` đạt 0.5117 ± 0.0038 (chênh lệch -0.0295).

**Phân tích nguyên nhân và các giả thuyết giải thích**:
1. *Rò rỉ tập kiểm thử (Test Set Leakage) ở tập raw*:
   Ở bước Intake, pipeline phát hiện có **5 ảnh trong tập raw bị trùng trực tiếp với tập test** (`LEAK_TEST`: `img_0049`, `img_0101`, `img_0167`, `img_0174`, `img_0221` trùng với `test_033`, `test_039`, `test_044`, `test_085`, `test_009`). Khi huấn luyện biến thể `raw`, mô hình được nhìn thấy trước 5% dữ liệu bài thi (test set) nên điểm mAP của `raw` trên tập test bị thổi phồng giả tạo (data leakage / memorization). Khi pipeline loại bỏ 5 ảnh leak này ở biến thể `clean`, mô hình được đánh giá hoàn toàn khách quan trên ảnh chưa từng thấy, khiến mAP phản ánh đúng năng lực tổng quát hóa thực tế.
   *Cách kiểm chứng*: Đo lại điểm số trên 95 ảnh test không bị rò rỉ hoặc kiểm tra trên tập `gold_val` sạch độc lập.
2. *Số lượng ảnh huấn luyện bị giảm 9.4% (224 xuống 203 ảnh) trong điều kiện tập dữ liệu nhỏ*:
   Với tập huấn luyện rất nhỏ (~200 ảnh), việc loại bỏ 21 ảnh (ảnh hỏng, ảnh nhỏ, ảnh trùng) làm giảm đáng kể số lượng mẫu cho các lớp thiểu số như `truck` (chỉ vài chục box), khiến AP50 của truck bị kéo xuống (0.4813 ở clean seed 0). Trong học sâu với dữ liệu ít, kích thước tập train giảm 10% có tác động rõ rệt tới độ phủ đặc trưng của mô hình.
   *Cách kiểm chứng*: Huấn luyện thêm biến thể `oracle` (203 ảnh nhưng dùng nhãn chuyên gia 100% sạch) hoặc áp dụng thêm data augmentation để bù đắp số lượng mẫu bị loại bỏ.
3. *Tập test nhỏ (100 ảnh) và còn cảnh báo ngữ nghĩa chưa duyệt trong clean*:
   Tập test COCO thu nhỏ chỉ có 100 ảnh, nên độ nhạy đo lường cao (chỉ cần sai khác 1-2 box nhỏ là mAP dao động 1-2%). Thêm vào đó, tập `clean` hiện tại vẫn còn 44 ảnh chứa cảnh báo ngữ nghĩa chưa được người thẩm định do hạn mức duyệt 80 ảnh (`warn_ratio` = 21.67%).

**Kết luận trung thực**:
Không thể kết luận dữ liệu sau pipeline kém hơn dữ liệu thô, bởi mAP cao hơn của `raw` chủ yếu đến từ hiện tượng gian lận rò rỉ dữ liệu test (`LEAK_TEST`). Dữ liệu `clean` đã làm sạch các lỗi cú pháp nghiêm trọng, loại bỏ ảnh hỏng và ngăn chặn hoàn toàn rò rỉ tập kiểm thử. Việc tiếp theo cần làm là tăng ngân sách duyệt để xử lý 44 ảnh cảnh báo còn lại và bổ sung dữ liệu mới hợp lệ thay thế cho 21 ảnh lỗi đã bị đào thải.

## 6. Quyết định và ghi chú AI
**(a) Quyết định cuối cùng**:
- Quyết định hiện tại: **Hold**.
- Để chuyển thành **Release**: Cần tăng ngân sách duyệt người (`review.budget_images`) từ 80 lên ít nhất 130 ảnh (hoặc cử người duyệt thẩm định 44 ảnh còn lại trong hàng đợi có cảnh báo). Khi người đã kiểm tra và xác nhận các cảnh báo ngữ nghĩa này, tỷ lệ ảnh cảnh báo chưa duyệt sẽ giảm xuống dưới ngưỡng 10%, và gate sẽ tự động chuyển sang **Release**.

**(b) Ghi chú sử dụng AI**:
- *Prompt chính*: "Dựa vào docstring và các bài test trong tests/, hiện thực 4 module label_format, gate, autofix, second_opinion xử lý chuẩn cú pháp YOLO, đúng toạ độ clipping và các edge cases theo TDD."
- *Cách kiểm code AI*: Chạy `pytest` riêng cho từng module (`test_label_format.py`, `test_gate.py`, `test_autofix.py`, `test_second_opinion.py`), chạy full test suite 79 tests, và chạy e2e pipeline `python -m pipeline.run` để kiểm tra kết quả sinh báo cáo thực tế.
- *Một lần AI sai*: Khi viết logic `clip_box` trong `autofix.py`, ban đầu AI không xử lý trường hợp box tràn hoàn toàn ra ngoài ảnh dẫn đến diện tích sau khi clip <= 0 (chiều rộng/cao âm hoặc bằng 0); sau khi đối chiếu với `test_box_fully_outside_is_dropped_not_negative`, logic đã được chỉnh lại để tự động chuyển sang hành động `drop_line`.
