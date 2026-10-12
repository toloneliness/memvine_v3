import json
import pendulum
from pathlib import Path

class ChatLogger:
    """
    数字生命体原始对话记录仪（只追加，不修改，绝对安全）。
    使用 JSONL 格式，每行一条记录，支持流式写入和人类阅读。
    """

    def __init__(self, log_dir="memvine_logs", clock=None):
        self.clock = clock
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._update_log_path()

    def _update_log_path(self):
        today = self.clock.now_local().format('YYYY-MM-DD') if self.clock else pendulum.now().format('YYYY-MM-DD')
        self.current_log_path = self.log_dir / f"memvine_chat_{today}.jsonl"

    def log_message(self, speaker: str, content: str, metadata: dict = None):
        """
        记录一条原始对话。speaker 为 "user" 或 "memvine"。
        """
        record = {
            "timestamp": self.clock.now_local().isoformat() if self.clock else pendulum.now().isoformat(),
            "speaker": speaker,
            "content": content,
            "metadata": metadata or {}
        }

        try:
            self._update_log_path()
            with open(self.current_log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(record, ensure_ascii=False) + '\n')
        except Exception as e:
            print(f"[日志警告] 聊天记录写入失败: {e}")

    def log_prompt(self, user_input: str, final_prompt: str, llm_reply: str):
        """
        记录最终提示词、用户输入和 LLM 回复，人类可读格式。
        """
        timestamp = self.clock.now_local().format('YYYY-MM-DD HH:mm:ss') if self.clock else pendulum.now().format('YYYY-MM-DD HH:mm:ss')
        self._update_log_path()
        prompt_log_path = self.log_dir / f"memvine_prompt_{self.clock.now_local().format('YYYY-MM-DD') if self.clock else pendulum.now().format('YYYY-MM-DD')}.log"

        separator = "=" * 70

        parts = [
            "",
            separator,
            f"[{timestamp}]",
            separator,
            "",
            ">>> 用户输入:",
            user_input,
            "",
            ">>> 最终提示词 (发送给 LLM 的完整内容):",
            "-" * 50,
            final_prompt,
            "-" * 50,
            "",
            "<<< LLM 回复:",
            llm_reply,
            "",
            separator,
            "",
        ]

        try:
            with open(prompt_log_path, 'a', encoding='utf-8') as f:
                f.write("\n".join(parts))
            print(f"   📝 [提示词日志] 已写入 {prompt_log_path}")
        except Exception as e:
            print(f"   ⚠️ [提示词日志] 写入失败: {e}")

    def log_pipeline(self, round_data: dict):
        """
        记录完整一轮对话管道数据（人类可读格式，追加到 prompt 日志）。
        """
        timestamp = round_data.get("timestamp", "")
        self._update_log_path()
        path = self.log_dir / f"memvine_prompt_{self.clock.now_local().format('YYYY-MM-DD') if self.clock else pendulum.now().format('YYYY-MM-DD')}.log"

        semantic = round_data.get("semantic", {})
        graph = round_data.get("graph", {})
        docs = round_data.get("documents", {})
        awareness = round_data.get("awareness", {})
        cogniweave = round_data.get("cogniweave")

        parts = []
        parts.append("=" * 70)
        parts.append(f"[{timestamp}]  #{round_data.get('round', '?')}  {round_data.get('path', '?')}")
        parts.append("=" * 70)

        # 用户输入
        parts.append(f"\n📩 用户: {round_data.get('user_input', '')}")

        # 语义提取
        parts.append(f"\n── 🔍 语义提取 ──")
        parts.append(f"  action={semantic.get('action','?')}  "
                     f"emotion={semantic.get('emotion','?')}  "
                     f"domain={semantic.get('domain','?')}  "
                     f"load={semantic.get('cognitive_load',0)}")
        parts.append(f"  target={semantic.get('target','')}  "
                     f"entities={semantic.get('entities',[])}")

        # 并行检索
        parts.append(f"\n── 📊 并行检索 ──")
        parts.append(f"  图: {graph.get('count',0)}条  "
                     f"top={graph.get('top_score',0):.3f}  "
                     f"avg={graph.get('avg_score',0):.3f}  "
                     f"类型={graph.get('type_dist',{})}")
        d_count = docs.get("count", 0)
        d_sim = docs.get("top_similarity")
        d_flag = "✅" if d_count > 0 else "⚠️"
        parts.append(f"  文档: query='{docs.get('query','')}' → {d_count}条 {d_flag}"
                     + (f"  sim={d_sim:.3f}" if d_sim else ""))
        parts.append(f"  自我知识: {'有' if round_data.get('self_knowledge') else '无'}  "
                     f"近期对话: {round_data.get('recent_rounds',0)}轮")

        # CogniWeave
        if cogniweave:
            parts.append(f"\n── 🧠 CogniWeave ──")
            parts.append(f"  议程: {cogniweave.get('agenda_count',0)}查询  "
                         f"成功: {cogniweave.get('success_count',0)}  "
                         f"耗时: {cogniweave.get('total_time',0):.2f}s")
            for q in cogniweave.get("queries", [])[:5]:
                parts.append(f"    q{q.get('id','?')}: {q.get('intent','')[:80]}")

        # 回复
        parts.append(f"\n── 💬 回复 (valence={round_data.get('valence',0):.2f}) ──")
        parts.append(round_data.get("llm_reply", ""))
        parts.append("")

        try:
            with open(path, 'a', encoding='utf-8') as f:
                f.write("\n".join(parts) + "\n")
            print(f"   📋 [管道日志] 已写入 {path}")
        except Exception as e:
            print(f"   ⚠️ [管道日志] 写入失败: {e}")

    def generate_graph_context(self, cortex, structured: dict) -> str:
        G = cortex.topology.graph
        n_nodes = G.number_of_nodes()
        n_edges = G.number_of_edges()
        oldest = self.clock.now_ts()
        for n in G.nodes:
            ts = G.nodes[n].get("created_at", oldest)
            if isinstance(ts, (int, float)):
                oldest = min(oldest, ts)
        age_hours = (self.clock.now_ts() - oldest) / 3600.0
        state = cortex.state_observer.observe(
            last_talk_ts=getattr(cortex, '_last_talk_ts', 0),
        )
        stats = state.get("stats", {})

        instruction = structured["instruction"]
        graph_results = structured["graph_results"]

        lines = []

        lines.append("▎意图路由")
        action = instruction.get("matched_action", "表达")
        strategy_name = instruction.get("strategy_name", "anchor_walk")
        mode = instruction.get("response_mode", "共鸣")
        lines.append(f"  输入: {cortex.last_user_input[:60]}")
        lines.append(f"  识别: {action} → 策略: {strategy_name}, 模式={mode}")

        lines.append("▎图状态")
        lines.append(f"  节点: {n_nodes}    边: {n_edges}    图龄: {age_hours:.1f}h")
        lines.append(f"  节点={stats.get('nodes',0)} 边={stats.get('edges',0)} 待处理={stats.get('pending_issues',0)} → 策略={strategy_name}")

        lines.append("▎核心记忆")
        core = cortex.topology.find_core_memories()
        if core and core.get("core_memories"):
            for idx, c in enumerate(core["core_memories"][:3]):
                mark = "★" if idx == 0 else "☆"
                lines.append(f"  {mark} [{c['score']:.2f}] {c['content'][:50]}")
        else:
            lines.append("  (暂无核心记忆)")

        lines.append("▎因果弧线")
        causal = graph_results.get("causal_inference") or cortex.topology.causal_inference()
        if causal and causal.get("causal_pairs"):
            chains = [cp for cp in causal["causal_pairs"] if cp["confidence"] > 0.5]
            for cp in chains[:3]:
                lines.append(f"  [{cp['confidence']:.2f}] {cp['direction']} ({cp['type']})")
        else:
            lines.append("  (暂无明确因果结构)")

        lines.append("▎社区结构")
        comms = cortex.topology.community_detect()
        if comms:
            for c in comms[:3]:
                first_content = c['members'][0]['content'][:30] if c['members'] else "空"
                lines.append(f"  [{c['size']:3d}条] 社区{c['community_id']}: {first_content}")

        lines.append("▎时间线")
        timeline = cortex.topology.get_timeline(limit=5)
        if timeline:
            for evt in timeline[-5:]:
                content = evt.get("content", "")[:40]
                lines.append(f"  〡 {content}")

        lines.append("▎异常检测")
        anomalies = graph_results.get("detect_anomalies") or cortex.topology.detect_anomalies()
        if anomalies and anomalies.get("suspicious_nodes"):
            for a in anomalies["suspicious_nodes"][:3]:
                lines.append(f"  ⚠ [{a['anomaly_score']:.1f}σ] {a['reason']}: {a['content'][:40]}")
        else:
            lines.append("  ✅ 无显著异常")

        lines.append("▎模式发现")
        motifs = graph_results.get("detect_motifs") or cortex.topology.detect_motifs()
        if motifs and motifs.get("frequent_patterns"):
            for p in motifs["frequent_patterns"][:3]:
                lines.append(f"  🔄 出现{p['count']}次 → {' → '.join(p['pattern'])}")

        lines.append("▎结构洞")
        holes = graph_results.get("structural_holes") or cortex.topology.structural_holes()
        if holes:
            for h in holes[:3]:
                lines.append(f"  🔍 [{h['constraint']:.3f}] {h['content'][:40]}")
                for mb in h["missing_bridges"][:1]:
                    a, b = mb.get("between", ["?", "?"])
                    la = cortex.topology._short_label(a) if cortex.topology else a
                    lb = cortex.topology._short_label(b) if cortex.topology else b
                    lines.append(f"      '{la}' ↔ '{lb}' 缺少直接关联")
        else:
            lines.append("  (无明显结构洞)")

        lines.append("▎图摘要")
        summary = graph_results.get("summarize") or cortex.topology.summarize(target_groups=5)
        if summary and summary.get("super_nodes"):
            for sn in summary["super_nodes"][:3]:
                lines.append(f"  📦 {sn['label']} → {', '.join(sn['sample_contents'][:2])}")

        lines.append("▎驱动与待办")
        todos = []
        if anomalies and anomalies.get("suspicious_nodes"):
            todos.append("待确认: 存在异常节点，建议信念传播更新")
        if holes:
            for h in holes[:2]:
                for mb in h["missing_bridges"][:1]:
                    a, b = mb.get("between", ["?", "?"])
                    la = cortex.topology._short_label(a) if cortex.topology else a
                    lb = cortex.topology._short_label(b) if cortex.topology else b
                    todos.append(f"好奇心: '{la}' 与 '{lb}' 缺少直接关联")
        if n_nodes > 100 and summary and summary.get("compression_ratio", 1.0) > 0.2:
            todos.append("维护: 节点较多，建议休眠时深度整理压缩")
        if todos:
            for todo in todos:
                lines.append(f"  ◦ {todo}")
        else:
            lines.append("  ✅ 当前认知稳定，无待办")

        return "\n".join(lines)

    def log_graph_state(self, cortex, structured: dict, final_prompt: str = None) -> None:
        timestamp = self.clock.now_local().format('YYYY-MM-DD HH:mm:ss') if self.clock else pendulum.now().format('YYYY-MM-DD HH:mm:ss')
        self._update_log_path()
        report_path = self.log_dir / f"memvine_graph_{self.clock.now_local().format('YYYY-MM-DD') if self.clock else pendulum.now().format('YYYY-MM-DD')}.log"

        G = cortex.topology.graph
        n_nodes = G.number_of_nodes()
        n_edges = G.number_of_edges()

        sep = "═" * 70
        lines = []
        lines.append("")
        lines.append(sep)
        lines.append(f"  MemVine 认知报告  │  {timestamp}  │  节点 {n_nodes}  │  边 {n_edges}")
        lines.append(sep)
        lines.append("")
        if final_prompt:
            lines.append(final_prompt)
        else:
            lines.append(self.generate_graph_context(cortex, structured))
        lines.append("")
        lines.append(sep)
        lines.append("")

        try:
            with open(report_path, 'a', encoding='utf-8') as f:
                f.write("\n".join(lines))
            print(f"   📊 [认知报告] 已写入 {report_path}")
        except Exception as e:
            print(f"   ⚠️ [认知报告] 写入失败: {e}")