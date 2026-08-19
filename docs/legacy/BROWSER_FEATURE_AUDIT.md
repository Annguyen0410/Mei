# LiteBrowser 3.0 - Audit tính năng, bug, phần thừa và khu vực code rối

> ⚠️ **Tài liệu legacy (thời kỳ 3.0)** — thông tin có thể lỗi thời so với code hiện tại (bản **6.2.0**, shell đa workspace + shim PyQt5/PyQt6). **Tài liệu hiện hành: `README.md`, `RUN_AND_BUILD.md`, `ARCHITECTURE.md`.**

## 1. Mục đích file này

File này không mô tả "browser có gì", mà đánh giá theo hướng sản phẩm và kỹ thuật:

- tính năng nào thực sự cần giữ
- tính năng nào không cần thiết hoặc nên gộp lại
- tính năng nào đang lỗi hoặc có dấu hiệu lỗi rõ ràng
- tính năng nào tồn tại nhưng function/hành vi chưa rõ, chưa chín, hoặc nửa vời
- khu vực code nào đang rối, chồng chéo, dễ gây lỗi
- phần nào đang dư thừa do kiến trúc cũ và mới cùng tồn tại

Đánh giá này dựa trên static review code hiện tại trong repo, chưa phải full runtime QA. Vì vậy:

- những lỗi logic rõ ràng được xem là bug mạnh
- những phần "không hoạt động" được hiểu là không có dây nối hành vi rõ ràng, hoặc chỉ hoạt động trong một số điều kiện hẹp
- một số điểm là “risk / design debt”, không phải crash bug

---

## 2. Tóm tắt ngắn

### Nên giữ

- Shell đa workspace với `AppShell`
- Browser `SearchWindow`
- Personal Hub: Notes, Tasks, Calendar
- AI Workspace với local retrieval
- Saved pages + Library
- Profile-based storage
- Session restore + tab hibernation

### Nên giữ nhưng cần sửa/gọt

- Boards
- Downloads
- Privacy center
- Password manager
- Tab sets
- Workspaces
- Omnibar

### Có dấu hiệu thừa hoặc nên bỏ/gộp

- ~~`LauncherWindow`~~ (đã gỡ khỏi repo; chỉ còn `AppShell`)
- Guide và Control Center kiểu dialog lớn nếu đã có shell + omnibar
- "sync-ready profile state" nếu chưa có sync thật
- vài control browser bị dựng lên rồi hide khi chạy embedded

### Bug rõ ràng nhất

