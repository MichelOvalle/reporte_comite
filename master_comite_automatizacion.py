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
        df_master['mes_apertura'] = pd.to_datetime(df_master['mes_apertura'], errors='coerce')
        df_master['fecha_cierre'] = pd.to_datetime(df_master['fecha_cierre'], errors='coerce')

        # Y: Mora_30-150 (Bandera de mora)
        df_master['Mora_30-150'] = np.where(df_master['bucket'].isin(buckets_mora_30_150), 'Sí', 'No')
        
        # AP: PR_Origen_Limpio (Para filtros interactivos, aunque no filtren el gráfico principal)
        digital_origenes = ["Promotor Digital", "Chatbot"]
        df_master['PR_Origen_Limpio'] = np.where(df_master['origen'].isin(digital_origenes), "Digital", "Físico")

        # Columnas esenciales para el gráfico (fecha_cierre, saldo_capital_total, Mora_30-150)
        return df_master[['fecha_cierre', 'saldo_capital_total', 'Mora_30-150', 'uen', 'PR_Origen_Limpio']].copy()

    except Exception as e:
        st.error(f"Error al cargar o transformar los datos. Detalle: {e}")
        return pd.DataFrame()


# --- FUNCIÓN DE CÁLCULO DE SALDO MORA ---
def calculate_mora_sum(df, time_periods=24, mora_filter="Sí", time_column='fecha_cierre', value_column='saldo_capital_total', mora_column='Mora_30-150'):
    
    # 1. Filtrar solo las filas con Mora 30-150 = "Sí"
    df_mora = df[df[mora_column] == mora_filter].copy()
    
    if df_mora.empty:
        return pd.DataFrame()

    # 2. Identificar los últimos N periodos de reporte
    all_dates = df_mora[time_column].sort_values(ascending=False).unique()
    last_n_dates = all_dates[:min(time_periods, len(all_dates))]
    
    # 3. Filtrar el DataFrame para incluir solo esos N periodos
    df_mora = df_mora[df_mora[time_column].isin(last_n_dates)]
    
    # 4. Agrupar por el periodo de tiempo y sumar el saldo
    df_summary = df_mora.groupby(time_column)[value_column].sum().reset_index()
    df_summary.columns = ['Fecha de Reporte', 'Saldo en Mora']
    
    # Ordenar por fecha para la visualización
    df_summary = df_summary.sort_values('Fecha de Reporte')
    
    return df_summary


# --- CARGA PRINCIPAL DEL DATAFRAME ---
df_master = load_and_transform_data(FILE_PATH)


# --- 2. INTERFAZ DE STREAMLIT ---

st.set_page_config(layout="wide")
st.title("📊 Saldo en Mora (Mora 30-150) por Mes de Reporte")

if df_master.empty:
    st.error("No se pudo cargar y procesar el DataFrame maestro.")
    st.stop()

# --- FILTROS LATERALES ---
st.sidebar.header("Filtros Interactivos")
st.sidebar.markdown("**Nota:** Este gráfico muestra el saldo agregado de los últimos 24 meses de reporte y no se ve afectado por estos filtros.")

# 1. Filtro por UEN
uen_options = df_master['uen'].unique()
st.sidebar.multiselect("Selecciona UEN", uen_options, default=uen_options[:min(2, len(uen_options))])

# 2. Filtro por Origen Limpio
origen_options = df_master['PR_Origen_Limpio'].unique()
st.sidebar.multiselect("Selecciona Origen", origen_options, default=origen_options)

# --- VISUALIZACIÓN PRINCIPAL: SALDO EN MORA ---

st.header("1. Saldo Capital Total en Mora (Mora 30-150) - Últimos 24 Meses")

try:
    # Calcular el Saldo en Mora
    df_saldo_mora = calculate_mora_sum(df_master.copy()) 

    if not df_saldo_mora.empty:
        # Formato de la Fecha para el eje X
        df_saldo_mora['Fecha de Reporte'] = df_saldo_mora['Fecha de Reporte'].dt.strftime('%Y-%m')

        # Crear Gráfico de Barras
        fig_mora = px.bar(
            df_saldo_mora,
            x='Fecha de Reporte',
            y='Saldo en Mora',
            title='Suma de Saldo Capital Total con Mora 30-150',
            labels={'Saldo en Mora': 'Saldo (Mora 30-150)', 'Fecha de Reporte': 'Mes de Reporte'},
            template='plotly_white',
            text='Saldo en Mora' # Mostrar valor sobre la barra
        )
        # Formato de texto para el valor (opcional)
        fig_mora.update_traces(texttemplate='%{y:,.0f}', textposition='outside')
        fig_mora.update_yaxes(title='Saldo en Mora', tickformat=",0f")
        
        # Mostrar Gráfico
        st.plotly_chart(fig_mora, use_container_width=True)

        # Mostrar Tabla Resumen
        st.subheader("Tabla de Saldo en Mora")
        df_saldo_mora['Saldo en Mora'] = df_saldo_mora['Saldo en Mora'].apply(lambda x: f'{x:,.2f}')
        st.dataframe(df_saldo_mora)

    else:
        st.warning("No hay datos que cumplan con la condición 'Mora 30-150 = Sí' para generar el gráfico.")

except Exception as e:
    st.error(f"Error al generar el gráfico de Saldo en Mora: {e}")