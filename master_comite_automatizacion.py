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

# --- 1. FUNCIÓN DE CARGA Y TRANSFORMACIÓN COMPLETA ---
@st.cache_data
def load_and_transform_data(file_path):
    """Carga los datos y aplica las transformaciones necesarias, incluyendo las columnas C2 a C25."""
    try:
        # 1.1 Importación
        df_master = pd.read_excel(file_path, sheet_name=SHEET_MASTER)
        
        # Dependencias de mora y mapeo
        buckets_mora_30_150 = ["031-060", "061-090", "091-120", "121-150"]
        buckets_mora_08_90 = ["008-030", "031-060", "061-090"]

        # Conversiones de tipo (Corrección de fecha robusta)
        def convert_mes_apertura(value):
            if pd.isna(value) or value in ['nan', 'NaN', '']:
                return pd.NaT
            if isinstance(value, (int, float)) and value > 1000:
                try:
                    return pd.to_datetime(value, unit='D', origin='1899-12-30')
                except:
                    pass
            try:
                return pd.to_datetime(str(value).strip(), errors='coerce', infer_datetime_format=True)
            except:
                return pd.NaT

        df_master['mes_apertura'] = df_master['mes_apertura'].apply(convert_mes_apertura)
        df_master['fecha_cierre'] = pd.to_datetime(df_master['fecha_cierre'], errors='coerce')

        # W: Mes_BperturB (FIN.MES)
        df_master['Mes_BperturB'] = df_master['mes_apertura'] + pd.offsets.MonthEnd(0)
        
        # Bandera: Mora_30-150
        df_master['Mora_30-150'] = np.where(df_master['bucket'].isin(buckets_mora_30_150), 'Sí', 'No')
        
        # Bandera: Mora_08-90
        df_master['Mora_08-90'] = np.where(df_master['bucket'].isin(buckets_mora_08_90), 'Sí', 'No')

        # AP: PR_Origen_Limpio
        digital_origenes = ["Promotor Digital", "Chatbot"]
        df_master['PR_Origen_Limpio'] = np.where(df_master['origen'].isin(digital_origenes), "Digital", "Físico")

        # --- CÁLCULO DE DIFERENCIA DE MESES (Antigüedad) ---
        
        # Función para calcular la diferencia de meses (fecha_cierre - Mes_BperturB)
        def get_month_diff(date1, date2):
            if pd.isna(date1) or pd.isna(date2):
                return np.nan
            # Resta date1 (Mes_BperturB) de date2 (fecha_cierre)
            return (date2.year - date1.year) * 12 + (date2.month - date1.month)

        df_master['dif_mes'] = df_master.apply(
            lambda row: get_month_diff(row['Mes_BperturB'], row['fecha_cierre']), axis=1
        )

        # --- COLUMNAS DE SALDO CONDICIONAL ---
        df_master['saldo_capital_total_30150'] = np.where(
            df_master['Mora_30-150'] == 'Sí',
            df_master['saldo_capital_total'],
            0
        )
        df_master['saldo_capital_total_890'] = np.where(
            df_master['Mora_08-90'] == 'Sí',
            df_master['saldo_capital_total'],
            0
        )
        df_master['saldo_capital_total'] = pd.to_numeric(df_master['saldo_capital_total'], errors='coerce').fillna(0)
        
        
        # --- COLUMNAS DE SEGUIMIENTO POR ANTIGÜEDAD (C2 a C25) ---
        
        # Iteramos desde la antigüedad 1 (C2) hasta la 24 (C25)
        for n in range(1, 25):
            col_index = n + 1 # Columna C2, C3, ..., C25
            col_name = f'saldo_capital_total_c{col_index}'
            
            # Lógica: SI(dif_meses = n, saldo_capital_total_30150, 0)
            df_master[col_name] = np.where(
                df_master['dif_mes'] == n,
                df_master['saldo_capital_total_30150'], 
                0
            )
        
        return df_master

    except Exception as e:
        st.error(f"Error al cargar o transformar los datos. Detalle: {e}. Por favor, verifique la ruta del archivo y el formato de la columna 'mes_apertura'.")
        return pd.DataFrame()


