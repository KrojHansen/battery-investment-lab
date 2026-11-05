"""Homepage with genuinely precomputed, transparent demonstration results."""
import streamlit as st
import pandas as pd
from demo_data import showcase, historical_spot_chart, strategies
from ui import metric_card, footer

D = showcase()
market = D['market_2025']
reference = D['strategy_2025_q4']

st.markdown("""<div class="bil-hero">
<div class="bil-eyebrow">PORTFOLIO PROJECT / PYTHON · ML · OPTIMIZATION</div>
<h1>From electricity prices to<br>investment decisions.</h1>
<p>Et interaktivt analyseværktøj til at undersøge batterilagring på det danske elmarked. Udforsk historiske spotpriser, optimeret batteridrift, fem handelsstrategier og økonomiske investeringsscenarier.</p>
</div>""",unsafe_allow_html=True)

st.markdown('<span class="bil-chip">DK1 · Historiske eksempler fra 2025 · 10 MW / 20 MWh</span>',unsafe_allow_html=True)

c1,c2,c3 = st.columns(3)
with c1:
    metric_card('Bruttoarbitrage 2025', '5,68 mio. kr.', 'Teoretisk maksimum med fuld prisviden og månedsvis optimering.')
with c2:
    metric_card('Historisk backtest, Q4', '218.000 kr.', 'Kalenderregression, 90 dage, efter batterislitage, uden nettariffer.',accent=True)
with c3:
    metric_card('Andel af dagsoptimum', '45,2 %', 'Kalenderregression mod perfekt dagsfacit med maksimalt én cyklus pr. dag.')

st.caption('Fremhævede beløb stammer fra projektets tidligere lokale beregninger. De er ikke en prognose for indtjeningen i et kommercielt batterianlæg.')

st.markdown('## Udforsk energimarkedet')
left,right=st.columns([1.55,1],gap='large')
with left:
    st.markdown('### Elpriser i DK1, 2025')
    st.caption('Historiske day-ahead spotpriser. Dagligt gennemsnit i DKK/MWh, beregnet fra de originale time- og kvartersprodukter.')
    chart = historical_spot_chart().set_index('date')[['price_dkk_mwh']]
    st.line_chart(chart, color='#39D9C1', x_label='Dato', y_label='DKK/MWh', height=280)
    st.caption('Kilde: Energinet, Energi Data Service. Data er aggregeret til daglige gennemsnit.')
with right:
    st.markdown('### Fra data til beslutning')
    with st.container(border=True):
        st.markdown('**01 · Markedsoptimering**')
        st.caption('Hvad er batteriets teoretiske handelsmuligheder, når historiske priser er kendt?')
        st.page_link('market_optimization.py',label='Åbn markedsoptimering',icon='🔋',use_container_width=True)
    with st.container(border=True):
        st.markdown('**02 · Handelsstrategier**')
        st.caption('Hvor godt klarer algoritmerne sig, når de kun må bruge tidligere priser?')
        st.page_link('pages/2_Realistisk_handelsstrategi.py',label='Se handelsstrategier',icon='📈',use_container_width=True)
    with st.container(border=True):
        st.markdown('**03 · Investeringsanalyse**')
        st.caption('Hvordan påvirker anlæggets pris, OPEX og rente projektets nutidsværdi?')
        st.page_link('pages/1_Investeringsanalyse.py',label='Prøv investeringsanalyse',icon='💰',use_container_width=True)

st.markdown('## Hvilken handelsstrategi klarede sig bedst?')
st.caption('Eksempel fra en 90-dages historisk test, 3. oktober til 31. december 2025. Samme maksimale antal cyklusser pr. dag, nul tariffer og handelsgebyrer.')
rows = strategies()
chart = rows[['strategy','profit_dkk']].rename(columns={'strategy':'Strategi','profit_dkk':'Nettoresultat (DKK)'})
st.bar_chart(chart.set_index('Strategi'), color='#39D9C1',horizontal=True,height=300)

st.markdown('### Projektets metode')
m1,m2,m3=st.columns(3,gap='medium')
with m1:
    with st.container(border=True):
        st.markdown('**01 · Data og kvalitetssikring**')
        st.caption('Historiske priser fra Energinet, tidszoner, sommertid og skift fra timepriser til kvarterspriser.')
with m2:
    with st.container(border=True):
        st.markdown('**02 · Optimering og prognoser**')
        st.caption('Lineær/mixed-integer optimering, prisprognoser og walk-forward evaluering med Gradient Boosting.')
with m3:
    with st.container(border=True):
        st.markdown('**03 · Økonomisk evaluering**')
        st.caption('Indtjening, cyklusser, tabsgivende dage, omkostningsfølsomhed, NPV og IRR.')

with st.expander('Hvad betyder tallene, og hvad er ikke modelleret?'):
    st.write('Alle handelsresultater er historiske simuleringer. Perfekt prisviden er en øvre teoretisk reference og kan ikke handles direkte. De prognosebaserede backtests antager fuld ordreudførelse til clearingprisen. Ubalancer, likviditet, prisafhængige bud og fulde projektspecifikke omkostninger er ikke modelleret. Den viste 90-dages test er tidligere blevet brugt til modelsammenligning og er ikke en uberørt testperiode.')
    st.write('Kilde: Energinet, Energi Data Service, under Creative Commons CC BY 4.0. Data er ændret ved aggregering til daglige gennemsnit.')

footer()
