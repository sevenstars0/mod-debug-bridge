---
name: 游戏内执行代码
description: >
  【前提】游戏已启动且 DebugBridge 端口可用（netstat 确认 14530 客户端 / 14531 服务端监听）时才加载。游戏没开/端口没监听时**不要加载**——大部分编码场景用 modsdk-mcp-server 查资料就够，本 skill 只在需要运行时数据或实测验证时才用。DebugBridge mod 直接 exec 任意 Python，调 clientApi/serverApi、查方块实体 NBT、跑服务端逻辑、验证 mod 行为、热重载 mod 代码免重启。适用：需要查运行时数据（方块/实体/NBT/背包/坐标）、验证某 API 的实际返回、跑服务端逻辑测试、排查端口连接问题、改完代码后热重载。
---

通过一个调试 mod（DebugBridge），在游戏运行时执行任意 Python 代码并拿回 stdout/stderr。客户端开 `14530`、服务端开 `14531`，外部 TCP 连进去发 code，mod `exec` 后回传结果。**无白名单限制，`clientApi`/`serverApi` 全可用**。

## 触发前提（不满足不要用）

1. **游戏已启动**：`tasklist | grep -i Minecraft.Windows`
2. **DebugBridge mod 已部署**：mod 源码在调试工程的行为包里，实际运行环境路径（改这里才生效）：
   ```
   C:/MCStudioDownload/work/<你的MCStudio账号>/Cpp/AddOn/<工程hash>/DebugBridgeB/DebugBridge/
   ```
   4 个文件：`config.py`（ExecListener 类 + 端口常量）、`modMain.py`、`clientSystem.py`、`serverSystem.py`。
3. **端口监听确认**：`netstat -ano | grep -E "14530|14531"` 两个端口都 LISTENING 才行。
   - 没监听 → 告诉用户：mod 没加载，或不是 MCStudio 运行/调试模式进存档。

## 客户端库

`scripts/debug_bridge_client.py`（本 skill 目录下）提供 `exec_client(code)` / `exec_server(code)`，各自开关一个 socket，返回 `{'success', 'stdout', 'stderr'}`。

```bash
cd "<skill 目录>/scripts"
/c/Python27/python.exe -B -c "
import debug_bridge_client as db
# 客户端：读玩家坐标
r = db.exec_client('''
import client.extraClientApi as clientApi
pid = clientApi.GetLocalPlayerId()
pos = clientApi.GetEngineCompFactory().CreatePos(pid).GetPos()
print repr(pos)
''')
print r['stdout'] if r['success'] else r['stderr']
# 服务端：列玩家
r = db.exec_server('print repr(serverApi.GetPlayerList())')
print r['stdout'] if r['success'] else r['stderr']
"
```

注意：`exec_server` 的 code 里直接用 `serverApi`（`import server.extraServerApi as serverApi`）；`exec_client` 里用 `clientApi`。code 在 mod 的 globals 里执行，无任何限制，可 import 已加载模块。

## 客户端 vs 服务端怎么选

| 需求 | 用什么 |
|------|--------|
| 服务端代码（读服务端方块/实体/NBT、调 serverApi、`CreateBlockState`/`GetBlockBasicInfo` 等客户端没有的方法） | `exec_server`（端口 14531） |
| 客户端组件 API（`CreateBlockInfo.GetBlockEntityData` 读方块实体 NBT 等） | `exec_client`（端口 14530） |

## mod 结构（实际路径见上方 AddOn）

- `config.py` — `ModName` + 端口常量 + `ExecListener` 类（非阻塞 TCP，tick 内 recv 捕 EAGAIN，不依赖 select）
- `modMain.py` — Mod Binding，注册 ClientSystem/ServerSystem
- `clientSystem.py` — 监听 `14530`，`OnScriptTickClient` 驱动，exec 在 clientSystem globals（`clientApi`/`CF`/`levelId` 可用）
- `serverSystem.py` — 监听 `14531`，`OnScriptTickServer` 驱动，exec 在 serverSystem globals（`serverApi`/`CF`/`levelId` 可用）

