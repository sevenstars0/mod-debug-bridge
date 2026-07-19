# -*- coding: utf-8 -*-
"""一行命令热重载整合包改动文件，等同"IDE 点击日志窗口"+ 修复常量不刷新的 bug。

用法（<pkg> 替换为你的 mod 顶层包名，如 chainScripts、myMod 等）：
    # 重载所有自上次调用以来改动过的 .py 文件（默认双端都重载）
    python hot_reload.py

    # 多个 mod 同时存在时，指定要操作的包
    python hot_reload.py --pkg chainScripts

    # 只重载指定模块（双端）
    python hot_reload.py chainScripts.chainServerSystem

    # 多个模块
    python hot_reload.py chainScripts.chainServerSystem chainScripts.chainconfig

    # 只重载一端
    python hot_reload.py --client chainScripts.chainClientSystem
    python hot_reload.py --server chainScripts.chainServerSystem

底层：
    - DebugBridge 进程注入了 dbreload(name) 函数（见 DebugBridge/config.py）。
    - dbreload 是 common.utils.xupdate.update 的修复版：
        * xupdate 的 bug：对没有 handler 的类型（str/list/dict/frozenset 等模块级
          常量），reload 后会把旧值塞回去，导致常量/数据永远拿不到新值。
        * dbreload 保留 xupdate 的"原地 setattr 函数/类 func_code"能力（让持有旧
          引用的代码也能看到新代码），但对无 handler 类型不再覆盖，让常量/数据生效。
    - 客户端进程 (14530) 和服务端进程 (14531) 的 sys.modules 是隔离的，必须各调
      一次才能让双端都生效。

==============================================================================
调试过程踩过的坑（保留备忘，便于排查异常情况）
==============================================================================

【坑 1】工作目录有多个历史 hash 副本，只有激活的才与运行时硬链接
    C:/MCStudioDownload/work/<邮箱>/Cpp/AddOn/ 下每个 hash 是同一份 mod 的一个快照，
    只有"当前激活的"那个目录会与运行时目录（C:/Users/<用户名>/AppData/Roaming/MinecraftPE_
    Netease/games/com.netease/behavior_packs/<包名>/）做成 NTFS 硬链接。改错副本时
    reload 读到的还是旧文件，**无报错但代码不生效**，极难发现。
    确认方法（fsutil 比 inode/Python os.stat 准）：
        powershell -NoProfile -Command "fsutil file queryfileid '<工作目录文件>'"
        powershell -NoProfile -Command "fsutil file queryfileid '<运行时文件>'"
        两个 ID 相同 → 硬链接 OK；不同 → 改错副本了。
    本脚本默认扫运行时目录，不踩这个坑。

【坑 2】mod 模块的 __file__ 是假的
    游戏进程里 sys.modules['chainScripts.chainconfig'].__file__ 不是真实路径，而是
    'chainScripts.chainconfig' 这种模块名形式。__path__ 才指向真实目录，但只到包根
    （'.../behavior_packs/chainb/'），不含文件名。所以本脚本扫磁盘时不依赖进程里的
    __file__，直接 walk 运行时目录的 .py 文件。

【坑 3】模块加载用的是引擎自定义 McpImporter，不是标准 Python importer
    sys.path_importer_cache 里全是 McpImporter 实例。它优先读 .mcs（加密字节码），
    其次读 .py（compile 后执行）。整合包发布时通常只有 .py，所以热重载读 .py 正常。

【坑 4】编辑器 / 工具的写入操作可能破坏 NTFS 硬链接
    "写 .tmp + rename"模式（VSCode、JetBrains、ZCode Edit 工具）通常保留硬链接。
    但某些操作（如部分 IDE 的"格式化全部"、外部 cp 覆盖）会断链。断链后改工作目录
    不再同步到运行时目录。每次 reload 不生效时先 fsutil 确认硬链接。

【坑 5】改了 mod 的 JSON 文件必须重启游戏
    .py 代码改完调本脚本即可热重载；但 JSON 文件（block.json / entity JSON / UI JSON
    / manifest.json / 行为包里任何 .json）改完必须重启游戏，热重载管不到 JSON——
    引擎在加载时把 JSON 解析成内部数据结构，运行时不重新读。skill 已规定改 JSON 后
    要 AskUserQuestion 提醒用户重启并提供"已重启"选项。

【坑 6】热重载管不到这些场景
    - 改类的基类 / 改 __metaclass__：dbreload 只替换 func_code 等属性，不重建继承
      关系，需要重启游戏。
    - 新增 import 没法触发依赖链：A 引用了 B 的新函数，光重载 A 不够，要连 B 一起。
      本脚本默认扫所有改过的 .py，能覆盖这种情况。
    - 模块顶层代码副作用（注册监听器、初始化全局状态）：reload 会重新执行顶层代码，
      可能重复注册。模块可定义 __before_update__ / __after_update__ / __onreload__
      钩子，dbreload 会自动调用做清理/重新初始化。

【坑 7】客户端 vs 服务端要各 reload 一次
    客户端进程和服务端进程的 sys.modules 完全隔离。改 chainconfig.py 这种双端共用
    的模块时，必须客户端 (14530) 和服务端 (14531) 各调一次 dbreload。本脚本默认双端
    都调；改单端专属文件时加 --client / --server 节省时间。

【坑 8】游戏处于后台时，DebugBridge 连接会卡死
    DebugBridge 的 ExecListener.update() 挂在 system 的 Update() tick 里驱动——游戏
    切到后台（窗口最小化 / 失焦 / 切到其他应用）时客户端 tick 暂停，socket 收不到新
    连接也发不出响应。具体表现：
        - netstat 看到端口仍 LISTENING，但有连接卡在 CLOSE_WAIT / FIN_WAIT_2
        - 新连接 socket.error 10061（连接被拒）或 10054（连接被重置）或 timeout
    解决：把游戏窗口切回前台（不需要重启游戏），等待几秒让 tick 推进状态机，连接自
    动释放后即可正常调用。本脚本已加重试（_dbreload_one_side 的 retries=2 + 退避），
    轻微卡顿能自愈，严重卡死时仍需手动切前台。
==============================================================================
"""
import os
import sys
import json

