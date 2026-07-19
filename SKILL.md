---
name: 游戏内执行代码
description: >
  大部分编码场景用 get_api_detail / search_api / search_identifier 查资料就够，以下情况时启用：查运行时数据（方块/实体/NBT/背包/坐标）、验证 API/事件 的实际返回、跑双端逻辑测试、改完代码后热重载验证。
---

通过 MCP 工具配合用户装载的 DebugBridge mod 在游戏运行时执行任意 Python 代码、捕获事件。

## MCP 工具

### execute_code：在游戏内执行 Python 2 代码

**示例 1**：服务端读玩家列表
code 内容（Python 2）：
```python
import server.extraServerApi as serverApi
print repr(serverApi.GetPlayerList())
```
参数：`side="server"`

**示例 2**：客户端读玩家坐标
code 内容（Python 2）：
```python
import client.extraClientApi as clientApi
pid = clientApi.GetLocalPlayerId()
pos = clientApi.GetEngineCompFactory().CreatePos(pid).GetPos()
print repr(pos)
```
参数：`side="client"`

### hot_reload：改完 .py 后热重载

参数：`side`（默认 `both`，可选 `client`/`server`）、`pkg`（可选，多 mod 时指定包名）、`modules`（可选，指定模块名列表）

封装 `tools/hot_reload.py`：自动扫整合包自上次调用以来改动过的 .py，双端各重载一次（修复了原版 xupdate 不重载模块级常量/数据的 bug）。返回脚本 stdout 原文，含每个模块的 `[OK]/[FAIL]` 状态。

```
# 改完代码后调用（默认双端都重载，自动扫改动）
hot_reload()

# 指定模块（不扫改动，只重载给定模块）
hot_reload(modules=["chainScripts.chainServerSystem"])

# 只重载一端
hot_reload(side="server")
```

前提跟 execute_code 一致（游戏已启动 + DebugBridge mod 已部署 + 进入存档）。改 JSON 文件无效（见下方"改 JSON 必须重启游戏"）。

### listen_event / get_event_log：捕获事件 args

```python
# 1. 注册要监听的事件（事件名用 search_api 查）
listen_event(event_name="DamageEvent", side="server")

# 2. 让用户在游戏里操作触发事件

# 3. 读结果
get_event_log()
```

## 客户端 vs 服务端怎么选

| 需求 | side |
|------|------|
| 服务端代码（读服务端方块/实体/NBT、调 serverApi、`CreateBlockState`/`GetBlockBasicInfo` 等客户端没有的方法） | `server` |
| 客户端组件 API（`CreateBlockInfo.GetBlockEntityData` 读方块实体 NBT 等） | `client` |

## 调试陷阱

### AddTimer / 异步回调里的 print 收不到

execute_code 只捕获 **exec 同步执行期间** 的 stdout。`AddTimer(0, func)` 或 `AddTimer(delay, func)` 的回调在**下一帧**执行，那时 exec 早已返回，回调里的 `print` 输出拿不到。

**错误写法**（拿不到结果）：
```python
Game.AddTimer(0, lambda: print '挖掘后耐久=%s' % itemComp.GetPlayerItem(2,0,True)['durability'])
```

**替代方案**（按场景选）：
- 大部分 API（`PlayerDestroyBlock`、`SetInvItemDurability`、`SpawnItemToPlayerInv` 等）是**同步生效**的，exec 内紧跟一行读结果即可，不要加 AddTimer。
- 确需等下一帧的（比如等引擎同步状态）：**分两次 execute_code**——第一次触发操作，隔 1~2 秒后第二次读结果。两次调用各自独立连 socket，不依赖回调。
- **禁止 `time.sleep`**：会阻塞整个服务端 tick，游戏卡死。

### 游戏处于后台时连接会卡死

DebugBridge 的 `ExecListener.update()` 挂在 system 的 `Update()` tick 里。游戏切到后台（窗口最小化 / 失焦 / 切到其他应用）时 tick 暂停，socket 收不到新连接也发不出响应。具体表现：
- 端口仍 LISTENING，但新连接报 `socket.error 10061/10054` 或 `timeout`

**解决**：把游戏窗口切回前台（**不需要重启游戏**），等几秒让 tick 推进释放卡住的连接，再调用即可。MCP 工具内部已加重试（3 次 + 退避），轻微卡顿能自愈，严重卡死时需要手动切前台。

### 工具/物品调试要点

- `GetPlayerItem(playerId=0表示自己/2表示carried槽, slotId, getUserData=True)` 返回的字典**天然带 `durability` 字段**（当前剩余耐久）。
- 耐久对应 NBT 的 `Damage` 字段（`{'__type__':3, '__value__':N}`，N 是已消耗量，`durability = maxDurability - Damage`）。
- **改 Damage 后用 `SpawnItemToPlayerInv` 覆写会失败**（返回 False）：因为读出的字典带 `durability`，和 `userData.Damage` 冲突。要先 `del item['durability']` 再写，或者直接用 `SetInvItemDurability(slot, value)`（推荐，内部会同步更新 Damage）。
- 想生成一把消耗过耐久的物品：生成时 `userData` 带 `{'Damage': {'__type__': 3, '__value__': N}}` 即可，`SpawnItemToPlayerInv` 生成新物品时认这个字段（只是**覆写已有物品**时不认）。

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

### 引擎静默交互（不触发任何脚本事件）

某些原版交互是引擎内部直接处理，**不触发任何脚本事件**，即使加了 `AddBlockItemListenForUseEvent` 白名单。典型：网易 3.9 中锄头右键砂土变泥土，用 `listen_event` 监听 `ClientItemUseOnEvent`/`ServerItemUseOnEvent`/`ServerBlockUseEvent` 全部捕获不到，但游戏内确实生效。这类交互脚本层无法感知，只能换思路（如在处理其他能触发事件的方块时连带处理）。

### 验证 mod 行为的标准流程

定位"某 API / 某机制是否生效"时，用**最小复现 + 对照**：
1. 生成/设置初始状态，`print` 记录前值（如耐久、NBT）
2. 执行被测操作（如 `PlayerDestroyBlock`）
3. 同步读后值，`print` 对比
4. 只改一个变量（如换 NBT 类型、加/删字段），重复，确认变量与结果的因果关系
5. 修改本地 json 或 python 文件后，需要使用 AskUserQuestion 方法等待用户重启完成后才能验证

## 热重载底层脚本（备选）

`hot_reload` MCP 工具内部调的脚本：`tools/hot_reload.py`（仓库根下）。需要直接跑命令行时（如调试工具自身）：

```bash
/c/Python27/python.exe -B "tools/hot_reload.py"
```

命令行参数：无参自动扫改动；`chainScripts.xxx` 指定模块；`--client`/`--server` 指定端；`--pkg <name>` 多 mod 时指定包名。实现细节、踩坑记录都在该脚本顶部注释里。

### ⚠️ 改 mod 的 JSON 文件必须先让用户重启游戏

热重载只对 .py 生效，**其他文件改完必须重启游戏**——引擎加载时把 JSON 解析成内部数据结构，运行时不重新读。

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

.py 改动不受这条规则约束，调 `hot_reload` 工具或 `tools/hot_reload.py` 即可。

## DebugBridge mod 运行路径

DebugBridge mod 部署到 MCStudio 工作目录后，实际运行时通过 NTFS 硬链接同步到游戏 `behavior_packs/<包名>/DebugBridge/` 下。具体路径取决于 MCStudio 工程配置。
