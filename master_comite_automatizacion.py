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

# --- 1. FUNCIÓN DE CARGA Y TRANSFORMACIÓN MÍNIMA ---
@st.cache_data
def load_and_transform_data(file_path):
    """Carga los datos y aplica las transformaciones mínimas necesarias."""
    try:
        # 1.1 Importación
        df_master = pd.read_excel(file_path, sheet_name=SHEET_MASTER)
        
        # Dependencias necesarias para la Mora_30-150
        buckets_mora_30_150 = ["031-060", "061-090", "091-120", "121-150"]

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
        
        # Y: Mora_30-150 (Bandera de mora)
        df_master['Mora_30-150'] = np.where(df_master['bucket'].isin(buckets_mora_30_150), 'Sí', 'No')
        
        # AP: PR_Origen_Limpio (Para filtros interactivos)
        digital_origenes = ["Promotor Digital", "Chatbot"]
        df_master['PR_Origen_Limpio'] = np.where(df_master['origen'].isin(digital_origenes), "Digital", "Físico")

        # Columnas esenciales
        return df_master[['Mes_BperturB', 'saldo_capital_total', 'Mora_30-150', 'uen', 'PR_Origen_Limpio']].copy()

    except Exception as e:
        st.error(f"Error al cargar o transformar los datos. Detalle: {e}. Por favor, verifique la ruta del archivo y el formato de la columna 'mes_apertura'.")
        return pd.DataFrame()


# --- FUNCIÓN DE CÁLCULO DE SALDO PIVOTE POR COHORTE Y MORA ---
def calculate_saldo_pivot(df, time_column='Mes_BperturB', value_column='saldo_capital_total', mora_column='Mora_30-150'):
    
    # Excluir NaT antes de procesar
    df_filtered = df.dropna(subset=[time_column]).copy()
    
    if df_filtered.empty:
        return pd.DataFrame()

    # 1. Agrupar por cohorte y mora para sumar el saldo
    df_summary = df_filtered.groupby([time_column, mora_column])[value_column].sum().reset_index()
    
    # 2. Pivotar la tabla
    pivot_table = df_summary.pivot_table(
        index=time_column,
        columns=mora_column,
        values=value_column,
        aggfunc='sum'
    ).fillna(0)
    
    # 3. Calcular el total y ordenar
    pivot_table['TOTAL SALDO'] = pivot_table.sum(axis=1)
    
    # 4. Formato final del índice
    pivot_table.index.name = "Mes de Apertura"
    pivot_table.index = pivot_table.index.strftime('%Y-%m')

    # 5. Renombrar columnas para claridad
    pivot_table.columns.name = "Mora 30-150"
    
    # Ordenar por fecha de cohorte (más reciente primero)
    return pivot_table.sort_index(ascending=False)


# --- CARGA PRINCIPAL DEL DATAFRAME ---
df_master = load_and_transform_data(FILE_PATH)


# --- 2. INTERFAZ DE STREAMLIT ---

st.set_page_config(layout="wide")
st.title("📊 Desglose de Saldo Capital Total por Cohorte y Mora")

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


# --- VISUALIZACIÓN PRINCIPAL: TABLA PIVOTE DE SALDO ---

st.header("1. Saldo Capital Total por Mes de Apertura y Bandera Mora 30-150")

try:
    # Calcular la Tabla Pivote
    df_pivot_saldo = calculate_saldo_pivot(df_filtered) 

    if not df_pivot_saldo.empty:
        # Formato de moneda para la tabla
        def format_currency(val):
            return f'{val:,.0f}'

        st.subheader(f"Suma de Saldo por Cohorte ({', '.join(selected_uens)})")
        
        # Mostrar la tabla formateada
        st.dataframe(df_pivot_saldo.applymap(format_currency))

        # Opcional: Gráfico de barras apiladas para visualizar la distribución
        st.subheader("Distribución de Saldo (Mora vs. No Mora)")
        
        df_pivot_chart = df_pivot_saldo.reset_index().melt(
            id_vars='Mes de Apertura',
            value_vars=['Sí', 'No'], # Columnas de Mora
            var_name='Mora 30-150',
            value_name='Saldo Capital'
        )
        
        fig_bar = px.bar(
            df_pivot_chart,
            x='Mes de Apertura',
            y='Saldo Capital',
            color='Mora 30-150',
            title='Distribución de Saldo Capital: Mora vs. No Mora',
            template='plotly_white',
            labels={'Saldo Capital': 'Saldo Capital Total'}
        )
        fig_bar.update_yaxes(tickformat=",0f")
        st.plotly_chart(fig_bar, use_container_width=True)

    else:
        st.warning("No hay datos que cumplan con los criterios de filtro para generar el gráfico.")

except Exception as e:
    st.error(f"Error al generar la tabla pivote de Saldo: {e}")