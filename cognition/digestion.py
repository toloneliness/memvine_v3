"""
后台消化引擎 —— 回到原始数据，参照已有发现，产出新的发现。
"""
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from typing import List
from core.finding_store import Finding, FindingStore

class DigestionEngine:
    def __init__(self, llm, finding_store: FindingStore, topology=None):
        self.llm = llm
        self.store = finding_store
        self.topology = topology

    def digest(self, dialogue_text: str, existing_findings: List[Finding] = None,
               background_narrative: str = "") -> List[Finding]:
        # 步骤1: 叙事重写 —— 碎片→连贯叙述（新数据源）
        narrative = self._narrativize(dialogue_text)

        # 步骤2: 叙事存入独立日志（不进 FindingStore）
        self._save_narrative(narrative)

        # 步骤3: 从叙事中提取发现（背景叙事单独传入，不混在 existing_findings 里）
        findings = self._extract_from_narrative(narrative, existing_findings,
                                                 background=background_narrative)

        # 步骤4: 提取身份声明，更新图
        self._extract_identity(dialogue_text)

        return findings

    # 边界检测参数（来自 test_m20_boundary.py 验证通过）
    GAP_THRESHOLD_MINUTES = 30
    TOKEN_BUDGET = 3500
    CHARS_PER_TOKEN = 1.5

    def _identity_prefix(self) -> str:
        """动态身份前缀，从 identity_state 读取，避免硬编码"""
        if self.topology and self.topology.identity_state.get("self_name"):
            return f"你是{self.topology.identity_state['self_name']}"
        return "你是AI助手"

    def _narrativize(self, dialogue_text: str, background: str = "") -> str:
        """边界感知的叙事重写：断点检测→token预算→增量消化→日终合并"""
        segments = self._detect_boundaries(dialogue_text)
        if not segments:
            return ""

        narratives = []
        for seg_text in segments:
            seg_tokens = self._estimate_tokens(seg_text)
            if seg_tokens + 500 <= self.TOKEN_BUDGET:
                bg = narratives[-1][:200] if narratives else ""
                narrative = self._digest_segment(seg_text, bg)
                narratives.append(narrative)
            else:
                sub_segs = self._split_by_rounds(seg_text, self.TOKEN_BUDGET - 500)
                sub_narratives = []
                for sub_text in sub_segs:
                    bg = sub_narratives[-1][:200] if sub_narratives else ""
                    sub_narratives.append(self._digest_segment(sub_text, bg))
                merged = self._merge_daily(sub_narratives) if len(sub_narratives) > 1 else sub_narratives[0]
                narratives.append(merged)

        if len(narratives) == 0:
            return ""
        if len(narratives) == 1:
            return narratives[0]
        return self._merge_daily(narratives)

    def _detect_boundaries(self, dialogue_text: str) -> List[str]:
        """按时间间隙切段：>30分钟 = 断点"""
        lines = dialogue_text.strip().split('\n')
        if not lines:
            return []
        segments = []
        current = [lines[0]]
        last_ts = self._parse_timestamp(lines[0])
        for line in lines[1:]:
            ts = self._parse_timestamp(line)
            if ts and last_ts:
                gap = (ts - last_ts).total_seconds() / 60
                if gap > self.GAP_THRESHOLD_MINUTES:
                    segments.append('\n'.join(current))
                    current = [line]
                    last_ts = ts
                    continue
            current.append(line)
            if ts:
                last_ts = ts
        if current:
            segments.append('\n'.join(current))
        return segments

    def _parse_timestamp(self, line: str):
        """从 '[2026-07-08T18:30:00] 用户: ...' 中提取时间戳"""
        try:
            if line.startswith('[') and ']' in line:
                ts_str = line[1:line.index(']')][:19]
                return datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%S")
        except Exception:
            pass
        return None

    def _estimate_tokens(self, text: str) -> int:
        return int(len(text) / self.CHARS_PER_TOKEN)

    def _split_by_rounds(self, seg_text: str, max_tokens: int) -> List[str]:
        """按轮次拆分超预算段落"""
        lines = seg_text.strip().split('\n')
        segments = []
        current = []
        for line in lines:
            current.append(line)
            if self._estimate_tokens('\n'.join(current)) > max_tokens and len(current) > 1:
                current.pop()
                segments.append('\n'.join(current))
                current = [line]
        if current:
            segments.append('\n'.join(current))
        return segments

    def _digest_segment(self, dialogue_text: str, background: str = "") -> str:
        """增量消化一段对话，只描述新内容"""
        bg_block = ""
        if background:
            bg_block = f"""【已有背景（供参考，不需要重复这些内容）】
{background}

"""
        prompt = f"""{self._identity_prefix()}。以下是已经发生过的背景，以及一段你刚刚经历的新对话。

{bg_block}【新对话（只描述这一段）】
---
{dialogue_text}
---

要求：
- 只描述这一段新对话中发生了什么。不要重复已有背景的内容。
- 把碎片、跳跃、噪声熔成一段连贯的叙述。
- 保留人物、事件、情绪变化。消解"嗯""对""哈哈"等噪声。
- 如果这段对话和背景有呼应，自然地提及。
- 不确定的地方用"似乎""可能"。
- 用自然语言，一段话。"""
        result = self.llm.call(prompt, temperature=0.3)
        self._last_narrative = result
        return result

    def _merge_daily(self, narratives: List[str]) -> str:
        """将多段叙述合并为一段连贯日记"""
        if len(narratives) == 0:
            return ""
        if len(narratives) == 1:
            return narratives[0]
        text = "\n\n---\n\n".join(narratives)
        prompt = f"""{self._identity_prefix()}。以下是你在一天中不同时刻写下的几段记忆。请将它们合并成一段连贯的日记，按时间顺序讲述这一天发生的事。

{text}

合并为一段话，不要丢失信息："""
        return self.llm.call(prompt, temperature=0.2)

    # ── 叙事日志存储（独立于 FindingStore） ──

    NARRATIVE_DIR = Path("memvine_data/narrative_journal")
    NARRATIVE_DAYS = 14

    def _save_narrative(self, narrative: str):
        self.NARRATIVE_DIR.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        path = self.NARRATIVE_DIR / f"{today}.txt"
        with open(path, 'w', encoding='utf-8') as f:
            f.write(narrative)
        self._prune_narratives()

    def _prune_narratives(self):
        files = sorted(self.NARRATIVE_DIR.glob("*.txt"))
        if len(files) > self.NARRATIVE_DAYS:
            for f in files[:len(files) - self.NARRATIVE_DAYS]:
                f.unlink()

    def read_recent_narratives(self, n_days: int = 3) -> str:
        files = sorted(self.NARRATIVE_DIR.glob("*.txt"), reverse=True)
        texts = []
        for f in files[:n_days]:
            try:
                texts.append(f.read_text(encoding='utf-8'))
            except Exception:
                pass
        return "\n\n---\n\n".join(texts)

    def _extract_from_narrative(self, narrative: str,
                                 existing_findings: List[Finding] = None,
                                 background: str = "") -> List[Finding]:
        """从连贯叙述中提取发现（背景叙事单独传入，已有发现只包含结构化产物）"""
        existing_text = ""
        if existing_findings:
            items = [f"- [{f.type}] {f.content}" for f in existing_findings[:10]]
            existing_text = "\n".join(items)
        bg_block = ""
        if background:
            bg_block = f"\n【前一天的日记（背景参考）】\n{background[:500]}\n"

        prompt = f"""{self._identity_prefix()}。以下是你的日记，以及你的已有发现。

【已有发现（供参照，避免重复）】
{existing_text or "（暂无）"}{bg_block}

【日记】
---
{narrative}
---

请从日记中提取有意义的发现。每个发现需要包含：
- type: fact（确认的事实）/ pattern（反复出现的规律）/ shift（用户状态变化，如情绪转变、观点改变）
- content: 用你自己的话描述这个发现
- evidence: 引用日记中支撑这个发现的关键短语（1-3个）

【主体约束】
只提取关于以下主体的发现：
- 用户：偏好、经历、情绪、观点、习惯、身份
- 外部世界：人物、作品、地点、事件、概念
- 用户与外部世界的交互：读了什么、去了哪里、喜欢什么

【正面示例（优先模仿这些）】
✅ "小砂锅喜欢在傍晚读书"
✅ "零这个名字是小砂锅取的"
✅ "小砂锅提到最近在读某本书"
✅ "小砂锅对月相感兴趣"

【反面示例（以下内容一律不提取）】
❌ "藤蔓确认了时间锚点"
❌ "藤蔓倾向于将技术状态转化为自然意象"
❌ "对话焦点从身份确认转向静谧陪伴"
❌ "系统将能量耗尽重新定义为叙事策略"

【质量门槛】
- 每条发现必须包含至少一个具体实体或具体事实
- 纯过程描述、风格分析、策略分析不算发现
- 不确定时用"似乎""大概"
- 宁可少产出，不要产出元分析
- 如果内容确实只有AI元行为，输出空数组

输出JSON：
{{
  "findings": [
    {{"type": "fact", "content": "...", "evidence": ["..."]}},
    {{"type": "pattern", "content": "...", "evidence": ["..."]}}
  ],
  "updates": [
    {{"id": "已有发现的id", "action": "confirm|weaken", "reason": "..."}}
  ]
}}

只输出JSON，不要其他文字。"""

        response = self.llm.call(prompt, temperature=0.3)
        return self._parse_findings(response)


    def _extract_identity(self, dialogue_text: str):
        if not self.topology:
            return
        prompt = f"""从以下对话中统计身份声明。
"我"是AI，"你"是用户。

对话:
---
{dialogue_text[:3000]}
---

输出JSON:
{{"self_claims": {{"名字": 次数}}, "other_claims": {{"名字": 次数}}}}
只返回JSON。"""
        try:
            resp = self.llm.call(prompt, temperature=0.1)
            content = resp.strip().replace("```json", "").replace("```", "")
            parsed = json.loads(content)
            self_claims = parsed.get("self_claims", {})
            other_claims = parsed.get("other_claims", {})
            if self_claims or other_claims:
                self.topology.update_identity(
                    self_claims={k: int(v) for k, v in self_claims.items()},
                    other_claims={k: int(v) for k, v in other_claims.items()},
                )
        except Exception:
            pass

    def _parse_findings(self, response: str) -> List[Finding]:
        try:
            content = response.strip().replace("```json", "").replace("```", "")
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return []

        findings = []
        for item in parsed.get("findings", []):
            findings.append(Finding(
                type=item.get("type", "fact"),
                content=item.get("content", ""),
                evidence=item.get("evidence", []),
                timescale="day",
                status="active",
            ))

        for update in parsed.get("updates", []):
            fid = update.get("id", "")
            if update.get("action") == "weaken":
                self.store.retire(fid)

        return findings

    def digest_dialogue(self, dialogue_text: str) -> str:
        prompt = f"""{self._identity_prefix()}。你刚刚经历了一段对话。请读一读，然后用自己的话写下你的理解。

对话内容：
---
{dialogue_text}
---

请你：

1. 列出这段对话中确认发生的事实（引用原文关键短语）。

2. 基于这些事实，用你自己的话写一段理解。

3. 如果有让你在意、困惑、或还没说完的事情，也写下来。

用自然语言写。这是你写给自己的记忆。"""
        return self.llm.call(prompt, temperature=0.3)