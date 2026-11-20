# -*- coding: utf-8 -*-
"""开发测试存档流程：MCP 工具 restart_world / launch_world / full_restart 的底层实现。

三段能力：
  - 存档-模组映射：扫 MCStudio 测试存档配置（cppconfig），从模组文件路径/hash/包名/存档名反查存档
  - 存档生命周期：RestartLocalGame / QuitLocalGame（DebugBridge 桥）+ 等就绪 + 等存档落盘
  - MCStudio MCP 客户端：调 MCStudio 的 launch_world，由 MCStudio 部署文件并拉起游戏进程

文件改动的重载边界：.py 内容用 hot_reload、已有 JSON 内容重载存档（restart_world）即可；
新增/删除任何文件必须彻底重启——引擎只在进程启动时扫描文件列表，重载存档不重扫。

各工具失败时用 diagnose_environment 输出四级环境状态（游戏进程 / 桥端口 / MCStudio 进程 /
MCStudio MCP），调用方据此决定下一步（改用 launch_world、提醒用户启动 MCStudio 或开启其 MCP）。
"""
import ctypes
import glob
import json
import os
import re
import socket
import subprocess
import threading
import time
import urllib.request

import debug_bridge_client as bridge

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

GAME_EXE = "Minecraft.Windows.exe"
MCSTUDIO_EXE = "MCStudio.exe"
MCSTUDIO_MCP_SSE = "http://localhost:19131/sse"
MCSTUDIO_MCP_PORT = 19131
GAME_CONFIG_ROOT = r"C:\MCStudioDownload\game\config"
LOGS_DIR = os.path.join(os.environ.get("APPDATA", ""), "MinecraftPE_Netease", "logs")

GET_LEVEL_ID_CODE = "import mod.client.extraClientApi as clientApi\nprint repr(clientApi.GetLevelId())"
QUIT_CODE = "import mod.client.extraClientApi as clientApi\nprint repr(clientApi.QuitLocalGame())"
PLAYER_LIST_CODE = "import mod.server.extraServerApi as serverApi\nprint len(serverApi.GetPlayerList())"


# ---------------------------------------------------------------- 窗口/进程
def activate_game_window():
    """游戏窗口置前台。DebugBridge 挂在游戏 tick 里，最小化/后台时 tick 暂停、连接卡死。"""
    hwnd = user32.FindWindowW("OGLES", None)
    if not hwnd or user32.GetForegroundWindow() == hwnd:
        return
    title = ctypes.create_unicode_buffer(64)
    user32.GetWindowTextW(hwnd, title, 64)
    if "Minecraft" not in title.value:
        return
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    # 本进程不是前台进程，直接 SetForegroundWindow 会被 Windows 拒绝，先按 ALT 取得激活权
    user32.keybd_event(0x12, 0, 0, 0)  # VK_MENU 按下
    user32.SetForegroundWindow(hwnd)
    user32.keybd_event(0x12, 0, 2, 0)  # KEYEVENTF_KEYUP


def tasklist_pids(exe_name):
    # tasklist 输出跟随系统代码页（中文环境 GBK），按 bytes 匹配避免解码问题
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq " + exe_name, "/FO", "CSV", "/NH"],
                         capture_output=True).stdout
    return {int(line.split(b'","')[1]) for line in out.splitlines() if exe_name.encode() in line}


def minecraft_pids():
    return tasklist_pids(GAME_EXE)


