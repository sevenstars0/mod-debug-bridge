# -*- coding: utf-8 -*-
import sys, socket, struct, json, StringIO, traceback, codecs

ModName = 'DebugBridge'
CLIENT_PORT = 14530
SERVER_PORT = 14531
EAGAIN = (11, 35, 10035)


def _to_unicode(s):
    """统一转 unicode：json.dumps 对 unicode 不触发二次解码。
    Windows 中文环境下字节多为 UTF-8，少数为 GBK，两种都尝试。"""
    if isinstance(s, unicode):
        return s
    try:
        return s.decode('utf-8')
    except UnicodeDecodeError:
        return s.decode('gbk', 'replace')


_CODING_TAGS = ('coding:', 'coding=')


def _strip_coding_decl(code):
    """exec compile(unicode_code) 不接受 coding declaration，把首两行的声明替换成空注释。"""
    lines = code.splitlines(True)
    for i in range(min(2, len(lines))):
        stripped = lines[i].lstrip()
        if not stripped.startswith('#'):
            break
        if any(tag in stripped for tag in _CODING_TAGS):
            lines[i] = '# \n'
    return ''.join(lines)


class ExecListener(object):
    """非阻塞 TCP：外部发 code，exec 后回传 stdout/stderr。
    帧: 4字节大端长度 + JSON。非阻塞靠 setblocking(False) + tick 内 recv 捕 EAGAIN。"""

    def __init__(self, port, label, exec_globals):
        self._port = port
        self._label = label
        self._g = exec_globals
        # 注入热重载函数到 exec globals，让外部 exec 能直接调用
        self._g['dbreload'] = dbreload
        self._g['dbreload_get_baseline'] = dbreload_get_baseline
        self._srv = None
        self._cli = None
        self._buf = ''
        # 启动时扫一次磁盘作为热重载基线，让 hot_reload.py 首次调用就能扫到改动
        # （不依赖 sys.modules，纯扫 behavior_packs 下所有 .py 文件）
        dbreload_scan_baseline()

    def start(self):
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.setblocking(False)
        try:
            self._srv.bind(('127.0.0.1', self._port))
            self._srv.listen(1)
            print '[%s] listen %d' % (self._label, self._port)
        except socket.error as e:
            print '[%s] bind fail: %s' % (self._label, e)
            self._srv = None

    def stop(self):
        self._close_cli()
        if self._srv:
            self._srv.close()
            self._srv = None

    def update(self):
        if not self._srv:
            return
        self._accept()
        if self._cli:
            self._recv()

    def _accept(self):
        try:
            sock, addr = self._srv.accept()
        except socket.error as e:
            if getattr(e, 'errno', e[0]) not in EAGAIN:
                print '[%s] accept: %s' % (self._label, e)
            return
        if self._cli:
            sock.close()
            return
        sock.setblocking(False)
        self._cli = sock
        self._buf = ''
        print '[%s] connected %s' % (self._label, addr)

    def _recv(self):
        try:
            data = self._cli.recv(65536)
        except socket.error as e:
            if getattr(e, 'errno', e[0]) in EAGAIN:
                return
            self._close_cli()
            return
        if not data:
            self._close_cli()
            return
        self._buf += data
        while len(self._buf) >= 4:
            n = struct.unpack('!I', self._buf[:4])[0]
            if len(self._buf) < 4 + n:
                return
            self._handle(self._buf[4:4 + n])
            self._buf = self._buf[4 + n:]

    def _handle(self, payload):
        try:
            msg = json.loads(payload.decode('utf-8'))
        except Exception as e:
            self._send({'id': None, 'success': False, 'stderr': str(e)})
            return
        buf = codecs.getwriter('utf-8')(StringIO.StringIO())
        old = sys.stdout
        success, stderr = True, ''
        try:
            sys.stdout = buf
            exec compile(_strip_coding_decl(msg['code']), '<debugbridge>', 'exec') in self._g
        except Exception:
            success, stderr = False, traceback.format_exc()
        finally:
            sys.stdout = old
        msg['success'] = success
        msg['stdout'] = _to_unicode(buf.getvalue())
        msg['stderr'] = _to_unicode(stderr)
        self._send(msg)

    def _send(self, msg):
        if not self._cli:
            return
        try:
            data = json.dumps(msg, ensure_ascii=False).encode('utf-8')
            self._cli.sendall(struct.pack('!I', len(data)) + data)
        except socket.error:
            self._close_cli()

    def _close_cli(self):
        if self._cli:
            self._cli.close()
            self._cli = None
            self._buf = ''


# ============ 热重载 ============
# 修复 common.utils.xupdate.update 的 bug：原版对没有 handler 的类型（str/list/dict/
# frozenset 等模块级常量），reload 后会把旧值塞回去，导致常量/数据
# 永远拿不到新值。dbreload 保留 xupdate 的"原地 setattr 函数/类对象"能力（让持有旧
# 引用的代码也能看到新代码），但对无 handler 类型不再覆盖，让常量/数据生效。
#
# 与 IDE 点击日志窗口的差异：
#   IDE → command_funcs_client.rl() → xupdate.update()    （常量不刷新）
#   这里 → dbreload()                                       （常量刷新）


