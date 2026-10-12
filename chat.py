# chat.py

import time
import sys
from core.cortex import Cortex
from core.user_registry import UserRegistry
from core.document_importer import DocumentImporter
import os


if __name__ == "__main__":
    # ── 用户注册拦截 ──
    registry = UserRegistry()

    print("=" * 60)
    print("🧠 MemVine v3 数字生命体 — 对话模式")
    print("=" * 60)

    user_id = input("\n👤 请输入你的ID (回车跳过=陌生人): ").strip()
    if not user_id:
        user_id = "stranger"
        print("   以陌生人身份进入...")
    else:
        profile = registry.get_or_create(user_id)
        if profile.first_seen < profile.last_seen:
            from datetime import datetime
            first = datetime.fromtimestamp(profile.first_seen).strftime("%Y-%m-%d %H:%M")
            print(f"   欢迎回来！首次注册于 {first}，已对话 {profile.message_count} 次")
        else:
            print(f"   新用户注册成功！")

    cortex = Cortex()
    importer = DocumentImporter(cortex)

    print("\n💬 你可以开始和这个数字生命体对话了。")
    print("   输入 'quit' 退出 | ':user' 切换用户 | 'status' 查看状态\n")

    while True:
        try:
            user_input = input(f"👤 [{user_id}]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n👋 {cortex.get_identity_name() or '系统'} 进入休眠...")
            break

        if not user_input:
            continue
        if user_input.lower() == "quit":
            print("💾 [持久化] 保存记忆...")
            cortex.save()
            identity = cortex.get_identity_name()
            print(f"👋 {identity or '系统'} 进入休眠...")
            break

        # ── 用户切换快捷键 ──
        if user_input.lower() == ":user":
            print(f"\n   当前用户: {user_id}")
            new_id = input("   切换为 (回车保持当前 / 输入 'stranger' 降级): ").strip()
            if new_id:
                user_id = new_id if new_id.lower() != "stranger" else "stranger"
                if user_id != "stranger":
                    profile = registry.get_or_create(user_id)
                    if profile.first_seen < profile.last_seen:
                        from datetime import datetime
                        first = datetime.fromtimestamp(profile.first_seen).strftime("%Y-%m-%d %H:%M")
                        print(f"   欢迎回来！首次注册于 {first}，已对话 {profile.message_count} 次")
                    else:
                        print(f"   新用户注册成功！")
                else:
                    print("   以陌生人身份继续...")
            print()
            continue

        if user_input.lower() == "save":
            cortex.save()
            continue
        if user_input.lower() == "status":
            stats = cortex.get_stats()
            print(f"📊 节点: {stats['node_count']} | 边: {stats['edge_count']}")
            print(f"   知识: {stats['knowledge_edges']} | 身份: {stats['identity_edges']} | 时间: {stats['timeline_edges']}")
            print(f"   预存储池: {stats['prestore_size']}条 | 对话轮次: {stats['turn_count']}")
            continue

        if user_input.lower().startswith("import"):
            parts = user_input.split(maxsplit=2)
            if len(parts) < 2:
                print("📥 import 用法:")
                print("   import file <路径>         导入单个文件")
                print("   import dir <目录>          导入目录下所有文件")
                print("   import url <网址>          导入网页")
                print("   import dir <目录> -r       递归导入子目录")
                continue

            sub = parts[1]
            target = parts[2] if len(parts) > 2 else ""

            if sub == "file" and target:
                print(f"📥 导入文件: {target}")
                result = importer.import_file(target, user_id=user_id)
                print(f"   ✅ 成功: {result['success']}, 段数: {result['chunks']}")
                if result["errors"]:
                    for e in result["errors"]:
                        print(f"   ⚠️ {e}")

            elif sub == "dir" and target:
                recursive = "-r" in user_input
                print(f"📥 批量导入目录: {target} {'(递归)' if recursive else ''}")
                result = importer.import_directory(target, user_id=user_id, recursive=recursive)
                print(f"   ✅ 扫描: {result['total']} 个文件, 成功导入: {result['imported']}, 总段数: {result['total_chunks']}")

            elif sub == "url" and target:
                print(f"📥 抓取网页: {target}")
                result = importer.import_url(target, user_id=user_id)
                print(f"   ✅ 成功: {result['success']}, 段数: {result['chunks']}")
                if result.get("title"):
                    print(f"   📄 标题: {result['title']}")
                if result["errors"]:
                    for e in result["errors"]:
                        print(f"   ⚠️ {e}")

            else:
                print("📥 import 用法: import file <路径> | import dir <目录> | import url <网址>")
            continue


        # ── 自动识别：拖入文件路径 ──
        stripped = user_input.strip().strip('"').strip("'")
        if os.path.exists(stripped):
            if os.path.isfile(stripped):
                print(f"📥 检测到文件拖入: {os.path.basename(stripped)}")
                result = importer.import_file(stripped, user_id=user_id)
                print(f"   ✅ 成功: {result['success']}, 段数: {result['chunks']}")
                if result["errors"]:
                    for e in result["errors"]:
                        print(f"   ⚠️ {e}")
                continue
            elif os.path.isdir(stripped):
                print(f"📥 检测到目录拖入: {stripped}")
                result = importer.import_directory(stripped, user_id=user_id)
                print(f"   ✅ 扫描: {result['total']} 个文件, 成功导入: {result['imported']}, 总段数: {result['total_chunks']}")
                continue

        # ── 自动识别：粘贴网址 ──
        if user_input.startswith("http://") or user_input.startswith("https://"):
            print(f"📥 检测到网址: {user_input[:60]}...")
            result = importer.import_url(user_input, user_id=user_id)
            print(f"   ✅ 成功: {result['success']}, 段数: {result['chunks']}")
            if result.get("title"):
                print(f"   📄 标题: {result['title']}")
            if result["errors"]:
                for e in result["errors"]:
                    print(f"   ⚠️ {e}")
            continue

        reply = cortex.chat(user_input, user_id=user_id)
        identity = cortex.get_identity_name()
        print(f"🤖 {identity or ''}: {reply}\n")