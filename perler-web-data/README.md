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

### 稳定性与手机端修复（2026-09-11）

- 快速核对：使用真正的视口固定悬浮窗，滚动编辑区时保持在右上角。点击 `＋ / −` 放大缩小，拖动查看，手机支持双指缩放；`适应` 恢复全图，点击标题收起。点击 `关闭悬浮窗` 后保留 `打开快速核对` 按钮；关闭时不渲染图片。手机端宽度随屏幕调整，高度不超过视口的 55%，适配安全区域。
- 上传限制为 20 MB / 2000 万像素；工作图片最长边缩至 3200 px，自动校正手机照片方向，透明背景按白色处理。原始上传文件仍用于历史存档。
- 输出上限为 1600 万像素、横纵最多 300 豆。超过时显示提示；颜色匹配分批计算以降低峰值内存，逐格采样使用 uint8 图片。
- OCR 模型按需加载、每个推理线程数为 1、共享模型串行调用；Supabase 客户端按会话隔离，刷新 token 使用 SDK 公共接口；库存初始化每次登录只执行一次。
- 手机端预览纵向排列，导航可换行，输入字体至少 16 px。

在本目录执行 `python -m unittest -v test_regressions`。测试使用模拟登录，不向云端写入数据；界面验证使用临时合成图片测试入口，验证后已移除。

本地已通过 6 项回归测试、390×844 手机及 1280×900 桌面浏览器检查。测试环境为 Python 3.12、Streamlit 1.57.0，部署固定版本仍为 requirements.txt 中的 1.55.0；云端版本和 iOS 微信内置浏览器仍需上线复验。双指手势已实现，但本地浏览器检查仅实测按钮缩放、恢复、收起和布局。

部署必须包含新增的 `image_safety.py`、`image_viewer.py`、`ocr_runtime.py`，不能只提交 app.py。入口保持 `perler-web-data/app.py`。Streamlit 配置按工作目录读取；若云端从仓库根目录启动，将本项目 `.streamlit/config.toml` 的 server 限制合并到仓库根配置中。即使该配置未被加载，程序仍执行图片大小与像素检查。

截图中的 `Received no response from server / Code: 1ST` 不能单凭截图确定原因。这次修复消除了可见的资源风险；尚未取得部署服务日志，未宣称云端错误已彻底解决。若上线后仍出现，在 Streamlit Cloud 的 Manage app 查看发生时间对应的日志，检查进程重启、内存耗尽、依赖启动异常及网络连接。[Streamlit 官方排查说明](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app)。

如果正在使用 Clash 等代理软件
确认代理已启动，然后按实际 HTTP 代理端口配置，例如端口为 7890：
git config --global http.proxy http://127.0.0.1:7890
git config --global https.proxy http://127.0.0.1:7890

如果代理端口不是 7890，替换成软件中显示的端口。