协议：`4字节大端长度 + JSON {"id","code"}` → `{"id","success","stdout","stderr"}`。

## 运行环境

- 本地调用用 **`/c/Python27/python.exe -B`**（py2.7，与游戏一致；`-B` 防 pyc 污染）。

## 调试技巧与陷阱

### AddTimer / 异步回调里的 print 收不到

执行窗口只捕获 **exec 同步执行期间** 的 stdout。`AddTimer(0, func)` 或 `AddTimer(delay, func)` 的回调在**下一帧**执行，那时 exec 早已返回，回调里的 `print` 输出拿不到。

**错误写法**（拿不到结果）：
```python
Game.AddTimer(0, lambda: print '挖掘后耐久=%s' % itemComp.GetPlayerItem(2,0,True)['durability'])
```

**替代方案**（按场景选）：
- 大部分 API（`PlayerDestroyBlock`、`SetInvItemDurability`、`SpawnItemToPlayerInv` 等）是**同步生效**的，exec 内紧跟一行读结果即可，不要加 AddTimer。
- 确需等下一帧的（比如等引擎同步状态）：**分两次 exec**——第一次触发操作，隔 1~2 秒后第二次 exec 读结果。两次调用各自独立连 socket，不依赖回调。
- **禁止 `time.sleep`**：会阻塞整个服务端 tick，游戏卡死。

### 游戏处于后台时 DebugBridge 连接会卡死

DebugBridge 的 `ExecListener.update()` 挂在 system 的 `Update()` tick 里驱动。游戏切到后台（窗口最小化 / 失焦 / 切到其他应用）时客户端 tick 暂停，socket 收不到新连接也发不出响应。具体表现：

- `netstat` 看到端口仍 LISTENING，但有连接卡在 `CLOSE_WAIT` / `FIN_WAIT_2`
- 新连接报 `socket.error 10061`（连接被拒）/ `10054`（连接被重置）/ `timeout`

**解决**：把游戏窗口切回前台（**不需要重启游戏**），等几秒让 tick 推进状态机、释放卡住的连接，再调用 exec 即可。hot_reload.py 自带重试（`retries=2 + 退避`），轻微卡顿能自愈，严重卡死时需要手动切前台。

### Git Bash 里中文 print 会乱码

`print '挖掘前'` 在 Git Bash 输出乱码（GBK/UTF-8 编码冲突）。调试输出**用英文/数字/ascii**最稳妥，或者 `print repr(value)` 看原始值。需要确认中文内容时优先读字段值（如 `itemName` 字段）而非自己拼中文。

### 工具/物品调试要点

- `GetPlayerItem(playerId=0表示自己/2表示carried槽, slotId, getUserData=True)` 返回的字典**天然带 `durability` 字段**（当前剩余耐久）。
- 耐久对应 NBT 的 `Damage` 字段（`{'__type__':3, '__value__':N}`，N 是已消耗量，`durability = maxDurability - Damage`）。
- **改 Damage 后用 `SpawnItemToPlayerInv` 覆写会失败**（返回 False）：因为读出的字典带 `durability`，和 `userData.Damage` 冲突。要先 `del item['durability']` 再写，或者直接用 `SetInvItemDurability(slot, value)`（推荐，内部会同步更新 Damage）。
- 想生成一把消耗过耐久的物品：生成时 `userData` 带 `{'Damage': {'__type__': 3, '__value__': N}}` 即可，`SpawnItemToPlayerInv` 生成新物品时认这个字段（只是**覆写已有物品**时不认）。

### 验证 mod 行为的标准流程

