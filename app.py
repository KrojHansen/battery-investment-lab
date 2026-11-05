"""Portfolio entrypoint for Battery Investment Lab. Run: streamlit run app.py"""
import streamlit as st
from ui import apply_theme, side_brand

st.set_page_config(
    page_title='Battery Investment Lab | Energy market analytics',
    page_icon='🔋',
    layout='wide',
    initial_sidebar_state='expanded',
)

apply_theme()
side_brand()

navigation = st.navigation(
    {
        'START HER': [
            st.Page('overview.py', title='Oversigt', icon='🏠', default=True),
        ],
        'ANALYSER': [
            st.Page('market_optimization.py', title='Markedsoptimering', icon='🔋', url_path='market'),
            st.Page('pages/2_Realistisk_handelsstrategi.py', title='Handelsstrategier', icon='📈', url_path='strategies'),
            st.Page('pages/1_Investeringsanalyse.py', title='Investeringsanalyse', icon='💰', url_path='investment'),
        ],
    },
    position='sidebar',
)

st.sidebar.caption('Research prototype · Version 1.0')
navigation.run()
