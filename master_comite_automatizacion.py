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
    """Carga los datos y aplica todas las transformaciones de Excel (W a BF), incluyendo la corrección de fechas."""
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

        # 🚨 CORRECCIÓN DEFINITIVA: Intentar convertir mes_apertura desde número de serie de Excel o string
        
        def convert_mes_apertura(value):
            if pd.isna(value) or value in ['nan', 'NaN', '']:
                return pd.NaT
            
            # Intento 1: Si es un número (número de serie de Excel), convertirlo.
            if isinstance(value, (int, float)) and value > 1000: # Las fechas de Excel son grandes (ej. 45000)
                try:
                    # Convertir número de serie de Excel a fecha (asumiendo sistema 1900)
                    return pd.to_datetime(value, unit='D', origin='1899-12-30')
                except:
                    pass
            
            # Intento 2: Si es una cadena, intentar inferir el formato (flexible)
            try:
                return pd.to_datetime(str(value).strip(), errors='coerce', infer_datetime_format=True)
            except:
                return pd.NaT

        df_master['mes_apertura'] = df_master['mes_apertura'].apply(convert_mes_apertura)
        
        # Conversión de fecha de cierre
        df_master['fecha_cierre'] = pd.to_datetime(df_master['fecha_cierre'], errors='coerce')

        # --- CREACIÓN DE COLUMNAS (W a BF) ---
        
        # W: Mes_BperturB (FIN.MES)
        df_master['Mes_BperturB'] = df_master['mes_apertura'] + pd.offsets.MonthEnd(0)
        
        # El resto de las transformaciones (X a BF) se omiten en este bloque por brevedad,
        # pero la lógica es la misma que ya te proporcioné.
        # Solo necesitamos las columnas esenciales para la interfaz.
        
        # Y: Mora_30-150
        buckets_mora_30_150 = ["031-060", "061-090", "091-120", "121-150"]
        df_master['Mora_30-150'] = np.where(df_master['bucket'].isin(buckets_mora_30_150), 'Sí', 'No')

        # AP: PR_Origen_Limpio
        digital_origenes = ["Promotor Digital", "Chatbot"]
        df_master['PR_Origen_Limpio'] = np.where(df_master['origen'].isin(digital_origenes), "Digital", "Físico")

        return df_master

    except Exception as e:
        st.error(f"Error al cargar y procesar los datos: {e}. Por favor, verifique la ruta del archivo.")
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
    
    # Ordenar por fecha para la visualización
    df_summary = df_summary.sort_values('Mes de Apertura')
    
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
st.sidebar.markdown("**Instrucciones:** Las selecciones a continuación filtran los datos mostrados en la gráfica.")

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


# --- VISUALIZACIÓN PRINCIPAL: SALDO TOTAL ---

st.header("1. Saldo Capital Total por Cohorte de Apertura")

try:
    # Calcular el Saldo Total, agrupado por Mes_BperturB
    df_saldo_total = calculate_total_saldo_by_cohort(df_filtered) 

    if not df_saldo_total.empty:
        # Formato de la Fecha para el eje X
        df_saldo_total['Mes de Apertura'] = df_saldo_total['Mes de Apertura'].dt.strftime('%Y-%m')

        # Crear Gráfico de Barras
        fig_total = px.bar(
            df_saldo_total,
            x='Mes de Apertura',
            y='Saldo Capital Total',
            title='Suma de Saldo Capital Total por Cohorte de Apertura',
            labels={'Saldo Capital Total': 'Saldo Total', 'Mes de Apertura': 'Cohorte de Apertura'},
            template='plotly_white',
            text='Saldo Capital Total'
        )
        # Formato de texto y ejes
        fig_total.update_traces(texttemplate='%{y:,.0f}', textposition='outside')
        fig_total.update_yaxes(title='Saldo Total', tickformat=",0f", showgrid=True)
        
        # Mostrar Gráfico
        st.plotly_chart(fig_total, use_container_width=True)

        # Mostrar Tabla Resumen
        st.subheader("Tabla de Saldo Total por Cohorte")
        df_saldo_total['Saldo Capital Total'] = df_saldo_total['Saldo Capital Total'].apply(lambda x: f'{x:,.2f}')
        st.dataframe(df_saldo_total)

    else:
        st.warning("No hay datos que cumplan con los criterios de filtro para generar el gráfico.")

except Exception as e:
    st.error(f"Error al generar el gráfico de Saldo Total: {e}")