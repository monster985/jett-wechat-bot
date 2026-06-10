# 🤖 怪兽的微信 AI 助手 — Jett

让你在微信（企业微信）里随时随地跟 Jett 聊天！

---

## 🏗️ 架构

```
你（企业微信）→ 发消息 → 企业微信服务器 → POST 到你的服务器
                                              ↓
                                          main.py（FastAPI）
                                              ↓
                                         DeepSeek API
                                              ↓
                                         Jett 的回复
                                              ↓
你（企业微信）← 收到回复 ← 企业微信服务器 ← 返回 XML
```

---

## 📋 第一步：注册必需账号（全部免费）

### 1.1 注册企业微信
1. 打开 https://work.weixin.qq.com/
2. 点「企业注册」→ 用个人微信扫码
3. 随便填个企业名（比如"怪兽的工作室"）
4. **免费！个人也可以用！**

### 1.2 创建自建应用
1. 登录企业微信后台 → 「应用管理」→「自建」→「创建应用」
2. 应用名：`Jett助手`
3. 上传个头像（用你的照片也行 😎）
4. 创建完后，记下三个东西：
   - **CorpID**（企业 ID）
   - **AgentId**（应用 AgentId）
   - **Secret**（应用 Secret — 点「查看」获取）

### 1.3 注册 DeepSeek API（AI 大脑）
1. 打开 https://platform.deepseek.com/
2. 注册账号，手机号就行
3. 进「API Keys」→「创建 API Key」→ **复制保存！只显示一次！**
4. **新用户免费送 500 万 tokens，够你聊好几个月！**

---

## 💻 第二步：在这台电脑上跑起来

### 2.1 安装依赖

打开终端（PowerShell），进入项目目录：

```powershell
cd "D:\AI\claude code\VX-chat-AI"
pip install -r requirements.txt
```

### 2.2 配置密钥

复制 `.env.example` 为 `.env`，然后填入你的密钥：

```powershell
copy .env.example .env
```

用记事本打开 `.env`，把下面几个填好：

```
WECHAT_CORP_ID=你的企业ID          ← 从企业微信后台复制
WECHAT_CORP_SECRET=你的应用Secret   ← 从企业微信后台复制
WECHAT_AGENT_ID=你的应用AgentId     ← 从企业微信后台复制
AI_API_KEY=你的DeepSeek_API_Key    ← 从 DeepSeek 后台复制
```

**其他的不用动！**

### 2.3 启动服务

```powershell
uvicorn main:app --host 0.0.0.0 --port 8080
```

看到这个就成功了：
```
INFO:     Uvicorn running on http://0.0.0.0:8080
```

---

## 🌐 第三步：让外网能访问（ngrok）

你的电脑在家，企业微信服务器在外面，需要一个"隧道"。

### 3.1 下载 ngrok
1. 打开 https://ngrok.com/
2. 注册账号（GitHub 登录也行）
3. 下载 Windows 版 → 解压到 `D:\AI\` 下面

### 3.2 配置 ngrok token
```powershell
cd D:\AI
.\ngrok config add-authtoken 你的ngrok_token
```

### 3.3 启动隧道（新开一个终端窗口）
```powershell
cd D:\AI
.\ngrok http 8080
```

会显示：
```
Forwarding  https://xxxx-xxx-xxx.ngrok-free.app -> http://localhost:8080
```

**复制那个 `https://xxxx.ngrok-free.app` 地址！** 👈 这就是你的公网地址。

---

## 🔗 第四步：对接企业微信

### 4.1 设置回调 URL
1. 回到企业微信后台 → 你的自建应用
2. 找到「接收消息」→「设置 API 接收」
3. URL 填：`https://xxxx.ngrok-free.app/wechat`（ 👈 用 ngrok 给的地址）
4. Token 填：`monster`（跟 .env 里一致就行）
5. EncodingAESKey 点「随机获取」
6. **先别点保存！先启动你的 main.py！**
7. 启动 main.py 后再点保存 → 企业微信会验证你的 URL

### 4.2 配置权限
1. 在企业微信后台 → 你的应用 →「企业可信 IP」
2. 把你的公网 IP 填进去（或者先不配置也行）

### 4.3 添加到工作台
- 企业微信后台 →「我的企业」→「微信插件」→ 扫码关注
- 这样你就能在**个人微信**里收到企业微信的消息了！

---

## 🎉 第五步：测试！

1. 打开**企业微信 App**（手机上下载）
2. 找到「工作台」→ 点开「Jett助手」
3. 发一条消息：`Jett，你在吗？`
4. 应该收到回复！🚀

---

## 💰 费用

| 项目 | 费用 |
|------|------|
| 企业微信 | **免费** |
| DeepSeek API | 新用户送 500 万 tokens ≈ **免费几个月** |
| ngrok | 免费版够用（限制带宽） |
| **总计** | **¥0**  |

等免费额度用完了，DeepSeek 价格：**¥1/百万 tokens**，一个月也就 **几块钱**。

---

## 🔧 常见问题

**Q: 收不到回复？**
- 检查 main.py 是否在运行
- 检查 ngrok 是否在运行
- 检查 .env 里的密钥是否填对

**Q: ngrok 地址变了怎么办？**
- 免费版 ngrok 每次重启地址会变
- 变了就去企业微信后台更新回调 URL
- 或者花 $8/月搞个固定域名

**Q: 能接 Claude 吗？**
- 可以！在 .env 里改成 Claude API 的地址和 Key 就行
- 不过 DeepSeek 更便宜，日常聊天够用了

---

## 🧠 AI 后端切换

默认用 DeepSeek，想换的话改 `.env`：

```bash
# Claude
AI_API_URL=https://api.anthropic.com/v1/messages
AI_MODEL=claude-haiku-4-5-20251001

# OpenAI
AI_API_URL=https://api.openai.com/v1/chat/completions
AI_MODEL=gpt-4o-mini
```

---

> 💙 怪兽出品 — 由 Jett 亲手打造
