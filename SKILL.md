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
pos = clientApi.GetEngineCompFactory().CreatePos(pid).GetFootPos()
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

前提跟 execute_code 一致（游戏已启动 + DebugBridge mod 已部署 + 进入存档）。改 JSON 文件无效（见下方"改 JSON 需重新加载"）。

### listen_event / get_event_log：捕获事件 args

```python
# 1. 注册要监听的事件（事件名用 search_api 查）
listen_event(event_name="DamageEvent", side="server")

# 2. 让用户在游戏里操作触发事件

# 3. 读结果
get_event_log()
```

`listen_event` 可传 `callback_code`：事件触发时执行的代码段，可访问 `args`（事件参数 dict），用 `print` 输出额外数据（如根据 `args['entityId']` 调 API 查位置）。注意：**自定义 callback 时原始 args 不会自动打印**，要拿事件参数必须在 callback 里显式 `print args`；不传 callback 才默认 `print args`。另实测注册表双端共享：一端不带 `event_name` 的 unlisten 会把另一端注册的监听也一并取消。

```python
listen_event(
    event_name="DamageEvent",
    side="server",
    callback_code="print 'damage:', args['damage']\nprint 'pos:', serverApi.GetEntityPos(args['entityId'])",
)
```

字段名必须先用 `get_api_detail` 查事件文档确认，文档未标注可选时禁止 `args.get('key')`，直接用 `args['key']`。

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

**解决**：把游戏窗口切回前台（**不需要重启游戏**），等几秒让 tick 推进释放卡住的连接，再调用即可。MCP 工具内部已加重试（3 次 + 退避），轻微卡顿能自愈，严重卡死时需要手动切前台。Minecraft.Windows.exe 是 UWP 进程，`MainWindowHandle` 常为 0 拿不到句柄，PowerShell 置前台用 `(New-Object -ComObject WScript.Shell).AppActivate('Minecraft')`，或 EnumWindows 按标题含 "Minecraft" 找可见窗口再 ShowWindow+SetForegroundWindow。

**断连报错鉴别**：MCP 报「游戏未启动」「调试工具未加载」＝连接没建成（进程已死 / 还没进存档 / tick 暂停）；「Connection closed」＝已连上但对端中途断开——**代码已送达、进程在执行中死亡**（典型：触发原生崩溃，见下节）。诊断顺序：`tasklist | grep -i minecraft` 查进程 → `netstat -ano | grep 1453` 查 14530/14531 是否 LISTENING（LISTENING＝已进存档、mod 已初始化）。

### 行为包目录内 imp.load_source 撞活模块名 → 游戏整进程崩溃

游戏内加载 mod 的 .py 文件（典型场景：imp.load_source 对比优化前后两版数据模块）时，目标文件若在**行为包目录内**、且文件名（`os.path.splitext` 后的基名）与任一**已加载活模块**的源文件同名，游戏进程**立即原生崩溃**——非 Python 异常，try/except 拦不住、无 crash dump，连接表现为 Connection closed。实测 7/7 复现（网易 3.9）：

| load_source 目标 | 结果 |
|---|---|
| %TEMP% 下任意文件（任意大小/名字/内容） | 正常 |
| 行为包目录内小文件（28B）、或与活模块无关名字的 20KB 同内容文件 | 正常 |
| 行为包目录内 `chainconfig.py`（活模块 `chainScripts.chainconfig` 的源文件） | **崩溃** |
| 行为包目录内 `chainconfig.py.bak`（splitext 基名仍是 chainconfig.py，同样撞名） | **崩溃** |

机制：引擎模块注册表按源文件名索引，对同名源文件二次加载触发原生冲突。`import imp` 本身和 load_source 小文件都正常，别往"imp 被禁"上想。

**规避（游戏内对比两版模块的标准做法）**：宿主机先把两份文件复制到 %TEMP%（`cmp` 校验字节一致），游戏内从 temp 加载。py2 的 load_source 会写 pyc（对 `.bak` 会落地 `.bakc` 垃圾文件），先设 `sys.dont_write_bytecode = True`（实测 load_source 尊重该标志）：

```python
import sys, imp
sys.dont_write_bytecode = True
new = imp.load_source('v_new', r'C:\Users\<user>\AppData\Local\Temp\xxx_new.py')
old = imp.load_source('v_old', r'C:\Users\<user>\AppData\Local\Temp\xxx_old.py')
print set(new.Stones) == set(old.Stones)   # 纯数据模块可直接逐项断言
```

宿主机跑同样断言可直接用 `py -2 -B`（与游戏同族 py2.7，纯数据模块结论等价），不会碰游戏进程。

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

### 组件工厂对失效实体：comp 拿得到，取值方法返回 None

