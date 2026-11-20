---
name: 游戏内执行代码
description: >
  使用execute_code工具前加载此skill，教你查运行时数据、验证 API/事件 的实际返回、跑双端逻辑测试。
---

## MCP 工具

### execute_code：游戏内执行 Python 2 代码

```python
# 服务端读玩家列表（side="server"）
import server.extraServerApi as serverApi
print serverApi.GetPlayerList()
```

```python
# 客户端读本地玩家坐标（side="client"）
import client.extraClientApi as clientApi
CF = clientApi.GetEngineCompFactory()
print CF.CreatePos(clientApi.GetLocalPlayerId()).GetFootPos()
```

- import mod 模块用带包前缀的模块名（`from Litematica.paletteRotation import BlockPalette`），`sys.modules` 键同样带前缀
- **禁止 `time.sleep`**（卡死所在端 tick）；等异步结果用两次 execute_code，或写临时模块属性回读
- execute_code 只捕获同步执行期的 stdout：AddTimer/事件回调里的 print 拿不到；同步 API（PlayerDestroyBlock、SetInvItemDurability 等）exec 内紧跟一行读结果，不要加 AddTimer

```python
# 异步结果回读：第一次调用
scratch = sys.modules.setdefault('_scratch', type(sys)('scratch'))
scratch.result = 'pending'   # AddTimer/事件回调里写 scratch.result = 实际值
# 第二次 execute_code：print sys.modules['_scratch'].result
```

### hot_reload：改完 .py 后热重载

`hot_reload()` 自动扫改动（`side` 默认 both；`pkg` 多 mod 指定；`modules` 指定模块列表）。单端模块只在归属端重载，返回逐模块 `[OK]/[FAIL]/[SKIP]`。

