# Dakrosa WinCC Phase 1: callback canary trạm 2

Ngày triển khai: 2026-07-10  
Release dự kiến: `1.5.12`  
Phạm vi: sửa đơn vị năng lượng và kiểm chứng callback realtime trên Dakrosa2.

## Kết quả cần đạt

- `Dakrosa2` vẫn gửi snapshot chuẩn 105 canonical tags theo nhịp hiện tại.
- Một tiến trình Python 32-bit riêng subscribe read-only bốn tag:
  `LV-KW`, `H1-KW`, `H2-KW`, `H3-KW`.
- Callback dùng cycle index `2`, tương ứng 500 ms.
- Canary chỉ ghi health metadata vào `runtime_canary`; không ghi WinCC, không
  thay canonical tags và không thay cadence snapshot/rawdump.
- `energy_5min` của `u1/u2/u3` tại Dakrosa2 được đổi đúng từ kW sang MWh.
  `bus_P` của Dakrosa2 và toàn bộ Dakrosa1 vẫn được hiểu là MW.

## Ranh giới an toàn

Không sửa các thành phần sau trong Phase 1:

- `bridge/updater.py` và logic kiểm tra OTA.
- NSSM, installer, service name hoặc service recovery.
- Cấu hình/DB/project WinCC.
- Binary Siemens hoặc DLL search path.
- Reader legacy được ghim riêng cho Dakrosa1.

Không được trộn DLL giữa hai trạm. Mỗi subscriber chỉ dùng bộ DLL cài tại máy
WinCC đang chạy nó.

## Gate canary

Canary chỉ khởi động khi đồng thời thỏa:

```text
station.name == Dakrosa2
winccbox.mode == local
station.read_mode == raw
không chạy service với --once
```

Trong release Phase 1, gate trên mặc định bật canary cho đúng Dakrosa2. Kill
switch trong `config.local.toml`:

```toml
[station]
runtime_callback_canary = false
```

Sau khi đổi kill switch phải restart `WinCCBridge` vì config chỉ được đọc lúc
process khởi động.

## ABI đã xác minh

Nguồn chính thức tại bộ WinCC trạm 2:

```text
Data/hmi/Scripting/DMCLIENT.H
aplib/apgenapi.h
```

- `DMCLIENT.H` dùng `#pragma pack(1)`.
- `DM_VARKEYW` có kích thước 270 byte.
- `DM_VAR_UPDATE_STRUCTEXW` có kích thước 560 byte.
- Export WinCC dùng `WINAPI`/stdcall thông qua `ctypes.WinDLL`.
- `DM_NOTIFY_VARIABLEEX_PROCW` không có `WINAPI`; callback phải dùng
  `ctypes.CFUNCTYPE`/cdecl.
- Lifecycle bắt buộc:

```text
DMConnectW
  -> DMBeginStartVarUpdateW
  -> DMStartVarUpdateExW(cycle=2)
  -> DMEndStartVarUpdateW
  -> callbacks
  -> DMStopVarUpdateW
  -> DMDisConnectW
```

Callback và key array phải được giữ reference đến khi Disconnect thành công,
kể cả khi Start, End hoặc Stop lỗi.

## Quan sát production

Payload Dakrosa2 có thêm trường `runtime_canary`. Trạng thái tốt phải có:

```text
event = heartbeat
mode = dmclient-callback-canary
callbacks tăng dần
items tăng dần
callback_errors = 0
oversized_callbacks = 0
last_age_sec < 5
tags có LV-KW, H1-KW, H2-KW, H3-KW
```

Mỗi tag canary ghi `value`, `state`, `quality`, `variant_type`, `count` và
`last_utc`. Đây là dữ liệu quan sát; Phase 1 chưa merge nó vào canonical tags.

Kiểm tra không cần credential:

```powershell
$d1 = Invoke-RestMethod 'https://dakrosa.svnagentic.site/api/dakrosa/wincc/latest?station=Dakrosa1'
$d2 = Invoke-RestMethod 'https://dakrosa.svnagentic.site/api/dakrosa/wincc/latest?station=Dakrosa2'
$d1.latest | Select-Object version, station, received_at
$d2.latest | Select-Object version, station, read_mode, received_at, runtime_canary
```

## Tiêu chí advance/hold/rollback

Advance sang Phase 2 khi duy trì được các điều kiện sau qua nhiều snapshot:

- Dakrosa2 ở đúng release, `read_mode=runtime`, khoảng 105 canonical tags.
- Callback có heartbeat mới, bốn tag đều xuất hiện, lỗi callback bằng 0.
- Snapshot, rawdump và OTA vẫn chạy bình thường.
- `u1/u2/u3_MWh_5min` về khoảng `0.05-0.08 MWh` khi công suất tổ máy khoảng
  `600-950 kW`, không còn khoảng `50-80 MWh`.
- Dakrosa1 tiếp tục có payload mới, không có `runtime_canary`, dữ liệu/tag cũ
  không đổi.

Hold nếu callback không chạy nhưng snapshot cũ vẫn ổn. Rollback ngay nếu mất
snapshot, tag canonical bị thay, callback làm WinCC/Data Manager không ổn định,
hoặc Dakrosa1 bị ảnh hưởng.

## Rollback

Rollback nhanh tại Dakrosa2 nếu có quyền máy:

1. Đặt `runtime_callback_canary = false`.
2. Restart `WinCCBridge`.
3. Xác nhận snapshot chuẩn vẫn tiếp tục và child callback đã dừng.

Rollback qua OTA:

1. Tạo forward-revert cho các commit Phase 1; không rewrite history.
2. Đặt một version mới khác bản lỗi, ví dụ `1.5.13`, vì updater chỉ so sánh
   chuỗi bằng/khác chứ không so semver.
3. Push `main` và theo dõi cả hai trạm đến khi nhận version rollback.

Nếu service/updater bị hỏng trước khi có thể poll, OTA không thể tự sửa; phải
khôi phục checkout/ZIP thủ công nhưng giữ nguyên `config.local.toml`.

## Lưu ý OTA cần nhớ

- Bump `version.txt` trên `main` là fleet release: cả hai trạm có thể kéo về.
- Dakrosa1 chỉ nhận reader legacy khi config đang chạy có
  `station.name = Dakrosa1`. Installer remote cũ có thể không ghi section này.
- Lần triển khai này dựa trên bằng chứng Dakrosa1 đã chạy ổn ở `1.5.11` sau cơ
  chế pin reader; vẫn phải giám sát Dakrosa1 song song khi bump version.
- HTTP ZIP fallback không xóa file thừa. Sau rollback, `runtime_canary.py` có
  thể còn trên đĩa nhưng không chạy nếu service cũ không import nó.
- Không sửa hoặc commit file local `test_updater_paths.py` đang untracked.

## Verification phát triển

- 64 unit tests liên quan đã qua trước release.
- `py_compile` qua cho reader/runtime/supervisor/service.
- Cú pháp được parse với Python feature version 3.7.
- `git diff --check` sạch.
- `test_e2e.py` là live SSH test và hiện không chạy được từ máy phát triển do
  APIPA `169.254.172.61:22` timeout; đây không phải regression unit test.

## Phase 2

Phase 1 chỉ chứng minh callback realtime ổn định. Dashboard web vẫn poll khoảng
30 giây. Phase 2 mới mở rộng allow-list, merge dữ liệu callback đã xác thực vào
canonical payload và thêm SSE/EventSource hoặc polling nhanh có fallback.
