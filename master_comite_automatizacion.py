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
    """Carga los datos y aplica las transformaciones necesarias, incluyendo saldos condicionales y columnas C1-C4."""
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
        
        # --- CÁLCULO DE C1, C2, C3, C4 (MORA INICIAL DE COHORTE MÁS RECIENTE) ---
        
        # 1. Encontrar el MAX(Mes_BperturB) global (Cohorte más reciente)
        max_mes_bperturb = df_master['Mes_BperturB'].max()
        
        # Lógica fija: Saldo si (Cohorte actual == MAX Cohorte) AND (Mora 30-150="Sí") AND (Fecha Cierre == Mes de Observación)
        is_max_cohorte = (df_master['Mes_BperturB'] == max_mes_bperturb)
        is_mora = (df_master['Mora_30-150'] == 'Sí')

        # Meses de Observación (FIN.MES(Mes_BperturB, N-1))
        # N=1 -> Primer mes (0 meses offset)
        # N=2 -> Segundo mes (1 mes offset)
        
        for n in range(1, 5): # n=1 (C1) a n=4 (C4)
            offset_months = n - 1
            col_name = f'saldo_capital_total_c{n}'
            
            # Calcular la fecha de observación esperada: FIN.MES(Mes_BperturB, n-1)
            # Esto se hace comparando la fecha de reporte (fecha_cierre) con el FIN.MES del mes de apertura.
            
            # Opción 1: Calcular FIN.MES(Mes_BperturB, offset) y comparar con fecha_cierre.
            # Esto es más seguro, pero requiere iteración o apply, lo cual es lento.
            
            # Opción 2 (Más eficiente): Comparar la antigüedad.
            # Como la columna Mes_BperturB ya es FIN.MES(mes_apertura, 0), necesitamos una función de meses:
            def get_aging_months(start, end):
                if pd.isna(start) or pd.isna(end):
                    return np.nan
                # Damos +1 porque en Excel el mes de apertura es el mes 1.
                return (end.year - start.year) * 12 + (end.month - start.month) + 1

            df_master['Temp_Aging'] = df_master.apply(
                lambda row: get_aging_months(row['Mes_BperturB'], row['fecha_cierre']), axis=1
            )
            
            # Condición de Antigüedad: Aging debe ser igual a N
            is_aging_n = (df_master['Temp_Aging'] == n)
            
            # Condición final: Y(Cohorte MAX, Mora, Aging == N)
            condition_cn = is_max_cohorte & is_mora & is_aging_n
            
            df_master[col_name] = np.where(
                condition_cn,
                df_master['saldo_capital_total'],
                0
            )
        
        # Eliminar la columna temporal de Aging
        df_master = df_master.drop(columns=['Temp_Aging'])
        
        return df_master

    except Exception as e:
        st.error(f"Error al cargar o transformar los datos. Detalle: {e}. Por favor, verifique la ruta del archivo y el formato de la columna 'mes_apertura'.")
        return pd.DataFrame()


# --- FUNCIÓN DE CÁLCULO DE SALDO CONSOLIDADO POR COHORTE (ACTUALIZADA) ---
def calculate_saldo_consolidado(df, time_column='Mes_BperturB'):
    
    # Excluir NaT antes de procesar
    df_filtered = df.dropna(subset=[time_column]).copy()
    
    if df_filtered.empty:
        return pd.DataFrame()

    # Agrupar y sumar las columnas de saldo (incluyendo C1, C2, C3, C4)
    df_summary = df_filtered.groupby(time_column).agg(
        {'saldo_capital_total': 'sum',
         'saldo_capital_total_30150': 'sum',
         'saldo_capital_total_890': 'sum',
         'saldo_capital_total_c1': 'sum',  # <-- NUEVO
         'saldo_capital_total_c2': 'sum',  # <-- NUEVO
         'saldo_capital_total_c3': 'sum',  # <-- NUEVO
         'saldo_capital_total_c4': 'sum'}  # <-- NUEVO
    ).reset_index()
    
    # Renombrar columnas para la presentación
    df_summary.columns = [
        'Mes de Apertura', 
        'Saldo Capital Total', 
        'Mora 30-150', 
        'Mora 08-90',
        'Mora Inicial C1 (Mes 1)', # <-- NUEVO
        'Mora Inicial C2 (Mes 2)',
        'Mora Inicial C3 (Mes 3)',
        'Mora Inicial C4 (Mes 4)'
    ]
    
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

st.header("1. Saldo Capital Total y Seguimiento de Mora Inicial (C1 a C4)")

try:
    # Calcular la Tabla Consolidada
    df_saldo_consolidado = calculate_saldo_consolidado(df_filtered) 

    if not df_saldo_consolidado.empty:
        # Formato de la Fecha
        df_saldo_consolidado['Mes de Apertura'] = df_saldo_consolidado['Mes de Apertura'].dt.strftime('%Y-%m')

        # Formato de moneda para la tabla
        def format_currency(val):
            return f'{val:,.0f}'

        st.subheader("Suma de Saldos Condicionales por Mes de Apertura")
        
        # Aplicar formato de moneda a las columnas numéricas
        df_display = df_saldo_consolidado.copy()
        for col in df_display.columns[1:]:
            df_display[col] = df_display[col].apply(format_currency)
            
        st.dataframe(df_display, hide_index=True)

    else:
        st.warning("No hay datos que cumplan con los criterios de filtro para generar la tabla.")

except Exception as e:
    st.error(f"Error al generar la tabla de Saldo Consolidado: {e}")