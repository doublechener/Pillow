"""Supabase 客户端单例,带 Streamlit session 绑定。

所有数据访问都走这个模块,统一携带当前用户的 access token,
这样 Postgres RLS 才能识别 auth.uid()。
"""
import streamlit as st
from supabase import create_client, Client


@st.cache_resource
def _base_client() -> Client:
	return create_client(
		st.secrets["supabase"]["url"],
		st.secrets["supabase"]["anon_key"],
	)


def get_client() -> Client:
	"""返回一个已带上当前会话的 Client。

	- 未登录:返回 anon client(只能访问公开内容,RLS 表都查不到)
	- 已登录:把 access_token / refresh_token 注入到 client,以后所有请求都带 JWT
	"""
	client = _base_client()
	session = st.session_state.get("sb_session")
	if session:
		client.postgrest.auth(session["access_token"])
		# 让 storage 也带上 JWT(supabase-py 2.x)
		try:
			client.storage._client.headers["Authorization"] = (
				f"Bearer {session['access_token']}"
			)
		except Exception:
			pass
	return client


def current_user_id() -> str | None:
	sess = st.session_state.get("sb_session")
	return sess.get("user_id") if sess else None