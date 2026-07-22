# -*- coding: utf-8 -*-
"""ModSDK MCP 服务器（极简版）。

七个工具：
  - get_api_detail(name)：按名称查接口/事件/枚举值的完整详情
  - search_api(pattern)：正则搜索 API/事件/枚举索引（grep 式）
  - search_identifier(pattern)：正则搜索基岩版方块/物品/实体/状态效果/附魔 ID
  - execute_code(code, side)：在游戏内 DebugBridge mod 执行 Python 代码（py2.7）
  - listen_event(event_name, side, ...)：注册事件监听器，捕获 args 存队列
  - get_event_log()：读取 listen_event 捕获的 args
  - hot_reload(side, pkg, modules)：改完 .py 后热重载，封装 hot_reload.py

前三个工具仅依赖 data/ 下的预编译索引；execute_code/listen_event/get_event_log
依赖 tools/debug_bridge_client.py 连接游戏进程（端口 14530/14531）；
hot_reload 通过 subprocess 调 py2 脚本（D:/mod-debug-bridge/scripts/hot_reload.py）。
"""
import asyncio
import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, CallToolResult

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
# 加 tools/ 到 import 路径，让 debug_bridge_client 可 import
sys.path.insert(0, str(BASE_DIR / "tools"))

import debug_bridge_client as db
# 启动时一次性加载预编译索引
INDEX = json.loads((DATA_DIR / "api_index.json").read_text(encoding="utf-8"))
LISTINGS = (DATA_DIR / "api_listings.txt").read_text(encoding="utf-8").splitlines()
MC_IDS = (DATA_DIR / "mc_ids.txt").read_text(encoding="utf-8").splitlines()

SEARCH_LIMIT = 20

server = Server("mod-debug-bridge")

@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="get_api_detail",
            description="按名称查询ModSDK接口/事件/枚举值的完整签名（参数、返回值、备注、示例）。同名多个结果全部返回。",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "接口/事件/枚举值的精确名称，如SpawnItemToPlayerInv、MobDieEvent、AttrType",
                    },
                    "side": {
                        "type": "string",
                        "enum": ["客户端", "服务端"],
                        "description": "只返回对应端侧的详情（同名跨端侧时过滤），不传则全部返回",
                    },
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="search_api",
            description="搜索ModSDK接口/事件/枚举值名称。每行格式：名称<TAB>类型<TAB>端侧<TAB>描述。返回匹配行，用于查找名称后用get_api_detail查详情。",
            inputSchema={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "正则表达式，如^Set.*Pos、设置实体.*位置",
                    },
                    "entry_type": {
                        "type": "string",
                        "enum": ["接口", "事件", "枚举"],
                        "description": "按类型过滤，不传则搜全部",
                    },
                },
                "required": ["pattern"],
            },
        ),
        Tool(
            name="search_identifier",
            description="搜索基岩版方块/物品/实体/状态效果/附魔的ID。每行格式：ID<TAB>类型<TAB>中文名。",
            inputSchema={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "正则表达式，如golden_apple、^.*_axe、苹果、剑|斧",
                    },
                    "entry_type": {
                        "type": "string",
                        "enum": ["方块", "物品", "实体", "状态效果", "附魔"],
                        "description": "按类型过滤，不传则搜全部",
                    },
                },
                "required": ["pattern"],
            },
        ),
        Tool(
            name="execute_code",
            description="在游戏内执行Python2代码。",
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "代码，支持换行，不要手动用\n拼接",
                    },
                    "side": {
                        "type": "string",
                        "enum": ["client", "server"],
                        "description": "在客户端还是服务端执行",
                    },
                },
                "required": ["code", "side"],
            },
        ),
        Tool(
            name="listen_event",
            description="在游戏内注册事件监听器，捕获引擎或模组自定义事件的args，事件触发后用get_event_log读取。",
            inputSchema={
                "type": "object",
                "properties": {
                    "event_name": {
                        "type": "string",
                        "description": "事件名，如DestroyBlockEvent",
                    },
                    "side": {
                        "type": "string",
                        "enum": ["client", "server"],
                        "description": "是客户端事件还是服务端事件",
                    },
                    "namespace": {
                        "type": "string",
                        "description": "事件命名空间，监听模组自定义事件才需要改",
                        "default": "Minecraft",
                    },
                    "system_name": {
                        "type": "string",
                        "description": "事件system名，监听模组自定义事件才需要改",
                        "default": "Engine",
                    },
                },
                "required": ["event_name", "side"],
            },
        ),
        Tool(
            name="get_event_log",
            description="读取listen_event注册的事件监听器捕获到的args列表，无事件触发时返回空字符串。",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="hot_reload",
            description="改完mod的.py文件后热重载，免重启游戏。",
            inputSchema={
                "type": "object",
                "properties": {
                    "side": {
                        "type": "string",
                        "enum": ["both", "client", "server"],
                        "description": "重载端：both（默认，双端都重载）/client/server",
                        "default": "both",
                    },
                    "pkg": {
                        "type": "string",
                        "description": "多个mod同时存在时指定包名（可选）",
                    },
                    "modules": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "指定模块名列表（如[\"chainScripts.chainServerSystem\"]），不传则自动扫改动",
                    },
                },
                "required": [],
            },
        ),
    ]