`CF.CreatePos(deadId)` / `CF.CreateRot(deadId)` / `CF.CreateName(deadId)` 等对已销毁实体**不抛错、返回有效 comp**，但 `GetFootPos()` / `GetRot()` / `GetName()` 返回 **None**。所以判空要判**返回值**而不是判 comp：`pos = CF.CreatePos(boatId).GetFootPos()` 后 `if not pos: return`，不要 `if comp:`。例外：传空字符串 `''` 这类非法 id 时组件工厂可能返回 None（`None.GetFootPos()` 直接 AttributeError），入参可能为空串时先 `if entityId:` 预判。来源：引擎 entityMgr.py 实现 + 既有代码信任模式交叉验证。`GetPos` 与 `GetFootPos` 对**非玩家**完全一致（都是脚底坐标），仅玩家有眼位差（站立/行走 +1.62、睡觉 +0.2、骑乘约 +1.4）。

### ExtraData 存引用，落盘只在 SetExtraData 时快照

引擎 ExtraData 管理器（extraDataMgr.py 的 `self.mEntityData[entityId][key] = val`）**存引用**：`GetExtraData` 返回的是 SetExtraData 存入的同一对象，运行期原地修改（`del d[k]`、`d[k] = v`、子 dict 增删）全局立即可见；但**落盘（msgpack 快照）只发生在调用 SetExtraData 的那一刻**。原地改完引用不重新 SetExtraData，正常流程无恙，服务端异常退出后读档回退到旧快照。结论：**改引用必写回**——`comp.SetExtraData('DV_X', d)` 再执行一次即可。

### BlockPalette 调色板分层：common 记全部方块，actor 只是实体数据层

`SerializeBlockPalette()` 输出（paletteRotation.py 同构）的 `paletteData` 分层，**遍历全部实体方块必须用 common**：
- `common`：`{(name, aux): [index, ...]}`，**全部实体方块的形态记录，含带方块实体的方块**（控制台/箱子/告示牌等都在内）
- `actor`：`{name: {index: …}}`，只是其中带方块实体数据那部分的**索引记录层**，不贡献方块形态——拿它当"全部方块"遍历会漏掉普通方块；反过来按 common 遍历不会漏箱子
- `extra`：附加层（如含水的 `(minecraft:water, level)` 水层）
- `nbtData`：`{index: nbt}`，方块实体 NBT，独立于 actor 按 index 取
- 序号编码 `index = z + x*vz + y*vx*vz`；`volume` 为 `(vz, vx, vy)`（z 在前，与直觉的 xyz 相反）；`pos = (blockPos.z + index%vz, …)` 类反解用整除链 `index/vz%vx, index/vx/vz, index%vz`

### 方块含水（waterlogged）的放置/清除/记录语义

实测（网易 3.9）结论，处理水/含水方块/结构放置（船只停靠、建筑印刷）时直接引用：

- **放置保水**：可含液体方块（栅栏/玻璃板/活板门等）放进有液体格 → 引擎保留液体（自动含水）；实体方块（木板等）→ 挤掉液体。`SetBlockNew` 与 `SetBlockByBlockPalette` 行为一致，纯引擎行为（引擎 Python 层无任何液体逻辑）
- **检测**：`GetLiquidBlock(pos, dim)` 返回 None=非液体，水返回 `{'aux': 0, 'name': 'minecraft:water'}`
- **extra 水层不依赖环境水**：调色板 extra 写 `('minecraft:water', 0)`，目标格是干空气也能让可含液体方块含水；不可含液体的方块静默丢弃水层（无报错无坏状态）
- **空气调色板清液体**：common 全空气的调色板放置后**连液体层一起清掉** → "先清空占地再放置"的流程里引擎保水不会生效，要让方块含水必须把水写进 extra（覆盖处是水→extra 加水、否则删水的判定不可省）
- **含水方块置空气是两步**：第一次置空气留下的是**水方块**，第二次才干净——"置空后查 GetLiquidBlock 再置一次"双 set 模式的原因：

```python
bi.SetBlockNew(pos, {'name':'minecraft:air'}, 0, dim)
if bi.GetLiquidBlock(pos, dim):   # 含水方块第一次置空后变纯水方块
    bi.SetBlockNew(pos, {'name':'minecraft:air'}, 0, dim)
```

- **空气+水extra 的调色板** → 该格直接变水方块
- **记录捕获含水**：`GetBlockPaletteBetweenPos` 把含水状态写进 extra，record→place→record 自洽
- **含水方块会扩散**：流体/邻居更新时含水方块向相邻空气格扩散水。清密闭舱室空气必须 `updateNeighbors=False`；与舱内空气相邻的含水方块会经回流把舱灌满，要么脱水要么别触发更新
- **实验方法**：石壳围出隔离测试格，单次 execute_code 原子完成"放水→操作→GetBlockNew+GetLiquidBlock 双查"（同 tick 内无流体 tick 干扰）；收尾扫残留水——扫描窗向下多扫几十层、用水面海平面区分天然水与实验残留

### 引擎静默交互（不触发任何脚本事件）

