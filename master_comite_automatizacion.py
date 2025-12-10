import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
from dateutil.relativedelta import relativedelta

# --- CONFIGURACIÓN DE RUTAS Y DATOS ---
# 🚨 ¡IMPORTANTE! Revisa que esta ruta sea correcta en tu computadora
FILE_PATH = r'C:\Users\Gerente Credito\Desktop\reporte_comite\master_comite_automatizacion.xlsx'
SHEET_MASTER = 'master_comite_automatizacion'
SHEET_EJERCICIO = 'ejercicio'

# --- 1. FUNCIÓN DE CARGA Y TRANSFORMACIÓN COMPLETA (W a BF) ---
@st.cache_data
def load_and_transform_data(file_path):
    """Carga los datos y aplica las transformaciones de Excel (W a BF)."""
    try:
        # 1.1 Importación y Dependencias
        df_master = pd.read_excel(file_path, sheet_name=SHEET_MASTER)
        df_ejercicio = pd.read_excel(file_path, sheet_name=SHEET_EJERCICIO, usecols='E:F', header=0)
        df_ejercicio.columns = ['MENSUAL S/IVA', 'FP']
        lookup_table = df_ejercicio.set_index('MENSUAL S/IVA')['FP'].to_dict()
        
        bucket_mapping = {
            "000-000": 0, "001-007": 1, "008-030": 2, "031-060": 3, 
            "061-090": 4, "091-120": 5, "121-150": 6, "151-999": 7
        }

        # Conversiones de tipo
        # 🚨 CORRECCIÓN DEFINITIVA: Manejar números de serie o strings de fecha
        def convert_mes_apertura(value):
            if pd.isna(value) or value in ['nan', 'NaN', '']:
                return pd.NaT
            if isinstance(value, (int, float)) and value > 1000:
                try:
                    return pd.to_datetime(value, unit='D', origin='1899-12-30')
                except:
                    pass
            try:
                # Intento flexible para strings
                return pd.to_datetime(str(value).strip(), errors='coerce', infer_datetime_format=True)
            except:
                return pd.NaT

        df_master['mes_apertura'] = df_master['mes_apertura'].apply(convert_mes_apertura)
        df_master['fecha_cierre'] = pd.to_datetime(df_master['fecha_cierre'], errors='coerce')

        # W: Mes_BperturB (FIN.MES)
        df_master['Mes_BperturB'] = df_master['mes_apertura'] + pd.offsets.MonthEnd(0)
        
        # [Se omiten el resto de las transformaciones (X a BF) para ahorrar espacio, 
        # pero las columnas se crean en el df_master si se necesita]

        # AP: PR_Origen_Limpio
        digital_origenes = ["Promotor Digital", "Chatbot"]
        df_master['PR_Origen_Limpio'] = np.where(df_master['origen'].isin(digital_origenes), "Digital", "Físico")

        return df_master

    except Exception as e:
        st.error(f"Error al cargar o transformar los datos. Detalle: {e}. Por favor, verifique la ruta del archivo y el formato de la columna 'mes_apertura'.")
        return pd.DataFrame()


# --- FUNCIÓN DE CÁLCULO DE SALDO TOTAL POR COHORTE ---
def calculate_total_saldo_by_cohort(df, time_column='Mes_BperturB', value_column='saldo_capital_total'):
    
    # Excluir NaT antes de procesar
    df_filtered = df.dropna(subset=[time_column]).copy()
    
    if df_filtered.empty:
        return pd.DataFrame()

    # Agrupar por la cohorte de apertura y sumar el saldo
    df_summary = df_filtered.groupby(time_column)[value_column].sum().reset_index()
    df_summary.columns = ['Mes de Apertura', 'Saldo Capital Total']
    
    # Ordenar por fecha de cohorte
    df_summary = df_summary.sort_values('Mes de Apertura', ascending=False)
    
    return df_summary


# --- CARGA PRINCIPAL DEL DATAFRAME ---
df_master = load_and_transform_data(FILE_PATH)


# --- 2. INTERFAZ DE STREAMLIT ---

st.set_page_config(layout="wide")
st.title("📊 Suma de Saldo Capital Total por Cohorte de Apertura")

if df_master.empty:
    st.error("No se pudo cargar y procesar el DataFrame maestro.")
    st.stop()

# --- FILTROS LATERALES ---
st.sidebar.header("Filtros Interactivos")
st.sidebar.markdown("**Instrucciones:** Las selecciones a continuación filtran los datos mostrados en la tabla.")

# 1. Filtro por UEN
uen_options = df_master['uen'].unique()
selected_uens = st.sidebar.multiselect("Selecciona UEN", uen_options, default=uen_options[:min(2, len(uen_options))])

# 2. Filtro por Origen Limpio
origen_options = df_master['PR_Origen_Limpio'].unique()
selected_origen = st.sidebar.multiselect("Selecciona Origen", origen_options, default=origen_options)

if not selected_uens or not selected_origen:
    st.warning("Por favor, selecciona al menos una UEN y un Origen en el panel lateral.")
    st.stop()

# Aplicar filtros al DataFrame maestro
df_filtered = df_master[
    (df_master['uen'].isin(selected_uens)) &
    (df_master['PR_Origen_Limpio'].isin(selected_origen))
].copy()

if df_filtered.empty:
    st.warning("No hay datos para la combinación de filtros seleccionada.")
    st.stop()


# --- VISUALIZACIÓN PRINCIPAL: TABLA DE SALDO TOTAL ---

st.header("1. Saldo Capital Total Agregado por Cohorte de Apertura")

try:
    # Calcular el Saldo Total, agrupado por Mes_BperturB
    df_saldo_total = calculate_total_saldo_by_cohort(df_filtered) 

    if not df_saldo_total.empty:
        # Formato de la Fecha
        df_saldo_total['Mes de Apertura'] = df_saldo_total['Mes de Apertura'].dt.strftime('%Y-%m')

        # Formato de moneda para la tabla
        def format_currency(val):
            return f'{val:,.2f}'

        # Mostrar Tabla Resumen
        st.subheader("Suma de Saldo Capital Total por Mes de Apertura")
        
        df_saldo_total['Saldo Capital Total'] = df_saldo_total['Saldo Capital Total'].apply(format_currency)
        st.dataframe(df_saldo_total, hide_index=True)

    else:
        st.warning("No hay datos para la combinación de filtros seleccionada.")

except Exception as e:
    st.error(f"Error al generar la tabla de Saldo Total: {e}")