def _search(arguments, lines):
    """正则搜索 + 可选类型过滤。带 entry_type 时去掉类型列（AI 已知类型）。"""
    pattern = arguments.get("pattern", "")
    entry_type = arguments.get("entry_type", "")
    try:
        regex = re.compile(pattern)
    except re.error as e:
        return [TextContent(type="text", text="正则表达式错误：{}".format(e))]
    matched = [
        line for line in lines
        if regex.search(line)
        and (not entry_type or line.split("\t")[1] == entry_type)
    ]
    if not matched:
        return [TextContent(type="text", text="未找到匹配'{}'的条目。".format(pattern))]
    # 带 entry_type 时去掉类型列（第 2 列），保留其余列
    if entry_type:
        matched = ["\t".join(p for i, p in enumerate(line.split("\t")) if i != 1) for line in matched]
    truncated = len(matched) > SEARCH_LIMIT
    result = "\n".join(matched[:SEARCH_LIMIT])
    if truncated:
        result += "\n\n...（共{}条匹配，仅显示前{}条，请用更精确的正则缩小范围）".format(
            len(matched), SEARCH_LIMIT)
    return [TextContent(type="text", text=result)]

def _exec_with_retry(code, side):
    """在 mod 端执行代码，带连接重试。
    返回 (success, payload, is_tool_error)：
      - 代码执行成功： (True, stdout, False)
      - 代码报错：     (False, stderr, False)  ← 代码错不算工具错
      - 连接彻底失败： (False, 诊断文案, True)
    """
    import time
    port = db.CLIENT_PORT if side == "client" else db.SERVER_PORT
    exec_func = db.exec_client if side == "client" else db.exec_server
    # 重试：上次连接的 _cli 要等 mod 端 tick 推进到 _recv 返回空才清除，
    # 新连接若赶在清除前到达会被 reset（WinError 10054）。退避让 tick 留时间清理。
    for attempt in range(3):
        try:
            resp = exec_func(code)
            if resp.get("success"):
                return True, resp.get("stdout", ""), False
            return False, resp.get("stderr", "(no stderr)"), False
        except (socket.error, socket.timeout, EOFError):
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
                continue
            return False, _diagnose_connection_failure(port), True

def _diagnose_connection_failure(port):
    """socket 连不上时自动探测原因，返回精准错误文案。
    探测顺序：游戏进程 → 端口监听 → 兜底超时文案。"""
    # 1. 进程探测：网易版基岩 exe 名固定为 Minecraft.Windows.exe
    try:
        r = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Minecraft.Windows.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=5,
        )
        game_running = bool(r.stdout and r.stdout.strip())
    except Exception:
        game_running = False
    if not game_running:
        return "游戏未启动，请让用户先启动游戏"

    # 2. 端口监听探测：netstat 找 :port 行是否含 LISTENING
    try:
        r = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True, timeout=5,
        )
        port_listening = any(":{}".format(port) in line and "LISTENING" in line
                             for line in r.stdout.splitlines())
    except Exception:
        port_listening = False
    if not port_listening:
        return "调试工具未加载，请让用户装载调试工具mod后再进行开发测试"

    # 3. 端口在监听但 socket 连不上 → 多数是游戏后台/最小化导致 tick 暂停
    return "连接超时，可能游戏处于后台，tick暂停导致socket卡死，请把游戏窗口切回前台再试"