# skill scripts/ 目录下
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import debug_bridge_client as db

# 状态文件：记录上次扫描时各 .py 文件的 mtime，本次扫描比对找改动
STATE_FILE = os.path.join(HERE, '.hot_reload_state.json')

# 运行时 mods 根目录（含 mod 顶层包目录的那层）。整合包标准布局：
#   <mods_root>/<pkg_name>/<xxx>System.py
# 不传参时自动从服务端 sys.modules 找 behavior_packs 下的顶层包推断。
DEFAULT_MODS_ROOT = None


def _discover_mod_roots(prefer_pkg=None):
    """从服务端进程找所有用户的 mod 包根目录。
    返回 [(pkg_name, mods_root), ...]，每个 mod 一个条目。
    prefer_pkg 指定时只返回该包（找不到返回空列表）。"""
    code = (
        "import sys, os\n"
        "result = []\n"
        "for name, mod in sys.modules.items():\n"
        "    if mod is None: continue\n"
        "    paths = getattr(mod, '__path__', None)\n"
        "    if not paths: continue\n"
        "    if '.' in name: continue   # 只看顶层包\n"
        "    if name == 'DebugBridge': continue\n"
        "    p = paths[0].replace('\\\\', '/')\n"
        "    if 'behavior_packs' not in p: continue\n"
        "    result.append((name, os.path.dirname(p)))\n"
        "print repr(result)\n"
    )
    try:
        r = db.exec_server(code)
    except Exception:
        return []
    if not r['success']:
        return []
    import ast
    try:
        candidates = ast.literal_eval(r['stdout'].strip().splitlines()[-1])
    except (ValueError, IndexError, SyntaxError):
        return []
    if prefer_pkg:
        return [(n, root) for n, root in candidates if n == prefer_pkg]
    return candidates


def _discover_mods_root(prefer_pkg=None):
    """兼容旧接口：返回单个 mods_root。多包场景下应改用 _discover_mod_roots。"""
    roots = _discover_mod_roots(prefer_pkg)
    return roots[0][1] if roots else None


