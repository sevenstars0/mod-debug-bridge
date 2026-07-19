# -*- coding: utf-8 -*-
"""DebugBridge 外部客户端：连 mod 的 14530(客户端)/14531(服务端) 执行代码并拿回结果。"""
import socket, struct, json, sys

CLIENT_PORT = 14530
SERVER_PORT = 14531


def _to_unicode(code):
    # 统一转 unicode：json.dumps 对 unicode 不触发二次解码，避免 py2 str 含非 ASCII 字节时崩 UnicodeDecodeError。
    # Windows 中文环境经 Bash -c 传入的字节多为 UTF-8，少数为 GBK，两种都尝试。
    if isinstance(code, unicode):
        return code
    try:
        return code.decode('utf-8')
    except UnicodeDecodeError:
        return code.decode('gbk')


def _call(port, code):
    code = _to_unicode(code)
    s = socket.create_connection(('127.0.0.1', port), timeout=10.0)
    s.settimeout(30.0)
    try:
        payload = json.dumps({'id': 1, 'code': code}, ensure_ascii=False).encode('utf-8')
        s.sendall(struct.pack('!I', len(payload)) + payload)
        n = struct.unpack('!I', s.recv(4))[0]
        body = ''
        while len(body) < n:
            body += s.recv(n - len(body))
        return json.loads(body.decode('utf-8'))
    finally:
        s.close()


def exec_client(code):
    """在客户端 mod 进程执行（clientApi 全可用，无白名单限制）。"""
    return _call(CLIENT_PORT, code)


def exec_server(code):
    """在服务端 mod 进程执行（serverApi 全可用）—— 这是核心新能力。"""
    return _call(SERVER_PORT, code)


if __name__ == '__main__':
    target = exec_server if '-s' in sys.argv else exec_client
    r = target('print "hello from " + ("server" if %d == %d else "client")' % (SERVER_PORT, SERVER_PORT))
    print 'success:', r.get('success')
    print 'stdout:', r.get('stdout', '')
    print 'stderr:', r.get('stderr', '')
