"""Supabase 客户端单例,带 Streamlit session 绑定。

所有数据访问都走这个模块,统一携带当前用户的 access token,
这样 Postgres RLS 才能识别 auth.uid()。
"""
import streamlit as st
from supabase import create_client, Client, ClientOptions


def _base_client() -> Client:
	# Auth and request headers are mutable: never share this across users.
	if "sb_client" not in st.session_state:
		st.session_state["sb_client"] = create_client(
			st.secrets["supabase"]["url"],
			st.secrets["supabase"]["anon_key"],
			options=ClientOptions(auto_refresh_token=False,
				postgrest_client_timeout=15, storage_client_timeout=20),
		)
	return st.session_state["sb_client"]


def get_client() -> Client:
	"""返回一个已带上当前会话的 Client。

	- 未登录:返回 anon client(只能访问公开内容,RLS 表都查不到)
	- 已登录:把 access_token / refresh_token 注入到 client,以后所有请求都带 JWT
	"""
	client = _base_client()
	session = st.session_state.get("sb_session")
	if session:
		# Public auth API refreshes expired tokens and updates PostgREST/Storage.
		live = client.auth.get_session()
		if live is None:
			live = client.auth.set_session(
				session["access_token"], session["refresh_token"]).session
		if live is None:
			raise RuntimeError("登录已失效，请重新登录。")
		session.update(access_token=live.access_token, refresh_token=live.refresh_token)
	return client


def current_user_id() -> str | None:
	sess = st.session_state.get("sb_session")
	return sess.get("user_id") if sess else None
