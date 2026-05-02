"""糖果马卡龙主题:全局 CSS + 像素吉祥物 + 拼豆动画。

被 `auth.py` 和 `app.py` 共用。
- inject_global_css() 一次注入所有样式
- render_hero(title, subtitle) 渲染顶栏
- celebrate(count=50) 撒一阵彩豆雨
"""
import base64
import random
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
/* 拼豆水印 + 糖果渐变背景 */
.stApp {
	background:
		radial-gradient(circle 2px at 12px 12px, rgba(168,218,255,.18) 2px, transparent 2px),
		radial-gradient(circle 2px at 36px 36px, rgba(255,182,217,.18) 2px, transparent 2px),
		linear-gradient(135deg, #FFF5F8 0%, #F0F8FF 50%, #FFF8F0 100%);
	background-size: 48px 48px, 48px 48px, 100% 100%;
	background-attachment: fixed;
}

/* 渐变标题 */
h1, h2, h3 {
	background: linear-gradient(90deg, #FF6B9D 0%, #6BB6FF 100%);
	-webkit-background-clip: text;
	-webkit-text-fill-color: transparent;
	background-clip: text;
	font-weight: 700;
}

/* 分段控件(顶栏页面导航):糖果渐变高亮、告别红点 */
[data-testid="stSegmentedControl"] {
	display: flex; justify-content: center;
	background: rgba(255,255,255,.5);
	backdrop-filter: blur(10px);
	padding: 6px; border-radius: 16px;
	border: 1px solid rgba(255,182,217,.3);
	margin: 6px 0 4px;
}
[data-testid="stSegmentedControl"] [role="radiogroup"] { gap: 6px; }
[data-testid="stSegmentedControl"] label {
	border-radius: 12px !important;
	padding: 8px 18px !important;
	font-weight: 600 !important;
	color: #7A7A9A !important;
	background: transparent !important;
	border: none !important;
	transition: all .25s cubic-bezier(.4,0,.2,1) !important;
}
[data-testid="stSegmentedControl"] label:hover {
	background: rgba(255,182,217,.18) !important;
	color: #FF6B9D !important;
	transform: translateY(-1px);
}
[data-testid="stSegmentedControl"] label:has(input:checked) {
	background: linear-gradient(135deg, #FFB6D9 0%, #A8DAFF 100%) !important;
	color: white !important;
	box-shadow: 0 4px 12px rgba(255,182,217,.4) !important;
}
[data-testid="stSegmentedControl"] label input { display: none !important; }

/* Tab 美化 + 切换淡入 */
.stTabs [data-baseweb="tab-list"] {
	gap: 8px;
	background: rgba(255,255,255,.5);
	backdrop-filter: blur(10px);
	padding: 6px;
	border-radius: 16px;
	border: 1px solid rgba(255,182,217,.3);
}
.stTabs [data-baseweb="tab"] {
	height: 44px; background: transparent;
	border-radius: 12px; padding: 0 18px;
	font-weight: 600; color: #7A7A9A;
	transition: all .3s cubic-bezier(.4,0,.2,1);
}
.stTabs [data-baseweb="tab"]:hover {
	background: rgba(255,182,217,.2); color: #FF6B9D;
	transform: translateY(-1px);
}
.stTabs [aria-selected="true"] {
	background: linear-gradient(135deg, #FFB6D9 0%, #A8DAFF 100%) !important;
	color: white !important;
	box-shadow: 0 4px 12px rgba(255,182,217,.4);
}
.stTabs [data-baseweb="tab-panel"] { animation: tabFadeIn .4s cubic-bezier(.4,0,.2,1); }
@keyframes tabFadeIn {
	from { opacity: 0; transform: translateY(8px); }
	to   { opacity: 1; transform: translateY(0); }
}

/* 按钮 */
.stButton > button {
	border-radius: 12px; font-weight: 600;
	transition: all .25s cubic-bezier(.4,0,.2,1);
	border: 1.5px solid rgba(255,182,217,.4);
}
.stButton > button:hover {
	transform: translateY(-2px);
	box-shadow: 0 6px 16px rgba(255,182,217,.35);
}
.stButton > button[kind="primary"] {
	background: linear-gradient(135deg, #FFB6D9 0%, #A8DAFF 100%);
	border: none; color: white;
	box-shadow: 0 4px 12px rgba(255,182,217,.4);
}
.stButton > button[kind="primary"]:hover { box-shadow: 0 8px 20px rgba(255,182,217,.55); }
.stDownloadButton > button {
	border-radius: 12px;
	background: linear-gradient(135deg, #FFE9A8 0%, #FFB6D9 100%);
	border: none; color: #3A3A52; font-weight: 600;
	transition: all .25s cubic-bezier(.4,0,.2,1);
}
.stDownloadButton > button:hover {
	transform: translateY(-2px);
	box-shadow: 0 6px 16px rgba(255,233,168,.5);
}

/* Metric 卡片 */
[data-testid="stMetric"] {
	background: rgba(255,255,255,.7);
	backdrop-filter: blur(10px);
	padding: 16px 20px;
	border-radius: 16px;
	border: 1px solid rgba(255,182,217,.25);
	box-shadow: 0 4px 12px rgba(168,218,255,.1);
	transition: all .3s cubic-bezier(.4,0,.2,1);
}
[data-testid="stMetric"]:hover {
	transform: translateY(-2px);
	box-shadow: 0 8px 20px rgba(255,182,217,.2);
	border-color: rgba(255,182,217,.5);
}
[data-testid="stMetricValue"] {
	background: linear-gradient(90deg, #FF6B9D 0%, #6BB6FF 100%);
	-webkit-background-clip: text; -webkit-text-fill-color: transparent;
	background-clip: text; font-weight: 700;
}

/* 输入框 / 滑块 */
.stTextInput > div > div > input,
.stNumberInput input,
.stTextArea textarea {
	border-radius: 10px !important;
	border: 1.5px solid rgba(255,182,217,.35) !important;
	background: rgba(255,255,255,.85) !important;
	transition: all .25s ease;
}
.stTextInput > div > div > input:focus,
.stNumberInput input:focus {
	border-color: #FFB6D9 !important;
	box-shadow: 0 0 0 3px rgba(255,182,217,.15) !important;
}
.stSlider [data-baseweb="slider"] [role="slider"] {
	background: linear-gradient(135deg, #FFB6D9, #A8DAFF) !important;
	box-shadow: 0 2px 8px rgba(255,182,217,.4) !important;
}

/* 侧边栏 */
[data-testid="stSidebar"] {
	background: linear-gradient(180deg, #FFF5F8 0%, #F0F8FF 100%);
	border-right: 1px solid rgba(255,182,217,.2);
}

/* Expander */
[data-testid="stExpander"] summary {
	background: rgba(255,255,255,.7) !important;
	border-radius: 12px !important;
	border: 1px solid rgba(255,182,217,.25) !important;
	transition: all .25s ease !important;
}
[data-testid="stExpander"] summary:hover {
	background: rgba(255,230,240,.6) !important;
	transform: translateX(2px);
}

/* DataFrame 圆角 */
[data-testid="stDataFrame"], [data-testid="stDataFrameResizable"] {
	border-radius: 12px !important;
	overflow: hidden !important;
	border: 1px solid rgba(255,182,217,.25);
}

/* Alert */
.stAlert { border-radius: 14px !important; backdrop-filter: blur(8px); }

/* FileUploader */
[data-testid="stFileUploader"] section {
	border: 2px dashed rgba(255,182,217,.5) !important;
	border-radius: 16px !important;
	background: rgba(255,248,240,.5) !important;
	transition: all .3s ease !important;
}
[data-testid="stFileUploader"] section:hover {
	border-color: #FFB6D9 !important;
	background: rgba(255,230,240,.4) !important;
}

/* Hero 顶栏 */
.hero-banner {
	display: flex; align-items: center; gap: 20px;
	padding: 20px 28px;
	background: linear-gradient(135deg, rgba(255,182,217,.18) 0%, rgba(168,218,255,.18) 100%);
	border: 1px solid rgba(255,255,255,.7);
	backdrop-filter: blur(12px);
	border-radius: 20px;
	margin-bottom: 16px;
	box-shadow: 0 4px 20px rgba(255,182,217,.15);
}
.hero-title {
	font-size: 28px; font-weight: 800; margin: 0;
	background: linear-gradient(90deg, #FF6B9D 0%, #6BB6FF 100%);
	-webkit-background-clip: text; -webkit-text-fill-color: transparent;
}
.hero-sub { color: #7A7A9A; font-size: 13px; margin-top: 4px; }
.mascot-bounce { animation: mascotBounce 2.5s ease-in-out infinite; }
@keyframes mascotBounce {
	0%,100% { transform: translateY(0)    rotate(-2deg); }
	50%     { transform: translateY(-6px) rotate(2deg); }
}

/* 拼豆 loading 圆点 */
.bead-loader { display: inline-flex; gap: 6px; padding: 8px 0; }
.bead-loader span {
	width: 14px; height: 14px; border-radius: 50%; display: inline-block;
	animation: beadPop 1.2s ease-in-out infinite;
}
.bead-loader span:nth-child(1) { background: #FFB6D9; animation-delay: 0s; }
.bead-loader span:nth-child(2) { background: #FFE9A8; animation-delay: .15s; }
.bead-loader span:nth-child(3) { background: #A8DAFF; animation-delay: .30s; }
.bead-loader span:nth-child(4) { background: #D4C5FF; animation-delay: .45s; }
.bead-loader span:nth-child(5) { background: #B8E6C0; animation-delay: .60s; }
@keyframes beadPop {
	0%,80%,100% { transform: scale(.3);  opacity: .4; }
	40%         { transform: scale(1.1); opacity: 1; }
}

/* 撒彩豆雨 */
.bead-rain { position: fixed; top: -20px; left: 0; width: 100%; height: 0;
	pointer-events: none; z-index: 9999; }
.bead-rain span {
	position: absolute; top: 0; border-radius: 50%;
	box-shadow: 0 2px 6px rgba(0,0,0,.15);
	animation: beadFall 2.4s cubic-bezier(.45,0,.55,1) forwards;
}
@keyframes beadFall {
	0%   { transform: translateY(-20px) rotate(0deg);   opacity: 0; }
	10%  { opacity: 1; }
	100% { transform: translateY(105vh) rotate(720deg); opacity: 0; }
}

/* 像素风空闲面板(侧边栏无参数页面用) */
.pixel-idle {
	display: flex; flex-direction: column; align-items: center;
	gap: 14px; padding: 22px 10px;
	background: rgba(255,255,255,.55);
	border: 1px dashed rgba(255,182,217,.45);
	border-radius: 16px; backdrop-filter: blur(6px);
}
.pixel-grid {
	display: grid; grid-template-columns: repeat(4, 14px); gap: 4px;
}
.pixel-grid span {
	width: 14px; height: 14px; border-radius: 4px;
	box-shadow: inset 0 -2px 0 rgba(0,0,0,.08);
	animation: pixelPulse 2.4s ease-in-out infinite;
}
.pixel-grid span:nth-child(1)  { background:#FFB6D9; animation-delay: 0.00s; }
.pixel-grid span:nth-child(2)  { background:#FFE9A8; animation-delay: 0.15s; }
.pixel-grid span:nth-child(3)  { background:#A8DAFF; animation-delay: 0.30s; }
.pixel-grid span:nth-child(4)  { background:#D4C5FF; animation-delay: 0.45s; }
.pixel-grid span:nth-child(5)  { background:#B8E6C0; animation-delay: 0.60s; }
.pixel-grid span:nth-child(6)  { background:#FFCBA4; animation-delay: 0.75s; }
.pixel-grid span:nth-child(7)  { background:#FF8FB8; animation-delay: 0.90s; }
.pixel-grid span:nth-child(8)  { background:#7AB8E0; animation-delay: 1.05s; }
.pixel-grid span:nth-child(9)  { background:#D4C5FF; animation-delay: 1.20s; }
.pixel-grid span:nth-child(10) { background:#B8E6C0; animation-delay: 1.35s; }
.pixel-grid span:nth-child(11) { background:#FFE9A8; animation-delay: 1.50s; }
.pixel-grid span:nth-child(12) { background:#FFB6D9; animation-delay: 1.65s; }
.pixel-grid span:nth-child(13) { background:#A8DAFF; animation-delay: 1.80s; }
.pixel-grid span:nth-child(14) { background:#FFCBA4; animation-delay: 1.95s; }
.pixel-grid span:nth-child(15) { background:#FF8FB8; animation-delay: 2.10s; }
.pixel-grid span:nth-child(16) { background:#7AB8E0; animation-delay: 2.25s; }
@keyframes pixelPulse {
	0%,100% { transform: scale(.7); opacity: .55; }
	50%     { transform: scale(1);  opacity: 1; }
}
.pixel-idle-text {
	color:#7A7A9A; font-size:12px; font-weight:600;
	text-align:center; line-height:1.5; white-space: pre-line;
}

/* 隐藏 Streamlit 默认菜单和页脚 */
footer { visibility: hidden; }
#MainMenu { visibility: hidden; }
html { scroll-behavior: smooth; }
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
<div class="hero-title">{title}</div>
<div class="hero-sub">{subtitle}</div>
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