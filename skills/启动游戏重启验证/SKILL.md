---
name: 启动游戏重启验证
description: 启动网易我的世界开发测试并完成模组改动后的重启+验证闭环，不需要用户手动操作。用户说"启动xxx开发测试"、"启动测试存档"、"重启存档验证"、"重新开发测试"、"重启游戏"、"闭环验证"、"改完JSON你自己重启验证"时加载此skill。改完模组文件需要重新加载验证、且热重载（hot_reload）管不到时必须加载。
---

主路径用 mod-debug-bridge MCP 的存档工具；工具全挂时才走本目录的手动 GUI 操作。

**重启（杀进程/重启 MCStudio/重进存档）前必须获得用户同意**——重启会干扰用户在游戏里的操作。

## 主路径：存档工具

| 场景 | 工具 |
|---|---|
| 重启存档（改了已有 JSON 内容 / 要重进世界） | `restart_world` |
| 彻底重启（新增/删除任何文件后必须） | `full_restart`（省略 target 重进当前存档） |
| 启动开发测试（改完代码要验证） | `launch_world`：target 传改动文件路径/项目hash/包名/存档名，多匹配自动取第一个 |
| 新建测试存档（换版本/组件） | `mcp__mc-studio__`：create_world、get_project_info、open_editor、validate_mod |

- 验证闭环内置于工具（等玩家进服）；超时返回进程状态，稍后用 execute_code 查 GetPlayerList 确认
- 勿绕过工具直接 taskkill 存档中的进程（会损坏存档）；工具已内置"保存退出→等落盘→再杀"

## 出错排查

工具失败时自动附四级诊断（游戏进程 / DebugBridge 桥 / MCStudio / MCStudio MCP）：

| 诊断 | 处理 |
|---|---|
| 游戏未启动 | 改用 `launch_world` |
| 游戏在跑但桥不通 | 未进存档或该存档未勾选 DebugBridge 组件，让用户进对存档 |
| MCStudio 未启动 | 先跑 `py -3 -B <skill目录>/launch-mcstudio`（登录窗自动 Enter）；失败请用户手动启动并登录 |
| MCStudio 在但 MCP 不通 | 主窗口出现后数十秒才就绪；一直不通提醒用户开启 MCStudio 的 MCP |
| 启动后约 20 秒退出（ucrtbase abort） | 皮肤反作弊：按工具崩溃提示传 `skin_name`（"史蒂夫"/"爱丽克丝"/"4D测试皮肤"/"黑洞之心"/"4D云霄战姬"/"4D学生晴音"）重调 launch_world/full_restart，重写一次后换任意皮肤（含原皮肤）均正常 |
| 其他崩溃 | 查 `%APPDATA%\MinecraftPE_Netease\logs` 最新 Debug_Log 与事件日志（`Get-WinEvent -FilterHashtable @{LogName='Application'; Id=1000; StartTime=(Get-Date).AddMinutes(-10)}`）；模组代码没改而崩溃 → 向用户报告，不无限重试 |

## 回退：手动 GUI 操作（MCP 工具全挂时）

需要视觉能力读截图；没有视觉时用 AskUserQuestion 请用户切换模型，盲点坐标会点错菜单。

操作回路：**截屏看界面 → pyautogui 点击 → 截屏验证**，循环推进。

- 观察：computer-use 的 `getAXStateAndScreenshot()`（MCStudio 的 a11y 树可读，游戏本体基本是盲的）；全屏截图 pyautogui.screenshot 存 PNG 后 Read
- 输入：`py -3 -B -c` 调 pyautogui（先 `pyautogui.FAILSAFE = False`）；computer-use 物理点击被 `independent_surface_requires_association` 拒绝时整体改用 pyautogui，computer-use 只观察
- 以截图为准判断点击是否生效；发键盘事件前先点窗口标题栏聚焦
- 坐标：a11y bounds 是物理坐标直接点；raster 换算 `物理 = 窗口原点 + raster × (窗口物理尺寸 / raster 尺寸)`；pyautogui 坐标 = 物理像素；PowerShell 发物理坐标前先 `[Win32]::SetProcessDPIAware()`
- computer-use 的 window_id 即 Win32 HWND，可直接 PostMessage

### MCStudio 窗口

- 主窗口标题**我的世界编辑器**；"MC Studio" 是屏幕中央 2x2 辅助窗口（a11y 可读但截图空白）
- 判断窗口存在用 `FindWindowW(None, 标题)`（登录后 MainWindowHandle 为 0）
- 启动：`Start-Process 'C:\Program Files (x86)\MCStudio\MCStudio.exe' -WorkingDirectory 'C:\Program Files (x86)\MCStudio'`（工作目录错会弹网易通用登录组件）；登录窗 Enter 登录
- 主窗口幽灵态（rect 正常但截图不渲染）→ 重启 MCStudio（先确认无 Minecraft.Windows.exe 进程）

### 操作1：游戏内重启存档（无新增文件）

1. 点标题栏聚焦 → 发 `Escape` → 截图确认暂停菜单 → 点"保存并退出" `[305, 597]` → 等回主菜单
2. 点"开始游戏" `[640, 404]` → 点左上角第一张存档卡片 `[165, 320]`（测试存档保持列表第一）
3. 轮询 execute_code 直到 GetPlayerList 返回

坐标对应 1280x755 raster；截图里按钮位置明显不同时以截图为准重新取。

### 操作2：MCStudio 面板启动（新增/删除文件后）

1. 主窗口 → 左侧"作品库"→"基岩版组件"→ 顶部标签"附加包"（AddOn 模组）
2. 右侧"测试存档记录"面板（按时间倒序）→ 点目标模组行的 ▶ 继续**已有**存档；**不要点"开发测试"按钮**（弹版本选择，选了会新建存档）；误开弹窗向其 HWND 发 `PostMessage(hwnd, 0x10, 0, 0)` 关闭
3. 弹"只能启动一个测试作品"点【继续测试】
4. 轮询 `tasklist //FI "IMAGENAME eq Minecraft.Windows.exe" //FO CSV //NH` 等新 pid（≤60 秒）→ 再等约 25 秒 → 轮询 execute_code 验证

## 通用排查

- execute_code 连接超时/10061 → 游戏窗口后台 tick 暂停，切前台重试
- 多游戏实例分不清：`netstat -ano | grep <pid> | grep -i listen`，14530/14531 归谁连谁
- 用户手动开的游戏实例残留无害，不要主动杀
- 闭环标准：execute_code（server）返回玩家列表
