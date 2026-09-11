"""工坊浅色主题：统一界面样式与像素品牌标记。

被 `auth.py` 和 `app.py` 共用。
- inject_global_css() 一次注入所有样式
- render_hero(title, subtitle) 渲染顶栏
- celebrate(count=50) 撒一阵彩豆雨
"""
import base64
import random
from html import escape
import streamlit as st


# ============================================================
# 配色(糖果马卡龙)
# ============================================================
COLORS = {
	"pink": "#FFB6D9", "pink_deep": "#FF6B9D",
	"blue": "#A8DAFF", "blue_deep": "#6BB6FF",
	"yellow": "#FFE9A8", "purple": "#D4C5FF", "green": "#B8E6C0",
	"cream": "#FFF8F2", "ink": "#3A3A52", "ink_soft": "#7A7A9A",
}


# ============================================================
# 像素小熊吉祥物 SVG(16×16 像素艺术,身后落了三颗拼豆)
# ============================================================
MASCOT_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" shape-rendering="crispEdges">
  <rect x="2" y="2" width="2" height="2" fill="#FFB6D9"/>
  <rect x="12" y="2" width="2" height="2" fill="#FFB6D9"/>
  <rect x="3" y="3" width="10" height="9" fill="#FFD6E5"/>
  <rect x="3" y="3" width="10" height="1" fill="#FFB6D9"/>
  <rect x="3" y="11" width="10" height="1" fill="#FFB6D9"/>
  <rect x="5" y="6" width="2" height="2" fill="#3A3A52"/>
  <rect x="9" y="6" width="2" height="2" fill="#3A3A52"/>
  <rect x="5" y="6" width="1" height="1" fill="#FFFFFF"/>
  <rect x="9" y="6" width="1" height="1" fill="#FFFFFF"/>
  <rect x="3" y="8" width="2" height="1" fill="#FF8FB8"/>
  <rect x="11" y="8" width="2" height="1" fill="#FF8FB8"/>
  <rect x="7" y="9" width="2" height="1" fill="#FF6B9D"/>
  <rect x="1" y="13" width="2" height="2" fill="#A8DAFF"/>
  <rect x="13" y="13" width="2" height="2" fill="#FFE9A8"/>
  <rect x="7" y="14" width="2" height="2" fill="#D4C5FF"/>
