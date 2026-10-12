"""意图清单 —— 仅保留响应风格，不再承担策略路由职责。

检索策略已改为并行全量查询，不再由意图标签决定。
意图标签只影响：响应模式（简洁/精确/共鸣）和基本意图分组。
"""

from dataclasses import dataclass

@dataclass
class IntentSpec:
    mode: str                        # 响应模式：简洁/精确/共鸣/无
    intent_group: str                # phatic/query/narrative/affective/critical/ingest

    @property
    def is_phatic(self) -> bool:
        return self.intent_group == "phatic"

    @property
    def is_ingest(self) -> bool:
        return self.intent_group == "ingest"

INTENT_MANIFEST: dict[str, IntentSpec] = {
    "问候":     IntentSpec(mode="简洁", intent_group="phatic"),
    "告别":     IntentSpec(mode="简洁", intent_group="phatic"),
    "询问":     IntentSpec(mode="精确", intent_group="query"),
    "询问身份": IntentSpec(mode="精确", intent_group="query"),
    "询问关系": IntentSpec(mode="精确", intent_group="query"),
    "询问时间": IntentSpec(mode="精确", intent_group="query"),
    "询问原因": IntentSpec(mode="精确", intent_group="query"),
    "引用原文": IntentSpec(mode="精确", intent_group="query"),
    "引用出处": IntentSpec(mode="精确", intent_group="query"),
    "陈述事实": IntentSpec(mode="简洁", intent_group="narrative"),
    "回忆":     IntentSpec(mode="共鸣", intent_group="narrative"),
    "反思":     IntentSpec(mode="精确", intent_group="narrative"),
    "对比":     IntentSpec(mode="精确", intent_group="narrative"),
    "假设":     IntentSpec(mode="精确", intent_group="narrative"),
    "分享情绪": IntentSpec(mode="共鸣", intent_group="affective"),
    "表达":     IntentSpec(mode="共鸣", intent_group="affective"),
    "质疑":     IntentSpec(mode="精确", intent_group="critical"),
    "知识块导入": IntentSpec(mode="无",  intent_group="ingest"),
}

def get_default_spec() -> IntentSpec:
    """当意图标签不在清单中时的回退"""
    return INTENT_MANIFEST["陈述事实"]