import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
from dateutil.relativedelta import relativedelta

# --- CONFIGURACIÓN DE RUTAS Y DATOS ---
# 🚨 ¡IMPORTANTE! Revisa que esta ruta sea correcta en tu computadora
FILE_PATH = r'C:\Users\Gerente Credito\Desktop\reporte_comite\master_comite_automatizacion.xlsx'
SHEET_MASTER = 'master_comite_automatizacion'

# --- 1. FUNCIÓN DE CARGA Y TRANSFORMACIÓN MÍNIMA ---
@st.cache_data
def load_and_transform_data(file_path):
    """Carga los datos y aplica las transformaciones mínimas necesarias."""
    try:
        # 1.1 Importación
        df_master = pd.read_excel(file_path, sheet_name=SHEET_MASTER)
        
        # Dependencias necesarias para el filtro de mora
        buckets_mora_30_150 = ["031-060", "061-090", "091-120", "121-150"]

        # Conversiones de tipo
        # Forzar el formato YYYY-MM para mes_apertura
        df_master['mes_apertura'] = pd.to_datetime(
            df_master['mes_apertura'], 
            format='%Y-%m', 
            errors='coerce' # Convierte valores no válidos a NaT
        )
        df_master['fecha_cierre'] = pd.to_datetime(df_master['fecha_cierre'], errors='coerce')

        # W: Mes_BperturB (FIN.MES)
        df_master['Mes_BperturB'] = df_master['mes_apertura'] + pd.offsets.MonthEnd(0)

        # Y: Mora_30-150 (Bandera de mora)
        df_master['Mora_30-150'] = np.where(df_master['bucket'].isin(buckets_mora_30_150), 'Sí', 'No')
        
        # AP: PR_Origen_Limpio (Para filtros interactivos)
        digital_origenes = ["Promotor Digital", "Chatbot"]
        df_master['PR_Origen_Limpio'] = np.where(df_master['origen'].isin(digital_origenes), "Digital", "Físico")

        # Columnas esenciales para el gráfico y filtros
        return df_master[['Mes_BperturB', 'saldo_capital_total', 'Mora_30-150', 'uen', 'PR_Origen_Limpio', 'fecha_cierre']].copy()

    except Exception as e:
        st.error(f"Error al cargar o transformar los datos. Detalle: {e}")
        return pd.DataFrame()


# --- FUNCIÓN DE CÁLCULO DE TABLA PIVOTE DE MORA ---
def calculate_pivot_table(df, time_periods=24, time_column='Mes_BperturB', value_column='saldo_capital_total', mora_column='Mora_30-150'):
    
    # 1. Identificar los últimos N cohortes
    all_dates = df[time_column].dropna().sort_values(ascending=False).unique()
    last_n_dates = all_dates[:min(time_periods, len(all_dates))]
    
    # 2. Filtrar el DataFrame para incluir solo esas N cohortes
    df_filtered = df[df[time_column].isin(last_n_dates)].copy()
    
    # 3. Agrupar y sumar
    df_summary = df_filtered.groupby([time_column, mora_column])[value_column].sum().reset_index()
    
    # 4. Pivotar la tabla
    pivot_table = df_summary.pivot_table(
        index=time_column,
        columns=mora_column,
        values=value_column,
        aggfunc='sum'
    ).fillna(0)
    
    # 5. Formato de índice y total
    pivot_table.index = pivot_table.index.strftime('%Y-%m')
    pivot_table['TOTAL SALDO'] = pivot_table.sum(axis=1)

    return pivot_table.sort_index(ascending=False)


# --- CARGA PRINCIPAL DEL DATAFRAME ---
df_master = load_and_transform_data(FILE_PATH)


# --- 2. INTERFAZ DE STREAMLIT ---

st.set_page_config(layout="wide")
st.title("📊 Desglose de Saldo por Cohorte de Apertura y Mora")

if df_master.empty:
    st.error("No se pudo cargar y procesar el DataFrame maestro.")
    st.stop()

# --- FILTROS LATERALES ---
st.sidebar.header("Filtros Interactivos")
st.sidebar.markdown("**Nota:** Los datos de la tabla se limitan a las últimas 24 cohortes de apertura y no se ven afectados por estos filtros de UEN/Origen.")

# 1. Filtro por UEN
uen_options = df_master['uen'].unique()
st.sidebar.multiselect("Selecciona UEN (Filtro informativo)", uen_options, default=uen_options[:min(2, len(uen_options))])

# 2. Filtro por Origen Limpio
origen_options = df_master['PR_Origen_Limpio'].unique()
st.sidebar.multiselect("Selecciona Origen (Filtro informativo)", origen_options, default=origen_options)

# --- VISUALIZACIÓN PRINCIPAL: TABLA PIVOTE ---

st.header("1. Saldo Capital Total por Cohorte de Apertura y Bandera Mora 30-150")
st.markdown("La tabla muestra la suma de `saldo_capital_total` para las últimas 24 cohortes de `Mes_BperturB`, segmentado por la bandera `Mora 30-150`.")

try:
    # Calcular la Tabla Pivote
    df_pivot_mora = calculate_pivot_table(df_master.copy()) 

    if not df_pivot_mora.empty:
        st.subheader("Tabla Pivote de Saldo por Mora (Últimas 24 Cohortes)")
        
        # Formato de la tabla
        def format_currency(val):
            return f'{val:,.0f}'

        # Mostrar la tabla formateada
        st.dataframe(df_pivot_mora.applymap(format_currency))
        
        # Opcional: Gráfico de barras apiladas basado en la tabla pivote
        st.subheader("Visualización de Saldo en Mora por Cohorte")
        df_pivot_chart = df_pivot_mora.reset_index().melt(
            id_vars='Mes de Apertura',
            value_vars=['Sí', 'No'], # Solo Mora y No-Mora
            var_name='Mora 30-150',
            value_name='Saldo Capital'
        )
        
        fig_bar = px.bar(
            df_pivot_chart,
            x='Mes de Apertura',
            y='Saldo Capital',
            color='Mora 30-150',
            title='Suma de Saldo Capital (Mora vs. No Mora) por Cohorte de Apertura',
            template='plotly_white',
            labels={'Saldo Capital': 'Saldo Capital Total'}
        )
        fig_bar.update_yaxes(tickformat=",0f")
        st.plotly_chart(fig_bar, use_container_width=True)


    else:
        st.warning("No hay datos suficientes para generar la tabla pivote de Saldo por Mora.")

except Exception as e:
    st.error(f"Error al generar la tabla pivote: {e}")