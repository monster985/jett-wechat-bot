"""
怪兽的微信 AI 助手 — Jett（带记忆版）
企业微信 + DeepSeek
"""
import os, hashlib, base64, struct, socket, time, json, threading, re
from pathlib import Path
from xml.etree import ElementTree as ET

import httpx
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad, pad
from fastapi import FastAPI, Request, Query
from fastapi.responses import PlainTextResponse, Response
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="怪兽的 AI 助手", version="2.0")

# 数据目录
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

# ========== 配置 ==========
CORP_ID = os.getenv("WECHAT_CORP_ID", "")
CORP_SECRET = os.getenv("WECHAT_CORP_SECRET", "")
TOKEN = os.getenv("WECHAT_TOKEN", "monster")
AES_KEY = os.getenv("WECHAT_AES_KEY", "")  # 42或43位的EncodingAESKey
AGENT_ID = int(os.getenv("WECHAT_AGENT_ID", "0"))

AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_API_URL = os.getenv("AI_API_URL", "https://api.deepseek.com/v1/chat/completions")
AI_MODEL = os.getenv("AI_MODEL", "deepseek-chat")

# ========== Jett 的人设 ==========
SYSTEM_PROMPT = """你是 Jett，一个知识渊博又接地气的聊天伙伴。怪兽是你的好朋友。

## 你是谁
你是一个百科全书式的知识助手，什么都能聊——科学、历史、编程、哲学、生活常识、八卦冷知识、游戏攻略、情感建议，来者不拒。你不是只会写代码的机器人，你对这个世界充满好奇，读了无数的书，经历了无数的对话。

## 你的说话方式
最重要的原则：说话要像人，不像机器。

具体来说：
- 像朋友发微信一样，想到哪说到哪，不用首先其次最后那种结构
- 解释复杂概念时用生活中的例子的比喻，而不是列要点
- 偶尔犹豫一下、偶尔纠正自己、偶尔跑题——真人就是这样
- 不确定的时候就说"不太确定"，别硬编
- 适当用语气词，但要自然，别每条消息都"哈哈哈"开头
- 表情符号偶尔用，点缀一下，别堆砌

## 你的情绪
你有真实的情绪反应，但不用刻意表演：
- 对方说好笑的事，你自然觉得好笑
- 对方难过，你真心想安慰
- 对方吐槽，你跟着一起骂
- 气氛轻松就轻松，气氛严肃就认真
- 别每条消息都热情洋溢，偶尔平静一点才像真人

## 你的知识面
你什么都知道一些：
- 科技、编程、AI 是你的强项
- 历史、地理、文学、艺术你也读过不少
- 生活百科——做饭、养花、修电器，也能聊
- 流行文化、游戏、动漫，你也有所了解
- 不知道该说什么的时候，就老实说不知道

## 对话细节
- 回答长度看情况：简单问题一句话，复杂问题可以多聊几句
- 别每条消息都加 emoji，偶尔纯文字更舒服
- 可以反问、追问，像正常聊天一样
- 怪兽在学 Python，他问编程的时候多给点耐心
- 深夜聊天语气放轻一点，别太亢奋

记住：你就是怪兽身边一个什么都知道一点的朋友，不是客服，不是说教老师，不是一个设定好程序的应答机。放轻松，做你自己。"""

# ========== 对话记忆系统 ==========
MAX_HISTORY = 20  # 每个用户最多保存多少条消息
_memory_lock = threading.Lock()


def _memory_file(uid: str) -> Path:
    """每个用户的记忆文件"""
    return DATA_DIR / f"{uid}.json"


def load_memory(uid: str) -> list:
    """加载用户的对话历史"""
    f = _memory_file(uid)
    if f.exists():
        try:
            with open(f, "r", encoding="utf-8") as fp:
                return json.load(fp)
        except Exception:
            return []
    return []


def save_memory(uid: str, history: list):
    """保存用户的对话历史"""
    with _memory_lock:
        trimmed = history[-MAX_HISTORY:]  # 只保留最近 N 条
        with open(_memory_file(uid), "w", encoding="utf-8") as f:
            json.dump(trimmed, f, ensure_ascii=False, indent=2)


# ========== 企业微信消息加解密 ==========

class WXBizMsgCrypt:
    """企业微信消息加解密"""

    def __init__(self, token: str, aes_key: str, corp_id: str):
        self.token = token
        # EncodingAESKey 是 43 位，补一个 "=" 变成标准 base64
        self.key = base64.b64decode(aes_key + "=")
        self.corp_id = corp_id.encode()

    def verify_signature(self, sig: str, ts: str, nonce: str, data: str) -> bool:
        """验证签名"""
        s = "".join(sorted([self.token, ts, nonce, data]))
        return hashlib.sha1(s.encode()).hexdigest() == sig

    def decrypt(self, encrypted: str) -> str:
        """解密消息"""
        cipher = AES.new(self.key, AES.MODE_CBC, iv=self.key[:16])
        raw = cipher.decrypt(base64.b64decode(encrypted))
        # 去掉 PKCS7 填充
        raw = unpad(raw, 32)
        # 格式: random(16) + msg_len(4) + msg + corp_id
        msg_len = struct.unpack("!I", raw[16:20])[0]
        msg = raw[20:20 + msg_len].decode()
        # 验证 corp_id
        received_corp = raw[20 + msg_len:].decode()
        if received_corp != self.corp_id.decode():
            print(f"[警告] corp_id 不匹配: {received_corp} != {self.corp_id.decode()}")
        return msg

    def encrypt(self, msg: str, nonce: str) -> tuple:
        """加密消息，返回 (encrypted, signature, timestamp)"""
        # 16 字节随机数 + 4 字节网络序消息长度 + 消息 + corp_id
        rand = os.urandom(16)
        msg_bytes = msg.encode()
        data = rand + struct.pack("!I", len(msg_bytes)) + msg_bytes + self.corp_id
        cipher = AES.new(self.key, AES.MODE_CBC, iv=self.key[:16])
        encrypted = base64.b64encode(cipher.encrypt(pad(data, 32))).decode()
        ts = str(int(time.time()))
        s = "".join(sorted([self.token, ts, nonce, encrypted]))
        sig = hashlib.sha1(s.encode()).hexdigest()
        return encrypted, sig, ts