def _walk_py_files(mods_root):
    """枚举 mods_root 下所有 .py 文件，返回 [(abs_path, module_name), ...]。
    module_name 用相对路径转（chainScripts/chainServerSystem.py → chainScripts.chainServerSystem）。
    忽略 __pycache__、.bak、.tmp、以 _ 开头的临时文件、__init__.py（属于父包不单独重载）。"""
    result = []
    for dirpath, dirnames, filenames in os.walk(mods_root):
        # 不递归进 __pycache__
        dirnames[:] = [d for d in dirnames if d != '__pycache__']
        for fname in filenames:
            if not fname.endswith('.py'):
                continue
            # 忽略备份/临时文件（不应作为模块重载）
            if fname.endswith('.bak') or fname.endswith('.tmp'):
                continue
            # 忽略 _ 开头的临时模块（_rltest.py 这种调试文件）
            if fname.startswith('_'):
                continue
            # __init__.py 是包的初始化文件，重载会触发整个包重新加载（甚至崩溃），
            # 不应作为独立模块重载——它的改动需要重启游戏
            if fname == '__init__.py':
                continue
            abs_path = os.path.join(dirpath, fname).replace('\\', '/')
            rel = os.path.relpath(abs_path, mods_root)
            # Windows 路径分隔符统一替换
            rel = rel.replace('\\', '/').replace(os.sep, '/')
            module_name = rel[:-3].replace('/', '.')   # 去 .py 后缀，斜杠转点
            result.append((abs_path, module_name))
    return result


def _load_state():
    if not os.path.isfile(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    except (ValueError, IOError):
        return {}


def _fetch_mod_baseline():
    """从 mod 端取启动时扫描的基线（mod 启动时扫一次磁盘）。
    用于首次调用时避免"先建基线再 reload"的两步流程。
    返回 {abs_path: mtime}，失败返回空 dict。
    紧接 _discover_mod_roots 的调用可能失败：ExecListener 同一时刻只接 1 个连接
    （config.py 的 if self._cli: sock.close()），上次连接的 _cli 要等下一次 tick 的
    _recv 返回空才清除；新连接若赶在清除前到达会被直接拒绝（10061/10054）。
    退避重试是给 tick 留时间推进到 _close_cli，与 TIME_WAIT 无关。"""
    import ast, time
    for attempt in range(3):
        try:
            r = db.exec_server('print repr(dbreload_get_baseline())')
        except Exception:
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
                continue
            return {}
        if not r['success']:
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
                continue
            return {}
        try:
            return ast.literal_eval(r['stdout'].strip().splitlines()[-1])
        except (ValueError, IndexError, SyntaxError):
            return {}
    return {}


def _save_state(state):
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f)
    except IOError:
        pass


def _scan_mods(mods_root, old_state, new_state):
    """扫 mods_root 下所有 .py 文件，把 mtime 写入 new_state，返回改过的 module_name 列表。
    old_state/new_state 由调用方维护，支持多 mod 包共用同一份状态。"""
    changed = []
    for abs_path, module_name in _walk_py_files(mods_root):
        try:
            mtime = os.path.getmtime(abs_path)
        except OSError:
            continue
        new_state[abs_path] = mtime
        if old_state.get(abs_path) != mtime:
            changed.append(module_name)
    return changed


def _find_changed_modules(mods_root):
    """单 mod 包场景：扫 mods_root 所有 .py，与状态文件对比，返回改过的 module_name 列表。
    首次调用（状态文件不存在）从 mod 端取启动时扫描的基线作为对比基准。"""
    old_state = _load_state()
    if not old_state:
        old_state = _fetch_mod_baseline()
    new_state = {}
    changed = _scan_mods(mods_root, old_state, new_state)
    _save_state(new_state)
    return changed


def _find_changed_modules_multi(mods_roots):
    """多 mod 包场景：扫所有 mods_root，共享一份状态文件。
    mods_roots: [mods_root, ...]
    首次调用（状态文件不存在）从 mod 端取启动时扫描的基线作为对比基准，
    这样用户改完代码第一次调用就能 reload（不需要"先建基线"的两步流程）。"""
    old_state = _load_state()
    if not old_state:
        # 首次调用：从 mod 端取启动时基线
        old_state = _fetch_mod_baseline()
    new_state = {}
    changed = []
    for mods_root in mods_roots:
        changed.extend(_scan_mods(mods_root, old_state, new_state))
    _save_state(new_state)
    return changed