</svg>'''


def mascot_html(size: int = 64) -> str:
	"""返回像素吉祥物的 HTML(嵌入式 SVG,无网络请求)。"""
	encoded = base64.b64encode(MASCOT_SVG.encode("utf-8")).decode("ascii")
	return (f'<img src="data:image/svg+xml;base64,{encoded}" '
	        f'width="{size}" height="{size}" '
	        f'style="image-rendering:pixelated;display:block;"/>')


# ============================================================
# 全局 CSS
# ============================================================
GLOBAL_CSS = """
<style>
/* Atelier: warm paper, dark ink, one restrained accent. */
:root {
    --paper: #f6f7f9; --surface: #ffffff; --ink: #202938;
    --muted: #687487; --line: #e3e7ed; --accent: #475c77;
    --accent-soft: #edf1f6; --radius: 12px;
}
.stApp { background: var(--paper); color: var(--ink); }
.stApp, input, textarea, button {
    font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif;
}
[data-testid="stHeader"] { background: rgba(246,247,249,.96); }
[data-testid="stMainBlockContainer"] { max-width: 1440px; padding-top: 2rem; padding-bottom: 4rem; }
h1,h2,h3 { color: var(--ink); font-weight: 650; letter-spacing: -.035em; }
h1 { font-size: 2rem; } h2 { font-size: 1.5rem; } h3 { font-size: 1.2rem; }
[data-testid="stCaptionContainer"] { color: var(--muted); line-height: 1.7; opacity:1; }
[data-testid="stCaptionContainer"] p { color: var(--muted); }
.st-key-login-panel { max-width:480px; margin:32px auto; }
.st-key-app-header [data-testid="stHorizontalBlock"] { flex-wrap:nowrap; align-items:center; }
.st-key-app-header [data-testid="stColumn"]:first-child { flex:1 1 auto; min-width:0; }
.st-key-app-header [data-testid="stColumn"]:last-child { flex:0 0 72px; min-width:72px; }
hr { border-color: var(--line); margin: 1.1rem 0; }
/* Compact brand header with a small craft signature. */
.hero-banner { display:flex; align-items:center; gap:16px; padding: 8px 0 18px; }
.hero-banner .mascot-bounce {
    flex-shrink:0; padding:10px; border:1px solid var(--line);
    border-radius:16px; background:var(--surface);
}
.hero-banner .mascot-bounce img { width:36px; height:36px; }
.hero-eyebrow { font-size:10px; font-weight:700; letter-spacing:.22em; color:var(--muted); margin-bottom:4px; }
.hero-title { font-size:28px; line-height:1.3; font-weight:700; letter-spacing:.06em; color:var(--ink); }
.hero-sub { color:var(--muted); font-size:12px; margin-top:6px; line-height:1.6; }
/* Tabs and radio options share one visual language. */
[data-testid="stRadio"] > div[role="radiogroup"], .stTabs [data-baseweb="tab-list"] {
    display:flex; flex-wrap:wrap; gap:4px; padding:5px; border:1px solid var(--line);
    border-radius:12px; background:#eef0f4; width:fit-content; max-width:100%;
}
[data-testid="stRadio"] > div[role="radiogroup"] > label {
    min-height:42px; margin:0!important; padding:0 15px!important;
    border-radius:8px; display:inline-flex; align-items:center; cursor:pointer;
    color:var(--muted); transition:background .15s ease;
}
[data-testid="stRadio"] > div[role="radiogroup"] > label > div:first-child { display:none; }
[data-testid="stRadio"] > div[role="radiogroup"] > label p { color:inherit; font-size:13px; font-weight:600; margin:0; }
[data-testid="stRadio"] > div[role="radiogroup"] > label:has(input:checked),
.stTabs [data-baseweb="tab"][aria-selected="true"] {
    background:var(--surface)!important; color:var(--ink)!important;
    box-shadow:0 1px 4px rgba(24,39,58,.09); border-radius:8px;
}
[data-testid="stRadio"] label:hover { background:#e5e9ef; }
[data-testid="stRadio"] label:has(input:focus-visible) { outline:2px solid var(--accent); outline-offset:2px; }
.stTabs [data-baseweb="tab"] { min-height:42px; padding:0 16px; color:var(--muted); font-weight:600; }
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] { display:none; }
/* Deliberate action hierarchy, including forms and downloads. */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button,
[data-testid="stPopover"] > button {
    min-height:42px; border:1px solid #dce2e9; border-radius:9px;
    background:white; color:var(--ink); font-weight:600;
    transition:border-color .15s, box-shadow .15s;
}
.stButton > button:hover, .stDownloadButton > button:hover, .stFormSubmitButton > button:hover {
    border-color:#8796aa; background:#f7f9fc; color:var(--ink);
    box-shadow:0 2px 6px rgba(24,39,58,.06);
}
button[kind="primary"], button[kind="primaryFormSubmit"] {
    background:var(--accent)!important; border-color:var(--accent)!important; color:white!important;
}
button[kind="primary"]:hover, button[kind="primaryFormSubmit"]:hover { background:#364960!important; }
button:disabled { opacity:.45; }
button:focus-visible, input:focus-visible, textarea:focus-visible { outline:2px solid #6a819f; outline-offset:2px; }
/* Quiet, legible data surfaces. */
[data-testid="stMetric"] {
    padding:18px 20px; border:1px solid var(--line); border-radius:var(--radius);
    background:var(--surface); box-shadow:0 2px 4px rgba(24,39,58,.02);
}
[data-testid="stMetricLabel"] { color:var(--muted); }
[data-testid="stMetricValue"] { color:var(--ink); font-weight:650; font-variant-numeric:tabular-nums; }
[data-testid="stTextInput"] [data-baseweb="input"],
[data-testid="stNumberInput"] [data-baseweb="input"],
[data-testid="stTextArea"] textarea, [data-baseweb="select"] > div {
    background:var(--surface); border-color:var(--line); border-radius:9px;
}
input { font-variant-numeric:tabular-nums; }
[data-testid="stSlider"] [role="slider"] { background:var(--accent); }
[data-testid="stSidebar"] { background:#eef1f5; border-right:1px solid var(--line); }
[data-testid="stExpander"] > details { background:var(--surface); border:1px solid var(--line); border-radius:12px; }
[data-testid="stExpander"] summary { padding:12px 14px; color:var(--ink); }
[data-testid="stExpander"] summary:hover { background:#f7f9fb; }
[data-testid="stDataFrame"], [data-testid="stDataFrameResizable"], [data-testid="stForm"] {
    border:1px solid var(--line); border-radius:12px; background:var(--surface);
}
[data-testid="stFileUploader"] section {
    border:1px dashed #b9c4d2; border-radius:14px; background:var(--surface);
    padding:24px 20px; transition:border-color .15s;
}
[data-testid="stFileUploader"] section:hover { border-color:var(--accent); background:#fafbfd; }
[data-testid="stImage"] img { border-radius:10px; }
.pixel-idle { padding:24px 14px; border-top:1px solid #dce2e9; display:flex; flex-direction:column; align-items:center; gap:16px; }
.pixel-grid { display:grid; grid-template-columns:repeat(4,8px); gap:4px; }
.pixel-grid span { width:8px; height:8px; border-radius:2px; background:#bdc8d6; }
.pixel-grid span:nth-child(3n) { background:#8296b0; }
.pixel-grid span:nth-child(4n) { background:#d2bda6; }
.pixel-idle-text { color:var(--muted); font-size:12px; text-align:center; line-height:1.8; white-space:pre-line; }
.bead-loader { display:inline-flex; gap:5px; }
.bead-loader span { width:8px; height:8px; background:var(--accent); border-radius:50%; }
.bead-rain { display:none; }
footer, #MainMenu { visibility:hidden; }
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation:none!important; scroll-behavior:auto!important; transition:none!important; } }
/* Viewport-fixed reference: scrolling the editor must not move the window. */
.st-key-ocr-quick-check-panel,
.st-key-ocr-quick-check-reopen {
	position: fixed !important;
	top: calc(4rem + env(safe-area-inset-top, 0px)) !important;
	right: max(1rem, env(safe-area-inset-right, 0px)) !important;
	left: auto !important; bottom: auto !important;
	z-index: 1000; box-sizing: border-box;
}
.st-key-ocr-quick-check-panel {
	width: min(460px, calc(100vw - 2rem)) !important;
	max-height: calc(100dvh - 5rem); overflow-y: auto;
	background: #fff; border: 1px solid #dce2e9;
	border-radius: 12px; padding: 6px;
	box-shadow: 0 16px 48px rgba(24,39,58,.16), 0 2px 6px rgba(24,39,58,.06);
}
.st-key-ocr-quick-check-reopen {
	width: 180px !important; max-width: calc(100vw - 1rem);
	background: #fff; border-radius: 12px;
	box-shadow: 0 6px 20px rgba(58,58,82,.18);
}
.st-key-ocr-quick-check-panel iframe { width: 100%; border: 0; }
@media (max-width: 700px) {
	[data-testid="stMainBlockContainer"] { padding: 3.5rem .65rem 3rem; }
	[data-testid="stHorizontalBlock"] { flex-wrap: wrap; gap: .6rem; }
	[data-testid="stColumn"] { min-width: min(100%, 280px); flex: 1 1 280px; }
	[data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) > [data-testid="stColumn"] {
		min-width: calc(50% - .6rem); flex: 1 1 calc(50% - .6rem);
	}
	[data-testid="stMetric"] { padding: 14px; }
	[data-testid="stMetricValue"] { font-size: 26px; }
	[data-testid="stRadio"] > div { flex-wrap: wrap; gap: .3rem; }
	[data-baseweb="tab-list"] { overflow-x: auto; }
	[data-baseweb="tab"] { white-space: nowrap; }
	input, textarea, select { font-size: 16px !important; }
	button { min-height: 44px; }
	.hero-banner { padding: 4px 0 12px; gap: 12px; }
	.hero-eyebrow { font-size: 9px; }
	[data-testid="stRadio"] > div[role="radiogroup"] > label { padding: 0 10px !important; }
	.hero-title { font-size: 26px; }
	.hero-sub { overflow-wrap: anywhere; }
	.st-key-ocr-quick-check-panel,
	.st-key-ocr-quick-check-reopen {
		top: calc(3.75rem + env(safe-area-inset-top, 0px)) !important;
		right: max(.5rem, env(safe-area-inset-right, 0px)) !important;
	}
	.st-key-ocr-quick-check-panel {
		width: calc(100vw - 1rem) !important;
		max-height: min(420px, 55dvh);
	}
	.st-key-ocr-quick-check-panel iframe,
	.st-key-ocr-quick-check-panel [data-testid="stElementContainer"]:has(> iframe) {
		height: min(200px, 30dvh) !important;
		flex: none !important; min-height: 0 !important;
	}
}
</style>
"""


def inject_global_css() -> None:
	"""注入全局样式。在 app 最顶部调用一次即可。"""
	st.markdown(GLOBAL_CSS, unsafe_allow_html=True)


def render_hero(title: str, subtitle: str, mascot_size: int = 64) -> None:
	"""渲染带像素吉祥物的 hero 顶栏。"""
	st.markdown(f'''<div class="hero-banner">
