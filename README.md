# WinCC Bridge

Service tự cập nhật (OTA) chạy trên **máy trạm** (online, cùng LAN với máy WinCC offline). Mỗi 5 phút: SSH sang máy WinCC → đọc giá trị tag đã giải nén qua **WinCC OLE-DB Provider** (read-only) → tính thống kê → **POST lên n8n webhook**. Mỗi 15 phút tự `git pull` từ GitHub private để cập nhật.

```
GitHub private (OTA) ──git pull──► [Máy trạm: NSSM service]
                                      • 5p : ssh winccbox → py32 OLE-DB → stats → POST n8n
                                      • 15p: git pull → đồng bộ box → tự restart
                                          │ ssh/scp (LAN, read-only)
                                          ▼
                                   [Máy WinCC offline: py32 + OLE-DB reader]
```

## Cài trên máy trạm (1 lần)
1. Copy **`wincc-bridge.zip`** + **`setup.bat`** vào 1 thư mục.
2. Chạy **`setup.bat`** → nhập: webhook URL, GitHub token (read-only), IP/user máy WinCC, mật khẩu Windows (để service auto-start).
3. Khi được nhắc, chạy khối lệnh in ra trên **máy WinCC** (PowerShell Admin) để cấp quyền SSH key.
→ Service `WinCCBridge` tự khởi động cùng máy.

## Yêu cầu phía máy WinCC (đã chuẩn bị sẵn)
- OpenSSH server bật (key của máy trạm được cấp quyền).
- Python 3.11 **32-bit** + `pywin32` tại `C:\Users\<user>\Python311x86\`.
- `box\oledb_reader.py` (service tự đẩy sang qua scp).
- WinCC OLE-DB Provider đã đăng ký (mặc định có khi cài WinCC) + project active.

## Thành phần
- `box/oledb_reader.py` — py32, đọc OLE-DB → JSON snapshot (tự dò tag archive).
- `bridge/` — `service.py` (vòng lặp) · `collect.py` (ssh) · `poster.py` (POST) · `updater.py` (OTA) · `config.py`.
- `installer/` — `setup.bat` + `setup.ps1`.
- `config.local.toml` — secrets (gitignored, tạo lúc setup).

## Vận hành
```
tools\nssm.exe status  WinCCBridge
tools\nssm.exe restart WinCCBridge
tools\nssm.exe stop    WinCCBridge
```
Log: `logs\service.log`.

## Lưu ý dữ liệu
WinCC chỉ archive một số tag (vd nhóm 22kV: `U12, I1, P, Q`; mỗi tổ máy U1/U2/U3: `P, Q, U, I, GV, speed`). Reader tự bỏ qua tag không archive (F, điện áp pha, PF). Đọc **read-only** — không bao giờ ghi/ điều khiển.
