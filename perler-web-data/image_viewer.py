"""Isolated image viewer: no monkey-patching Streamlit or parent DOM."""
import base64
import io
import streamlit.components.v1 as components


def render_quick_check(image):
	buffer = io.BytesIO()
	image.save(buffer, format="PNG")
	image_b64 = base64.b64encode(buffer.getvalue()).decode("ascii")
	components.html(f"""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
html,body{{margin:0;width:100%;height:100%;overflow:hidden;background:transparent;}}
#viewer{{position:relative;width:100%;height:calc(100vh - 48px);overflow:hidden;
	border-radius:12px;background:#fff;touch-action:none;user-select:none;}}
#viewer img{{position:absolute;left:0;top:0;max-width:none;max-height:none;
	transform-origin:0 0;cursor:grab;-webkit-user-drag:none;}}
nav{{height:48px;display:flex;align-items:center;gap:8px;font:12px sans-serif;}}
button{{min-width:44px;min-height:44px;border:1px solid #ccc;border-radius:8px;background:white;cursor:pointer;}}
#viewer.dragging img{{cursor:grabbing;}}
</style>
</head>
<body>
<nav><button id="minus" aria-label="缩小">−</button><button id="plus" aria-label="放大">＋</button><button id="reset">适应</button><span>双指缩放 · 拖动查看</span></nav><div id="viewer"><img id="zoomImage" src="data:image/png;base64,{image_b64}" draggable="false"></div>
<script>
const viewer=document.getElementById('viewer');
const img=document.getElementById('zoomImage');
let minScale=0.01,scale=1,x=0,y=0,startX=0,startY=0,baseX=0,baseY=0;
const pointers=new Map(); let pinchDistance=0,pinchScale=1;
function clamp(v,a,b){{return Math.max(a,Math.min(b,v));}}
function draw(){{img.style.transform=`translate(${{x}}px,${{y}}px) scale(${{scale}})`;}}
function fit(){{
	const w=viewer.clientWidth,h=viewer.clientHeight;
	scale=Math.min(w/img.naturalWidth,h/img.naturalHeight);minScale=scale;
	x=(w-img.naturalWidth*scale)/2; y=(h-img.naturalHeight*scale)/2; draw();
}}
function zoomAt(px,py,next){{
	next=clamp(next,minScale,minScale*16); const ratio=next/scale;
	x=px-(px-x)*ratio; y=py-(py-y)*ratio; scale=next; draw();
}}
document.getElementById('plus').onclick=()=>zoomAt(viewer.clientWidth/2,viewer.clientHeight/2,scale*1.5);
document.getElementById('minus').onclick=()=>zoomAt(viewer.clientWidth/2,viewer.clientHeight/2,scale/1.5);
document.getElementById('reset').onclick=fit;
img.addEventListener('load',fit);if(img.complete)fit(); window.addEventListener('resize',fit);
viewer.addEventListener('wheel',e=>{{
	e.preventDefault(); const r=viewer.getBoundingClientRect();
	zoomAt(e.clientX-r.left,e.clientY-r.top,scale*(e.deltaY<0?1.14:0.88));
}},{{passive:false}});
viewer.addEventListener('dblclick',fit);
viewer.addEventListener('pointerdown',e=>{{
	viewer.setPointerCapture(e.pointerId); pointers.set(e.pointerId,{{x:e.clientX,y:e.clientY}});
	startX=e.clientX;startY=e.clientY;baseX=x;baseY=y;viewer.classList.add('dragging');
	if(pointers.size===2){{const p=[...pointers.values()];pinchDistance=Math.hypot(p[0].x-p[1].x,p[0].y-p[1].y);pinchScale=scale;}}
}});
viewer.addEventListener('pointermove',e=>{{
	if(!pointers.has(e.pointerId))return; pointers.set(e.pointerId,{{x:e.clientX,y:e.clientY}});
	if(pointers.size===1){{x=baseX+e.clientX-startX;y=baseY+e.clientY-startY;draw();}}
	else if(pointers.size===2){{const p=[...pointers.values()];const d=Math.hypot(p[0].x-p[1].x,p[0].y-p[1].y);
		const r=viewer.getBoundingClientRect();const cx=(p[0].x+p[1].x)/2-r.left,cy=(p[0].y+p[1].y)/2-r.top;
		zoomAt(cx,cy,pinchScale*d/Math.max(1,pinchDistance));}}
}});
function end(e){{pointers.delete(e.pointerId);viewer.classList.remove('dragging');if(pointers.size===1){{const p=[...pointers.values()][0];startX=p.x;startY=p.y;baseX=x;baseY=y;}}}}
viewer.addEventListener('pointerup',end);viewer.addEventListener('pointercancel',end);
</script>
</body>
</html>
""", height=260, scrolling=False)
