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
    """Carga los datos y aplica las transformaciones necesarias, incluyendo las columnas C1 a C25 y CAPITAL_C1 a CAPITAL_C25."""
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
        
        
        # --- COLUMNAS DE SEGUIMIENTO DE MORA (C1 a C25) ---
        
        # C1 (Inicializada a 0)
        df_master['saldo_capital_total_c1'] = 0 
        
        # Iteramos C2 a C25 (Antigüedad 1 a 24)
        for n in range(1, 25):
            col_index = n + 1 
            col_name = f'saldo_capital_total_c{col_index}'
            
            # Lógica: SI(dif_meses = n, saldo_capital_total_30150, 0)
            df_master[col_name] = np.where(
                df_master['dif_mes'] == n,
                df_master['saldo_capital_total_30150'], 
                0
            )

        # --- COLUMNAS DE CAPITAL (CAPITAL_C1 a CAPITAL_C25) ---
        
        # CAPITAL_C1 (Inicializada a 0)
        df_master['capital_c1'] = 0

        # Iteramos CAPITAL_C2 a CAPITAL_C25 (Antigüedad 1 a 24)
        for n in range(1, 25):
            col_index = n + 1 
            col_name = f'capital_c{col_index}'
            
            # Lógica: SI(dif_meses = n, saldo_capital_total, 0)
            df_master[col_name] = np.where(
                df_master['dif_mes'] == n,
                df_master['saldo_capital_total'], 
                0
            )
        
        return df_master

    except Exception as e:
        st.error(f"Error al cargar o transformar los datos. Detalle: {e}. Por favor, verifique la ruta del archivo y el formato de la columna 'mes_apertura'.")
        return pd.DataFrame()


# --- FUNCIÓN DE CÁLCULO DE SALDO CONSOLIDADO POR COHORTE (¡CALCULA LA TASA DE MORA!) ---
def calculate_saldo_consolidado(df, time_column='Mes_BperturB'):
    
    # Excluir NaT antes de procesar
    df_filtered = df.dropna(subset=[time_column]).copy()
    
    if df_filtered.empty:
        return pd.DataFrame()

    # 1. Definir columnas a sumar (Mora y Capital)
    agg_dict = {'saldo_capital_total': 'sum',
                'saldo_capital_total_30150': 'sum',
                'saldo_capital_total_890': 'sum',
                'saldo_capital_total_c1': 'sum',
                'capital_c1': 'sum'}
    
    # Listas para manejar los pares de columnas C_n y Capital_C_n
    c_cols_mora = ['saldo_capital_total_c1']
    c_cols_capital = ['capital_c1']

    for n in range(1, 25):
        col_index = n + 1
        mora_col = f'saldo_capital_total_c{col_index}'
        capital_col = f'capital_c{col_index}'
        
        agg_dict[mora_col] = 'sum'
        agg_dict[capital_col] = 'sum'
        
        c_cols_mora.append(mora_col)
        c_cols_capital.append(capital_col)

    # 2. Agrupar y sumar todas las columnas
    df_summary = df_filtered.groupby(time_column).agg(agg_dict).reset_index()
    
    # 3. Preparación y cálculo de la Tasa de Mora
    
    # Asegurar que 'Mes de Apertura' es Datetime
    df_summary['Mes de Apertura'] = pd.to_datetime(df_summary[time_column])
    
    # 🚨 CAMBIO CLAVE: Excluimos 'saldo_capital_total_30150' y 'saldo_capital_total_890'
    df_tasas = df_summary[['Mes de Apertura', 'saldo_capital_total']].copy()
    
    # Calcular las tasas C1 a C25
    for mora_col, capital_col in zip(c_cols_mora, c_cols_capital):
        # Tasa = (Mora_Cn / Capital_Cn) * 100
        tasa = np.where(
            df_summary[capital_col] != 0,
            (df_summary[mora_col] / df_summary[capital_col]) * 100,
            0
        )
        df_tasas[mora_col] = tasa
        
    # 4. Renombrar columnas para la presentación
    # La lista de nombres ahora tiene 2 columnas menos al inicio
    column_names = ['Mes de Apertura', 'Saldo Capital Total (Monto)']
    
    # Renombrar columnas de tasas C1 a C25
    for n in range(1, 26):
        column_names.append(f'Tasa Mora C{n} (Ant={n-1})')
    
    df_tasas.columns = column_names
    
    # 5. Ordenar por fecha de cohorte (más reciente primero)
    df_tasas = df_tasas.sort_values('Mes de Apertura', ascending=False)
    
    return df_tasas


# --- CARGA PRINCIPAL DEL DATAFRAME ---
df_master = load_and_transform_data(FILE_PATH)


# --- 2. INTERFAZ DE STREAMLIT ---

st.set_page_config(layout="wide")
st.title("📊 Tasa de Mora por Cohorte (Análisis Vintage)")

if df_master.empty:
    st.error("No se pudo cargar y procesar el DataFrame maestro.")
    st.stop()


# --- 🛑 FILTRO PARA VISUALIZACIÓN: ÚLTIMAS 24 COHORTES DE APERTURA ---
if not df_master['Mes_BperturB'].empty:
    # 1. Obtener las fechas únicas
    unique_cohort_dates = df_master['Mes_BperturB'].dropna().unique()
    
    # 2. Convertir a datetime y ordenar 
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


# --- VISUALIZACIÓN PRINCIPAL: TABLA DE TASAS DE MORA (VINTAGE) ---

st.header("1. Tasa de Mora 30-150 por Cohorte y Antigüedad (Vintage)")

try:
    # Calcular la Tabla Consolidada y las Tasas
    df_tasas_mora = calculate_saldo_consolidado(df_filtered) 

    if not df_tasas_mora.empty:
        # Formato de la Fecha 
        df_tasas_mora['Mes de Apertura'] = df_tasas_mora['Mes de Apertura'].dt.strftime('%Y-%m')

        # Formato de moneda para los montos y porcentaje para las tasas
        def format_currency(val):
            return f'{val:,.0f}'
        def format_percent(val):
            return f'{val:,.2f}%'

        st.subheader("Curva de Mora 30-150 de la Cartera por Antigüedad (C1 a C25)")
        
        df_display = df_tasas_mora.copy()
        
        # Aplicar formato: Monto solo a la segunda columna (índice 1: Saldo Capital Total)
        # 🚨 CAMBIO CLAVE: Solo la columna 1 (índice 1) es monto.
        
        # Montos (Columna 1: Saldo Capital Total (Monto))
        df_display.iloc[:, 1] = df_display.iloc[:, 1].apply(format_currency)
            
        # Tasas (Columnas 2 en adelante: Tasa Mora C1 a C25)
        for col in df_display.columns[2:]:
            df_display[col] = df_display[col].apply(format_percent)
            
        st.dataframe(df_display, hide_index=True)

    else:
        st.warning("No hay datos que cumplan con los criterios de filtro para generar la tabla.")

except Exception as e:
    st.error(f"Error al generar la tabla de Tasas de Mora: {e}")