- `remember_closed_window()` tự gọi lại chính nó vô hạn sau khi vừa lưu state, gây recursion bug rõ ràng tại [main_window.py](D:\Code folder\new browser\main_window.py#L1314) và [main_window.py](D:\Code folder\new browser\main_window.py#L1328)

### Khu vực rối nhất

- Workspace model
- Window model cũ/mới cùng tồn tại
- Browser actions bị chia giữa topbar, page menu, options menu, control center, guide, omnibar
- AI integration chéo giữa shell/browser/personal

---

## 3. Tính năng cần thiết nên giữ

## 3.1 AppShell

Đây là phần nên giữ mạnh nhất.

Lý do:

- Nó là lớp điều phối thống nhất cho Browser, AI, Personal, Library, History, Settings.
- Nó là thứ làm dự án này khác một browser PyQt đơn thuần.
- Nó là chỗ hợp nhất các flow liên workspace, đặc biệt là AI và dữ liệu cá nhân.

Ref:

- [app_shell.py](D:\Code folder\new browser\app_shell.py#L450)

Đánh giá:

- `Cần thiết`
- `Nên giữ`

## 3.2 Browser / SearchWindow

Browser vẫn là lõi sản phẩm.

Những phần nên giữ:

- tab
- restore session
- hibernate tab
- bookmarks
- history
- downloads
- page tools
- workspace filtering

Ref:

- [main_window.py](D:\Code folder\new browser\main_window.py#L45)
- [tab_manager.py](D:\Code folder\new browser\tab_manager.py#L94)

Đánh giá:

- `Cần thiết`
- `Nên giữ`

## 3.3 Notes / Tasks / Calendar

Đây là 3 phần của Personal Hub có giá trị thực tế rõ nhất.

Lý do:

- storage rõ ràng
- UI rõ ràng
- chức năng dễ hiểu
- dữ liệu có thể index cho AI
- không phụ thuộc nhiều vào hack UI

Ref:

- [personal_window.py](D:\Code folder\new browser\personal_window.py#L334)
- [personal_window.py](D:\Code folder\new browser\personal_window.py#L460)
- [personal_window.py](D:\Code folder\new browser\personal_window.py#L519)
- [life_service.py](D:\Code folder\new browser\life_service.py#L51)
- [life_service.py](D:\Code folder\new browser\life_service.py#L106)

Đánh giá:

- `Cần thiết`
- `Nên giữ`

## 3.4 AI Workspace với retrieval local

Đây là tính năng khác biệt và có lý do tồn tại rõ.

Điểm tốt:

- không phụ thuộc hoàn toàn vào cloud model
- index được bookmarks/history/notes/tasks/events/boards/saved pages
- nhận context từ Browser và Personal

Ref:

- [ai_window.py](D:\Code folder\new browser\ai_window.py#L36)
- [ai_service.py](D:\Code folder\new browser\ai_service.py#L24)
- [ai_service.py](D:\Code folder\new browser\ai_service.py#L266)

Đánh giá:

- `Cần thiết`
- `Nên giữ`

## 3.5 Saved pages + Library

Library không chỉ là “thêm một màn hình”, nó là điểm nối:

- Browser save page
- Personal search
- AI retrieval
- shell search flow

Ref:

- [app_shell.py](D:\Code folder\new browser\app_shell.py#L157)
- [main_window.py](D:\Code folder\new browser\main_window.py#L1429)
- [life_service.py](D:\Code folder\new browser\life_service.py#L262)

Đánh giá:

- `Cần thiết`
- `Nên giữ`

---

## 4. Tính năng cần giữ nhưng cần gọt mạnh

## 4.1 Boards

Boards có tiềm năng, nhưng hiện tại mới ở mức “canvas ghi chú + vẽ tay”, chưa thành hệ board đầy đủ.

Điểm tốt:

- có sticky cards
- có pan/zoom
- có draw mode
- có strokes được lưu lại

Điểm chưa chín:

- schema có `edges`, nhưng UI hiện gần như không dùng `edges`
- chưa có link semantics rõ giữa node-node
- chưa có search/open flow mạnh như notes/tasks

Ref:

- [life_service.py](D:\Code folder\new browser\life_service.py#L175)
- [life_service.py](D:\Code folder\new browser\life_service.py#L244)
- [personal_window.py](D:\Code folder\new browser\personal_window.py#L667)
- [personal_window.py](D:\Code folder\new browser\personal_window.py#L783)

Đánh giá:

- `Nên giữ`
- `Nhưng đang nửa vời`
- `Cần quyết định rõ: chỉ giữ sticky board, hay phát triển thành graph board thật`

## 4.2 Password manager

Có ích, nhưng hiện khá “basic”.

Điểm tốt:

- có encrypt
- có autofill
- có privacy settings

Điểm cần gọt:

- UX master password còn thô
- lưu form rất thủ công
- autofill heuristic đơn giản, dễ fail
- phụ thuộc `cryptography`, nhưng UI vẫn bày tính năng kể cả khi dependency thiếu

Ref:

- [password_manager.py](D:\Code folder\new browser\password_manager.py#L33)
- [main_window.py](D:\Code folder\new browser\main_window.py#L870)
- [dialogs.py](D:\Code folder\new browser\dialogs.py#L819)

Đánh giá:

- `Nên giữ`
- `Nhưng nên đơn giản hóa hoặc làm chín hơn`

## 4.3 Omnibar

Ý tưởng đúng, nhưng phạm vi hiện tại hơi mơ hồ.

Điểm tốt:

- điều hướng workspace
- tạo task/note/board nhanh
- save current page
- tìm trong Library

Điểm chưa tốt:

- command set chưa lớn nhưng lại gợi cảm giác “siêu command palette”
- chưa có help nội tại ngoài guide
- command parsing là chuỗi if/startswith khá dễ phình to

Ref:

- [app_shell.py](D:\Code folder\new browser\app_shell.py#L853)

Đánh giá:

- `Nên giữ`
- `Cần giới hạn scope rõ hơn`

## 4.4 Tab sets

Tính năng này hữu ích, nhưng implementation hiện còn lệch nhau giữa Search, Personal và AI.

Điểm tốt:

- Search set khá hợp lý
- AI set giúp lưu prompt history
- Launcher cũ có UI xem lịch sử listtab

Điểm chưa rõ:

- Personal “session” không giống tab thật
- ý nghĩa “save set” ở Personal/AI chưa trực quan bằng Browser

Ref:

- [tab_sets.py](D:\Code folder\new browser\tab_sets.py#L33)
- [main_window.py](D:\Code folder\new browser\main_window.py#L1568)
- [personal_window.py](D:\Code folder\new browser\personal_window.py#L1118)
- [ai_window.py](D:\Code folder\new browser\ai_window.py#L355)

Đánh giá:

- `Nên giữ`
- `Nhưng cần chuẩn hóa khái niệm`

---

## 5. Tính năng dư thừa hoặc nên bỏ/gộp

## 5.1 LauncherWindow

Đây là phần dư thừa rõ nhất về mặt kiến trúc.

Lý do:

- Entry tạo `AppShell` trực tiếp từ [`browser.py`](D:\Code folder\new browser\browser.py). `launcher_window.py` đã được gỡ (dead code); mọi điều hướng Search/Personal/AI đi qua shell.

## 5.2 Guide và Control Center dialog

Vấn đề không phải chúng vô dụng, mà là **trùng vai trò** với shell + omnibar + settings.

Hiện có:

- Guide dialog
- Control Center dialog
- Options menu
- Page menu
- Omnibar
- Left rail shell

Nhiều lớp entry-point cho cùng một nhóm hành động.

Ref:

- [dialogs.py](D:\Code folder\new browser\dialogs.py#L904)
- [dialogs.py](D:\Code folder\new browser\dialogs.py#L985)
- [main_window.py](D:\Code folder\new browser\main_window.py#L460)
- [app_shell.py](D:\Code folder\new browser\app_shell.py#L329)

Đánh giá:

- `Dư thừa một phần`
- `Nên gộp bớt`

## 5.3 "Sync-ready profile state"

Hiện tại phần này thiên về khẩu hiệu nhiều hơn tính năng hoàn chỉnh.

Lý do:

- code chỉ lưu state local như `enabled`, `pending_changes`, `last_sync_at`, `mode=local-cache`
- chưa có sync backend thật
- chưa có conflict model, transport, remote source, auth thực sự

Ref:

- [app_shell.py](D:\Code folder\new browser\app_shell.py#L264)
- [app_shell.py](D:\Code folder\new browser\app_shell.py#L362)
- [life_service.py](D:\Code folder\new browser\life_service.py#L299)
- [life_service.py](D:\Code folder\new browser\life_service.py#L327)

Đánh giá:

- `Không cần thiết ở UI hiện tại`
- `Nên ẩn bớt hoặc đổi tên thành local profile state`

## 5.4 Hai shell window mặc định

Đây là thiết kế thú vị, nhưng với đa số người dùng nó có thể là dư hoặc gây rối.

Lý do:

- app luôn mở 2 cửa sổ shell cùng lúc
- điều này nặng nhận thức hơn nhiều so với một cửa sổ có workspace switch

Ref:

- [browser.py](D:\Code folder\new browser\browser.py#L83)
- [browser.py](D:\Code folder\new browser\browser.py#L89)

Đánh giá:

- `Có thể dư`
- `Nên cân nhắc chỉ mở shell thứ hai theo tùy chọn`

---

## 6. Bug hoặc lỗi logic rõ ràng

## 6.1 Recursion bug trong `remember_closed_window`

Đây là bug rõ ràng nhất trong code hiện tại.

Hàm:

- lưu state `recently_closed`
- rồi gọi lại chính nó với cùng `tabs`

Ref:

- [main_window.py](D:\Code folder\new browser\main_window.py#L1314)
- [main_window.py](D:\Code folder\new browser\main_window.py#L1328)

Hệ quả:

- nếu function này được gọi thật sự thì sẽ recursion vô hạn cho tới khi crash/stack overflow

Đánh giá:

- `Bug rõ ràng`
- `Mức ưu tiên cao`

## 6.2 Mô hình workspace bị chồng khái niệm `default` với `ws1/ws2`

`prefs.load_workspaces()` mặc định trả:

- workspace `default`

nhưng `workspace_manager.ensure_dual_workspaces()` lại thêm:

- `ws1`
- `ws2`

Tức là app có thể cùng lúc mang cả:

- workspace mặc định kiểu cũ
- workspace cứng kiểu mới

Ref:

- [prefs.py](D:\Code folder\new browser\prefs.py#L346)
- [workspace_manager.py](D:\Code folder\new browser\workspace_manager.py#L6)
- [workspace_manager.py](D:\Code folder\new browser\workspace_manager.py#L73)

Hệ quả:

- mô hình dữ liệu không sạch
- rất dễ sinh bug “tab thuộc workspace nào”
- current_id có thể chạy lệch giữa model cũ và model mới

Đánh giá:

- `Bug thiết kế`
- `Nên sửa sớm`

## 6.3 Pin tab không được persist

Tab pin có trong runtime role:

- `TAB_PINNED_ROLE`

Nhưng state save session/tab set hiện tại không lưu pin state rõ ràng.

Ref:

- [tab_manager.py](D:\Code folder\new browser\tab_manager.py#L22)
- [tab_manager.py](D:\Code folder\new browser\tab_manager.py#L136)
- [main_window.py](D:\Code folder\new browser\main_window.py#L1547)

Hệ quả:

- người dùng thấy pin là “tính năng trạng thái tab”
- nhưng restart/xuất session có thể mất ý nghĩa pin

Đánh giá:

- `Bug hành vi / inconsistency`

## 6.4 AI current page chỉ hoạt động khi Browser đang chạy trong shell

Không hẳn là bug code, nhưng là behavior trap.

Nếu mở Browser standalone, bấm AI current page sẽ hiện thông báo:

- “Open this browser inside the main shell...”

Ref:

- [main_window.py](D:\Code folder\new browser\main_window.py#L1440)
- [main_window.py](D:\Code folder\new browser\main_window.py#L1455)

Đánh giá:

- `Hoạt động có điều kiện`
- `Dễ làm user hiểu nhầm là lỗi`

## 6.5 Ask AI trong Personal cũng phụ thuộc shell host

Tương tự trên:

- nếu PersonalWindow mở standalone thì note/site AI không chạy

Ref:

- [personal_window.py](D:\Code folder\new browser\personal_window.py#L441)
- [personal_window.py](D:\Code folder\new browser\personal_window.py#L1054)

Đánh giá:

- `Không hỏng hoàn toàn`
- `Nhưng UX rất dễ bị xem là hỏng`

---

## 7. Tính năng tồn tại nhưng function chưa rõ hoặc nửa vời

## 7.1 Board `edges`

Data model có `edges`, nhưng UI hiện chủ yếu dùng:

- `nodes`
- `strokes`

Ref:

- [app_models.py](D:\Code folder\new browser\app_models.py#L109)
- [life_service.py](D:\Code folder\new browser\life_service.py#L175)
- [life_service.py](D:\Code folder\new browser\life_service.py#L244)
- [personal_window.py](D:\Code folder\new browser\personal_window.py#L783)

Đánh giá:

- `Function chưa rõ`
- `Schema đi trước UI`

## 7.2 Sync

Tên gọi ngoài UI nghe như sync thật, nhưng behavior hiện tại chỉ là local bookkeeping.

Ref:

- [app_shell.py](D:\Code folder\new browser\app_shell.py#L264)
- [life_service.py](D:\Code folder\new browser\life_service.py#L299)

Đánh giá:

- `Function chưa rõ`
- `Tên gọi vượt quá khả năng thật`

## 7.3 Compatibility mode cho AI websites

Code có `COMPATIBILITY_HOSTS` và patch JS, nhưng triết lý xử lý chưa rõ ràng:

- vừa có patch
- vừa có cảnh báo “mở browser ngoài”

Ref:

- [main_window.py](D:\Code folder\new browser\main_window.py#L35)
- [main_window.py](D:\Code folder\new browser\main_window.py#L853)
- [main_window.py](D:\Code folder\new browser\main_window.py#L897)

Đánh giá:

- `Nửa vời`
- `Chưa rõ định hướng: hỗ trợ thật, hay chỉ phát hiện rồi né`

## 7.4 Personal session save

Search save tab set là hợp lý. AI save session còn tạm hiểu được.

Nhưng Personal “save session” hiện không mạnh bằng hai loại kia, nên tính năng này hơi mơ hồ.

Ref:

- [personal_window.py](D:\Code folder\new browser\personal_window.py#L1123)

Đánh giá:

- `Function chưa rõ`

---

## 8. Khu vực code bị rối / tùm lum

## 8.1 Hệ window cũ và mới cùng tồn tại

Hiện có:

- `AppShell` (entry chính)
- các window standalone
- các window embedded

Ref:

- [app_shell.py](D:\Code folder\new browser\app_shell.py#L591)
- [app_shell.py](D:\Code folder\new browser\app_shell.py#L594)
- [app_shell.py](D:\Code folder\new browser\app_shell.py#L595)

Vấn đề:

- kiến trúc không còn một đường chính duy nhất
- khó biết đâu là UX chính thức
- nhiều flow chỉ chạy khi embedded

Đánh giá:

- `Rối cấp kiến trúc`

## 8.2 Browser actions bị phân tán quá nhiều nơi

Cùng một nhóm chức năng browser đang rải ở:

- topbar
- page menu
- options menu
- control center
- guide
- shell omnibar

Ref:

- [main_window.py](D:\Code folder\new browser\main_window.py#L260)
- [main_window.py](D:\Code folder\new browser\main_window.py#L460)
- [dialogs.py](D:\Code folder\new browser\dialogs.py#L904)
- [dialogs.py](D:\Code folder\new browser\dialogs.py#L985)
- [app_shell.py](D:\Code folder\new browser\app_shell.py#L853)

Vấn đề:

- học sử dụng khó
- bảo trì khó
- dễ trùng hành vi

Đánh giá:

- `Rối cấp sản phẩm`

## 8.3 AI integration chéo tay nhiều lớp

Ví dụ current page AI flow:

- Browser lấy page text
- Browser tìm shell host
- Browser gọi shell
- shell switch workspace AI
- shell gọi AI page
- AI page gọi ai_service

Vấn đề:

- coupling chéo khá chặt
- khó test riêng từng phần
- standalone mode dễ bị “mất dây”

Ref:

- [main_window.py](D:\Code folder\new browser\main_window.py#L1440)
- [main_window.py](D:\Code folder\new browser\main_window.py#L1464)
- [app_shell.py](D:\Code folder\new browser\app_shell.py#L959)

Đánh giá:

- `Rối cấp flow`

## 8.4 Workspace data model

Đây là một trong những điểm rối nhất vì:

- workspace app shell
- workspace browser
- current_id kiểu cũ `default`
- current_id kiểu mới `ws1/ws2`

Ref:

- [workspace_manager.py](D:\Code folder\new browser\workspace_manager.py#L6)
- [workspace_manager.py](D:\Code folder\new browser\workspace_manager.py#L24)
- [prefs.py](D:\Code folder\new browser\prefs.py#L346)

Đánh giá:

- `Rối cấp dữ liệu`

---

## 9. Tính năng dư thừa theo nghĩa “có cũng được, bỏ cũng không sao”

## 9.1 Control Center

Nếu shell/omnibar được làm tốt hơn, Control Center có thể bỏ.

Ref:

- [dialogs.py](D:\Code folder\new browser\dialogs.py#L904)

## 9.2 Guide dialog quá dài

Nếu onboarding nằm ngay trong shell hoặc có command help gọn, guide dialog HTML dài có thể bỏ/gọn.

Ref:

- [dialogs.py](D:\Code folder\new browser\dialogs.py#L985)

## 9.3 Mở 2 shell mặc định

Hay cho power user, nhưng thừa với user phổ thông.

Ref:

- [browser.py](D:\Code folder\new browser\browser.py#L83)

## 9.4 `LauncherWindow`

Đã xóa khỏi codebase; luồng duy nhất là `AppShell`.

---

## 10. Đề xuất cắt gọn sản phẩm

Nếu mục tiêu là một bản LiteBrowser dễ hiểu và dễ bảo trì hơn, tôi sẽ đề xuất:

### Giữ chắc

- AppShell
- SearchWindow
- Notes / Tasks / Calendar
- AI Workspace
- Library
- History backup/import
- Profile system

### Giữ nhưng thu gọn

- Boards: bỏ `edges` khỏi UI roadmap ngắn hạn, giữ sticky + draw
- Password manager: chỉ giữ save/fill cơ bản
- Omnibar: chỉ giữ 5-7 lệnh cốt lõi
- Tab sets: giữ cho Search trước, cân nhắc gỡ khỏi Personal

### Gộp hoặc bỏ

- bỏ `LauncherWindow`
- gộp Guide + Control Center vào Settings hoặc command help
- đổi tên/giấu sync-ready state nếu chưa có sync thật
- cân nhắc chỉ mở shell thứ hai khi user yêu cầu

---

## 11. Thứ tự ưu tiên sửa

### P0

- sửa recursion bug ở `remember_closed_window`
- thống nhất model workspace, bỏ chồng `default` với `ws1/ws2`

### P1

- quyết định luồng chính: chỉ AppShell hay vẫn giữ Launcher
- giảm số entry-point cho browser actions
- làm rõ AI-only-in-shell behavior

### P2

- chuẩn hóa tab sets
- làm gọn sync UI
- chốt roadmap Boards

### P3

- polish UX cho password manager
- tối giản guide/control center

---

## 12. Kết luận

Codebase này không thiếu tính năng. Vấn đề chính hiện tại không phải “thiếu chức năng”, mà là:

- quá nhiều lớp UI cùng tồn tại
- vài mô hình dữ liệu bị chồng lên nhau
- có một số tính năng tồn tại theo kiểu “đã bắt đầu nhưng chưa chốt”
- có ít nhất một bug logic rất rõ

Nếu phải nói ngắn gọn:

- phần đáng giữ nhất là `AppShell + Browser + Personal core + AI retrieval`
- phần đáng cắt/gộp nhất là `LauncherWindow`, `Guide/Control Center` trùng vai trò, và lớp “sync-ready” đang overpromise
- phần đáng sửa gấp nhất là recursion bug và mô hình workspace

