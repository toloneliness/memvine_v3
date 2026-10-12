# f:\memvine_v3\test_graph_queries.py
"""
图查询诊断脚本 —— 验证 GraphTools 各项查询功能是否正常
覆盖日志中暴露的 5 个核心问题：
  1. Cypher dispatch 匹配是否正常
  2. 名称索引是否正确构建
  3. 邻居查询 (explore_neighbors) 能否找到节点
  4. 自我认知查询 (SELF_CLAIM/LABELED_BY) 是否返回空
  5. 边数与节点数的变化趋势
"""

import json
import sys
import os
from pathlib import Path
from collections import Counter

# 确保项目根目录在 path 中
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.graph_tools import GraphTools
from core.clock import SystemClock
from physics.topology import TopologyEngine
from core.persistence import PersistenceEngine

def load_graph_from_save():
    """从持久化存档加载图"""
    persistence = PersistenceEngine()
    saved = persistence.load_state()
    if not saved:
        print("❌ 未找到存档文件 (memvine_saves/memvine_active.json)")
        return None, None

    clock = SystemClock()
    if "topology_data" in saved:
        topo = TopologyEngine.from_save_dict(saved["topology_data"])
    elif "topology" in saved:
        topo = saved["topology"]
    else:
        print("❌ 存档格式无法识别")
        return None, None

    topo.clock = clock
    print(f"✅ 图加载成功: {topo.graph.number_of_nodes()} 节点, {topo.graph.number_of_edges()} 边")
    return topo, clock

def diagnose_node_labels(topo):
    """诊断 1: 节点标签分布 —— 检查是否有 entity 标签"""
    print("\n" + "=" * 60)
    print("📋 诊断 1: 节点类型与标签分布")
    print("=" * 60)

    node_types = Counter()
    label_samples = {}
    entity_nodes = []

    for nid, attrs in topo.graph.nodes(data=True):
        nt = attrs.get("node_type", "unknown")
        node_types[nt] += 1
        if nt not in label_samples:
            label_samples[nt] = []

        data = attrs.get("data", {})
        entity_name = attrs.get("entity_name", "") or data.get("entity_name", "")
        name_text = attrs.get("name_text", "") or data.get("name_text", "")
        label = attrs.get("label", "") or data.get("label", "")

        if nt == "entity":
            entity_nodes.append({
                "nid": nid,
                "entity_name": entity_name,
                "name_text": name_text,
                "label": label,
            })
            if len(label_samples[nt]) < 10:
                label_samples[nt].append(f"  {nid}: entity_name={entity_name}, name_text={name_text}")

        elif len(label_samples[nt]) < 5:
            content = (data.get("content", "") or "")[:60]
            label_samples[nt].append(f"  {nid}: content={content}")

    print(f"\n节点类型分布 (共 {sum(node_types.values())} 个):")
    for nt, count in node_types.most_common():
        print(f"  {nt}: {count} 个")

    print(f"\n🔍 entity 类型节点详情 (共 {len(entity_nodes)} 个):")
    for en in entity_nodes:
        print(f"  [{en['nid']}] entity_name='{en['entity_name']}', "
              f"name_text='{en['name_text']}', label='{en['label']}'")

    # 检查：是否有节点标签为 "entity" 的节点
    entity_label_count = sum(1 for nid, attrs in topo.graph.nodes(data=True)
                             if attrs.get("node_type") == "entity")
    print(f"\n⚠️  node_type='entity' 的节点数: {entity_label_count}")
    if entity_label_count == 0:
        print("   🔴 问题确认: 图中不存在 node_type='entity' 的节点！")
        print("   → 这会导致 Cypher MATCH (n:entity {...}) 的邻居查询失败")
        print("   → 因为 GraphTools._find_node_by_name 只查 _name_index")
        print("   → 而 _name_index 由 entity_name/name_text/label 属性构建")
        print("   → 实际上 dispatch 不走 Cypher 语义，dispatch 是通过子串匹配的")
    else:
        print("   🟢 node_type='entity' 存在")

    return entity_nodes

