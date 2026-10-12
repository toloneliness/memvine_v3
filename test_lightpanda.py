# f:\memvine_v3\test_LIGHTPANDA_CMD.py
"""
Lightpanda 功能测试脚本 (Windows ↔ WSL 跨系统版)
- MemVine 项目运行在 Windows
- Lightpanda 安装在 WSL
- 通过 wsl 命令桥接调用
- LLM 使用 LM Studio (Windows 上 localhost:7777)
"""
import subprocess
import os
import sys
import time
import platform

# ── 从 config 读取 LLM 配置 ──
LLM_BASE_URL = os.getenv("MEMVINE_LLM_URL", "http://localhost:7777/v1")
LLM_API_KEY = os.getenv("MEMVINE_LLM_KEY", "lm-studio")
LLM_MODEL = os.getenv("MEMVINE_LLM_MODEL", "qwen/qwen3.5-9b")

# ── 跨系统检测 ──
IS_WINDOWS = platform.system() == "Windows"

WSL_AVAILABLE = False
if IS_WINDOWS:
    try:
        r = subprocess.run(["wsl", "--version"], capture_output=True, text=True, timeout=5)
        WSL_AVAILABLE = r.returncode == 0
    except Exception:
        pass

# 从 WSL 获取 Windows 宿主 IP（WSL 访问 Windows 上 LM Studio 用）
WINDOWS_HOST_IP = "localhost"
if IS_WINDOWS and WSL_AVAILABLE:
    try:
        # 方法1: 通过 ip route 获取默认网关，即 Windows 宿主
        r = subprocess.run(
            ["wsl", "bash", "-c", "ip route show default 2>/dev/null | awk '{print $3}' || echo ''"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            WINDOWS_HOST_IP = r.stdout.strip().split("\n")[0].strip()
    except Exception:
        pass

    # 方法2: 如果 ip route 失败，尝试 mDNS
    if WINDOWS_HOST_IP == "localhost" or not WINDOWS_HOST_IP:
        try:
            r = subprocess.run(
                ["wsl", "bash", "-c", "hostname"],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0 and r.stdout.strip():
                WINDOWS_HOST_IP = f"{r.stdout.strip()}.local"
        except Exception:
            WINDOWS_HOST_IP = "localhost"

# 探测 Lightpanda 在 WSL 中的路径
LIGHTPANDA_CMD = "LIGHTPANDA_CMD"
if IS_WINDOWS and WSL_AVAILABLE:
    try:
        # 先尝试用 login shell 查找
        r = subprocess.run(
            ["wsl", "bash", "-lc", "which LIGHTPANDA_CMD 2>/dev/null || echo ''"],
            capture_output=True, text=True, timeout=5,
        )
        lp_path = r.stdout.strip()
        if lp_path:
            LIGHTPANDA_CMD = lp_path
        else:
            # 尝试常见路径
            for path in ["$HOME/.local/bin/LIGHTPANDA_CMD", "$HOME/bin/LIGHTPANDA_CMD", "/usr/local/bin/LIGHTPANDA_CMD"]:
                r = subprocess.run(
                    ["wsl", "bash", "-c", f"test -x {path} && echo '{path}' || echo ''"],
                    capture_output=True, text=True, timeout=5,
                )
                if r.stdout.strip():
                    LIGHTPANDA_CMD = r.stdout.strip()
                    break
    except Exception:
        pass
def _to_wsl_url(url: str) -> str:
    """将 Windows localhost URL 转为 WSL 内可访问的宿主 IP"""
    if IS_WINDOWS and WINDOWS_HOST_IP != "localhost":
        return url.replace("localhost", WINDOWS_HOST_IP).replace("127.0.0.1", WINDOWS_HOST_IP)
    return url

WSL_LLM_BASE_URL = _to_wsl_url(LLM_BASE_URL)

SEP = "=" * 60

def run(cmd_args: list, timeout: int = 60, extra_env: dict = None) -> subprocess.CompletedProcess:
    """
    运行命令。
    Windows → 通过 wsl bash -c 调用
    WSL/Linux → 直接调用
    """
    if IS_WINDOWS:
        # 构建 WSL 内的环境变量
        env_vars = [
            f"OPENAI_API_KEY='{LLM_API_KEY}'",
            f"OPENAI_BASE_URL='{WSL_LLM_BASE_URL}'",
        ]
        if extra_env:
            for k, v in extra_env.items():
                env_vars.append(f"{k}='{v}'")

        env_str = " ".join(env_vars)
        cmd_str = " ".join(cmd_args)
        full_cmd = ["wsl", "bash", "-lc", f"{env_str} {cmd_str}"]
    else:
        env = os.environ.copy()
        env["OPENAI_API_KEY"] = LLM_API_KEY
        env["OPENAI_BASE_URL"] = WSL_LLM_BASE_URL
        if extra_env:
            env.update(extra_env)
        full_cmd = cmd_args

    return subprocess.run(
        full_cmd,
        capture_output=True, text=True, timeout=timeout,
        **( {} if IS_WINDOWS else {"env": env} ),
    )

# ═══════════════════════════════════════════════════════════
# 测试用例
# ═══════════════════════════════════════════════════════════

def test_version():
    """测试 1: 检查 Lightpanda 是否可用"""
    print(f"\n{SEP}")
    print("📋 测试 1: LIGHTPANDA_CMD version")
    print(SEP)
    try:
        r = run(["LIGHTPANDA_CMD", "version"], timeout=10)
        if r.returncode == 0:
            print(f"✅ 已安装，版本输出:\n{r.stdout.strip()}")
            return True
        else:
            print(f"❌ 返回码异常: {r.returncode}\n{r.stderr.strip()[:300]}")
            return False
    except FileNotFoundError:
        print("❌ 未找到 LIGHTPANDA_CMD 命令")
        return False
    except subprocess.TimeoutExpired:
        print("❌ 超时")
        return False

def test_fetch():
    """测试 2: 静态页面抓取"""
    print(f"\n{SEP}")
    print("📋 测试 2: LIGHTPANDA_CMD fetch (静态抓取)")
    print(SEP)
    url = "https://example.com"
    print(f"   目标: {url}")

    try:
        r = run(["LIGHTPANDA_CMD", "fetch", url], timeout=30)
        if r.returncode == 0:
            content = r.stdout.strip()
            print(f"✅ 抓取成功！返回 {len(content)} 字符")
            print(f"   前 200 字符:\n   {content[:200]}…")
            return True
        else:
            print(f"❌ 抓取失败: {r.stderr.strip()[:300]}")
            return False
    except subprocess.TimeoutExpired:
        print("❌ 超时 (30s)")
        return False

def test_fetch_dump():
    """测试 3: fetch --dump markdown"""
    print(f"\n{SEP}")
    print("📋 测试 3: LIGHTPANDA_CMD fetch --dump markdown")
    print(SEP)
    url = "https://example.com"
    try:
        r = run(["LIGHTPANDA_CMD", "fetch", "--dump", "markdown", url], timeout=30)
        if r.returncode == 0:
            content = r.stdout.strip()
            print(f"✅ Markdown 抓取成功！返回 {len(content)} 字符")
            print(f"   前 200 字符:\n   {content[:200]}…")
            return True
        else:
            print(f"❌ 失败: {r.stderr.strip()[:200]}")
            return False
    except subprocess.TimeoutExpired:
        print("❌ 超时")
        return False

def test_agent_simple():
    """测试 4: agent --task 简单浏览"""
    print(f"\n{SEP}")
    print("📋 测试 4: LIGHTPANDA_CMD agent --task (Agent 模式)")
    print(SEP)
    task = "Go to https://example.com, read the page, and return a one-sentence summary."
    print(f"   任务: {task[:80]}…")
    print(f"   LLM: {LLM_MODEL} @ {LLM_BASE_URL}")
    print(f"   WSL 内 LLM: {WSL_LLM_BASE_URL}")

    try:
        r = run(
            ["LIGHTPANDA_CMD", "agent", "--provider", "openai",
             "--base-url", WSL_LLM_BASE_URL, "--model", LLM_MODEL, "--task", task],
            timeout=120,
        )
        if r.returncode == 0:
            output = r.stdout.strip()
            print(f"✅ Agent 任务完成！输出 {len(output)} 字符")
            print(f"   结果:\n   {output[:500]}{'…' if len(output) > 500 else ''}")
            return True
        else:
            print(f"❌ Agent 失败: {r.stderr.strip()[:500]}")
            return False
    except subprocess.TimeoutExpired:
        print("❌ 超时 (120s)")
        return False

def test_agent_search():
    """测试 5: agent --task 搜索"""
    print(f"\n{SEP}")
    print("📋 测试 5: LIGHTPANDA_CMD agent --task 搜索")
    print(SEP)
    task = "Search for 'LIGHTPANDA_CMD browser github stars' and tell me the result."
    try:
        r = run(
            ["LIGHTPANDA_CMD", "agent", "--provider", "openai",
             "--base-url", WSL_LLM_BASE_URL, "--model", LLM_MODEL, "--task", task],
            timeout=180,
        )
        if r.returncode == 0:
            output = r.stdout.strip()
            print(f"✅ 搜索任务完成！输出 {len(output)} 字符")
            print(f"   结果:\n   {output[:600]}{'…' if len(output) > 600 else ''}")
            return True
        else:
            print(f"❌ 搜索失败: {r.stderr.strip()[:500]}")
            return False
    except subprocess.TimeoutExpired:
        print("❌ 超时 (180s)")
        return False

def test_agent_script():
    """测试 6: agent --task --save 导出脚本"""
    print(f"\n{SEP}")
    print("📋 测试 6: LIGHTPANDA_CMD agent --task --save (导出 PandaScript)")
    print(SEP)
    task = "Go to https://example.com and extract the page title."
    script_path = "/tmp/test_LIGHTPANDA_CMD_script.js"
    try:
        r = run(
            ["LIGHTPANDA_CMD", "agent", "--provider", "openai",
             "--base-url", WSL_LLM_BASE_URL, "--model", LLM_MODEL,
             "--task", task, "--save", script_path],
            timeout=120,
        )
        if r.returncode == 0:
            # 检查 WSL 内是否生成了文件
            check = run(["test", "-f", script_path, "&&", "cat", script_path], timeout=10)
            if check.returncode == 0 and check.stdout.strip():
                print(f"✅ 脚本已导出: {script_path} ({len(check.stdout)} 字符)")
                print(f"   脚本前 300 字符:\n   {check.stdout[:300]}…")
                run(["rm", "-f", script_path], timeout=5)
                return True
            else:
                print("⚠️ 任务完成但未生成脚本文件")
                return False
        else:
            print(f"❌ 失败: {r.stderr.strip()[:300]}")
            return False
    except subprocess.TimeoutExpired:
        print("❌ 超时")
        return False

def test_agent_no_llm():
    """测试 7: agent --no-llm 启动验证"""
    print(f"\n{SEP}")
    print("📋 测试 7: LIGHTPANDA_CMD agent --no-llm (启动验证)")
    print(SEP)
    print("   验证 LIGHTPANDA_CMD agent 在无 LLM 模式下能否启动…")

    try:
        r = run(
            ["timeout", "4", "LIGHTPANDA_CMD", "agent", "--no-llm"],
            timeout=10,
        )
        # timeout 命令返回 124 表示超时（正常，说明进程存活了 4 秒）
        if r.returncode in (0, 124):
            print("✅ --no-llm 模式启动成功，进程存活 4 秒后被终止")
            return True
        else:
            print(f"❌ 进程异常退出 (code={r.returncode})")
            print(f"   stderr: {r.stderr.strip()[:300]}")
            return False
    except subprocess.TimeoutExpired:
        print("❌ 超时")
        return False

def test_agent_info():
    """测试 8: 检查 agent --help 支持的功能"""
    print(f"\n{SEP}")
    print("📋 测试 8: LIGHTPANDA_CMD agent --help (功能检查)")
    print(SEP)
    try:
        r = run(["LIGHTPANDA_CMD", "agent", "--help"], timeout=10)
        output = r.stdout.strip()
        checks = {
            "--base-url": "自定义端点",
            "--model": "指定模型",
            "--save": "导出脚本",
            "--task": "单次任务",
            "--no-llm": "无 LLM 模式",
            "--provider": "多 Provider",
        }
        for flag, desc in checks.items():
            icon = "✅" if flag in output else "❌"
            print(f"   {icon} {desc} ({flag})")
        return True
    except Exception as e:
        print(f"❌ 异常: {e}")
        return False

# ═══════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════

def main():
    print(f"{SEP}")
    print("🧪 Lightpanda 功能测试 (Windows ↔ WSL 跨系统)")
    print(f"{SEP}")
    print(f"   运行环境:      {'Windows' if IS_WINDOWS else platform.system()}")
    print(f"   WSL 可用:      {WSL_AVAILABLE}")
    if IS_WINDOWS and WSL_AVAILABLE:
        print(f"   Windows 宿主 IP: {WINDOWS_HOST_IP}")
        print(f"   Lightpanda:    {LIGHTPANDA_CMD}")
    print(f"   LLM 配置:      {LLM_MODEL} @ {LLM_BASE_URL}")
    print(f"   WSL 内 LLM:    {WSL_LLM_BASE_URL}")
    print(f"   API Key:       {'***' + LLM_API_KEY[-4:] if len(LLM_API_KEY) > 4 else '***'}")

    if IS_WINDOWS and not WSL_AVAILABLE:
        print("\n❌ 当前在 Windows 上但 WSL 不可用，请先安装 WSL 并在其中安装 Lightpanda。")
        sys.exit(1)

    results = {}

    # ── 基础检查（不需要 LLM）──
    results["version"] = test_version()
    if not results["version"]:
        print("\n⚠️ Lightpanda 不可用，跳过后续测试。")
        print_summary(results)
        sys.exit(1)

    results["agent_info"] = test_agent_info()
    results["fetch"] = test_fetch()
    results["fetch_dump"] = test_fetch_dump()
    results["no_llm"] = test_agent_no_llm()

    # ── Agent 模式（需要 LLM）──
    print(f"\n{SEP}")
    print("⚠️ 以下测试需要 LLM，请确保 LM Studio 已启动并加载模型")
    print(f"   Windows 地址: {LLM_BASE_URL}")
    print(f"   WSL 访问地址: {WSL_LLM_BASE_URL}")
    print(SEP)

    if WINDOWS_HOST_IP != "localhost":
        print(f"\n💡 提示: 如果 WSL 无法访问 LM Studio，请检查:")
        print(f"   1. LM Studio 是否开启了本地网络访问 (Settings → Local Network Access)")
        print(f"   2. Windows 防火墙是否放行端口 7777")
        print(f"   3. 尝试在 WSL 中运行: curl {WSL_LLM_BASE_URL}/models")

    input("\n按 Enter 继续…")

    results["agent_simple"] = test_agent_simple()
    results["agent_search"] = test_agent_search()
    results["agent_script"] = test_agent_script()

    print_summary(results)

def print_summary(results: dict):
    print(f"\n\n{SEP}")
    print("📊 测试汇总")
    print(SEP)
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    for name, ok in results.items():
        print(f"   {'✅' if ok else '❌'} {name}")
    print(f"\n   通过: {passed}/{total}")
    if passed == total:
        print("🎉 全部通过！Lightpanda 与 MemVine 跨系统连接正常。")
    elif passed >= total - 2:
        print("⚠️ 大部分通过，少数失败可能因网络或模型问题。")
    else:
        print("❌ 多项失败，请检查 WSL 安装和 LLM 连通性。")

if __name__ == "__main__":
    main()