定位"某 API / 某机制是否生效"时，用**最小复现 + 对照**：
1. 生成/设置初始状态，`print` 记录前值（如耐久、NBT）
2. 执行被测操作（如 `PlayerDestroyBlock`）
3. 同步读后值，`print` 对比
4. 只改一个变量（如换 NBT 类型、加/删字段），重复，确认变量与结果的因果关系

### 方块操作必须传 dimensionId

`CreateBlockInfo(levelId)` 创建的 comp，`GetBlockNew(pos)` / `SetBlockNew(pos, dict)` **不传 dimensionId 会返回 None / 失败**。这是最常见的"明明调了却没效果"原因。

```python
# 错：返回 None
comp.GetBlockNew((5,93,-21))
comp.SetBlockNew((5,93,-21), {'name':'minecraft:dirt','aux':0})

# 对：用玩家维度（CreateDimension(pid).GetEntityDimensionId() 或 args['dimensionId']）
dim = CF.CreateDimension(playerId).GetEntityDimensionId()
comp.GetBlockNew((5,93,-21), dim)
comp.SetBlockNew((5,93,-21), {'name':'minecraft:dirt','aux':0}, 1, dim)  # 第3参数oldBlockHandling
```

`SetBlockNew` 参数顺序：`pos, blockDict, oldBlockHandling(0=保留/1=替换销毁), dimensionId`。要强制替换已有方块用 `oldBlockHandling=1`。

### 监听事件并获取事件消息（核心调试模式）

DebugBridge 只能捕获 **exec 同步执行期间** 的 stdout。而事件是异步的——当玩家在游戏里操作触发事件时，exec 早已返回。所以"想知道某操作触发了什么事件、事件参数是什么"，不能靠 exec 里 print，要用**全局列表存 + 两次 exec** 的模式：

**原理**：第1次 exec 注册一个监听器，把事件参数存到 `__main__` 的全局变量里（跨 exec 持久存活）；让用户在游戏里操作触发事件；第2次 exec 读全局变量拿结果。

**第1次 exec —— 注册监听器**：

```python
import server.extraServerApi as serverApi
import __main__
EN, ESN = serverApi.GetEngineNamespace(), serverApi.GetEngineSystemName()
# 关键：用目标 mod 已注册的 system 实例来 ListenForEvent
# 用 serverApi.GetSystem(EN, ESN) 会返回 None，必须用具体的 mod 命名空间
sys = serverApi.GetSystem('chainMod', 'chainServerSystem')  # 换成目标 mod 的命名空间/system名
if not hasattr(__main__, '_eventLog'):
    __main__._eventLog = []  # 全局列表，跨 exec 存活
    def handler(args):
        # 把关心的字段存下来，别存整个 args（可能含不可序列化对象）
        __main__._eventLog.append({'blockName': args.get('blockName'), 'item': args.get('itemDict',{}).get('newItemName')})
    sys.ListenForEvent(EN, ESN, 'ServerItemUseOnEvent', sys, handler)
    print 'READY'  # 确认注册成功
```

**第2次 exec —— 读结果**（用户操作之后）：

```python
import __main__
print __main__._eventLog
```

**要点**：
- `ListenForEvent` 第4个参数（`self`/instance）要传那个 system 实例本身，保持引用防 GC。
- `hasattr` 守卫防重复注册（多次 exec 第1段会重复加监听器）。
- 事件名用 `search_api` 查（如 `ServerItemUseOnEvent`、`ServerBlockUseEvent`、`DestroyBlockEvent`），区分**服务端/客户端**事件——服务端事件用 `exec_server`，客户端事件用 `exec_client`。
- `if not hasattr` 守卫意味着想重新捕获要手动 `del __main__._eventLog` 或换变量名。

**这个模式能解决什么问题**：
- "玩家做了某操作，到底触发了哪些事件？" → 注册多个候选事件，看哪些列表非空
- "事件参数长什么样？" → handler 里把 args 的字段都存下来
- "某操作根本不触发任何脚本事件？" → 所有候选事件列表都为空，但游戏内状态确实变了 → 引擎静默交互（见下）