def _dbreload_one_side(exec_func, label, module_name, retries=2):
    """在一端调 dbreload，返回 (ok, info_str)。
    单个模块失败（包括 socket 断开、reload 触发崩溃）不应影响其他模块。
    连接被拒（10061/10054）多数是上一调用的 _cli 尚未被 ExecListener 清除（见
    _fetch_mod_baseline 注释），tick 推进后即恢复，故失败退避重试。"""
    # 用 repr 防模块名里的特殊字符
    code = "ok, msg = dbreload(%r)\nprint 'OK' if ok else 'FAIL', msg" % module_name
    import time
    last_err = None
    for attempt in range(retries + 1):
        try:
            r = exec_func(code)
        except Exception as e:
            last_err = str(e)[:60]
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))   # 退避：0.5s, 1s
                continue
            return False, '%s: connection lost (%s)' % (label, last_err)
        if not r['success']:
            err = r.get('stderr', '').strip().splitlines()
            last = err[-1] if err else 'unknown error'
            return False, '%s: %s' % (label, last[:80])
        out = r['stdout'].strip()
        first_line = out.splitlines()[0] if out else ''
        return out.startswith('OK'), '%s: %s' % (label, first_line)
    return False, '%s: retries exhausted (%s)' % (label, last_err)


def reload_modules(module_names, sides=('client', 'server')):
    """对指定模块列表，在指定端各调一次 dbreload。"""
    exec_funcs = []
    if 'client' in sides:
        exec_funcs.append((db.exec_client, 'client'))
    if 'server' in sides:
        exec_funcs.append((db.exec_server, 'server'))

    results = []   # [(module_name, [(ok, info), ...]), ...]
    for name in module_names:
        per_side = []
        for exec_func, label in exec_funcs:
            ok, info = _dbreload_one_side(exec_func, label, name)
            per_side.append((ok, info))
        results.append((name, per_side))
    return results


def _format_results(results):
    lines = []
    for name, per_side in results:
        statuses = ' '.join('[%s]' % ('OK' if ok else 'FAIL') for ok, _ in per_side)
        lines.append('%s %s' % (statuses, name))
        for ok, info in per_side:
            if not ok:
                lines.append('  ' + info)
    return '\n'.join(lines)


def main(argv):
    # 解析参数
    sides = ('client', 'server')
    prefer_pkg = None
    explicit_modules = []
    args = argv[1:]
    if '--client' in args:
        sides = ('client',)
        args = [a for a in args if a != '--client']
    if '--server' in args:
        sides = ('server',)
        args = [a for a in args if a != '--server']
    # --pkg <name> 指定 mod 顶层包名（多个 mod 时强制选某个）
    if '--pkg' in args:
        i = args.index('--pkg')
        if i + 1 < len(args):
            prefer_pkg = args[i + 1]
            args = args[:i] + args[i+2:]
    explicit_modules = [a for a in args if not a.startswith('-')]

    # 确定要重载的模块
    if explicit_modules:
        modules = explicit_modules
    else:
        # 自动扫改动：找所有用户的 mod 包，共享一份状态
        if DEFAULT_MODS_ROOT:
            roots = [(None, DEFAULT_MODS_ROOT)]
        else:
            roots = _discover_mod_roots(prefer_pkg)
        if not roots:
            print 'FAIL: cannot discover any mod package'
            print '      no behavior_packs/<pkg> with __path__ in sys.modules?'
            print '      pass module names explicitly: python hot_reload.py <pkg>.xxx'
            return 1
        # 同一目录下可能有多个 mod 包（如 chainScripts + simpleBindParticle 都在 chainb/），
        # 去重避免重复扫描
        seen = set()
        mods_roots = []
        for _, r in roots:
            if os.path.isdir(r) and r not in seen:
                seen.add(r)
                mods_roots.append(r)
        modules = _find_changed_modules_multi(mods_roots)
        if not modules:
            print 'no .py changed since mod start (state: %s)' % STATE_FILE
            return 0

    print 'reloading %d module(s) on %s...' % (len(modules), '/'.join(sides))
    results = reload_modules(modules, sides)
    print _format_results(results)

    # 汇总
    failed = sum(1 for _, per_side in results for ok, _ in per_side if not ok)
    if failed:
        print '%d failure(s)' % failed
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