<div class="mascot-bounce">{mascot_html(mascot_size)}</div>
<div>
<div class="hero-eyebrow">BEAD ATELIER / 拼豆创作</div>
<div class="hero-title">{escape(title)}</div>
<div class="hero-sub">{escape(subtitle)}</div>
</div>
</div>''', unsafe_allow_html=True)


def bead_loader_html(text: str = "拼豆中…") -> str:
	"""返回拼豆 loading 的 HTML(配 st.empty().markdown 使用)。"""
	return (f'<div style="display:flex;align-items:center;gap:14px;padding:8px 0;">'
	        f'<div class="bead-loader">'
	        f'<span></span><span></span><span></span><span></span><span></span>'
	        f'</div>'
	        f'<span style="color:#7A7A9A;font-weight:600;">{text}</span>'
	        f'</div>')


def render_idle_pixel(text: str = "歇会儿,像素豆豆陪你 ✿") -> None:
	"""侧边栏空闲面板:像素吉祥物 + 4×4 拼豆色块脉冲动画。

	用于不需要参数的页面(库存/识别/历史/色板),代替堆一坨
	用不到的控件,留出呼吸感。
	"""
	st.markdown(f'''<div class="pixel-idle">
<div class="mascot-bounce">{mascot_html(56)}</div>
<div class="pixel-grid">
<span></span><span></span><span></span><span></span>
<span></span><span></span><span></span><span></span>
<span></span><span></span><span></span><span></span>
<span></span><span></span><span></span><span></span>
</div>
<div class="pixel-idle-text">{text}</div>
</div>''', unsafe_allow_html=True)


def celebrate(count: int = 50) -> None:
	"""撒一阵彩豆雨庆祝。纯 CSS 动画,~2.5 秒后自动消失。"""
	palette = ["#FFB6D9", "#A8DAFF", "#FFE9A8", "#D4C5FF", "#B8E6C0",
	           "#FFCBA4", "#FF8FB8", "#7AB8E0"]
	spans = []
	for _ in range(count):
		left = random.uniform(0, 100)
		delay = random.uniform(0, 0.6)
		dur = random.uniform(1.8, 3.0)
		size = random.randint(8, 18)
		color = random.choice(palette)
		spans.append(
			f'<span style="left:{left:.1f}%;background:{color};'
			f'width:{size}px;height:{size}px;'
			f'animation-delay:{delay:.2f}s;animation-duration:{dur:.2f}s;"></span>'
		)
	st.markdown(f'<div class="bead-rain">{"".join(spans)}</div>',
	            unsafe_allow_html=True)
