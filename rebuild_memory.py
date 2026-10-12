import json
import uuid
import pendulum
from pathlib import Path
from core.cortex import Cortex
from core.molecules import EventMolecule
from config import IDENTITY_EDGE_WEIGHT



def load_jsonl(filepath: str) -> list[dict]:
    messages = []
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                messages.append(json.loads(line))
    return messages


def rebuild_from_logs(cortex: Cortex, log_files: list[str]) -> dict:
    cortex._rebuild_mode = True
    stats = {
        "total_messages": 0,
        "user_messages": 0,
        "memvine_messages": 0,
        "nodes_created": 0,
        "identity_nodes": 0,
        "errors": []
    }

    print("=" * 60)
    print("🔄 开始从聊天日志重建记忆图谱（语义解析模式）...")
    print("=" * 60)

    for log_file in log_files:
        if not Path(log_file).exists():
            stats["errors"].append(f"文件不存在: {log_file}")
            continue

        messages = load_jsonl(log_file)
        print(f"\n📂 处理文件: {log_file} ({len(messages)} 条消息)")

        for i, msg in enumerate(messages):
            speaker = msg.get("speaker", "")
            content = msg.get("content", "")
            metadata = msg.get("metadata", {})
            timestamp_str = msg.get("timestamp", "")

            if not content.strip():
                continue

            stats["total_messages"] += 1

            try:
                ts = pendulum.parse(timestamp_str) if timestamp_str else pendulum.now('Asia/Shanghai')
            except Exception:
                ts = pendulum.now('Asia/Shanghai')

            valence = metadata.get("valence", 0.0)
            now_ts = ts.timestamp()

            if speaker == "user":
                cortex._ingest_with_semantics(content, "user", valence, now_ts)
                stats["user_messages"] += 1
                stats["nodes_created"] += 1

            elif speaker == "memvine":
                cortex._ingest_with_semantics(content, "self", valence, now_ts)
                stats["memvine_messages"] += 1
                stats["nodes_created"] += 1

            if (i + 1) % 5 == 0:
                print(f"   已处理 {i + 1}/{len(messages)} 条...")

    identity_count = _count_identity_edges(cortex)
    stats["identity_nodes"] = identity_count
    cortex._rebuild_mode = False

    return stats


def _count_identity_edges(cortex: Cortex) -> int:
    count = 0
    for _, _, data in cortex.topology.graph.edges(data=True):
        if data.get("relation", "").startswith("identity_"):
            count += 1
    return count


def main():
    print("\n" + "=" * 60)
    print("🧠 MemVine v3 图库重建工具（语义解析版）")
    print("=" * 60)

    save_path = Path("memvine_saves/memvine_active.json")
    if save_path.exists():
        backup_name = f"memvine_saves/memvine_old_{int(time.time())}.json"
        import shutil
        shutil.move(str(save_path), backup_name)
        print(f"📦 旧存档已备份至: {backup_name}")

    cortex = Cortex()

    log_dir = Path("memvine_logs")
    if not log_dir.exists():
        print("❌ 未找到 memvine_logs 目录，无法重建。")
        return

    log_files = sorted(str(f) for f in log_dir.glob("memvine_chat_*.jsonl"))

    if not log_files:
        print("❌ 未找到任何聊天日志文件。")
        return

    print(f"📚 发现 {len(log_files)} 个日志文件:")
    for f in log_files:
        print(f"   - {f}")

    stats = rebuild_from_logs(cortex, log_files)

    cortex.topology.discover_self()
    cortex._rebuild_identity_edges()
    root = cortex.topology.find_root_node()

    cortex.save()

    # tension 已随 emotion 模块移除
    tension = 0
    identity = cortex._extract_identity()

    print("\n" + "=" * 60)
    print("✅ 重建完成！")
    print("=" * 60)
    print(f"\n📊 统计信息:")
    print(f"   总消息数:     {stats['total_messages']}")
    print(f"   用户消息:     {stats['user_messages']}")
    print(f"   生命体回复:   {stats['memvine_messages']}")
    print(f"   记忆节点:     {cortex.topology.graph.number_of_nodes()}")
    print(f"   突触连接:     {cortex.topology.graph.number_of_edges()}")
    print(f"   身份边:       {stats['identity_nodes']}")
    print(f"   轨迹数:       {len(cortex.topology.traces)}")
    print(f"\n⚡ 当前能量状态:")
    state = cortex.state_observer.observe(
        last_talk_ts=getattr(cortex, '_last_talk_ts', 0),
    )
    print(f"   认知负载:     {state['load']}")
    print(f"   信息代谢:     {state['metabolism']}")
    print(f"\n🧠 自我认知:")
    print(f"   根节点ID:     {root}")
    print(f"   身份摘要:     {identity}")

    if stats["errors"]:
        print(f"\n⚠️ 警告 ({len(stats['errors'])} 个):")
        for err in stats["errors"]:
            print(f"   - {err}")

    print(f"\n💾 新存档已保存（语义解析格式）")
    print(f"   下次启动将自动加载，可直接开始对话。")


if __name__ == "__main__":
    main()