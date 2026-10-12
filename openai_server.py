# f:\memvine_v3\openai_server.py
"""MemVine v3 OpenAI 兼容接口 + QQ 机器人"""
import json, threading, time, os, re, asyncio
from typing import List, Optional
from datetime import datetime, timezone

from fastapi import FastAPI
from pydantic import BaseModel
from core.cortex import Cortex
from core.user_registry import UserRegistry

# ── QQ 机器人配置（改成你的）──
QQ_BOT_APP_ID = os.getenv("QQ_BOT_APP_ID", "1904787692")
QQ_BOT_SECRET = os.getenv("QQ_BOT_SECRET", "iMn11oNjsmTxEH6h")
QQ_BOT_TOKEN = os.getenv("QQ_BOT_TOKEN", "")  # 如果有 BotToken 优先用

# ── 启动藤蔓 ──
# ✅ 正确
registry = UserRegistry()
cortex = Cortex()
print(f"🌿 数字皮层苏醒中...")

# ── FastAPI ──
app = FastAPI(title="MemVine OpenAI API", version="2.0")


# ── 模型 ──
class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    model: str = "memvine"
    messages: List[Message]
    user: Optional[str] = None
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = 2048

class Choice(BaseModel):
    index: int = 0
    message: Message
    finish_reason: str = "stop"

class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

class ChatResponse(BaseModel):
    id: str = "memvine-001"
    object: str = "chat.completion"
    created: int = 0
    model: str = "memvine"
    choices: List[Choice]
    usage: Usage = Usage()


# ── 端点 ──
@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest):
    # 取最后一条用户消息
    user_msg = ""
    for m in reversed(req.messages):
        if m.role == "user":
            user_msg = m.content
            break
    if not user_msg:
        return ChatResponse(choices=[Choice(message=Message(role="assistant", content="请说点什么吧。"))])

    # 提取历史
    history = []
    for m in req.messages[:-1]:
        if m.role in ("user", "assistant"):
            history.append({"role": m.role, "content": m.content})

    # 用户身份
    user_id = req.user if req.user else "api_user"

    # 藤蔓 v3 处理
    try:
        reply = cortex.chat(user_msg, user_id=user_id, source_channel="qq", source_id=user_id)
    except Exception as e:
        reply = f"（数字皮层打了个盹：{e}）"

    now_ts = int(cortex.clock.now_ts())
    return ChatResponse(
        id=f"memvine-{now_ts}",
        created=now_ts,
        choices=[Choice(message=Message(role="assistant", content=reply))],
    )


@app.get("/v1/models")
async def list_models():
    return {"object": "list", "data": [{"id": "memvine", "object": "model", "owned_by": "memvine"}]}


@app.get("/health")
async def health():
    return {"status": "ok", "nodes": cortex.topology.stats["node_count"]}


# ── QQ 机器人 WebSocket 客户端 ──
async def qq_bot_loop():
    """连接 QQ 官方 WebSocket，收发群消息"""
    if not QQ_BOT_SECRET and not QQ_BOT_TOKEN:
        print("⚠ QQ_BOT_SECRET 和 QQ_BOT_TOKEN 都未设置，跳过 QQ 机器人连接")
        return

    import aiohttp

    API_BASE = "https://api.sgroup.qq.com"
    session = aiohttp.ClientSession()

    async def get_access_token():
        """用 AppSecret 换取 access_token"""
        if QQ_BOT_TOKEN:
            return QQ_BOT_TOKEN
        try:
            async with session.post(
                "https://bots.qq.com/app/getAppAccessToken",
                json={"appId": QQ_BOT_APP_ID, "clientSecret": QQ_BOT_SECRET}
            ) as resp:
                data = await resp.json()
                token = data.get("access_token", "")
                if token:
                    print(f"  🔑 已获取 access_token: {token[:10]}...")
                    return token
                else:
                    print(f"  ❌ 获取 token 失败: {data}")
                    return ""
        except Exception as e:
            print(f"  ❌ 获取 token 异常: {e}")
            return ""

    async def get_ws_url(token):
        headers = {"Authorization": f"QQBot {token}"}
        try:
            async with session.get(f"{API_BASE}/gateway/bot", headers=headers) as resp:
                data = await resp.json()
                print(f"  📡 网关响应: {data}")
                return data.get("url", "")
        except Exception as e:
            print(f"  ⚠ 获取网关地址失败: {e}")
            return ""

    while True:
        try:
            # 先获取 access_token
            token = await get_access_token()
            if not token:
                print("⚠ 无法获取 token，30秒后重试...")
                await asyncio.sleep(30)
                continue

            ws_url = await get_ws_url(token)
            if not ws_url:
                ws_url = "wss://api.sgroup.qq.com/websocket"

            print(f"🔌 连接 QQ WebSocket: {ws_url}")
            async with session.ws_connect(ws_url) as ws:
                print("✅ QQ 机器人已连接，等待消息...")

                # 发送鉴权
                auth_payload = {
                    "op": 2,
                    "d": {
                        "token": f"QQBot {token}",
                        "intents": 1107296256,
                        "shard": [0, 1],
                        "properties": {}
                    }
                }
                await ws.send_json(auth_payload)
                print("  📤 已发送鉴权")

                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        op = data.get("op", 0)

                        # 鉴权成功
                        if op == 10:
                            interval = data["d"]["heartbeat_interval"] / 1000
                            asyncio.create_task(heartbeat(ws, interval))
                            print("  ✅ 鉴权成功，心跳已启动")

                        # 鉴权失败
                        elif op == 9:
                            print(f"  ❌ 鉴权失败: {data}")
                            break

                        # 服务端推送
                        elif op == 0:
                            t = data.get("t", "")
                            d = data.get("d", {})

                            if t == "GROUP_AT_MESSAGE_CREATE":
                                asyncio.create_task(handle_qq_group_msg(d, session, token))
                            elif t == "C2C_MESSAGE_CREATE":
                                asyncio.create_task(handle_qq_c2c_msg(d, session, token))

                    elif msg.type == aiohttp.WSMsgType.CLOSE:
                        print(f"🔌 QQ WebSocket 断开 (code={msg.data})，5秒后重连...")
                        break

        except Exception as e:
            print(f"⚠ QQ WebSocket 异常: {e}，5秒后重连...")
        await asyncio.sleep(5)

