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
Chưa chạy (phần bài làm thực hiện tập trung vào core pipeline trên môi trường máy cá nhân không GPU; phần train đối chứng YOLO26n với 2 seed trên Google Colab sẽ được chạy bổ sung sau theo tài liệu `docs/COLAB.md`).

## 6. Quyết định và ghi chú AI
**(a) Quyết định cuối cùng**:
- Quyết định hiện tại: **Hold**.
- Để chuyển thành **Release**: Cần tăng ngân sách duyệt người (`review.budget_images`) từ 80 lên ít nhất 130 ảnh (hoặc cử người duyệt thẩm định 44 ảnh còn lại trong hàng đợi có cảnh báo). Khi người đã kiểm tra và xác nhận các cảnh báo ngữ nghĩa này, tỷ lệ ảnh cảnh báo chưa duyệt sẽ giảm xuống dưới ngưỡng 10%, và gate sẽ tự động chuyển sang **Release**.

**(b) Ghi chú sử dụng AI**:
- *Prompt chính*: "Dựa vào docstring và các bài test trong tests/, hiện thực 4 module label_format, gate, autofix, second_opinion xử lý chuẩn cú pháp YOLO, đúng toạ độ clipping và các edge cases theo TDD."
- *Cách kiểm code AI*: Chạy `pytest` riêng cho từng module (`test_label_format.py`, `test_gate.py`, `test_autofix.py`, `test_second_opinion.py`), chạy full test suite 79 tests, và chạy e2e pipeline `python -m pipeline.run` để kiểm tra kết quả sinh báo cáo thực tế.
- *Một lần AI sai*: Khi viết logic `clip_box` trong `autofix.py`, ban đầu AI không xử lý trường hợp box tràn hoàn toàn ra ngoài ảnh dẫn đến diện tích sau khi clip <= 0 (chiều rộng/cao âm hoặc bằng 0); sau khi đối chiếu với `test_box_fully_outside_is_dropped_not_negative`, logic đã được chỉnh lại để tự động chuyển sang hành động `drop_line`.
