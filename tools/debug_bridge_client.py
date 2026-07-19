# -*- coding: utf-8 -*-
"""DebugBridge MCP 客户端：连接游戏内 DebugBridge mod 执行 Python 代码。

协议（与 D:/mod-debug-bridge/scripts/debug_bridge_client.py 的 py2 版完全一致）：
  请求帧 = 4 字节大端长度 + JSON {"id":1, "code":...}（UTF-8）
  响应帧 = 4 字节大端长度 + JSON {"id","success","stdout","stderr"}

端口固定：客户端 14530，服务端 14531。mod 端实现见 DebugBridge/config.py。

兼容 py2/py3：py3 直接用 str（默认 unicode）；py2 调用方传 str 字面量时
（含非 ASCII 字节，如中文注释），_to_unicode 先 decode 成 unicode 再 json.dumps，
避免 ascii codec 报 UnicodeDecodeError。
"""
import json
import socket
import struct

CLIENT_PORT = 14530
SERVER_PORT = 14531

CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 30.0

try:
    _UNICODE_TYPE = unicode  # py2
except NameError:
    _UNICODE_TYPE = str      # py3


def _to_unicode(code):
    """py3 直接返回（str 即 unicode）；py2 把 str 字节串 decode 成 unicode。
    Windows 中文环境的字节多为 UTF-8，少数为 GBK，两种都尝试。"""
    if isinstance(code, _UNICODE_TYPE):
        return code
    try:
        return code.decode("utf-8")
    except UnicodeDecodeError:
        return code.decode("gbk", "replace")


def _call(port, code):
    """连 mod 端口发 code，返回 mod 端的响应 dict。
    dict 字段：success(bool) / stdout(str) / stderr(str)。
    连接/读超时直接抛 socket.error 或 socket.timeout，由调用方处理。"""
    code = _to_unicode(code)
    sock = socket.create_connection(("127.0.0.1", port), timeout=CONNECT_TIMEOUT)
    sock.settimeout(READ_TIMEOUT)
    try:
        payload = json.dumps({"id": 1, "code": code}, ensure_ascii=False).encode("utf-8")
        sock.sendall(struct.pack("!I", len(payload)) + payload)
        n = struct.unpack("!I", _recv_exact(sock, 4))[0]
        body = _recv_exact(sock, n)
        return json.loads(body.decode("utf-8"))
    finally:
        sock.close()


def _recv_exact(sock, n):
    """精确收 n 字节，对端提前关闭则抛 EOFError。"""
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise EOFError("socket closed before {} bytes received".format(n))
        buf += chunk
    return buf


def exec_client(code):
    """在客户端 mod 进程执行（clientApi 全可用）。"""
    return _call(CLIENT_PORT, code)


def exec_server(code):
    """在服务端 mod 进程执行（serverApi 全可用）。"""
    return _call(SERVER_PORT, code)