def process_alive(pid):
    handle = kernel32.OpenProcess(0x1000, 0, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if handle:
        kernel32.CloseHandle(handle)
        return True
    return False


# ---------------------------------------------------------------- 桥执行与等待
def bridge_reachable(side):
    port = bridge.CLIENT_PORT if side == "client" else bridge.SERVER_PORT
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(1.0)
    try:
        probe.connect(("127.0.0.1", port))
        return True
    except (socket.error, socket.timeout):
        return False
    finally:
        probe.close()


def run_in_game(side, code):
    """桥执行代码返回 stdout。失焦导致连接复位时置前台重试一次；执行报错抛 IOError。"""
    call = bridge.exec_client if side == "client" else bridge.exec_server
    for attempt in (1, 2):
        try:
            resp = call(code)
        except Exception:
            if attempt == 1:
                activate_game_window()
                time.sleep(3)
                continue
            raise
        if not resp.get("success"):
            raise IOError("游戏内执行报错:\n" + resp.get("stderr", ""))
        return resp.get("stdout", "")


def wait_world_ready(timeout, pids=None):
    """轮询服务端桥直到玩家进服。返回 (status, hint)，status: ready/timeout/crashed。"""
    activate_game_window()
    if pids is None:
        pids = minecraft_pids()
    deadline = time.time()+timeout
    last_beat = time.time()
    while time.time()<deadline:
        try:
            resp = bridge.exec_server(PLAYER_LIST_CODE)
            if resp.get("success") and resp.get("stdout", "").strip() not in ("", "0"):
                return "ready", ""
        except Exception:
            pass
        if time.time()-last_beat>15:
            if pids and not any(process_alive(pid) for pid in pids):
                return "crashed", crash_hint()
            activate_game_window()
            last_beat = time.time()
        time.sleep(3)
    if pids and not any(process_alive(pid) for pid in pids):
        return "crashed", crash_hint()
    return "timeout", "等待就绪超时（{}秒），游戏进程仍在运行，可能仍在加载；可稍后用execute_code执行GetPlayerList确认".format(timeout)


# ---------------------------------------------------------------- 游戏日志
def newest_debug_log():
    logs = glob.glob(os.path.join(LOGS_DIR, "Debug_Log*.txt"))
    return max(logs, key=os.path.getmtime) if logs else None


def wait_level_destructed(timeout):
    """轮询最新 Debug_Log 增量出现 Level-LevelDestructed（最后一次存盘之后才出现）。"""
    log = newest_debug_log()
    if not log:
        return False
    with open(log, "rb") as fp:
        fp.seek(0, os.SEEK_END)
        deadline = time.time()+timeout
        while time.time()<deadline:
            line = fp.readline()
            if b"Level-LevelDestructed" in line:
                return True
            if not line:
                time.sleep(0.5)
    return False


def crash_hint():
    """进程退出时读最新 Debug_Log 尾部，识别已知的皮肤反作弊退出症候。"""
    log = newest_debug_log()
    if not log:
        return "游戏进程已退出（疑似崩溃），未找到游戏日志（%APPDATA%\\MinecraftPE_Netease\\logs）"
    with open(log, "rb") as fp:
        fp.seek(0, os.SEEK_END)
        fp.seek(max(0, fp.tell()-8192))
        tail = fp.read().decode("utf-8", "replace")
    if "slin_file not founded" in tail or "cheat founded" in tail:
        return ('游戏进程已退出：存档皮肤状态陈旧触发反作弊（日志出现 slin_file not founded / '
                'cheat founded）。用 launch_world 带 skin_name（如"史蒂夫"）重写皮肤配置后重启')
    return "游戏进程已退出（疑似崩溃），查日志: " + log


# ---------------------------------------------------------------- 存档-模组映射
def is_game_id(target):
    return len(target)==36 and target.count("-")==4


def iter_cppconfigs():
    """遍历 MCStudio 测试存档配置，yield (game_id, cfg)。game_id 即 cppconfig 文件名去后缀。"""
    pattern = os.path.join(GAME_CONFIG_ROOT, "*", "Cpp", "MC_GAME", "*.cppconfig")
    for path in glob.glob(pattern):
        try:
            with open(path, encoding="utf-8") as fp:
                yield os.path.basename(path)[:-len(".cppconfig")], json.load(fp)
        except (ValueError, OSError):
            pass


def resolve_keyword(target):
    """模组文件路径 → 项目hash/包名；普通关键词原样返回。"""
    hash_match = re.search(r"AddOn[\\/]+([0-9a-fA-F]{32})", target)
    if hash_match:
        return hash_match.group(1).lower()
    pack_match = re.search(r"(?:behavior_packs|resource_packs)[\\/]+([^\\/]+)", target)
    return pack_match.group(1) if pack_match else target


def find_test_worlds(keyword):
    """查加载了指定模组的测试存档，返回 [(存档名, game_id)]。"""
    keyword = resolve_keyword(keyword)
    rows = []
    for game_id, cfg in iter_cppconfigs():
        world = cfg.get("world_info", {})
        packs = world.get("behavior_packs", [])+world.get("resource_packs", [])
        projects = list((cfg.get("LocalComponentPathsDict") or {}).keys())
        haystack = " ".join([game_id, world.get("name", ""), cfg.get("MainComponentId", "")]+packs+projects)
        if keyword.lower() in haystack.lower():
            rows.append((world.get("name", "?"), game_id))
    return rows


def resolve_target_to_game_id(target):
    """target 归一为 game_id。返回 (game_id, note)：game_id 为 None 时 note 是失败原因；
    多个匹配取第一个并在 note 说明。"""
    if is_game_id(target):
        return target, ""
    rows = find_test_worlds(target)
    if not rows:
        return None, "没有测试存档匹配'{}'。需先在MCStudio对该模组执行开发测试以生成测试存档，或检查路径/名称".format(target)
    note = "匹配存档: " + rows[0][0]
    if len(rows)>1:
        note += "（共{}个匹配取第一个: {}）".format(len(rows), ", ".join(name for name, _ in rows))
    return rows[0][1], note


# ---------------------------------------------------------------- 环境诊断
def mcstudio_mcp_reachable():
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(2.0)
    try:
        probe.connect(("127.0.0.1", MCSTUDIO_MCP_PORT))
        return True
    except (socket.error, socket.timeout):
        return False
    finally:
        probe.close()


def diagnose_environment():
    """四级探测：游戏进程 / 桥端口 / MCStudio 进程 / MCStudio MCP。返回多行诊断文案。"""
    pids = minecraft_pids()
    lines = ["环境诊断：", "- 游戏进程: " + ("运行中" if pids else "未启动")]
    for side, port in (("client", bridge.CLIENT_PORT), ("server", bridge.SERVER_PORT)):
        lines.append("- DebugBridge桥({}端 {}): {}".format(side, port, "通" if bridge_reachable(side) else "不通"))
    if pids and not bridge_reachable("client") and not bridge_reachable("server"):
        lines.append("  （游戏在跑但桥不通：未进存档，或该存档未勾选DebugBridge组件）")
    if tasklist_pids(MCSTUDIO_EXE):
        if mcstudio_mcp_reachable():
            lines.append("- MCStudio: 运行中，MCP可用")
        else:
            lines.append("- MCStudio: 运行中，MCP不通（主窗口出现后数十秒才就绪；若一直不通请用户在MCStudio中开启MCP）")
    else:
        lines.append("- MCStudio: 未启动（本工具不代启动MCStudio，请用户手动启动并登录）")
    return "\n".join(lines)


# ---------------------------------------------------------------- MCStudio MCP 客户端
class McpClient:
    """stdlib 实现的 MCP SSE 传输：GET /sse 拿 endpoint，POST JSON-RPC，响应走 SSE 流。"""

    def __init__(self, url):
        self.url = url
        self.events = []
        self.lock = threading.Lock()
        self.endpoint = None
        self.resp = None
        self.req_id = 0

    def _reader(self, resp):
        try:
            for raw in resp:
                line = raw.decode("utf-8", "replace").rstrip("\n")
                if line.startswith("data:"):
                    try:
                        msg = json.loads(line[5:].strip())
                    except ValueError:
                        continue
                    with self.lock:
                        self.events.append(msg)
        except Exception:
            pass  # 会话关闭时 reader 线程静默退出

    def _post(self, msg):
        body = json.dumps(msg).encode("utf-8")
        req = urllib.request.Request(self.endpoint, data=body, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=30).read()

    def _request(self, method, params=None, timeout=60):
        with self.lock:
            self.req_id += 1
            rid = self.req_id
        msg = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            msg["params"] = params
        self._post(msg)
        deadline = time.time()+timeout
        while time.time()<deadline:
            with self.lock:
                for i, ev in enumerate(self.events):
                    if ev.get("id")==rid:
                        del self.events[i]
                        if "error" in ev:
                            raise IOError(ev["error"].get("message", str(ev["error"])))
                        return ev.get("result")
            time.sleep(0.2)
        raise IOError("MCP响应超时: " + method)

    def connect(self):
        self.resp = urllib.request.urlopen(self.url, timeout=10)
        first = self.resp.readline().decode("utf-8").strip()  # event: endpoint
        if "endpoint" not in first:
            self.close()
            raise IOError("SSE首事件非endpoint: %r" % first)
        data = self.resp.readline().decode("utf-8").strip()   # data: /messages?sid=...
        self.endpoint = self.url.rsplit("/", 1)[0]+data[5:].strip()
        threading.Thread(target=self._reader, args=(self.resp,), daemon=True).start()
        self._request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                      "clientInfo": {"name": "mod-debug-bridge", "version": "1.0"}})
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return self

    def tool(self, name, arguments, timeout=60):
        result = self._request("tools/call", {"name": name, "arguments": arguments}, timeout=timeout)
        return "\n".join(c.get("text", "") for c in (result or {}).get("content", []) if c.get("type") == "text")

    def close(self):
        if self.resp:
            try:
                self.resp.close()
            except Exception:
                pass