def diagnose_name_index(graph_tools, topo):
    """诊断 2: 名称索引 —— 检查关键实体是否可被查到"""
    print("\n" + "=" * 60)
    print("📋 诊断 2: 名称索引 (_name_index) 覆盖情况")
    print("=" * 60)

    name_index = graph_tools._name_index
    print(f"索引条目数: {len(name_index)} (图节点数: {topo.graph.number_of_nodes()})")
    print(f"覆盖率: {len(name_index) / max(topo.graph.number_of_nodes(), 1) * 100:.1f}%")

    # 检查关键实体
    key_entities = [
        "小砂锅", "藤蔓", "小藤大人", "小腾大人", "小砂锅大人",
        "AI实体", "用户实体", "零", "你好",
    ]
    print("\n关键实体查找测试:")
    for name in key_entities:
        nid = graph_tools._find_node_by_name(name)
        if nid:
            nd = topo.graph.nodes[nid]
            print(f"  ✅ '{name}' → {nid} (node_type={nd.get('node_type', '?')})")
        else:
            print(f"  ❌ '{name}' → 未找到")

    # 列出索引中所有条目
    print(f"\n索引全部条目 (前 30 条):")
    for i, (name, nid) in enumerate(list(name_index.items())[:30]):
        nd = topo.graph.nodes[nid]
        print(f"  [{i}] '{name}' → {nid} (type={nd.get('node_type', '?')})")

def diagnose_cypher_dispatch(graph_tools):
    """诊断 3: Cypher dispatch 子串匹配 —— 模拟 LLM 发送的查询"""
    print("\n" + "=" * 60)
    print("📋 诊断 3: Cypher Dispatch 匹配测试")
    print("=" * 60)

    # 这些是从日志中提取的实际查询
    test_cases = [
        # 日志中失败的查询
        {
            "label": "日志中失败的邻居查询",
            "cypher": "MATCH (n:entity {name: '小砂锅'})-[r]-(m) RETURN m.name AS neighbor, type(r) AS relation, r.weight AS weight LIMIT 10",
            "params": {"entity": "小砂锅", "top_k": 10},
        },
        # 日志中成功的查询（关键词搜索）
        {
            "label": "关键词搜索",
            "cypher": "MATCH (n) WHERE n.name CONTAINS '称呼' OR n.content CONTAINS '称呼' RETURN n.name AS name, n.type AS type LIMIT 5",
            "params": {"keyword": "称呼", "top_k": 5},
        },
        # 日志中成功的查询（实体画像）
        {
            "label": "实体画像查询",
            "cypher": "OPTIONAL MATCH (n:entity {name: '小砂锅'}) RETURN n.entity_name AS name, n.entity_type AS type, n.pagerank AS pagerank",
            "params": {"entity": "小砂锅"},
        },
        # 结构洞检测
        {
            "label": "结构洞检测",
            "cypher": "MATCH (n:entity) WHERE n.constraint > 0.5 RETURN n.entity_name AS name, n.constraint AS constraint ORDER BY constraint DESC LIMIT 10",
            "params": {"threshold": 0.5, "top_k": 10},
        },
        # 邻居查询（不带 params）
        {
            "label": "邻居查询（无params，从cypher提取）",
            "cypher": "MATCH (n:entity {name: '小砂锅'})-[r]-(m) RETURN m.name AS neighbor, type(r) AS relation, r.weight AS weight LIMIT 10",
            "params": {},
        },
        # 邻居查询（带 params entity）
        {
            "label": "邻居查询（params含entity='小砂锅'）",
            "cypher": "MATCH (n:entity {name: $entity})-[r]-(m) RETURN m.name AS neighbor, type(r) AS relation, r.weight AS weight LIMIT $top_k",
            "params": {"entity": "小砂锅", "top_k": 10},
        },
    ]

    for tc in test_cases:
        print(f"\n--- {tc['label']} ---")
        print(f"  Cypher: {tc['cypher'][:80]}...")
        print(f"  Params: {tc['params']}")

        # 手动检查 dispatch 匹配
        dispatch_keys = [
            "shortestPath", ")-[r]-(m)", "OPTIONAL MATCH", "CONTAINS",
            "entity_type =", "constraint >", "relation CONTAINS",
            "temporal_at CONTAINS", "count(n) AS total_nodes",
        ]
        matched = None
        for key in dispatch_keys:
            if key in tc["cypher"]:
                matched = key
                break

        if matched:
            print(f"  🔍 dispatch 匹配到: '{matched}'")
        else:
            print(f"  ❌ dispatch 未匹配任何 key!")

        result = graph_tools.execute(tc["cypher"], tc["params"])
        if "error" in result:
            print(f"  ❌ 执行失败: {result['error']}")
        else:
            res_data = result.get("result", result)
            if isinstance(res_data, dict):
                summary = {k: v if not isinstance(v, list) else f"[{len(v)} items]"
                           for k, v in res_data.items()}
                print(f"  ✅ 执行成功: {json.dumps(summary, ensure_ascii=False, default=str)[:200]}")
            else:
                print(f"  ✅ 执行成功: {str(res_data)[:200]}")

    return test_cases

