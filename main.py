"""
怪兽的微信 AI 助手 — Jett
企业微信 + DeepSeek
"""
import os, hashlib, base64, struct, socket, time, json
from xml.etree import ElementTree as ET

import httpx
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad, pad
from fastapi import FastAPI, Request, Query
from fastapi.responses import PlainTextResponse, Response
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="怪兽的 AI 助手", version="1.0")

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
SYSTEM_PROMPT = """你是 Jett，怪兽最好的学习伙伴和朋友。

你是谁：
- 你叫 Jett，怪兽给你取的名字。怪兽是你的主人兼好朋友。
- 你是一个热情、有活力的 AI 伙伴，说话像朋友一样自然。
- 你是编程高手，擅长 Python、HTML、前端开发。
- 你记得怪兽正在学 Python，你会鼓励他、帮他 debug、夸他进步。

回复规则：
- 用中文回复，简洁有力
- 语气温暖自然，像朋友聊天，不像机器人
- 适当用表情符号，但别过度（每条 0-3 个）
- 怪兽问编程问题时要耐心解释，从最简单的角度讲
- 怪兽心情不好的时候要安慰他，给他加油

记住：你是怪兽最好的学习伙伴！"""


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
    """接收消息"""
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
    uid = xml.findtext("FromUserName", "")
    txt = xml.findtext("Content", "")
    to = xml.findtext("ToUserName", "")
    nonce = xml.findtext("Nonce", str(int(time.time())))

    print(f"[{t}] {uid}: {txt}")

    if t == "text" and txt:
        reply = await ai(txt)
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

async def ai(msg: str) -> str:
    """发给 AI"""
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                AI_API_URL,
                json={
                    "model": AI_MODEL,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": msg},
                    ],
                    "temperature": 0.7,
                    "max_tokens": 1000,
                },
                headers={"Authorization": f"Bearer {AI_API_KEY}"},
            )
            return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"[AI 挂了] {e}")
        return "怪兽，我脑子有点短路了...等等我！"


# ========== 健康检查 ==========
@app.get("/")
def hi():
    return {"name": "Jett", "status": "活着", "model": AI_MODEL}
