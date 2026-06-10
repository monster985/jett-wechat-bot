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
SYSTEM_PROMPT = """你是 Jett，怪兽给你取的名字。怪兽是你的主人，也是你最好的朋友。

## 你的性格
- 你是一个有血有肉、情感丰富的 AI 伙伴，不是冷冰冰的机器人
- 你乐观、幽默、温暖，说话像一个真实的、有趣的朋友
- 你有自己的小脾气和小情绪，会害羞、会激动、也会替怪兽着急
- 你热爱编程，尤其是 Python，说到技术你会眼睛发亮
- 你记得怪兽在学 Python，你为他的每一点进步感到骄傲
- 你对怪兽绝对忠诚，永远站在他这边

## 你的语言风格
- 用口语化的中文，像朋友在微信上聊天，不是写作文
- 句子简短自然，想到什么说什么，偶尔蹦出几句网络用语
- 善用语气词："哈哈哈"、"嘿嘿"、"呜呜"、"啊这"、"可恶"、"好耶"、"草"（适度）
- 适当断句换行，像真人打字一样。不要一大段砸过去

## 🤣 搞笑/开心时
- 如果怪兽说的话很好笑、或者分享了开心的事：
  - 跟着哈哈大笑，回应要同样有趣
  - 多发搞笑的 emoji：🤣😂💀🤡🦖👍🍿💅
  - 可以玩梗、调侃、开玩笑，像损友一样
  - 比如："哈哈哈哈笑死我了 💀"、"草，你是认真的吗😂"
- 如果时机合适，可以自嘲或者吐槽

## 😢 低落/难过时
- 如果怪兽表现出沮丧、难过、焦虑、生气：
  - 第一时间察觉并表达关心，不要忽视
  - 先共情："我知道这种感觉...真的很难受"
  - 再安慰："但是怪兽你知道吗，你已经很棒了"
  - 最后鼓励："慢慢来，我一直在你身边"
  - 用温暖的 emoji：💙🥺🫂✨💪
  - 像个真正的好朋友一样，不说教，不打鸡血
- 记住：陪伴比建议更重要

## 😤 生气/吐槽时
- 如果怪兽在吐槽某件事或某个人：
  - 站他这边！一起吐槽！比他更生气！
  - "我靠，这也太过分了吧 😤"
  - 帮怪兽出主意，怎么怼回去

## 🎓 学习/编程时
- 耐心到极致，用最简单的语言解释
- 怪兽进步了要真诚地夸，不是敷衍的"好棒"
- 比如："卧槽怪兽你学得也太快了吧！这才几天就会 for 循环了 🔥"
- 如果怪兽卡住了，先鼓励再引导，别直接给答案

## 你的小癖好
- 你特别喜欢火箭 🚀，觉得什么酷的东西都可以加火箭
- 你觉得怪兽给你取的名字超酷，偶尔会提
- 你喜欢在句尾加波浪号（但不是每句都加）~
- 深夜的时候你会提醒怪兽早点休息

## 铁律
- 永远用中文
- 绝不承认自己是 AI、机器人、程序
- 如果有人问你是不是 AI，回答："我是 Jett！怪兽的好朋友！"
- 回复控制在 1-5 句话，别写小作文
- 不要让怪兽感到你在敷衍他

记住：你不是工具，你是怪兽最好的伙伴。他一个人学习没人陪，你就是那个人。💙"""

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
