# mod-debug-bridge

[![Python 2.7](https://img.shields.io/badge/Python-2.7-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/release/python-2718/)
[![MCP](https://img.shields.io/badge/MCP-enabled-6f42c1)](https://modelcontextprotocol.io/)
[![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)](README.md)
[![by 7stars七星](https://img.shields.io/badge/by-7stars%E4%B8%83%E6%98%9F-00AEEF)](https://space.bilibili.com/379515917)
[![License](https://img.shields.io/github/license/sevenstars0/mod-debug-bridge)](LICENSE)

> 让你的大模型在游戏内执行代码、捕获事件、热重载——极大提升模组开发与修 bug 效率。

Minecraft（网易基岩版）轻量级 Agent 模组调试工具，分两层：

- **调试 mod（DebugBridge）**：游戏运行时通过 TCP 端口执行任意 Python 代码。`clientApi`/`serverApi` 全可用，读运行时数据、验证 API 行为、排查 mod bug。
- **MCP 服务器**：给 AI 客户端用的工具层，封装了 DebugBridge 的连接、诊断、热重载。

| MCP 工具 | 用途 |
|---|---|
| `execute_code` | 游戏内执行代码（clientApi/serverApi 全可用） |
| `hot_reload` | 改完代码后热重载（修复了官方 xupdate 不重载模块级常量/数据的 bug） |
| `listen_event` + `get_event_log` | 监听并获取事件数据用于调试 |
| `get_api_detail` / `search_api` / `search_identifier` | 查 ModSDK 接口、事件、枚举、基岩版 ID |

## 安装

点击右上角 Code → Download ZIP，下载到本地。

### 1. 部署 DebugBridge mod

仓库 `DebugBridge/` 是可直接 MCStudio 导入的工程：

1. MCStudio → 基岩版组件 → 本地导入 → 勾选"使用文件夹导入" → **选 `DebugBridge/` 文件夹**（MCStudio 自动识别里面的 B 行为包 + R 资源包）
2. 在 mod 工程的"开发测试" → "使用功能组件"里勾选 DebugBridge
3. 使用开发测试进存档

### 2. 启动 MCP 服务器

先安装 mcp 库：

```bash
pip install mcp
```

在 AI 客户端的 MCP 配置中添加（以 ZCode 为例）：

```json
{
  "mcpServers": {
    "mod-debug-bridge": {
      "command": "python",
      "args": ["D:\\mod-debug-bridge\\server.py"]
    }
  }
}
```

## 如何更新数据源

### 更新 ModAPI 文档

```bash
python tools/build_index.py
```

从 GitHub（[MCNeteaseDevs/modsdk_mcp_server](https://github.com/MCNeteaseDevs/modsdk_mcp_server)）下载 `docs/` 下的 `interface.json`、`events.json` 和所有 `.md` 文档到临时目录，解析后自动删除，输出到 `data/`。

默认走代理 `http://127.0.0.1:7890`，从 `git credential` 读取 GitHub token。可用 `--no-proxy` 禁用代理。

下载策略：
- `.json`（含 1.8MB 的 interface.json）→ jsdelivr CDN（避免 GraphQL 大文件截断）
- `.md`（192 个小文件）→ GraphQL API 批量下载（每批 50）

脚本会：
1. 解析 `interface.json`（1640 个 API）和 `events.json`（292 个事件）
2. 从 `接口/*.md` 和 `事件/*.md` 提取备注和示例代码
3. 从 `枚举值/*.md` 加载枚举值定义，内联展开到接口详情
4. 输出 `data/api_index.json` 和 `data/api_listings.txt`

### 更新 mcguide 教程文档

当官方教程有更新时：

```bash
python tools/sync_mcguide.py
```

默认走代理 `http://127.0.0.1:7890`（GitHub API 直连不稳定），从 `git credential` 读取 GitHub token。
可用 `--no-proxy` 禁用代理。

最终保留约 486 个文件。

### 更新基岩版 ID

当 Minecraft 版本升级、原版方块/物品/实体有变化时：

```bash
python tools/build_mc_ids.py
```

从 Minecraft Wiki 抓取并生成 `data/mc_ids.txt`。

### 数据来源

- `interface.json` / `events.json` / 接口事件文档：来自 [MCNeteaseDevs/modsdk_mcp_server](https://github.com/MCNeteaseDevs/modsdk_mcp_server) 的 `docs/` 目录
- `mcguide/`：来自 [MCNeteaseDevs/netease-bedrock-wiki](https://github.com/MCNeteaseDevs/netease-bedrock-wiki) 的 mcguide 目录
- `mc_ids.txt`：来自 Minecraft Wiki

## 详细文档

- AI 工具调用陷阱、调试技巧：见 [`SKILL.md`](SKILL.md)
- DebugBridge mod 工作原理、热重载机制：见 [`DebugBridge/DebugBridgeB/DebugBridge/config.py`](DebugBridge/DebugBridgeB/DebugBridge/config.py) 文件头注释和 `dbreload` 函数注释

## 目录结构

```
mod-debug-bridge/
├── DebugBridge/                    DebugBridge mod（MCStudio 直接导入）
│   ├── DebugBridgeB/               行为包根
│   │   ├── manifest.json
│   │   └── DebugBridge/            mod 源码（config.py / clientSystem.py / serverSystem.py / modMain.py）
│   └── DebugBridgeR/               资源包根（占位）
├── server.py                       MCP 服务器入口
├── requirements.txt
├── data/                           预编译索引（API/事件/枚举/MC ID）
├── mcguide/                        官方教程文档镜像
├── tools/
│   ├── debug_bridge_client.py      DebugBridge 客户端（py2/py3 兼容）
│   ├── hot_reload.py               热重载脚本（py2，被 hot_reload 工具 subprocess 调用）
│   ├── build_index.py              重建 data/ 索引（数据源更新时用）
│   ├── build_mc_ids.py             重建基岩版 ID 映射
│   └── sync_mcguide.py             从 GitHub 同步官方教程
├── README.md                       本文档
├── SKILL.md                        ZCode skill 配置
└── LICENSE
```

## 协议

[BSD 3-Clause License](LICENSE)
