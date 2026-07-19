# -*- coding: utf-8 -*-
"""从 GitHub 下载 mcguide 目录下的所有 .md 文件（不含图片）。

流程：
  1. 用 git trees API 获取 mcguide 完整文件树（单次请求）
  2. 筛选 .md 文件，用 GraphQL API 批量下载内容（每批 50 个）
  3. 清理：删除 0 字节文件、删除 20-玩法开发/14-预设玩法编程

GitHub 认证 token 从 git credential 自动读取。
默认走代理 http://127.0.0.1:7890（raw/API 直连不稳定）。

用法：
    python sync_mcguide.py [--no-proxy] [--output ..\\mcguide]
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

REPO_OWNER = "MCNeteaseDevs"
REPO_NAME = "netease-bedrock-wiki"
BRANCH = "main"
PROXY_URL = "http://127.0.0.1:7890"
BATCH_SIZE = 50
# 下载后要删除的目录（相对 mcguide/）
PRUNE_DIRS = ["20-玩法开发/14-预设玩法编程"]

DEFAULT_OUTPUT = str(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根
) + os.sep + "mcguide"


# ============================================================
# 凭据 / HTTP
# ============================================================

def get_token():
    """从 git credential 读取 GitHub token。"""
    try:
        result = subprocess.run(
            ["git", "credential", "fill"],
            input="protocol=https\nhost=github.com\n\n",
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.splitlines():
            if line.startswith("password="):
                return line[len("password="):]
    except Exception:
        pass
    return None


def make_opener(use_proxy):
    if not use_proxy:
        return urllib.request.build_opener()
    handler = urllib.request.ProxyHandler({
        "http": PROXY_URL,
        "https": PROXY_URL,
    })
    return urllib.request.build_opener(handler)


# ============================================================
# 步骤1：获取文件树
# ============================================================

def get_tree(opener, token):
    """用 git trees API 递归获取完整文件树，返回 tree item 列表。"""
    # 先拿分支最新 commit sha
    req = urllib.request.Request(
        "https://api.github.com/repos/{}/{}/commits/{}".format(REPO_OWNER, REPO_NAME, BRANCH),
        headers={"User-Agent": "mcguide-sync", "Authorization": "token " + token},
    )
    resp = opener.open(req, timeout=30)
    sha = json.load(resp)["sha"]
    print("分支 {} 最新 commit: {}".format(BRANCH, sha[:12]))

    # 递归获取 tree
    req = urllib.request.Request(
        "https://api.github.com/repos/{}/{}/git/trees/{}?recursive=1".format(
            REPO_OWNER, REPO_NAME, sha),
        headers={"User-Agent": "mcguide-sync", "Authorization": "token " + token},
    )
    resp = opener.open(req, timeout=30)
    data = json.load(resp)
    if data.get("truncated"):
        print("警告：文件树被截断，结果可能不完整！")
    return data.get("tree", [])


# ============================================================
# 步骤2：GraphQL 批量下载
# ============================================================

def fetch_batch(opener, token, paths, retries=3):
    """通过 GraphQL 批量获取文件内容，返回 {path: text}。"""
    aliases = []
    for i, p in enumerate(paths):
        escaped = p.replace('\\', '\\\\').replace('"', '\\"')
        aliases.append(
            'f{}: object(expression: "{}:{}") {{ ... on Blob {{ text }} }}'.format(i, BRANCH, escaped))
    query = '{{ repository(owner: "{}", name: "{}") {{ {} }} }}'.format(
        REPO_OWNER, REPO_NAME, " ".join(aliases))
    payload = json.dumps({"query": query}).encode("utf-8")

    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                "https://api.github.com/graphql",
                data=payload,
                headers={
                    "Authorization": "bearer " + token,
                    "Content-Type": "application/json",
                    "User-Agent": "mcguide-sync",
                },
            )
            resp = opener.open(req, timeout=60)
            result = json.load(resp)
            if "errors" in result:
                raise Exception(result["errors"][0].get("message", "")[:200])
            repo = result["data"]["repository"]
            out = {}
            for i, p in enumerate(paths):
                obj = repo["f{}".format(i)]
                if obj:
                    out[p] = obj["text"]
            return out
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(3)
    return {}


def download_all(opener, token, md_paths, dest_root):
    total = len(md_paths)
    print("共 {} 个 md 文件，分 {} 批下载".format(total, (total + BATCH_SIZE - 1) // BATCH_SIZE))

    ok_count = 0
    fail_count = 0
    failed = []

    for start in range(0, total, BATCH_SIZE):
        batch = md_paths[start:start + BATCH_SIZE]
        batch_num = start // BATCH_SIZE + 1
        total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE

        try:
            results = fetch_batch(opener, token, batch)
        except Exception as e:
            print("批次 {}/{} 失败: {}".format(batch_num, total_batches, e))
            failed.extend(batch)
            fail_count += len(batch)
            continue

        for path in batch:
            text = results.get(path)
            if text is None:
                failed.append(path)
                fail_count += 1
                continue
            rel = path[len("mcguide/"):]
            local = os.path.join(dest_root, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(local), exist_ok=True)
            with open(local, "w", encoding="utf-8") as f:
                f.write(text)
            ok_count += 1

        print("批次 {}/{}: {}/{} ok".format(batch_num, total_batches, len(results), len(batch)))

    print("\n下载完成：成功 {}，失败 {}".format(ok_count, fail_count))
    if failed:
        print("失败文件（前 20 个）:")
        for p in failed[:20]:
            print("  " + p)
    return ok_count, fail_count


# ============================================================
# 步骤3：清理
# ============================================================

def cleanup(dest_root):
    """删除 0 字节文件和指定目录。"""
    # 删除 0 字节文件（空的 readme 等）
    empty_count = 0
    for dirpath, dirnames, filenames in os.walk(dest_root):
        for fn in filenames:
            fp = os.path.join(dirpath, fn)
            try:
                if os.path.getsize(fp) == 0:
                    os.remove(fp)
                    empty_count += 1
            except OSError:
                pass
    if empty_count:
        print("删除 {} 个 0 字节文件".format(empty_count))

    # 删除根目录的 readme（占位文件，非教程内容）
    readme = os.path.join(dest_root, "readme.md")
    if os.path.isfile(readme):
        os.remove(readme)
        print("删除 readme.md")

    # 删除指定目录
    for rel_dir in PRUNE_DIRS:
        target = os.path.join(dest_root, *rel_dir.split("/"))
        if os.path.isdir(target):
            import shutil
            file_count = sum(len(files) for _, _, files in os.walk(target))
            shutil.rmtree(target)
            print("删除目录 {} ({} 个文件)".format(rel_dir, file_count))

    # 清理空目录
    for dirpath, dirnames, filenames in os.walk(dest_root, topdown=False):
        if not os.listdir(dirpath) and dirpath != dest_root:
            os.rmdir(dirpath)


# ============================================================
# 主流程
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="从 GitHub 下载 mcguide md 文件")
    parser.add_argument("--output", default=DEFAULT_OUTPUT,
                        help="输出目录（默认 {}）".format(DEFAULT_OUTPUT))
    parser.add_argument("--no-proxy", action="store_true", help="不走代理")
    args = parser.parse_args()

    dest_root = args.output
    print("输出目录: {}".format(dest_root))

    token = get_token()
    if not token:
        print("错误：无法从 git credential 获取 GitHub token")
        sys.exit(1)
    print("已获取 GitHub token")

    use_proxy = not args.no_proxy
    opener = make_opener(use_proxy)
    print("代理: {}".format("启用 " + PROXY_URL if use_proxy else "禁用"))

    # 步骤1：获取文件树
    print("\n=== 步骤1：获取文件树 ===")
    tree = get_tree(opener, token)
    md_paths = [
        item["path"] for item in tree
        if item["type"] == "blob"
        and item["path"].startswith("mcguide/")
        and item["path"].lower().endswith(".md")
    ]
    print("mcguide 下共 {} 个 md 文件".format(len(md_paths)))

    # 步骤2：下载
    print("\n=== 步骤2：下载 ===")
    os.makedirs(dest_root, exist_ok=True)
    download_all(opener, token, md_paths, dest_root)

    # 步骤3：清理
    print("\n=== 步骤3：清理 ===")
    cleanup(dest_root)

    # 统计
    remaining = sum(len(files) for _, _, files in os.walk(dest_root))
    total_size = sum(
        os.path.getsize(os.path.join(dp, fn))
        for dp, _, fns in os.walk(dest_root) for fn in fns
    )
    print("\n最终: {} 个文件, {:.1f} KB".format(remaining, total_size / 1024.0))


if __name__ == "__main__":
    main()