def _db_get_xupdate():
    try:
        import common.utils.xupdate as x
        return x
    except Exception:
        return None


def dbreload(module_name, is_update_data=False):
    """热重载单个模块：函数/类/常量/数据全部刷新。
    返回 (ok, msg)。ok=False 时 msg 是错误描述。"""
    import sys
    module_name = module_name.replace('/', '.')
    if module_name.endswith('.py'):
        module_name = module_name[:-3]

    module = sys.modules.get(module_name)
    if not module:
        # 首次 import，走 xupdate 的首次加载流程（含 __first_import__ 钩子）
        x = _db_get_xupdate()
        if x is None:
            return False, 'xupdate not available'
        try:
            x.update(module_name, is_update_data)
            return True, 'first import: %s' % module_name
        except Exception:
            import traceback
            return False, traceback.format_exc()

    x = _db_get_xupdate()
    handlers = x.get_valid_handlers(is_update_data) if x else {}

    # 备份旧属性（用于 reload 后判断类型是否变化、给 handler 用）
    old_dict = dict(module.__dict__)
    # 调 xupdate 的 before 钩子
    if x:
        x._call_module_func(module, '__before_update__')

    try:
        reload(module)
    except Exception:
        # reload 失败时回滚 __dict__，避免半残状态
        for k, v in old_dict.items():
            module.__dict__[k] = v
        import traceback
        return False, traceback.format_exc()

    # 把新函数/类的 func_code setattr 到旧对象上（保留旧引用有效性）；
    # 对无 handler 的类型（常量/数据）保留 reload 的新值——这是与 xupdate.update 的关键差异。
    for key, newobj in list(module.__dict__.items()):
        if key not in old_dict:
            continue   # 新增属性，reload 已设置
        oldobj = old_dict[key]
        if newobj is oldobj:
            continue
        if type(newobj) != type(oldobj):
            continue   # 类型变了，保留 reload 的新值
        handler = handlers.get(type(newobj))
        if handler is None:
            continue   # 无 handler 类型（常量/数据）—— 保留 reload 的新值
        try:
            handler(oldobj, newobj, 2)
            module.__dict__[key] = oldobj   # 保留旧对象引用有效性
        except Exception as e:
            print '[dbreload] handler fail for %s: %s' % (key, e)

    # 调 xupdate 的 after / onreload 钩子
    if x:
        x._call_module_func(module, '__after_update__')
        x._call_module_func(module, '__onreload__', dict(module.__dict__))
    return True, 'reloaded: %s' % module_name


# ============ 热重载基线扫描 ============
# ExecListener 启动时扫一次磁盘，记录所有 .py 的 mtime 作为基线。
# 这样 hot_reload.py 首次调用就能比对出"自 mod 启动以来改过的文件"，
# 不需要"先调用一次建基线、改文件、再调用一次"的两步流程。
#
# 全局字典：{绝对路径: mtime}
# 注入到 exec globals 后，hot_reload.py 通过 exec 拿到这个字典。

_DB_BASELINE = {}


def _db_find_behavior_packs_root():
    """找运行时 behavior_packs 根目录。
    通过 sys.modules['DebugBridge'].__path__ 反推：
      DebugBridge.__path__ = [.../behavior_packs/<工程名>B/DebugBridge/]
      → 往上 3 级 = .../behavior_packs/
    """
    import sys, os
    mod = sys.modules.get('DebugBridge')
    if mod is None or not getattr(mod, '__path__', None):
        return None
    pkg_path = mod.__path__[0].replace('\\', '/')
    # pkg_path 形如 C:/.../behavior_packs/DebugBridgeB/DebugBridge
    # 往上找包含 'behavior_packs' 的祖先
    parts = pkg_path.split('/')
    for i in range(len(parts) - 1, -1, -1):
        if parts[i].lower() == 'behavior_packs':
            return '/'.join(parts[:i + 1])
    return None


def dbreload_scan_baseline():
    """扫 behavior_packs 下所有 .py 文件，记录 mtime 到 _DB_BASELINE。
    重复调用会刷新基线（一般不需要）。"""
    import os
    global _DB_BASELINE
    root = _db_find_behavior_packs_root()
    if not root or not os.path.isdir(root):
        return 0
    baseline = {}
    for dirpath, dirnames, filenames in os.walk(root):
        # 不递归进 __pycache__
        dirnames[:] = [d for d in dirnames if d != '__pycache__']
        for fname in filenames:
            if not fname.endswith('.py'):
                continue
            if fname.endswith('.bak') or fname.endswith('.tmp'):
                continue
            abs_path = os.path.join(dirpath, fname).replace('\\', '/')
            try:
                baseline[abs_path] = os.path.getmtime(abs_path)
            except OSError:
                pass
    _DB_BASELINE = baseline
    return len(baseline)


def dbreload_get_baseline():
    """外部 exec 调用：返回基线 dict 的拷贝。
    第一次 ExecListener 启动时已扫描，所以基线始终可用。"""
    return dict(_DB_BASELINE)


