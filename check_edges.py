# f:\memvine_v3\check_edges.py
"""检查 entity_ai / entity_user 与 藤蔓/小砂锅/零 之间的边方向和关系类型"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from core.persistence import PersistenceEngine
from physics.topology import TopologyEngine

p = PersistenceEngine()
s = p.load_state()
t = TopologyEngine.from_save_dict(s["topology_data"])
G = t.graph

for name, eid in [("藤蔓", "entity_31c98e65"), ("小砂锅", "entity_af02295a"), ("零", "entity_9ff376e9")]:
    print(f"\n=== {name} ({eid}) ===")
    found = False
    for u, v, d in G.edges(data=True):
        if {u, v} == {eid, "entity_ai"} or {u, v} == {eid, "entity_user"}:
            ul = t._short_label(u) or u[:16]
            vl = t._short_label(v) or v[:16]
            print(f"  {ul} → {vl}  rel={d.get('relation')}  w={d.get('weight')}")
            found = True
    if not found:
        print("  ❌ 没有任何边！")