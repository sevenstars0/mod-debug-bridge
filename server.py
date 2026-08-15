# -*- coding: utf-8 -*-
"""ModSDK MCP 服务器（极简版）。

八个工具：
  - get_api_detail(name)：按名称查接口/事件/枚举值的完整详情
  - search_api(pattern)：正则搜索 API/事件/枚举索引（grep 式）
  - search_identifier(pattern)：正则搜索基岩版方块/物品/实体/状态效果/附魔 ID
  - execute_code(code, side)：在游戏内 DebugBridge mod 执行 Python 代码（py2.7）
  - listen_event(event_name, side, ...)：注册事件监听器，捕获 args 字典（支持同时监听多个事件）
  - get_event_log()：读取 listen_event 回调代码中 print 内容
  - unlisten_event(event_name, side, ...)：取消 listen_event 注册的监听器，不传 event_name 取消该端全部
  - hot_reload(side, pkg, modules)：改完 .py 后热重载，封装 hot_reload.py

前三个工具仅依赖 data/ 下的预编译索引；execute_code/listen_event/get_event_log
依赖 tools/debug_bridge_client.py 连接游戏进程（端口 14530/14531）；
hot_reload 通过 subprocess 调 py2 脚本（D:/mod-debug-bridge/scripts/hot_reload.py）。
"""
import asyncio
import ctypes
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
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
            description="在游戏内注册事件监听器，捕获引擎或模组自定义事件的args字典，事件触发后用get_event_log读取。",
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
                    "callback_code": {
                        "type": "string",
                        "description": "事件回调代码段，可访问args，默认print args",
                        "default": "print args",
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
            name="unlisten_event",
            description="取消listen_event注册的事件监听器，防止log爆炸或残留监听。不传event_name时取消该端全部监听器。",
            inputSchema={
                "type": "object",
                "properties": {
                    "event_name": {
                        "type": "string",
                        "description": "要取消的事件名，须与listen_event时的namespace/system_name匹配，不传则取消该端全部",
                    },
                    "side": {
                        "type": "string",
                        "enum": ["client", "server"],
                        "description": "在客户端还是服务端取消",
                    },
                    "namespace": {
                        "type": "string",
                        "description": "事件命名空间，取消模组自定义事件监听才需要改",
                        "default": "Minecraft",
                    },
                    "system_name": {
                        "type": "string",
                        "description": "事件system名，取消模组自定义事件监听才需要改",
                        "default": "Engine",
                    },
                },
                "required": ["side"],
            },
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

def _tool_error(text):
    """构造 isError=True 的工具错误返回（连接失败/脚本缺失等，区别于代码报错）。"""
    return CallToolResult(content=[TextContent(type="text", text=text)], isError=True)

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
    result = "\n".join(matched[:SEARCH_LIMIT])
    if len(matched) > SEARCH_LIMIT:
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


def _build_listen_code(namespace, systemName, eventName, side, callback_code):
    """构造 mod 端注册事件监听器的代码。

    三处关键设计：
    1. 引擎日志隔离：RegisterEngineHandler 等日志走 Python stdout，会被 ExecListener
       的 buf 捕获混入回传。注册期间临时把 sys.stdout 切回真实 stdout（sys.__stdout__），
       让引擎日志进游戏日志而非 MCP 回传。
    2. callback 捕获：handler 内部把 callback_code 的 print 重定向到 StringIO，
       直接入队（默认 print args → 每条即 args）。get_event_log 拿到 callback 输出。
    3. 多监听：state 存进 __main__._db_event_states（dict，key 为
       "namespace:systemName:eventName"），只有同 key 重复注册才替换旧监听，
       不同事件互不影响——支持同时监听多个事件做时序分析。
    """
    return """\
import __main__, sys, StringIO, codecs, traceback
from collections import deque
from common.eventUtil import instance as event

_states = getattr(__main__, "_db_event_states", None)
if _states is None:
    _states = {}
    __main__._db_event_states = _states

_key = %(namespace)r + ":" + %(systemName)r + ":" + %(eventName)r
prev = _states.get(_key)
if prev is not None:
    # 只顶掉同 key 的旧监听：同事件重复注册仍替换，其他事件的监听不受影响
    try:
        if prev["side"] == "client":
            event.UnListenForEventClient(prev["namespace"], prev["systemName"], prev["eventName"], prev["instance"], prev["handler"])
        else:
            event.UnListenForEventServer(prev["namespace"], prev["systemName"], prev["eventName"], prev["instance"], prev["handler"])
    except Exception as e:
        print "UnListen prev failed: " + str(e)

state = {"namespace": %(namespace)r, "systemName": %(systemName)r, "eventName": %(eventName)r, "side": %(side)r, "queue": deque(maxlen=10), "handler": None, "instance": __main__}

def _db_event_handler(args):
    # 用 utf-8 writer 包装 StringIO：引擎事件分发同栈里 logging 会写 unicode 日志，
    # 裸 StringIO 只收 str，写 unicode 会抛 IOError [Errno 0]。包装后自动编码成 utf-8。
    _buf = codecs.getwriter('utf-8')(StringIO.StringIO())
    _old = sys.stdout
    sys.stdout = _buf
    try:
%(callback_body)s
    except Exception:
        print traceback.format_exc()
    finally:
        sys.stdout = _old
    _extra = _buf.getvalue().rstrip()
    state["queue"].append(_extra)

state["handler"] = _db_event_handler
_states[_key] = state  # handler 存进 state、state 进 __main__ 上的全局 dict，即防 handler 被 GC

# 注册期间把 stdout 切回真实 stdout：RegisterEngineHandler 等引擎日志走 Python stdout，
# 否则会污染本次 exec 的回传 buf。注册后立即恢复。
_outer_stdout = sys.stdout
sys.stdout = sys.__stdout__ if sys.__stdout__ else _outer_stdout
try:
    if %(side)r == "client":
        event.ListenForEventClient(%(namespace)r, %(systemName)r, %(eventName)r, __main__, _db_event_handler)
        from common.system.systemRegister import client as _sys
    else:
        event.ListenForEventServer(%(namespace)r, %(systemName)r, %(eventName)r, __main__, _db_event_handler)
        from common.system.systemRegister import server as _sys
finally:
    sys.stdout = _outer_stdout

# 复查：引擎事件必须在对应端的事件表里有 cppID，否则引擎层已判定为未定义事件
if %(namespace)r == "Minecraft" and %(systemName)r == "Engine":
    _eventID = %(namespace)r + ":" + %(systemName)r + ":" + %(eventName)r
    if _sys.eventBus.GetEngineEventID(_eventID) is None:
        print "FAIL undefined engine event: " + _eventID
        # 引擎层没注册成功，从 states 撤掉，避免留下永不触发的空监听器
        _states.pop(_key, None)
    else:
        print "OK listening"
else:
    print "OK listening"
# 附当前活跃监听器数量与清单，便于确认多监听生效
print "active listeners (%%d): %%s" %% (len(_states), ", ".join(sorted(_states)))
""" % {
        "namespace": namespace,
        "systemName": systemName,
        "eventName": eventName,
        "side": side,
        "callback_body": textwrap.indent(callback_code, "        "),
    }


def _build_unlisten_code(namespace, systemName, eventName, side):
    """构造 mod 端取消事件监听器的 py2 代码。eventName 为 None 时取消该端全部。

    输出协议（py3 侧解析）：NO_LISTENERS（无任何监听器）/ CANCELLED n（取消数）/
    REMAINING m（剩余数）。UnListen 抛异常也照样从 _db_event_states 删条目，
    避免留下删不掉的死条目，只是不计入取消数。
    """
    # 传了 event_name 才定位到具体 key，否则 None 代表全部
    target = '"{}:{}:{}"'.format(namespace, systemName, eventName) if eventName else "None"
    return """\
import __main__
from common.eventUtil import instance as event

_states = getattr(__main__, "_db_event_states", None)
if not _states:
    print "NO_LISTENERS"
else:
    _target = %(target)s
    _keys = sorted(_states) if _target is None else [k for k in sorted(_states) if k == _target]
    _count = 0
    for k in _keys:
        st = _states[k]
        try:
            # 与注册对称：side/instance/handler 都从 state 里取
            if st["side"] == "client":
                event.UnListenForEventClient(st["namespace"], st["systemName"], st["eventName"], st["instance"], st["handler"])
            else:
                event.UnListenForEventServer(st["namespace"], st["systemName"], st["eventName"], st["instance"], st["handler"])
            _count += 1
        except Exception as e:
            print "UnListen " + k + " failed: " + str(e)
        del _states[k]
    print "CANCELLED " + str(_count)
    if _states:
        print "REMAINING " + str(len(_states))
""" % {"target": target}


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
            return _tool_error(payload)
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
        callback_code = arguments.get("callback_code") or "print args"
        if not event_name:
            return [TextContent(type="text", text="event_name 不能为空")]
        listen_code = _build_listen_code(namespace, system_name, event_name, side, callback_code)
        success, payload, is_tool_error = _exec_with_retry(listen_code, side)
        if is_tool_error:
            return _tool_error(payload)
        if success:
            text = payload.strip() or "执行成功，无输出"
            # 引擎层面判定未定义事件——算工具错（不是代码错），AI 能立即纠正事件名。
            if "FAIL undefined engine event" in text:
                return _tool_error("未定义的引擎事件：{}。事件名拼写错误、不存在，或该事件不在{}端"
                                   .format(event_name, side))
            return [TextContent(type="text", text=text)]
        return [TextContent(type="text", text=payload[:4000])]

    elif name == "get_event_log":
        # 遍历 __main__._db_event_states（多监听），每个监听器输出一段：标注行 + queue 内容。
        # 空段也输出标注行，让用户看到监听器存在但没触发。
        # 不知道当前 side，两端都试一遍——listen_event 注册的端会有 states，另一端会拿到 NOT_REGISTERED。
        for side in ("server", "client"):
            success, payload, is_tool_error = _exec_with_retry(
                'import __main__\n'
                'st = getattr(__main__, "_db_event_states", None)\n'
                'if not st:\n'
                '    print "NOT_REGISTERED"\n'
                'else:\n'
                '    for k in sorted(st):\n'
                '        print "=== " + k + " ==="\n'
                '        print chr(10).join(list(st[k]["queue"]))\n',
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

    elif name == "unlisten_event":
        event_name = arguments.get("event_name") or ""
        side = arguments.get("side", "server")
        namespace = arguments.get("namespace") or "Minecraft"
        system_name = arguments.get("system_name") or "Engine"
        unlisten_code = _build_unlisten_code(namespace, system_name, event_name or None, side)
        success, payload, is_tool_error = _exec_with_retry(unlisten_code, side)
        if is_tool_error:
            return _tool_error(payload)
        if success:
            text = payload.strip()
            if "NO_LISTENERS" in text:
                return [TextContent(type="text", text="该端没有注册任何事件监听器")]
            cancelled = re.search(r"CANCELLED (\d+)", text)
            count = int(cancelled.group(1)) if cancelled else 0
            if not count:
                # 没匹配到可取消的监听器不算工具错误，提示用户检查事件名
                return [TextContent(type="text", text="未找到事件{}的监听器".format(event_name))]
            message = "已取消{}个监听器".format(count)
            remaining = re.search(r"REMAINING (\d+)", text)
            if remaining:
                message += "，剩余{}个".format(remaining.group(1))
            return [TextContent(type="text", text=message)]
        return [TextContent(type="text", text=payload[:4000])]

    elif name == "hot_reload":
        side = arguments.get("side", "both")
        pkg = arguments.get("pkg")
        modules = arguments.get("modules") or []
        # 前置检测：复用 execute_code 的端口探测，游戏未启动/工具未加载时直接返回相同提示
        check_sides = ("client", "server") if side == "both" else (side,)
        for check_side in check_sides:
            port = db.CLIENT_PORT if check_side == "client" else db.SERVER_PORT
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            probe.settimeout(1.0)
            try:
                probe.connect(("127.0.0.1", port))
                probe.close()
            except (socket.error, socket.timeout):
                probe.close()
                return _tool_error(_diagnose_connection_failure(port))
        # hot_reload.py 跟 server.py 同项目，相对路径找
        script = BASE_DIR / "tools" / "hot_reload.py"
        if not script.is_file():
            return _tool_error("hot_reload.py脚本未找到：{}".format(script))
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
            with tempfile.NamedTemporaryFile(mode='w+b', delete=False) as _out_f, \
                 tempfile.NamedTemporaryFile(mode='w+b', delete=False) as _err_f:
                _out_path, _err_path = _out_f.name, _err_f.name
            with open(_out_path, 'w') as _o, open(_err_path, 'w') as _e:
                _proc = subprocess.Popen(cmd, stdout=_o, stderr=_e, stdin=subprocess.DEVNULL)
                try:
                    _proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    # 不 kill 会残留孤儿 py2 进程继续占用游戏端口，干扰下次重试
                    _proc.kill()
                    _proc.wait()
                    raise
            with open(_out_path, 'rb') as _f:
                _out = _f.read().decode('gbk', 'replace')
            with open(_err_path, 'rb') as _f:
                _err = _f.read().decode('gbk', 'replace')
            for _p in (_out_path, _err_path):
                try:
                    os.remove(_p)
                except OSError:
                    pass
        except subprocess.TimeoutExpired:
            return _tool_error("hot_reload执行超时（>5s），多半是游戏处于后台tick暂停导致连接卡死，请把游戏窗口切回前台再试")
        except Exception as e:
            return _tool_error("hot_reload执行失败：{}".format(e))
        # 脚本退出码非 0（有 failure）不算工具错——跟 execute_code 语义一致
        text = _out or ""
        if _err:
            text = (text + "\n---stderr---\n" + _err) if text else _err
        return [TextContent(type="text", text=text.strip() or "执行成功，无输出")]

    return [TextContent(type="text", text="未知工具：{}".format(name))]

def _kill_stale_instance():
    """单实例：杀掉上一个残留的 server.py 进程。

    ZCode 重启 MCP 时只 spawn 新进程、不关旧 stdin，导致旧 server 残留。
    本函数读 pid 锁文件，若上个进程还活着就 taskkill 干掉，再写自己的 pid。
    """
    lock = BASE_DIR / "server.pid"
    if lock.is_file():
        try:
            old_pid = int(lock.read_text(encoding="utf-8").strip())
            if old_pid != os.getpid():
                # 探测旧进程是否还活着
                kernel32 = ctypes.windll.kernel32
                handle = kernel32.OpenProcess(0x1000, False, old_pid)  # PROCESS_QUERY_LIMITED_INFORMATION
                if handle:
                    exit_code = ctypes.c_ulong()
                    kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
                    kernel32.CloseHandle(handle)
                    if exit_code.value == 259:  # STILL_ACTIVE
                        subprocess.run(["taskkill", "/F", "/PID", str(old_pid)],
                                       capture_output=True, timeout=5)
        except Exception:
            pass  # 锁文件损坏/进程已死，忽略
    lock.write_text(str(os.getpid()), encoding="utf-8")


async def _watch_parent_task():
    """监控父进程（ZCode），父进程退出时主动终止本进程。

    兜底 ZCode 异常退出不关闭 stdin 管道导致 server 进程残留的问题。
    正常情况下 stdin 关闭会让 server.run() 自然返回，此任务不介入。
    """
    kernel32 = ctypes.windll.kernel32
    parent_pid = os.getppid()
    while True:
        await asyncio.sleep(5)
        try:
            handle = kernel32.OpenProcess(0x1000, False, parent_pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                break  # 父进程已退出
            exit_code = ctypes.c_ulong()
            kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            kernel32.CloseHandle(handle)
            if exit_code.value != 259:  # STILL_ACTIVE
                break
        except Exception:
            break  # 探测异常也退出，避免僵死
    os._exit(1)


async def main():
    # 杀掉上一个残留的 server（ZCode 重启 MCP 时不杀旧的）
    _kill_stale_instance()
    # 启动父进程监控任务（兜底 ZCode 整体退出但 stdin 未关闭的情况）
    monitor_task = asyncio.create_task(_watch_parent_task())
    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())
    finally:
        monitor_task.cancel()

if __name__ == "__main__":
    asyncio.run(main())