@server.call_tool()
async def call_tool(name, arguments):
    if name == "get_api_detail":
        api_name = arguments.get("name", "")
        side = arguments.get("side", "")
        entries = INDEX.get(api_name)
        if not entries:
            output = "未找到名为`{}`的API或事件。请检查名称拼写。\n".format(api_name)
            output += "提示：可通过search_api正则搜索索引来查找名称。"
        elif side:
            # 按 ### 分段，保留 header 含 (side) 的段；无匹配则忽略 side 返回全部
            parts = re.split(r"(?=^### )", entries[0], flags=re.MULTILINE)
            filtered = [p for p in parts if "({})".format(side) in p.split("\n")[0]]
            output = "".join(filtered) if filtered else entries[0]
        else:
            output = entries[0]
        return [TextContent(type="text", text=output)]

    elif name == "search_api":
        return _search(arguments, LISTINGS)

    elif name == "search_identifier":
        return _search(arguments, MC_IDS)

    elif name == "execute_code":
        code = arguments.get("code", "")
        side = arguments.get("side", "server")
        success, payload, is_tool_error = _exec_with_retry(code, side)
        if is_tool_error:
            return CallToolResult(content=[TextContent(type="text", text=payload)], isError=True)
        if success:
            text = payload if payload.strip() else "执行成功，无输出"
            return [TextContent(type="text", text=text)]
        # 代码报错：返回 traceback 文本，isError=false（代码错 ≠ 工具错）
        return [TextContent(type="text", text=payload[:4000])]

    elif name == "listen_event":
        event_name = arguments.get("event_name", "")
        side = arguments.get("side", "server")
        namespace = arguments.get("namespace") or "Minecraft"
        system_name = arguments.get("system_name") or "Engine"
        if not event_name:
            return [TextContent(type="text", text="event_name 不能为空")]
        # mod 端在 __main__._db_event_state 维护单槽（namespace/systemName/eventName/side/queue/handler/instance）。
        # 每次调用：先 UnListen 上次的（如有），再注册新的并清空队列。
        # 引擎事件（Minecraft/Engine）注册未定义事件时引擎只打日志不抛异常，ListenForEventServer
        # 还返回 None，工具会误以为成功。注册后用 eventBus.GetEngineEventID 复查——合法事件返回
        # int ID，未定义返回 None——拿不到 ID 就报错。客户端/服务端各自有独立事件表，
        # 所以用对应端的 eventBus 检查。
        listen_code = '''
import __main__
from collections import deque
from common.eventUtil import instance as event

prev = getattr(__main__, "_db_event_state", None)
if prev is not None:
    try:
        if prev["side"] == "client":
            event.UnListenForEventClient(prev["namespace"], prev["systemName"], prev["eventName"], prev["instance"], prev["handler"])
        else:
            event.UnListenForEventServer(prev["namespace"], prev["systemName"], prev["eventName"], prev["instance"], prev["handler"])
    except Exception as e:
        print "UnListen prev failed: " + str(e)

state = {"namespace": %r, "systemName": %r, "eventName": %r, "side": %r, "queue": deque(maxlen=10), "handler": None, "instance": __main__}

def _db_event_handler(*argv, **kwargs):
    args = argv[0] if len(argv) == 1 else argv
    state["queue"].append(str(args))

state["handler"] = _db_event_handler
__main__._db_event_state = state
__main__._db_event_handler = _db_event_handler  # 防 GC

if %r == "client":
    event.ListenForEventClient(%r, %r, %r, __main__, _db_event_handler)
    from common.system.systemRegister import client as _sys
else:
    event.ListenForEventServer(%r, %r, %r, __main__, _db_event_handler)
    from common.system.systemRegister import server as _sys

# 复查：引擎事件必须在对应端的事件表里有 cppID，否则引擎层已判定为未定义事件
if %r == "Minecraft" and %r == "Engine":
    _eventID = %r + ":" + %r + ":" + %r
    if _sys.eventBus.GetEngineEventID(_eventID) is None:
        print "FAIL undefined engine event: " + _eventID
    else:
        print "OK listening"
else:
    print "OK listening"
''' % (namespace, system_name, event_name, side,
       side, namespace, system_name, event_name,
       namespace, system_name, event_name,
       namespace, system_name, namespace, system_name, event_name)
        success, payload, is_tool_error = _exec_with_retry(listen_code, side)
        if is_tool_error:
            return CallToolResult(content=[TextContent(type="text", text=payload)], isError=True)
        if success:
            text = payload.strip() or "执行成功，无输出"
            # 引擎层面判定未定义事件——算工具错（不是代码错），AI 能立即纠正事件名。
            # 注意 payload 可能以引擎 [INFO][Engine] 日志开头（listen 过程触发的 RegisterEngineHandler
            # 日志也被 stdout 捕获），用 "FAIL undefined engine event" in text 判断而不是 startswith。
            if "FAIL undefined engine event" in text:
                return CallToolResult(content=[TextContent(type="text",
                text="未定义的引擎事件：{}。事件名拼写错误、不存在，或该事件不在{}端".format(event_name, side))], isError=True)
            return [TextContent(type="text", text=text)]
        return [TextContent(type="text", text=payload[:4000])]

    elif name == "get_event_log":
        # 读 __main__._db_event_state.queue，'\n'.join(map(str, args)) 返回。
        # 不知道当前 side，两端都试一遍——listen_event 注册的端会有 state，另一端会拿到 AttributeError。
        for side in ("server", "client"):
            success, payload, is_tool_error = _exec_with_retry(
                'import __main__\n'
                'st = getattr(__main__, "_db_event_state", None)\n'
                'if st is None:\n'
                '    print "NOT_REGISTERED"\n'
                'else:\n'
                '    print chr(10).join(list(st["queue"]))\n',
                side,
            )
            if is_tool_error:
                # 一端连接失败不算最终结果，继续试另一端
                continue
            if not success:
                continue
            text = payload.strip()
            if text == "NOT_REGISTERED":
                continue
            return [TextContent(type="text", text=text if text else "(no events captured yet)")]
        return [TextContent(type="text", text="未注册任何事件监听器，请先调用listen_event")]

    elif name == "hot_reload":
        side = arguments.get("side", "both")
        pkg = arguments.get("pkg")
        modules = arguments.get("modules") or []
        # hot_reload.py 跟 server.py 同项目，相对路径找
        script = BASE_DIR / "tools" / "hot_reload.py"
        if not script.is_file():
            return CallToolResult(
                content=[TextContent(type="text", text="hot_reload.py脚本未找到：{}".format(script))],
                isError=True,
            )
        cmd = [r"C:\Python27\python.exe", "-B", str(script)]
        if side == "client":
            cmd.append("--client")
        elif side == "server":
            cmd.append("--server")
        if pkg:
            cmd += ["--pkg", pkg]
        cmd += list(modules)
        try:
            # hot_reload.py 是 py2 脚本，Windows 下 print 中文走 MBCS(GBK)，不是 UTF-8。
            # py3 subprocess 默认 UTF-8 解码会抛 UnicodeDecodeError，显式指定 GBK。
            #
            # 注意：不能用 subprocess.run(capture_output=True) 或 Popen(stdout=PIPE)。
            # 本进程的 stdio 被 mcp.server.stdio_server 接管（asyncio），子进程继承
            # stdout/stderr 句柄后 Popen.communicate 卡 30s（PIPE 读不到 EOF）。
            # 改为输出重定向到临时文件，wait 完再读，绕开管道通信。0.08s 正常返回。
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w+b', delete=False) as _out_f, \
                 tempfile.NamedTemporaryFile(mode='w+b', delete=False) as _err_f:
                _out_path, _err_path = _out_f.name, _err_f.name
            with open(_out_path, 'w') as _o, open(_err_path, 'w') as _e:
                _proc = subprocess.Popen(cmd, stdout=_o, stderr=_e, stdin=subprocess.DEVNULL)
                _proc.wait()
            with open(_out_path, 'rb') as _f:
                _out = _f.read().decode('gbk', 'replace')
            with open(_err_path, 'rb') as _f:
                _err = _f.read().decode('gbk', 'replace')
            for _p in (_out_path, _err_path):
                try:
                    os.remove(_p)
                except OSError:
                    pass
            r = subprocess.CompletedProcess(args=cmd, returncode=_proc.returncode,
                                            stdout=_out, stderr=_err)
        except subprocess.TimeoutExpired:
            return CallToolResult(
                content=[TextContent(type="text", text="hot_reload执行超时（>120s）")],
                isError=True,
            )
        except Exception as e:
            return CallToolResult(
                content=[TextContent(type="text", text="hot_reload执行失败：{}".format(e))],
                isError=True,
            )
        # 脚本退出码非 0（有 failure）不算工具错——跟 execute_code 语义一致
        text = r.stdout or ""
        if r.stderr:
            text = (text + "\n---stderr---\n" + r.stderr) if text else r.stderr
        return [TextContent(type="text", text=text.strip() or "执行成功，无输出")]

    return [TextContent(type="text", text="未知工具：{}".format(name))]

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())