"""Shared portfolio UI. Decorative HTML only; no user inputs in markup."""
import streamlit as st

CSS = r"""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap');
:root { --ink: #E7EDF5; --muted: #9DB0C4; --aqua: #39D9C1; --navy: #09111F; }
html, body, [class*="css"], [data-testid="stAppViewContainer"] { font-family: 'DM Sans', sans-serif; }
[data-testid="stAppViewContainer"] { background: radial-gradient(ellipse 70% 26% at 72% -8%, rgba(24,117,127,0.16), transparent 75%), #09111F; }
[data-testid="stSidebar"] { background: #0C1727; border-right: 1px solid rgba(173,199,217,.10); }
[data-testid="stSidebarNav"] { padding-top: 8px; }
[data-testid="stMainBlockContainer"] { padding-top: 2rem; max-width: 1230px; padding-bottom: 5rem; }
h1, h2, h3 { font-family: 'Space Grotesk', sans-serif; letter-spacing: -.025em; }
h1 { font-weight:700; }
h2 { margin-top: 1.3rem; }
[data-testid="stMetric"] { background: rgba(20,37,55,.83); border:1px solid rgba(118,173,194,.14); border-radius:16px; padding:17px 20px; }
[data-testid="stMetricLabel"] { color:#A5B7CB; }
[data-testid="stMetricValue"] { color:#F2F7FC; font-family: 'Space Grotesk', sans-serif; font-weight:600; }
[data-testid="stVerticalBlockBorderWrapper"] { border-color: rgba(118,173,194,.15)!important; border-radius: 16px; }
div.stButton > button[kind="primary"], div.stDownloadButton > button[kind="primary"] { background: #28C9B3; color: #081322; border: 0; font-weight: 700; border-radius: 9px; }
div.stButton > button[kind="primary"]:hover { background: #65E9D8; color: #07131C; }
button, input { font-family:'DM Sans',sans-serif; }
[data-testid="stTabs"] button { font-weight: 600; }
[data-testid="stSidebarNavItems"] { gap: 2px; }
.bil-eyebrow { color:var(--aqua);font-size:.70rem;font-weight:800;letter-spacing:.15em;text-transform:uppercase;margin:0 0 12px 0; }
.bil-hero { margin-top:8px; margin-bottom:26px; padding:42px 46px; border-radius:22px; border:1px solid rgba(83,197,187,.24); background: radial-gradient(ellipse 70% 90% at 90% 10%,rgba(48,190,183,.14),transparent 78%), linear-gradient(135deg,#14253A 0%,#0E1A2C 65%,#111F30 100%); }
.bil-hero h1 { font-size:clamp(2.0rem,4.1vw,3.4rem);line-height:1.11;color:#F3F8FD;margin:0 0 17px 0;max-width:710px; }
.bil-hero p { color:#B9CADB;max-width:720px;font-size:1.02rem;line-height:1.68;margin:0; }
.bil-hero .bil-eyebrow { margin-bottom:14px; }
.bil-chip { display:inline-block; font-size:.77rem; color:#93E8D9; background:rgba(48,200,177,.09);border:1px solid rgba(66,215,197,.20);border-radius:99px;padding:6px 11px;margin-bottom:20px; }
.bil-card { background:linear-gradient(145deg,rgba(20,37,55,.93),rgba(15,30,47,.95));border:1px solid rgba(118,173,194,.15);border-radius:17px;padding:23px 24px;min-height:165px;margin:0 0 8px; }
.bil-card .bil-kicker { font-size:.7rem;letter-spacing:.08em;text-transform:uppercase;font-weight:700;color:#96A9BC;margin-bottom:13px; }
.bil-card .bil-big { font-size:clamp(1.55rem,2.7vw,2.25rem);font-weight:700;font-family:'Space Grotesk';line-height:1.2;color:#F3F8FD; }
.bil-card .bil-descr { color:#95ABC1;font-size:.82rem;margin-top:11px;line-height:1.45; }
.bil-card .bil-accent { color:#59E9D3; }
.bil-brand {font-family:'Space Grotesk',sans-serif;font-size:1.05rem;font-weight:700;letter-spacing:-.02em;color:#F0F5FB;margin:3px 0 4px;}
.bil-brand-sub {font-size:.71rem;letter-spacing:.10em;color:#76D8CB;text-transform:uppercase;margin-bottom:18px;}
.bil-label {display:inline-block;letter-spacing:.1em;text-transform:uppercase;color:#66D7C4;font-size:.70rem;font-weight:800;margin:12px 0 8px;}
.bil-panel-heading {font-family:'Space Grotesk',sans-serif;font-size:1.22rem;color:#EDF4FB;font-weight:650;margin:0 0 7px;}
.bil-panel-text {color:#9BB0C5;font-size:.9rem;line-height:1.55;margin:0 0 9px;}
.bil-footer {font-size:.77rem;color:#8A9CB1;border-top:1px solid rgba(136,168,196,.14);padding-top:21px;margin-top:45px;line-height:1.8;}
@media(max-width:650px){.bil-hero{padding:28px 24px;border-radius:16px;}[data-testid="stMainBlockContainer"]{padding-top:1rem;}.bil-card{min-height:0;}}
</style>
"""

def apply_theme():
    st.markdown(CSS, unsafe_allow_html=True)

def side_brand():
    st.sidebar.markdown('<div class="bil-brand">◈ Battery Investment Lab</div><div class="bil-brand-sub">ENERGY · DATA · OPTIMIZATION</div>', unsafe_allow_html=True)

def section_intro(tag, heading, summary):
    st.markdown(f'<div class="bil-label">{tag}</div>', unsafe_allow_html=True)
    st.title(heading)
    st.caption(summary)

def metric_card(label, value, description, accent=False):
    # All inputs are locally defined showcase constants, not arbitrary user HTML.
    cls = 'bil-big bil-accent' if accent else 'bil-big'
    st.markdown(f'<div class="bil-card"><div class="bil-kicker">{label}</div><div class="{cls}">{value}</div><div class="bil-descr">{description}</div></div>', unsafe_allow_html=True)

def footer():
    st.markdown('<div class="bil-footer">Historiske spotdata: Energinet, Energi Data Service (CC BY 4.0). Priser er aggregeret til daglige gennemsnit for visning. Historiske simuleringsresultater er ikke prognoser eller finansiel rådgivning.<br>Independent portfolio project · Battery Investment Lab</div>',unsafe_allow_html=True)