| 症状 | 处理 |
|---|---|
| 类属性初值改了不生效 | 旧值被还原：execute_code 手动矫正，或 `restart_world` |
| UI 类改动不生效 | UI 实例（CreateUI 产物）不重绑新类 → `restart_world` |
| 类基类 / `__metaclass__` / `__init__.py` 改动 | 热重载管不到 → `restart_world` |
| 重载成功但行为没变 | 改在非激活 hash 副本目录：`fsutil file queryfileid` 比对工作目录与运行时文件（`%APPDATA%\MinecraftPE_Netease\games\com.netease\behavior_packs\<包名>\`），ID 不同即改错副本 |

命令行（调试工具自身时）：`py -2 -B <仓库>/tools/hot_reload.py`（无参自动扫；`模块名` 指定；`--client`/`--server` 指定端；`--pkg` 多 mod 指定）

### listen_event / get_event_log：捕获事件 args

```python
listen_event(event_name="DamageEvent", side="server")   # 事件名先用 search_api 查
# 用户在游戏里操作触发
get_event_log()                  # 自动双端读
unlisten_event(side="server")    # 用完取消
```

- 模组自定义事件传 `namespace`/`system_name`
- `callback_code` 可访问 args；传了 callback 时 args 不自动打印，要拿事件参数必须显式 `print args`（不传才默认 print args）
- 字段名先 `get_api_detail` 查事件文档；文档未标注可选禁止 `args.get('key')`
- 不带 `event_name` 的 unlisten 取消该端全部（双端共享注册表，会连另一端注册的一起取消）
- 对系统已监听的事件再挂监听收不到（引擎去重）→ 先 unlisten_event
- 调试模组真实事件链路/回调长逻辑 → 加载「探针调试工作流」skill

### 文件改动后的重载

| 改动 | 工具 |
|---|---|
| 只改已有 .py 内容 | `hot_reload` |
| 只改已有 JSON 内容 | `restart_world` |
| 新增/删除任何文件（含 .py、JSON、贴图等） | `full_restart` |

重载会打断用户操作，先 AskUserQuestion 征得同意；新增/删除文件时措辞换成"彻底重启游戏"。完整流程见「启动游戏重启验证」skill。

## 双端选择

服务端管数据/逻辑，客户端管操作/UI/渲染。**同名接口双端签名可能不同**（如 `GetBlockEntityData` 客户端不带 dimensionId、客户端 `GetBlock` 返回 tuple 服务端 `GetBlockNew` 返回 dict）：跨端调用前 `get_api_detail` 核对两端参数表；参数不匹配不报错、静默返回 None。

## 调试陷阱（症状 → 排查）

### API 静默无效（返回 None/False，无报错）

1. Player 系行为 API（PlayerDestroyBlock、PlayerUseItemToPos 等模拟玩家操作）挂 `CreateBlockInfo(playerId)`，用 levelId 组件调返回 False；纯方块/世界操作（GetBlockNew/SetBlockNew/UseItemToPos）用 levelId
2. 方法参数传执行者：`SetCommand('/give @s ...', playerId)`，`@s` 解析为第二参实体
3. 服务端方块/容器操作漏传 dimensionId → 返回 None：`GetBlockNew(pos, dimensionId)`、`GetContainerItem(pos, slot, dimensionId)`
4. 失效实体：comp 拿得到但取值返回 None → 判返回值别判 comp；入参可能是空串时先 `if entityId:` 预判（空串时工厂返回 None，直接 `.GetFootPos()` 抛 AttributeError）
5. 跨端签名不匹配（见"双端选择"）

```python
CF = serverApi.GetEngineCompFactory()
dimensionId = CF.CreateDimension(playerId).GetEntityDimensionId()
CF.CreateBlockInfo(levelId).GetBlockNew((5,93,-21), dimensionId)     # 方块读：levelId 组件 + 维度
CF.CreateItem(levelId).GetContainerItem((5,93,-21), 0, dimensionId)  # 容器读：维度必传
CF.CreateBlockInfo(playerId).PlayerDestroyBlock((5,93,-21), 0)       # 玩家行为：playerId 组件
```

- `SetBlockNew` 参数顺序：`pos, blockDict, oldBlockHandling(0=替换/1=销毁/2=保留), dimensionId, isLegacy, updateNeighbors`；多状态方块（床等双格结构）传 `isLegacy=True`，否则 state 映射解释错 aux、引擎不补全另一半
- `GetPos`/`GetFootPos` 非玩家完全一致（脚底坐标），玩家有站(+1.62)/睡(+0.2)/骑乘(约+1.4)眼位差

### ExtraData 改了没存上

`GetExtraData` 返回存入的同一引用：原地改（`del d[k]`、`d[k]=v`）运行期生效，落盘只在 SetExtraData 时快照 → **改引用必写回** `comp.SetExtraData(key, d)`；不写回时服务端异常退出后读档回退旧值。

### imp.load_source 撞活模块名 → 进程原生崩溃

行为包目录内 load_source 的文件基名与已加载模块源文件同名（含 `.bak` 剥后缀同名）→ 进程立即崩溃，try/except 拦不住、无 crash dump，MCP 随后报"游戏未启动"。对比两版模块：宿主机先复制到 %TEMP%（`cmp` 校验字节一致），游戏内从 temp 加载：

```python
import sys, imp
sys.dont_write_bytecode = True    # 防止落地 pyc 垃圾
new = imp.load_source('v_new', r'C:\Users\<user>\AppData\Local\Temp\xxx_new.py')
old = imp.load_source('v_old', r'C:\Users\<user>\AppData\Local\Temp\xxx_old.py')
print set(new.Stones)==set(old.Stones)
```

纯数据模块直接宿主机 `py -2 -B` 跑同样断言，不碰游戏进程。

### 物品 dict 覆写失败（SpawnItemToPlayerInv 返回 False）

- `GetPlayerItem(playerId=0表示自己/2表示carried槽, slotId, getUserData=True)` 返回 dict 天然带 `durability`（剩余耐久），与 `userData.Damage` 冲突 → 覆写前 `del item['durability']`，或直接 `SetInvItemDurability(slot, value)`（推荐）
- 生成带已消耗耐久的新物品：`userData` 带 `{'Damage': {'__type__': 3, '__value__': N}}`（N=已消耗量；生成认、覆写不认）
- itemDict 重新生成要保真：读写都带 getUserData=True，且 `pop('enchantData', None)`、`pop('modEnchantData', None)`（与 userData.Ench 冲突）

### 模拟联机时序

- 同 tick 生成实体 + `NotifyToMultiClients` → 客户端未收到出生同步，读该实体 pos 得 None、attr 得 -1 → 分两次 execute_code，等一次往返再触发攻击/通知
- Notify 事件包常先于血量属性同步包到客户端 → 客户端读到扣血前旧值；确定性逻辑（如伤害按扣血前血量截断）放服务端事件时机完成
- 载具移不动/清不掉（对船 `SetPos`、`DestroyEntity` 返回 False）→ `kill @e[type=boat]`

### 伤害/攻击事件

- 客户端 `PlayerAttackEntityEvent` 多触发（无敌帧挥击、打尸体都触发），damage 是不按剩余血量截断的护甲后原值 → 按 victimId 做 0.5s（10 tick）去重 + 自行 `min(damage, 血量)`
- 脚本 `UseItemAttackEntity` 触发的 `ActuallyHurtServerEvent` srcId 是 `'-1'`，`GetEngineTypeStr('-1')` 返回 None、IsPlayer 判 False → 识别脚本攻击靠自标记集合（攻击前记录目标 id，回调查 membership）
- `GetEntitiesAroundByType` 查询结果含中心实体自身

### 引擎静默交互

部分原版交互（如锄头右键砂土变泥土）引擎内部处理，任何脚本事件（含 ServerItemUseOnEvent、AddBlockItemUse 白名单）都捕获不到 → 换思路，在能触发事件的相邻交互里连带处理。

### UI / 跨维度

- 旧 UI 实例未销毁时 `CreateUI` 返回 None；模拟弄脏 UI 引用后用 `restart_world` 恢复；真实跨维度 UI 调试走「探针调试工作流」skill
- `CF.CreateDimension(playerId).ChangePlayerDimension(1, (0,128,0))`（0主/1下界/2末地）后，UI 重建/事件/RPC 往返等异步链路等下一次 execute_code 再验证

## 验证方法

最小复现 + 对照：print 前值 → 执行被测操作 → 同步读后值 → 每轮只改一个变量，确认变量与结果的因果。

## DebugBridge 源码

源码在仓库 `DebugBridge/DebugBridgeB/DebugBridge/`（MCStudio 直连运行），改完重启游戏生效。