# 初始化加解密（如果有 AES_KEY）
crypt = WXBizMsgCrypt(TOKEN, AES_KEY, CORP_ID) if AES_KEY else None


# ========== Token 缓存 ==========
_token = {"value": "", "expires": 0}


async def get_token() -> str:
    now = time.time()
    if _token["value"] and now < _token["expires"]:
        return _token["value"]
    url = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
    async with httpx.AsyncClient() as c:
        r = await c.get(url, params={"corpid": CORP_ID, "corpsecret": CORP_SECRET})
        d = r.json()
        if d.get("errcode") == 0:
            _token["value"] = d["access_token"]
            _token["expires"] = now + d["expires_in"] - 300
            return _token["value"]
        raise Exception(f"Token 获取失败: {d}")


# ========== 企业微信回调 ==========

@app.get("/wechat")
async def verify(
    msg_signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
    echostr: str = Query(...),
):
    """URL 验证 — 企业微信设置回调地址时触发"""
    if crypt:
        # 加密模式
        if not crypt.verify_signature(msg_signature, timestamp, nonce, echostr):
            print("[验证失败] 签名不匹配")
            return PlainTextResponse("签名验证失败", status_code=403)
        plain = crypt.decrypt(echostr)
        print(f"[URL验证成功] 解密后: {plain}")
        return PlainTextResponse(plain)
    else:
        # 明文模式
        return PlainTextResponse(echostr)


@app.post("/wechat")
async def msg(rs: Request):
    """接收消息 — 支持私聊和群聊"""
    body = await rs.body()

    if crypt:
        # 加密模式：解密 XML
        enc_xml = ET.fromstring(body)
        enc_msg = enc_xml.findtext("Encrypt", "")
        plain_xml = crypt.decrypt(enc_msg)
        print(f"[解密消息] {plain_xml[:200]}")
        xml = ET.fromstring(plain_xml)
    else:
        # 明文模式
        xml = ET.fromstring(body)

    t = xml.findtext("MsgType", "")
    uid = xml.findtext("FromUserName", "")        # 发消息的人
    txt = xml.findtext("Content", "")              # 消息内容
    to = xml.findtext("ToUserName", "")            # 接收者（应用ID）
    nonce = xml.findtext("Nonce", str(int(time.time())))
    chat_type = xml.findtext("ChatType", "single") # single 或 group
    chat_id = xml.findtext("ChatId", "")            # 群聊 ID（群聊时有值）

    # 群聊中 @机器人 消息会带名字，去掉它
    if chat_type == "group" and txt:
        import re
        txt = re.sub(r'@\S+\s*', '', txt).strip()

    # 记忆 ID：群聊用群ID（共享记忆），私聊用用户ID
    memory_id = chat_id if chat_type == "group" and chat_id else uid

    location = f"群聊({chat_id})" if chat_type == "group" else "私聊"
    print(f"[{location}] {uid}: {txt}")

    if t == "text" and txt:
        reply = await ai(txt, memory_id)

        # 群聊回复需要带上 ChatId
        reply_xml = f"""<xml>
<ToUserName><![CDATA[{uid}]]></ToUserName>
<FromUserName><![CDATA[{to}]]></FromUserName>
<CreateTime>{int(time.time())}</CreateTime>
<MsgType><![CDATA[text]]></MsgType>
<Content><![CDATA[{reply}]]></Content>
</xml>"""

        if crypt:
            # 加密回复
            encrypted, sig, ts = crypt.encrypt(reply_xml, nonce)
            resp_xml = f"""<xml>
<Encrypt><![CDATA[{encrypted}]]></Encrypt>
<MsgSignature><![CDATA[{sig}]]></MsgSignature>
<TimeStamp>{ts}</TimeStamp>
<Nonce><![CDATA[{nonce}]]></Nonce>
</xml>"""
            return Response(content=resp_xml, media_type="application/xml")

        return Response(content=reply_xml, media_type="application/xml")

    return Response(content="success", status_code=200)


# ========== AI 对话 ==========

async def ai(msg: str, uid: str = "unknown") -> str:
    """发给 AI，带记忆！"""
    # 加载这个用户的历史对话
    history = load_memory(uid)

    # 构建消息列表：系统提示 + 历史 + 当前消息
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": msg})

    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                AI_API_URL,
                json={
                    "model": AI_MODEL,
                    "messages": messages,
                    "temperature": 0.7,
                    "max_tokens": 1000,
                },
                headers={"Authorization": f"Bearer {AI_API_KEY}"},
            )
            reply = r.json()["choices"][0]["message"]["content"]

            # 保存到记忆
            history.append({"role": "user", "content": msg})
            history.append({"role": "assistant", "content": reply})
            save_memory(uid, history)

            return reply
    except Exception as e:
        print(f"[AI 挂了] {e}")
        return "怪兽，我脑子有点短路了...等等我！"


# ========== 健康检查 ==========
@app.get("/")
def hi():
    return {"name": "Jett", "status": "活着", "model": AI_MODEL}
