# 拼豆图纸生成器 — Supabase 多用户云端版

基于 Streamlit + Supabase 的拼豆图纸生成 / 库存管理 / OCR 识别工具,支持邮箱密码注册,所有数据云端持久化。

## ✨ 功能

-   🖼️ **生成图纸**:上传任意图片 → 转换成 MARD 221 色拼豆图
-   📦 **库存管理**:每个用户独立的 221 色库存,云端实时同步
-   🔍 **OCR 识别**:识别已有拼豆图的图例文字,一键扣减库存
-   🎨 **整图采样**:无图例时逐格采样色块识别
-   📚 **历史记录**:图纸 / OCR 识别 / 补货清单全部存档

## 🚀 本地运行

```bash
cd perler-web-data
pip install -r requirements.txt
streamlit run app.py
```

首次启动需在 `.streamlit/secrets.toml` 填入 Supabase URL 和 anon key:

```toml
[supabase]
url = "https://xxxxxxxxxxxx.supabase.co"
anon_key = "sb_publishable_..."
```

## ☁️ 部署到 Streamlit Cloud

1.  push 代码到 GitHub(确保 `.streamlit/secrets.toml` 已被 `.gitignore` 排除)
2.  [share.streamlit.io](http://share.streamlit.io) → Create app → 选仓库 → Main file: `perler-web-data/app.py`
3.  Advanced settings → Python 3.12
4.  Secrets 框粘贴上面的 TOML
5.  Deploy

## 🗂️ 项目结构

```
perler-web-data/
├── app.py                # Streamlit 主程序(带登录门 + 5 个 Tab)
├── auth.py               # 注册 / 登录 / 登出 / 会话
├── db.py                 # 库存 / 图纸 / OCR / 补货 CRUD
├── storage.py            # Supabase Storage 上传 + 签名 URL
├── supabase_client.py    # Supabase 客户端单例
├── palette.py            # MARD 221 色色板
├── requirements.txt
├── .streamlit/
│   └── secrets.toml      # ⚠️ 不进 Git
├── .gitignore
└── README.md
```

## 🛠️ 技术栈

-   **前端**: Streamlit
-   **数据库**: Supabase Postgres (RLS)
-   **认证**: Supabase Auth (邮箱 + 密码)
-   **文件存储**: Supabase Storage
-   **OCR**: rapidocr-onnxruntime
-   **图像处理**: Pillow + NumPy

## 🔒 数据隔离

所有 Postgres 表和 Storage Bucket 都启用了 Row Level Security,策略统一 `user_id = auth.uid()`。每个用户只能访问自己的数据,即使 anon key 泄漏也无法越权。

##  git 推送
如果正在使用 Clash 等代理软件
确认代理已启动，然后按实际 HTTP 代理端口配置，例如端口为 7890：
git config --global http.proxy http://127.0.0.1:7890
git config --global https.proxy http://127.0.0.1:7890

如果代理端口不是 7890，替换成软件中显示的端口。