某些原版交互是引擎内部直接处理，**不触发任何脚本事件**，即使加了 `AddBlockItemListenForUseEvent` 白名单。典型：网易 3.9 中锄头右键砂土变泥土，用 `listen_event` 监听 `ClientItemUseOnEvent`/`ServerItemUseOnEvent`/`ServerBlockUseEvent` 全部捕获不到，但游戏内确实生效。这类交互脚本层无法感知，只能换思路（如在处理其他能触发事件的方块时连带处理）。

### 模拟攻击/联机时序的竞争陷阱

- **同 tick 生成实体并触发自定义事件**：`CreateEngineEntityByTypeStr` 生成的实体，客户端还没收到出生同步，服务端同 tick 发的 `NotifyToMultiClients` 自定义事件包先到了——客户端此时对该实体 `CreatePos().GetFootPos()` 得 None、`CreateAttr().GetAttrValue(0)` 得 -1.0。模拟联机测试必须**分两次 execute_code**：第一次生成实体，等一次往返（客户端加载完）再触发攻击/通知。真实游戏里受击者是早已加载的实体，不存在该竞争。
- **自定义事件包 vs 引擎属性同步包**：实测 `NotifyToMultiClients` 的事件包稳定先于血量属性同步包到达客户端，客户端收到时读到的还是扣血前旧值（含击杀场景）；死亡动画期间受害者的坐标/血量客户端仍可读。但两者走不同通道、时序无契约，确定性逻辑（如伤害按扣血前血量截断）应在服务端事件时机完成。
- **API 操纵载具**：对船 `SetPos` 和 system 的 `DestroyEntity` 都返回 False（移不动、清不掉），清理测试船用 `kill @e[type=boat]` 命令。

### 伤害事件实测（网易 3.9）

- 客户端 `PlayerAttackEntityEvent` 会**多触发**：受击无敌帧内的挥击、打尸体都照样触发，且 damage 传的是不按剩余血量截断的护甲后原值（实测一头牛 4 次事件仅对应 2 次实际结算）。按它做伤害显示需按 victimId 做 0.5s（10 tick 无敌帧）去重，并自行 `min(damage, 血量)`。
- 脚本 `UseItemAttackEntity` 触发的 `ActuallyHurtServerEvent` 的 `srcId` 是 `'-1'` 而非攻击玩家，且 `GetEngineTypeStr('-1')` 返回 None → `IsPlayer` 判 False；要识别脚本发起的攻击只能靠自标记（攻击前把目标 id 加入集合，事件回调里查 membership）。
- `GetEntitiesAroundByType` 的查询结果**包含中心实体自身**（中心是玩家时自查询返回自己）。

### 验证 mod 行为的标准流程

定位"某 API / 某机制是否生效"时，用**最小复现 + 对照**：
1. 生成/设置初始状态，`print` 记录前值（如耐久、NBT）
2. 执行被测操作（如 `PlayerDestroyBlock`）
3. 同步读后值，`print` 对比
4. 只改一个变量（如换 NBT 类型、加/删字段），重复，确认变量与结果的因果关系

## 热重载底层脚本（备选）

`hot_reload` MCP 工具内部调的脚本：`tools/hot_reload.py`（仓库根下）。需要直接跑命令行时（如调试工具自身）：

```bash
py -2 -B tools/hot_reload.py
```

命令行参数：无参自动扫改动；`chainScripts.xxx` 指定模块；`--client`/`--server` 指定端；`--pkg <name>` 多 mod 时指定包名。实现细节、踩坑记录都在该脚本顶部注释里。

### ⚠️ 改 mod 的 JSON 文件需重新加载，分两种情况

热重载只对 .py 生效，JSON 改完必须让引擎重新读取——但加载方式区分两种：

| 改动类型 | 重新加载方式 |
|---------|------------|
| **只改已有 JSON 文件内容**（编辑已注册的 ui/*.json、已存在的行为包/资源包 json） | **重载存档即可**（退出存档再进，或切世界），不用重启游戏 |
| **新增 / 删除 JSON 文件**（新建 ui_common.json、往 _ui_defs.json 加新条目、新增方块/物品定义文件） | **必须彻底杀进程再重进游戏**（引擎只在进程启动时扫描文件列表） |

**改 JSON 的标准流程**：改完后**必须用 AskUserQuestion 提醒用户重新加载**，按上表选对应的措辞，提供"已完成"选项，**用户确认后才能继续验证**。示例：

```
questions: [{
  question: "JSON 文件改完后需要重载存档才能生效（热重载管不到 JSON）。重载完成后选择'已完成'继续。",
  header: "重载存档",
  options: [
    {label: "已完成", description: "存档已重载，可以继续验证"},
    {label: "等等", description: "还没重载，先暂停"}
  ]
}]
```

新增/删除文件时把措辞换成"彻底重启游戏（杀进程重进）"。

.py 改动不受这条规则约束，调 `hot_reload` 工具即可。

DebugBridge mod 实际运行路径：`C:/MCStudioDownload/work/<用户开发者邮箱>/Cpp/AddOn/<hash目录>/DebugBridgeB/DebugBridge/`