# ---------------------------------------------------------------- 启动/重启流程
def restart_world(timeout=120):
    """触发 RestartLocalGame 并等加载完成。返回 (status, hint)。
    先等旧世界卸载（服务端桥断开）再等就绪——RestartLocalGame 异步，触发后旧桥
    短时间内仍会应答，直接等就绪会拿旧世界的玩家列表误判 ready。"""
    activate_game_window()
    run_in_game("client",
                "import mod.client.extraClientApi as clientApi\nprint repr(clientApi.RestartLocalGame())")
    deadline = time.time()+60
    while time.time()<deadline:
        try:
            resp = bridge.exec_server(PLAYER_LIST_CODE)
            if not resp.get("success"):
                break  # 旧世界开始卸载
        except Exception:
            break
        time.sleep(1)
    return wait_world_ready(timeout)


def quit_world_safely():
    """保存退出当前存档（等落盘）后杀游戏进程，供彻底重启/启动前清理。
    返回 (level_id, error)：error 非 None 即失败（此时未杀进程，存档安全）；
    没有游戏进程在跑时返回 (None, None)。桥不通时不动进程——无法确认存档是否在跑，
    直接杀有损坏存档风险。"""
    if not minecraft_pids():
        return None, None
    if not bridge_reachable("client"):
        # 进程可能是刚被 taskkill 的残留（tasklist 里短暂可见）：等几秒确认真活着才报错
        deadline = time.time()+8
        while time.time()<deadline and minecraft_pids():
            time.sleep(1)
        if minecraft_pids():
            return None, ("游戏进程在跑但DebugBridge桥不通（未进存档或该存档未勾选DebugBridge组件），"
                          "无法安全保存退出；请用户手动退出到主菜单或关闭游戏后重试")
        return None, None
    try:
        level_id = run_in_game("client", GET_LEVEL_ID_CODE).strip().strip("'")
        if level_id and level_id != "None":
            run_in_game("client", QUIT_CODE)
            if not wait_level_destructed(30):
                return level_id, "等待存档落盘超时（30秒，Level-LevelDestructed未出现）；未杀进程，存档安全。确认游戏窗口前台后重试"
    except Exception as exc:
        return None, "保存退出失败（{}）".format(exc)
    subprocess.run(["taskkill", "/IM", GAME_EXE, "/F"], capture_output=True)
    return level_id, None