### 引擎静默交互：不触发任何脚本事件

某些原版交互是引擎内部直接处理，**不触发任何脚本事件**，即使加了 `AddBlockItemListenForUseEvent` 白名单。

案例：网易3.9中锄头右键砂土变泥土。用全局列表法注册了 `ClientItemUseOnEvent`（客户端）、`ServerItemUseOnEvent`、`ServerBlockUseEvent`（服务端），用户实际操作后三个列表全空，但砂土确实变成了泥土。说明这是引擎静默执行，脚本层无法感知。

这类交互脚本层无法捕获，只能换思路（如在处理其他能触发事件的方块时连带处理）。

### 玩家行为类 API 必须用 playerId 创建组件

`PlayerUseItemToPos`、`PlayerDestroyBlock` 等"模拟玩家操作"的 API，挂在 `CreateBlockInfo` 组件上。**必须用 `CreateBlockInfo(playerId)` 创建组件**，用 `CreateBlockInfo(levelId)` 创建的组件调用这些 API 会返回 False（静默失败，不报错）——因为引擎需要知道是哪个玩家在操作，levelId 不含玩家信息。

```python
# 错：返回 False，操作不生效
comp = CF.CreateBlockInfo(LVID)
comp.PlayerUseItemToPos(pos, 2, 0, 1)

# 对：返回 True，操作生效
comp = CF.CreateBlockInfo(playerId)
comp.PlayerUseItemToPos(pos, 2, 0, 1)
```

而 `GetBlockNew`、`SetBlockNew`、`UseItemToPos`（非 Player 版）等不依赖特定玩家的 API，用 `levelId` 即可。**区分依据**：API 名带 `Player` 或描述含"模拟玩家"的，用 playerId；纯方块/世界操作的，用 levelId。

### 热重载（改 .py 后免重启游戏）

改完 mod 的 **.py 文件**后，跑一行脚本让游戏立即加载新代码，不用退出游戏重进：

```bash
/c/Python27/python.exe -B "<skill 目录>/scripts/hot_reload.py"
```

- 不带参数：自动扫整合包自上次调用以来改动过的 .py，双端各重载一次
- 带模块名：只重载指定模块，如 `python hot_reload.py chainScripts.chainServerSystem`
- `--client` / `--server`：只重载一端（默认双端）
- 第一次调用建立基线（不重载），改完 .py 再调一次才会扫到

实现细节、踩坑记录都在 `hot_reload.py` 的注释里（DebugBridge config.py 的 dbreload 函数修复了原版 xupdate 不重载模块级常量/数据的 bug），无需关注，直接用即可。

#### ⚠️ 改 mod 的 JSON 文件必须先让用户重启游戏

热重载只对 .py 生效，**JSON 改完必须重启游戏**——引擎加载时把 JSON 解析成内部数据结构，运行时不重新读。涉及的所有 JSON：
- 方块/物品/实体/附魔/配方定义（`blocks.json`、`<entity>.json`、`<item>.json`、`<enchantment>.json`、`recipes/*.json`）
- UI JSON（`resource_packs/.../ui/*.json`）
- manifest.json、行为包/资源包配置
- 任何 `.json` 后缀文件

**改 JSON 的标准流程**：改完后**必须用 AskUserQuestion 提醒用户重启游戏**，提供"已重启"选项，**用户点击"已重启"之后才能继续验证**。示例：

```
questions: [{
  question: "JSON 文件改完后需要重启游戏才能生效（热重载管不到 JSON）。重启完成后选择'已重启'继续。",
  header: "重启游戏",
  options: [
    {label: "已重启", description: "游戏已重启完毕，可以继续验证"},
    {label: "等等", description: "还没重启，先暂停"}
  ]
}]
```

.py 改动不受这条规则约束，调 `hot_reload.py` 即可。