# --- FUNCIÓN DE CÁLCULO DE SALDO CONSOLIDADO POR COHORTE ---
def calculate_saldo_consolidado(df, time_column='Mes_BperturB'):
    
    # Excluir NaT antes de procesar
    df_filtered = df.dropna(subset=[time_column]).copy()
    
    if df_filtered.empty:
        return pd.DataFrame()

    # Generar el diccionario de agregación y el listado de nombres de columnas C
    agg_dict = {'saldo_capital_total': 'sum',
                'saldo_capital_total_30150': 'sum',
                'saldo_capital_total_890': 'sum'}
    
    column_names = ['Mes de Apertura', 'Saldo Capital Total', 'Mora 30-150', 'Mora 08-90']
    
    for n in range(1, 25):
        col_index = n + 1
        col_name = f'saldo_capital_total_c{col_index}'
        agg_dict[col_name] = 'sum'
        column_names.append(f'Mora C{col_index} (Ant={n})') # Ant=1 para C2, Ant=24 para C25

    # Agrupar y sumar todas las columnas de saldo (C2 a C25)
    df_summary = df_filtered.groupby(time_column).agg(agg_dict).reset_index()
    
    # Asignar los nombres de columna actualizados
    df_summary.columns = column_names
    
    # Ordenar por fecha de cohorte (más reciente primero)
    df_summary = df_summary.sort_values('Mes de Apertura', ascending=False)
    
    return df_summary


# --- CARGA PRINCIPAL DEL DATAFRAME ---
df_master = load_and_transform_data(FILE_PATH)


# --- 2. INTERFAZ DE STREAMLIT ---

st.set_page_config(layout="wide")
st.title("📊 Saldo Consolidado por Cohorte de Apertura")

if df_master.empty:
    st.error("No se pudo cargar y procesar el DataFrame maestro.")
    st.stop()


# --- 🛑 FILTRO PARA VISUALIZACIÓN: ÚLTIMAS 24 COHORTES DE APERTURA (CORREGIDO) 🛑 ---
if not df_master['Mes_BperturB'].empty:
    # 1. Obtener las fechas únicas
    unique_cohort_dates = df_master['Mes_BperturB'].dropna().unique()
    
    # 2. Convertir a datetime y ordenar (SOLUCIÓN AL ERROR)
    # Convertimos a Series para usar .sort_values()
    sorted_cohort_dates = pd.Series(pd.to_datetime(unique_cohort_dates)).sort_values(ascending=False)
    
    # 3. Seleccionar las últimas 24 (máximo)
    last_24_cohorts = sorted_cohort_dates.iloc[:24]
    
    # 4. Aplicar el filtro
    df_master = df_master[df_master['Mes_BperturB'].isin(last_24_cohorts)].copy()
    
    # Informar al usuario del filtro
    if not last_24_cohorts.empty:
        max_date = last_24_cohorts.max().strftime('%Y-%m')
        min_date = last_24_cohorts.min().strftime('%Y-%m')
        st.info(f"Filtro aplicado: Mostrando solo las últimas **{len(last_24_cohorts)} cohortes** de apertura, desde **{min_date}** hasta **{max_date}**.")
    
if df_master.empty:
    st.warning("El DataFrame maestro está vacío después de aplicar el filtro de las últimas 24 cohortes. Verifique que haya suficientes datos de cohorte.")
    st.stop()
# --- 🛑 FIN DEL FILTRO DE LAS 24 COHORTES 🛑 ---


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


# --- VISUALIZACIÓN PRINCIPAL: TABLA DE SALDO CONSOLIDADO ---

st.header("1. Saldo Capital Total y Seguimiento de Mora (C2 a C25)")

try:
    # Calcular la Tabla Consolidada
    df_saldo_consolidado = calculate_saldo_consolidado(df_filtered) 

    if not df_saldo_consolidado.empty:
        # Formato de la Fecha
        df_saldo_consolidado['Mes de Apertura'] = df_saldo_consolidado['Mes de Apertura'].dt.strftime('%Y-%m')

        # Formato de moneda para la tabla
        def format_currency(val):
            return f'{val:,.0f}'

        st.subheader("Suma de Saldos Condicionales por Mes de Apertura (Antigüedad C2 a C25)")
        
        # Aplicar formato de moneda a las columnas numéricas
        df_display = df_saldo_consolidado.copy()
        for col in df_display.columns[1:]:
            df_display[col] = df_display[col].apply(format_currency)
            
        st.dataframe(df_display, hide_index=True)

        st.subheader("Verificación de columnas clave para Antigüedad (Primeras 50 filas)")
        # Mostrar algunas columnas clave para la verificación del filtro y las transformaciones
        verification_cols = ['Mes_BperturB', 'fecha_cierre', 'dif_mes', 'Mora_30-150', 'saldo_capital_total', 'saldo_capital_total_c2', 'saldo_capital_total_c25']
        
        existing_cols = [col for col in verification_cols if col in df_filtered.columns]
        st.dataframe(df_filtered[existing_cols].head(50))

    else:
        st.warning("No hay datos que cumplan con los criterios de filtro para generar la tabla.")

except Exception as e:
    st.error(f"Error al generar la tabla de Saldo Consolidado: {e}")