def launch_world(game_id, timeout=180, skin_name=None):
    """经 MCStudio launch_world 启动测试存档并等就绪（MCStudio 负责部署文件、拉起游戏）。
    游戏进程已在跑时先保存退出并杀掉（等落盘，防存档损坏）。
    返回 (status, hint)，status: ready/timeout/crashed/failed。"""
    _, quit_error = quit_world_safely()
    if quit_error:
        return "failed", quit_error + "\n" + diagnose_environment()
    arguments = {"game_id": game_id}
    if skin_name:
        arguments["skin_name"] = skin_name
    result = {}
    def call_mcp():
        client = McpClient(MCSTUDIO_MCP_SSE)
        try:
            client.connect()
            result["text"] = client.tool("launch_world", arguments)
        except Exception as exc:
            result["error"] = str(exc)
        finally:
            client.close()
    threading.Thread(target=call_mcp, daemon=True).start()
    # launch_world 的 MCP 响应常慢于游戏进程出现甚至丢失：并行观察新进程，不空等响应
    before = minecraft_pids()
    new_pids = None
    deadline = time.time()+60
    while time.time()<deadline:
        new_pids = minecraft_pids()-before
        if new_pids or result:
            break
        time.sleep(3)
    if not new_pids:
        detail = result.get("error") or result.get("text") or "60秒未见新游戏进程"
        return "failed", "launch_world未拉起游戏进程：{}\n{}".format(detail, diagnose_environment())
    status, hint = wait_world_ready(timeout, pids=new_pids)
    extra = (result.get("text") or "").strip()
    if status == "ready":
        return "ready", "存档已启动，玩家已进服" + ("\nMCStudio输出: "+extra if extra else "")
    return status, hint + ("\nMCStudio输出: "+extra if extra else "")
