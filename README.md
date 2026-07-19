# mod-debug-bridge

[![Python 2.7](https://img.shields.io/badge/Python-2.7-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/release/python-2718/)
[![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)](README.md)
[![by 7stars七星](https://img.shields.io/badge/by-7stars%E4%B8%83%E6%98%9F-00AEEF)](https://space.bilibili.com/379515917)
[![License](https://img.shields.io/github/license/sevenstars0/mod-debug-bridge)](LICENSE)

> 让你的大模型能够在游戏内执行代码、获取日志、帮你热重载——极大提升模组开发与修 bug 效率。

Minecraft 基岩版（网易版）mod 开发调试工具包。包含两部分：

1. **DebugBridge mod**：在游戏运行时通过 TCP 端口执行任意 Python 代码（`clientApi`/`serverApi` 全可用），读取运行时数据、验证 API 行为、排查 mod bug。
2. **热重载脚本 `hot_reload.py`**：改完 .py 文件后一行命令热重载，免退出游戏重启。**修复了官方 `xupdate.update` 不重载模块级常量/数据的 bug**。

适用于 MCStudio + 网易基岩版 1.18+（Python 2.7）mod 开发场景。

---

## 目录

- [快速开始](#快速开始)
- [DebugBridge mod](#debugbridge-mod)
  - [部署](#部署)
  - [运行时执行代码](#运行时执行代码)
  - [调试技巧](#调试技巧)
- [热重载 hot_reload.py](#热重载-hot_reloadpy)
  - [为什么不是官方热重载](#为什么不是官方热重载)
  - [用法](#用法)
  - [限制](#限制)
- [SKILL.md 说明](#skillmd-说明)
- [已知坑](#已知坑)
- [文件结构](#文件结构)

---

## 快速开始

### 1. 部署 DebugBridge mod

仓库的 `DebugBridge/` 目录已经是 MCStudio 可识别的工程结构，含完整的 `DebugBridgeB/`（行为包）和 `DebugBridgeR/`（资源包）：

```
DebugBridge/
├── DebugBridgeB/                  ← 行为包根，导入这个
│   ├── manifest.json
│   ├── entities/                  ← 空目录（MCStudio 标准行为包结构占位）
│   └── DebugBridge/
│       ├── __init__.py
│       ├── config.py              ← ExecListener + dbreload 函数
│       ├── clientSystem.py
│       ├── serverSystem.py
│       └── modMain.py
└── DebugBridgeR/                  ← 资源包根，导入这个（占位，DebugBridge 本身不需要资源）
    ├── manifest.json
    └── textures/                  ← 空目录占位
```

部署步骤：

1. clone 或下载本仓库
2. 打开 MCStudio → **基岩版组件** → 右上角 **本地导入** → 勾选 **使用文件夹导入**
3. 直接选择仓库里的 `DebugBridge/` 文件夹导入（MCStudio 会自动识别里面的 `DebugBridgeB` 行为包和 `DebugBridgeR` 资源包）

> 仓库里 `DebugBridgeB/manifest.json` 的 UUID 是固定的，如果你之前导入过其他 DebugBridge（或与现有 mod UUID 冲突），用 UUID 生成器重新生成 `header.uuid` 和 `modules.uuid` 即可。

### 2. 启用 DebugBridge + 启动游戏

1. 在 MCStudio 你的 mod 工程的 **开发测试** 界面，右上角 **使用功能组件** 里勾选 **DebugBridge**
2. 用 **运行** 或 **调试** 模式启动游戏进入存档。DebugBridge mod 会在客户端开 `14530`、服务端开 `14531` 端口

确认端口监听：

```bash
netstat -ano | grep "1453"
# 应该看到 14530 和 14531 都 LISTENING
```

没监听 = mod 没加载（检查是否在"使用功能组件"里勾选了 DebugBridge、检查导入是否成功）。

### 3. 执行代码

```bash
cd scripts/
/c/Python27/python.exe -B -c "
import debug_bridge_client as db

# 服务端：列玩家
r = db.exec_server('print repr(serverApi.GetPlayerList())')
print r['stdout'] if r['success'] else r['stderr']

# 客户端：读本地玩家坐标
r = db.exec_client('''
import client.extraClientApi as clientApi
pid = clientApi.GetLocalPlayerId()
pos = clientApi.GetEngineCompFactory().CreatePos(pid).GetPos()
print repr(pos)
''')
print r['stdout'] if r['success'] else r['stderr']
"
```

### 4. 热重载

改完 mod 的 .py 文件后：

```bash
python scripts/hot_reload.py
```

DebugBridge 启动时已扫一次磁盘作为基线，所以改完 .py 第一次调用就能扫到改动并重载（无需"先建基线"的两步流程）。

---

## DebugBridge mod

### 部署

见 [快速开始](#快速开始)。要点：

- **DebugBridge mod 要和你的 mod 行为包在同一存档激活**。
- **改完 DebugBridge 的代码（如 config.py）必须重启游戏**——ExecListener 在游戏启动时初始化一次。
- **DebugBridge 不要发布到正式版**。它开了两个无密码 TCP 端口，任意本地进程都能 exec，**生产环境是严重安全风险**。仅用于开发调试。

### 运行时执行代码

`scripts/debug_bridge_client.py` 提供 `exec_client(code)` / `exec_server(code)`：

```python
import debug_bridge_client as db

# 客户端进程（端口 14530）
r = db.exec_client('print "hello client"')
# 返回 {'success': True/False, 'stdout': '...', 'stderr': '...'}

# 服务端进程（端口 14531）
r = db.exec_server('print "hello server"')
```

exec 的 globals 是 system 模块的 globals，已注入了：

| 名字 | 含义 |
|---|---|
| `clientApi` / `serverApi` | extraClientApi / extraServerApi（自动 import 到对应端） |
| `CF` | `clientApi.GetEngineCompFactory()` |
| `levelId` | `clientApi.GetLevelId()` / `serverApi.GetLevelId()` |
| `dbreload` | 热重载函数（见下文） |

code 在 mod 进程内执行，**无白名单限制**，可以 import 已加载的任何模块。

### 调试技巧

#### 客户端 vs 服务端怎么选

| 需求 | 用什么 |
|------|--------|
| 服务端代码（读服务端方块/实体/NBT、调 serverApi） | `exec_server`（14531） |
| 客户端组件 API（如读方块实体 NBT） | `exec_client`（14530） |

#### AddTimer / 异步回调里的 print 收不到

执行窗口只捕获 **exec 同步执行期间** 的 stdout。`AddTimer(0, func)` 回调在下一帧执行，那时 exec 早已返回，回调 print 拿不到。

- 大部分 API（`PlayerDestroyBlock`、`SpawnItemToPlayerInv` 等）**同步生效**，紧跟一行读结果即可
- 确需等下一帧：**分两次 exec**——第一次触发，隔 1~2 秒第二次读结果
- **禁止 `time.sleep`**：会阻塞整个服务端 tick

#### Git Bash 中文 print 乱码

`print '挖掘前'` 在 Git Bash 输出乱码。调试输出用英文/数字/ascii 最稳妥，或用 `print repr(value)` 看原始值。

#### 方块操作必须传 dimensionId

`CreateBlockInfo(levelId)` 的 comp，`GetBlockNew(pos)` / `SetBlockNew(pos, dict)` **不传 dimensionId 会返回 None / 失败**：

```python
# 错：返回 None
comp.GetBlockNew((5,93,-21))

# 对：传玩家维度
dim = CF.CreateDimension(playerId).GetEntityDimensionId()
comp.GetBlockNew((5,93,-21), dim)
```

#### 玩家行为类 API 必须用 playerId 创建组件

`PlayerUseItemToPos`、`PlayerDestroyBlock` 等挂在 `CreateBlockInfo` 上。**必须用 `CreateBlockInfo(playerId)`**，用 `CreateBlockInfo(levelId)` 调这些 API 会返回 False（静默失败）：

```python
# 错：返回 False
comp = CF.CreateBlockInfo(LVID)
comp.PlayerUseItemToPos(pos, 2, 0, 1)

# 对：返回 True
comp = CF.CreateBlockInfo(playerId)
comp.PlayerUseItemToPos(pos, 2, 0, 1)
```

#### 监听事件拿事件参数

DebugBridge 只能捕获 exec 同步执行期间的 stdout。事件是异步的，想知道某操作触发了什么事件 / 参数是什么，用**全局列表 + 两次 exec**：

第 1 次 exec 注册监听器：
```python
import server.extraServerApi as serverApi
import __main__
EN, ESN = serverApi.GetEngineNamespace(), serverApi.GetEngineSystemName()
sys = serverApi.GetSystem('你的mod命名空间', '你的serverSystem名')
if not hasattr(__main__, '_eventLog'):
    __main__._eventLog = []
    def handler(args):
        __main__._eventLog.append({'blockName': args.get('blockName')})
    sys.ListenForEvent(EN, ESN, 'ServerItemUseOnEvent', sys, handler)
print 'READY'
```

第 2 次 exec（用户在游戏里触发事件后）：
```python
import __main__
print __main__._eventLog
```

---

## 热重载 hot_reload.py

### 为什么不是官方热重载

MCStudio IDE "点击日志窗口"触发的热重载调的是 `common.utils.xupdate.update`。这个函数有个 bug：

> reload 后遍历 `new_module.__dict__`，对没有 handler 的类型（str/int/list/dict/frozenset 等模块级常量），会把旧值塞回去。导致常量/数据永远拿不到新值。

实测：

| 类型 | 官方 xupdate.update | 本工具 dbreload |
|---|---|---|
| 函数（`def foo(): ...`） | ✅ 生效 | ✅ 生效 |
| 类方法 | ✅ 生效 | ✅ 生效 |
| 模块级 str/int 常量（`MAX = 100`） | ❌ 仍是旧值 | ✅ 生效 |
| 模块级 list/dict/frozenset | ❌ 仍是旧值 | ✅ 生效 |
| 模块对象身份 | 不变（`is` 比较仍为 True） | 不变 |
| 持有旧函数/类引用 | ✅ 仍能看到新代码 | ✅ 仍能看到新代码 |

`dbreload` 保留 xupdate 的"原地 setattr 函数/类 func_code"能力（让持有旧引用的代码也看到新代码），但对无 handler 类型不再覆盖。

### 用法

```bash
# 重载所有自上次调用以来改动过的 .py（默认双端都重载）
python scripts/hot_reload.py

# DebugBridge 启动时已建立基线，改完 .py 直接调一次即可重载

# 多个 mod 同时存在时，指定要操作的包
python scripts/hot_reload.py --pkg 你的包名

# 只重载指定模块（双端）
python scripts/hot_reload.py 你的包名.serverSystem

# 只重载一端
python scripts/hot_reload.py --client 你的包名.clientSystem
python scripts/hot_reload.py --server 你的包名.serverSystem
```

成功输出形如：
```
reloading 2 module(s) on client/server...
[OK] [OK] yourpkg.serverSystem
[OK] [OK] yourpkg.config
```

`[OK] [OK]` = 客户端 OK + 服务端 OK。

### 限制

热重载管不到这些场景，需要重启游戏：

- **改了类的基类 / 改了 `__metaclass__`**：dbreload 只替换 func_code 等属性，不重建继承关系
- **改了 mod 的 JSON 文件**（block.json / entity / UI / manifest / 任何 .json）：引擎加载时把 JSON 解析成内部数据结构，运行时不重新读
- **改了 `__init__.py`**：包的初始化文件，重载会触发整个包重新加载（甚至崩溃）
- 模块顶层代码有副作用（注册监听器、初始化全局状态）：reload 会重新执行顶层代码，可能重复注册。模块可定义 `__before_update__` / `__after_update__` / `__onreload__` 钩子做清理

---

## SKILL.md 说明

`SKILL.md` 是一份 **agent 通用的 skill 配置**（采用 [ZCode](https://zcode.z.ai/cn) 的 skill 格式，但内容是各 agent 框架通用的调试指南）。它定义了一个名为 **"游戏内执行代码"** 的 skill：

- 触发前提：游戏已启动 + 端口监听
- 提供调试技巧文档（监听事件、API 用法、常见陷阱）
- 规定改 mod JSON 文件后必须先让用户重启游戏
- 包含热重载工作流（一行命令 + JSON 重启规则）

文件本身是纯 Markdown + 顶部 YAML frontmatter，任何支持 skill/agent 加载方式的框架（ZCode、Claude Code、Cursor 等）都可以适配使用。ZCode 用户把 `SKILL.md` 复制到 `~/.agents/skills/游戏内执行代码/SKILL.md`，把 `scripts/` 复制到 `~/.agents/skills/游戏内执行代码/scripts/`。其他框架按各自的 skill 加载规则放置即可。

如果你只想用 DebugBridge mod 和热重载脚本，可以忽略 `SKILL.md`，只看本 README 即可。

---

## 已知坑

完整坑列表见 `scripts/hot_reload.py` 文件头的注释（共 8 个坑），简版：

1. **工作目录有多个 hash 副本**：只有当前激活的副本与运行时目录是 NTFS 硬链接，改错副本 reload 不生效（无报错）。用 `fsutil file queryfileid` 比对确认。
2. **模块的 `__file__` 是假的**：是模块名形式 `'pkg.mod'`，不是真实路径。运行时目录要通过 `sys.modules['pkg'].__path__` 查。
3. **引擎用自定义 McpImporter 加载代码**：优先 `.mcs`（加密字节码），其次 `.py`。整合包发布时通常只有 `.py`。
4. **编辑器写入操作可能破坏 NTFS 硬链接**：少数情况会断链，改完代码 reload 不生效时检查硬链接。
5. **改 JSON 必须重启游戏**（见上文限制）。
6. **热重载管不到类基类、`__metaclass__`、`__init__.py` 改动**。
7. **客户端和服务端 sys.modules 隔离**：双端共用模块要各 reload 一次（hot_reload.py 默认双端都调）。
8. **游戏处于后台时 DebugBridge 连接会卡死**：tick 暂停导致 socket 收不到响应。把游戏窗口切回前台即可恢复，无需重启。

---

## 文件结构

```
mod-debug-bridge/
├── README.md                       本文档
├── SKILL.md                        ZCode skill 配置（可选）
├── .gitignore
├── DebugBridge/                    可直接导入的 MCStudio 工程结构
│   ├── DebugBridgeB/               ← 行为包根（导入这个）
│   │   ├── manifest.json
│   │   ├── entities/               ← 空目录占位
│   │   └── DebugBridge/            ← mod 源码
│   │       ├── __init__.py
│   │       ├── config.py           ← ExecListener + dbreload 函数
│   │       ├── clientSystem.py     ← 客户端 system，监听 14530
│   │       ├── serverSystem.py     ← 服务端 system，监听 14531
│   │       └── modMain.py          ← Mod Binding
│   └── DebugBridgeR/               ← 资源包根（导入这个，占位）
│       ├── manifest.json
│       └── textures/               ← 空目录占位
└── scripts/                        外部调用脚本
    ├── debug_bridge_client.py      ← exec_client / exec_server
    └── hot_reload.py               ← 一行命令热重载
```

---

## 协议

[BSD 3-Clause License](LICENSE)