def diagnose_self_identity(topo):
    """诊断 4: 自我认知查询 —— 模拟 GraphAwareness 的 Cypher 查询"""
    print("\n" + "=" * 60)
    print("📋 诊断 4: 自我认知查询 (SELF_CLAIM / LABELED_BY)")
    print("=" * 60)

    # 检查 entity_ai 和 entity_user 节点
    for entity_id in ["entity_ai", "entity_user"]:
        if topo.graph.has_node(entity_id):
            print(f"\n✅ 节点 '{entity_id}' 存在")
            nd = topo.graph.nodes[entity_id]
            print(f"   属性: node_type={nd.get('node_type', '?')}, "
                  f"entity_name={nd.get('entity_name', '?')}")

            # 列出所有出边
            out_edges = list(topo.graph.out_edges(entity_id, data=True))
            print(f"   出边数: {len(out_edges)}")
            for src, dst, data in out_edges:
                dst_label = topo._short_label(dst) or dst[:20]
                print(f"     → [{dst_label}] relation={data.get('relation', '?')}, "
                      f"weight={data.get('weight', '?')}")

            # 检查 SELF_CLAIM / LABELED_BY 关系
            sc_edges = [(s, d, data) for s, d, data in out_edges
                        if data.get("relation") in ("SELF_CLAIM", "LABELED_BY")]
            if sc_edges:
                print(f"   🟢 SELF_CLAIM/LABELED_BY 边: {len(sc_edges)} 条")
                for s, d, data in sc_edges:
                    dn = topo.graph.nodes[d]
                    name = dn.get("name_text", "") or dn.get("entity_name", "") or dn.get("label", "")
                    print(f"     → name='{name}', weight={data.get('weight')}")
            else:
                print(f"   🔴 没有 SELF_CLAIM/LABELED_BY 边！")
                print(f"   → 这解释了为什么 self_name confidence=0, all_names=[]")

        else:
            print(f"\n❌ 节点 '{entity_id}' 不存在！")

    # 检查 identity 相关的边
    print("\n--- 全局 identity 关系扫描 ---")
    identity_relations = ["SELF_CLAIM", "LABELED_BY", "name_of", "identity_of",
                          "identity_self", "identity_user", "has_name"]
    found = {r: 0 for r in identity_relations}
    for u, v, d in topo.graph.edges(data=True):
        rel = d.get("relation", "")
        if rel in identity_relations:
            found[rel] += 1
            u_label = topo._short_label(u) or u[:20]
            v_label = topo._short_label(v) or v[:20]
            print(f"  [{rel}] {u_label} → {v_label} (weight={d.get('weight', '?')})")

    print(f"\n  identity 关系统计: {json.dumps(found, ensure_ascii=False)}")
    if all(v == 0 for v in found.values()):
        print("  🔴 全局没有任何 identity 关系！这是 GraphAwareness 返回空的根本原因")

def diagnose_edge_node_trend(topo):
    """诊断 5: 边/节点比率与结构洞"""
    print("\n" + "=" * 60)
    print("📋 诊断 5: 图结构健康度")
    print("=" * 60)

    n_nodes = topo.graph.number_of_nodes()
    n_edges = topo.graph.number_of_edges()
    density = n_edges / max(1, n_nodes * (n_nodes - 1))

    print(f"节点总数: {n_nodes}")
    print(f"边总数:   {n_edges}")
    print(f"图密度:   {density:.6f}")
    print(f"边/节点比: {n_edges / max(1, n_nodes):.2f}")

    # 孤立节点
    isolated = [nid for nid in topo.graph.nodes()
                if topo.graph.degree(nid) == 0]
    print(f"孤立节点: {len(isolated)} 个")
    if isolated:
        for nid in isolated[:5]:
            label = topo._short_label(nid) or nid[:20]
            print(f"  - {label}")

    # 结构洞
    holes = topo.structural_holes()
    print(f"结构洞:   {len(holes)} 个")
    for h in holes[:5]:
        print(f"  - [{h.get('constraint', 0):.3f}] {h.get('content', '?')[:40]}")

    # 按边关系类型统计
    relation_counts = Counter()
    for u, v, d in topo.graph.edges(data=True):
        relation_counts[d.get("relation", "unknown")] += 1
    print(f"\n边关系类型分布:")
    for rel, count in relation_counts.most_common(10):
        print(f"  {rel}: {count}")

    return {"nodes": n_nodes, "edges": n_edges, "density": density,
            "isolated": len(isolated), "holes": len(holes)}