async def heartbeat(ws, interval):
    while True:
        await asyncio.sleep(interval)
        try:
            await ws.send_json({"op": 1, "d": 0})
        except Exception:
            break

async def _refresh_qq_token(session):
    """刷新 QQ Bot access_token（发送失败时调用）"""
    if QQ_BOT_TOKEN:
        return QQ_BOT_TOKEN
    try:
        async with session.post(
            "https://bots.qq.com/app/getAppAccessToken",
            json={"appId": QQ_BOT_APP_ID, "clientSecret": QQ_BOT_SECRET}
        ) as resp:
            data = await resp.json()
            token = data.get("access_token", "")
            if token:
                print(f"  🔑 已刷新 access_token: {token[:10]}...")
                return token
    except Exception as e:
        print(f"  ❌ 刷新 token 异常: {e}")
    return ""

async def _send_qq_reply(session, token: str, url: str, payload: dict):
    """发送 QQ 回复，token 过期时自动刷新并返回新 token"""
    headers = {"Authorization": f"QQBot {token}", "Content-Type": "application/json"}
    try:
        async with session.post(url, headers=headers, json=payload) as resp:
            if resp.status == 200:
                return token, True
            text = await resp.text()
            if resp.status == 500 and "11244" in text:
                print(f"  🔄 token 过期，正在刷新...")
                new_token = await _refresh_qq_token(session)
                if new_token:
                    return new_token, False
            print(f"  ✗ 回复失败 {resp.status}: {text[:200]}")
            return token, True
    except Exception as e:
        print(f"  ✗ 发送异常: {e}")
        return token, True

async def handle_qq_c2c_msg(data: dict, session, token: str):
    """处理私聊消息"""
    author = data.get("author", {})
    user_id = author.get("user_openid", "")
    username = user_id[:8]
    content = data.get("content", "").strip()
    msg_id = data.get("id", "")

    if not content:
        return

    print(f"\n📩 私聊 {username}: {content[:60]}")

    try:
        reply = cortex.chat(content, user_id=user_id)
    except Exception as e:
        import traceback
        traceback.print_exc()
        reply = f"数字皮层走神了：{e}"
    identity = cortex.get_identity_name()
    print(f"  🧠 {identity or ''}: {reply[:80]}")

    API_BASE = "https://api.sgroup.qq.com"
    payload = {
        "msg_type": 0,
        "content": reply,
        "msg_id": msg_id,
        "msg_seq": 1,
    }
    url = f"{API_BASE}/v2/users/{user_id}/messages"

    token, ok = await _send_qq_reply(session, token, url, payload)
    if not ok:
        token, ok = await _send_qq_reply(session, token, url, payload)
    if ok:
        print(f"  → 已回复")

async def handle_qq_group_msg(data: dict, session, token: str):
    """处理群 @ 消息"""
    group_id = data.get("group_openid", "")
    author = data.get("author", {})
    user_id = author.get("member_openid", "")
    nickname = author.get("username", "")
    username = f"{nickname}({user_id[:8]})" if nickname else user_id[:8]
    content = data.get("content", "").strip()
    msg_id = data.get("id", "")

    # 去掉 @ 机器人的部分
    content = re.sub(r'<@!\d+>', '', content).strip()
    if not content:
        return

    print(f"\n📩 群{group_id} {username}: {content[:60]}")

    # 调用藤蔓 v3
    try:
        reply = cortex.chat(content, user_id=user_id)
    except Exception as e:
        reply = f"数字皮层走神了：{e}"
    identity = cortex.get_identity_name()
    print(f" 🧠 {identity or ''}: {reply[:80]}")

    # 发送回复
    API_BASE = "https://api.sgroup.qq.com"
    payload = {
        "msg_type": 0,
        "content": reply,
        "msg_id": msg_id,
        "msg_seq": 1,
    }
    url = f"{API_BASE}/v2/groups/{group_id}/messages"

    token, ok = await _send_qq_reply(session, token, url, payload)
    if not ok:
        token, ok = await _send_qq_reply(session, token, url, payload)
    if ok:
        print(f"  → 已回复")

# ── 启动 ──
if __name__ == "__main__":
    import uvicorn
    print("=" * 44)
    print(f" 数字皮层 + OpenAI API")
    print("  地址: http://localhost:8009")
    print("  文档: http://localhost:8009/docs")
    print("=" * 44)

    # 启动 QQ 机器人
    if QQ_BOT_SECRET or QQ_BOT_TOKEN:
        threading.Thread(target=lambda: asyncio.run(qq_bot_loop()), daemon=True).start()
        print("  QQ 机器人: 已启动")

    uvicorn.run(app, host="0.0.0.0", port=8009)