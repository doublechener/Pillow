"""邮箱 + 密码用户系统。

Supabase Auth 会自动哈希密码、签发 JWT、刷新 token。
登录成功后我们把 access_token / refresh_token / user_id 存到
st.session_state['sb_session'],由 supabase_client.get_client() 自动注入。
"""
import streamlit as st
from supabase_client import _base_client, get_client
from theme import inject_global_css, render_hero


def _save_session(sess) -> None:
	st.session_state["sb_session"] = {
		"access_token": sess.access_token,
		"refresh_token": sess.refresh_token,
		"user_id": sess.user.id,
		"email": sess.user.email,
	}


def sign_up(email: str, password: str) -> tuple[bool, str]:
	try:
		res = _base_client().auth.sign_up({"email": email, "password": password})
		if res.session is None:
			# 邮箱验证开启时,session 会是 None,需要点邮件链接
			return True, "注册成功!请到邮箱点击验证链接后再登录。"
		_save_session(res.session)
		return True, "注册成功并已登录"
	except Exception as e:
		return False, f"注册失败:{e}"


def sign_in(email: str, password: str) -> tuple[bool, str]:
	try:
		res = _base_client().auth.sign_in_with_password(
			{"email": email, "password": password}
		)
		_save_session(res.session)
		return True, "登录成功"
	except Exception as e:
		return False, f"登录失败:{e}"


def sign_out() -> None:
	try:
		get_client().auth.sign_out()
	except Exception:
		pass
	for k in ("sb_session", "ocr_parsed", "ocr_raw_lines",
	         "ocr_unknown", "rec_counter", "rec_preview_bytes"):
		st.session_state.pop(k, None)


def require_login() -> dict | None:
	"""在主程序最顶部调用。未登录时渲染登录/注册表单并 st.stop()。
	登录后返回 session dict。"""
	sess = st.session_state.get("sb_session")
	if sess:
		return sess

	inject_global_css()
	render_hero("拼豆图纸生成器",
	            "基于 MARD 拼豆 221 色官方色板 · 云端多用户版 · 让创作如拼豆一般缤纷 ✨",
	            mascot_size=80)

	tab_login, tab_signup = st.tabs(["🔑 登录", "📝 注册"])

	with tab_login:
		with st.form("login_form"):
			email = st.text_input("邮箱", key="li_email")
			pw = st.text_input("密码", type="password", key="li_pw")
			ok = st.form_submit_button("登录", type="primary",
			                            width="stretch")
			if ok:
				success, msg = sign_in(email.strip(), pw)
				if success:
					st.success(msg)
					st.rerun()
				else:
					st.error(msg)

	with tab_signup:
		with st.form("signup_form"):
			email = st.text_input("邮箱", key="su_email")
			pw = st.text_input("密码 (≥6位)", type="password", key="su_pw")
			pw2 = st.text_input("再次输入密码", type="password", key="su_pw2")
			ok = st.form_submit_button("注册", type="primary",
			                            width="stretch")
			if ok:
				if pw != pw2:
					st.error("两次密码不一致")
				elif len(pw) < 6:
					st.error("密码至少 6 位")
				else:
					success, msg = sign_up(email.strip(), pw)
					(st.success if success else st.error)(msg)
					if success and "已登录" in msg:
						st.rerun()

	st.stop()