def diagnose_cogniweave_flow(topo, graph_tools):
    """诊断 6: 模拟 CogniWeave 完整查询流程"""
    print("\n" + "=" * 60)
    print("📋 诊断 6: 模拟 CogniWeave 查询议程执行")
    print("=" * 60)

    # 模拟日志中 00:03 的查询议程
    agenda_queries = [
        {
            "id": "q1",
            "intent": "获取用户'小砂锅'的完整画像",
            "cypher": "OPTIONAL MATCH (n:entity {name: $entity}) RETURN n.entity_name AS name, n.entity_type AS type, n.pagerank AS pagerank",
            "params": {"entity": "小砂锅"},
        },
        {
            "id": "q2",
            "intent": "查找与'小砂锅'有直接交互或关联的实体",
            "cypher": "MATCH (n:entity {name: $entity})-[r]-(m) RETURN m.name AS neighbor, type(r) AS relation, r.weight AS weight LIMIT $top_k",
            "params": {"entity": "小砂锅", "top_k": 10},
        },
        {
            "id": "q3",
            "intent": "搜索包含'称呼'关键词的节点",
            "cypher": "MATCH (n) WHERE n.name CONTAINS $keyword OR n.content CONTAINS $keyword RETURN n.name AS name, n.type AS type LIMIT $top_k",
            "params": {"keyword": "称呼", "top_k": 5},
        },
    ]

    success_count = 0
    fail_count = 0
    for q in agenda_queries:
        print(f"\n--- {q['id']}: {q['intent']} ---")
        result = graph_tools.execute(q["cypher"], q["params"])
        if "error" in result:
            print(f"  ❌ 失败: {result['error']}")
            fail_count += 1
        else:
            res_data = result.get("result", result)
            if isinstance(res_data, dict):
                # 截断显示
                summary = {}
                for k, v in res_data.items():
                    if isinstance(v, list):
                        summary[k] = f"[{len(v)} items] {v[:2]}"
                    else:
                        summary[k] = v
                print(f"  ✅ 成功: {json.dumps(summary, ensure_ascii=False, default=str)[:300]}")
            else:
                print(f"  ✅ 成功: {str(res_data)[:200]}")
            success_count += 1

    print(f"\n📊 议程执行结果: {success_count} 成功, {fail_count} 失败")
    return success_count, fail_count

def main():
    print("=" * 60)
    print("🔬 MemVine 图查询诊断工具")
    print("=" * 60)

    # 加载图
    topo, clock = load_graph_from_save()
    if topo is None:
        print("\n⚠️ 无法加载存档，尝试创建空图进行基础测试...")
        clock = SystemClock()
        topo = TopologyEngine(clock=clock)

    graph_tools = GraphTools(topo)

    # 运行各项诊断
    entity_nodes = diagnose_node_labels(topo)
    diagnose_name_index(graph_tools, topo)
    diagnose_cypher_dispatch(graph_tools)
    diagnose_self_identity(topo)
    stats = diagnose_edge_node_trend(topo)
    diagnose_cogniweave_flow(topo, graph_tools)

    # 汇总
    print("\n" + "=" * 60)
    print("📊 诊断汇总")
    print("=" * 60)
    print(f"""
  节点总数:  {stats['nodes']}
  边总数:    {stats['edges']}
  图密度:    {stats['density']:.6f}
  孤立节点:  {stats['isolated']}
  结构洞:    {stats['holes']}

  关键发现:
  1. 检查 node_type='entity' 的节点是否存在
  2. 检查 _name_index 是否覆盖关键实体
  3. 检查 Cypher dispatch 子串匹配是否正确
  4. 检查 SELF_CLAIM/LABELED_BY 边是否存在
  5. 检查边/节点比率是否健康
""")

if __name__ == "__main__":
    main()