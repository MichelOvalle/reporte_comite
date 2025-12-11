import streamlit as st
import pandas as pd
import numpy as np
from dateutil.relativedelta import relativedelta
import matplotlib as mpl 

# --- CONFIGURACIÓN DE RUTAS Y DATOS ---
# 🚨 ¡IMPORTANTE! Revisa que esta ruta sea correcta en tu computadora
FILE_PATH = r'C:\Users\Gerente Credito\Desktop\reporte_comite\master_comite_automatizacion.xlsx'
SHEET_MASTER = 'master_comite_automatizacion'
SHEET_EJERCICIO = 'ejercicio'

# --- 1. FUNCIÓN DE CARGA Y TRANSFORMACIÓN COMPLETA ---
@st.cache_data
def load_and_transform_data(file_path):
    """Carga los datos y aplica las transformaciones necesarias, incluyendo las columnas C1 a C25, CAPITAL_C1 a CAPITAL_C25 y las nuevas 890_C1 a 890_C25."""
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
        
        
        # --- COLUMNAS DE SEGUIMIENTO DE MORA 30-150 (C1 a C25) ---
        
        df_master['saldo_capital_total_c1'] = 0 
        
        for n in range(1, 25):
            col_index = n + 1 
            col_name = f'saldo_capital_total_c{col_index}'
            
            df_master[col_name] = np.where(
                df_master['dif_mes'] == n,
                df_master['saldo_capital_total_30150'], 
                0
            )

        # --- NUEVAS COLUMNAS DE SEGUIMIENTO DE MORA 8-90 (890_C1 a 890_C25) ---
        
        df_master['saldo_capital_total_890_c1'] = 0 
        
        for n in range(1, 25):
            col_index = n + 1 
            col_name = f'saldo_capital_total_890_c{col_index}'
            
            # Lógica: SI(dif_meses = n, saldo_capital_total_890, 0)
            df_master[col_name] = np.where(
                df_master['dif_mes'] == n,
                df_master['saldo_capital_total_890'], # Usamos la columna base 890
                0
            )

        # --- COLUMNAS DE CAPITAL (CAPITAL_C1 a CAPITAL_C25) ---
        
        df_master['capital_c1'] = 0

        for n in range(1, 25):
            col_index = n + 1 
            col_name = f'capital_c{col_index}'
            
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
    agg_dict = {'saldo_capital_total': 'sum'}
    
    # Listas para manejar los nombres de columnas
    c_cols_mora_30150 = []
    c_cols_mora_890 = []
    c_cols_capital = []

    for n in range(1, 26):
        mora_col_30150 = f'saldo_capital_total_c{n}'
        mora_col_890 = f'saldo_capital_total_890_c{n}' 
        capital_col = f'capital_c{n}'
        
        agg_dict[mora_col_30150] = 'sum'
        agg_dict[mora_col_890] = 'sum'
        agg_dict[capital_col] = 'sum'
        
        c_cols_mora_30150.append(mora_col_30150)
        c_cols_mora_890.append(mora_col_890)
        c_cols_capital.append(capital_col)

    # 2. Agrupar y sumar todas las columnas
    df_summary = df_filtered.groupby(time_column).agg(agg_dict).reset_index()
    
    # 3. Preparación y cálculo de la Tasa de Mora
    
    df_summary['Mes de Apertura'] = pd.to_datetime(df_summary[time_column])
    
    # Inicializamos el DataFrame de tasas con solo la cohorte y el saldo total
    df_tasas = df_summary[['Mes de Apertura', 'saldo_capital_total']].copy()
    
    # Encontrar la fecha de reporte más reciente (MAX fecha_cierre)
    max_fecha_cierre = df_filtered['fecha_cierre'].max()
    
    # 4. Calcular y nombrar las columnas de tasas (usando nombres de reporte temporales)
    
    for n in range(1, 26):
        antiguedad = n - 1 
        target_date = max_fecha_cierre - relativedelta(months=antiguedad)
        date_label = target_date.strftime('%Y-%m')
        
        mora_30150_col_orig = f'saldo_capital_total_c{n}'
        mora_890_col_orig = f'saldo_capital_total_890_c{n}'
        capital_col_orig = f'capital_c{n}'
        
        # Tasa 30-150
        tasa_30150 = np.where(
            df_summary[capital_col_orig] != 0,
            (df_summary[mora_30150_col_orig] / df_summary[capital_col_orig]) * 100,
            0
        )
        col_name_30150 = f'{date_label} (30-150)'
        df_tasas[col_name_30150] = tasa_30150

        # Tasa 8-90
        tasa_890 = np.where(
            df_summary[capital_col_orig] != 0,
            (df_summary[mora_890_col_orig] / df_summary[capital_col_orig]) * 100,
            0
        )
        col_name_890 = f'{date_label} (8-90)'
        df_tasas[col_name_890] = tasa_890

    # 5. Ordenar por fecha de cohorte (ASCENDENTE: más antiguo primero)
    df_tasas = df_tasas.sort_values('Mes de Apertura', ascending=True)
    
    # 6. Renombrar la columna de Saldo Capital
    df_tasas.rename(columns={'saldo_capital_total': 'Saldo Capital Total (Monto)'}, inplace=True)

    return df_tasas


# --- FUNCIÓN DE ESTILIZADO DE DATAFRAME (FORMATO CONDICIONAL) ---

# Función auxiliar para convertir strings de porcentaje a float para el gradiente
def clean_cell_to_float(val):
    if isinstance(val, str) and val.endswith('%'):
        try:
            return float(val.replace('%', '').replace(',', ''))
        except ValueError:
            return np.nan 
    return np.nan 

# Función que aplica el gradiente a una fila de tasas
def apply_gradient_by_row(row):
    """Aplica el gradiente a una Series (fila) de tasas, usando mapeo CSS."""
    
    # Excluir Mes de Apertura y Saldo Capital Total (primeras dos columnas)
    numeric_rates = row.iloc[2:].apply(clean_cell_to_float).dropna()
    
    styles = [''] * len(row)
    
    if len(numeric_rates) < 2:
        return styles

    cmap = mpl.cm.get_cmap('RdYlGn_r')
    
    v_min = numeric_rates.min()
    v_max = numeric_rates.max()
    
    if v_min == v_max:
        color_rgb = cmap(0.5)
        neutral_style = f'background-color: rgba({int(color_rgb[0]*255)}, {int(color_rgb[1]*255)}, {int(color_rgb[2]*255)}, 0.5); text-align: center;'
        
        for col_name in numeric_rates.index:
            col_loc = row.index.get_loc(col_name)
            styles[col_loc] = neutral_style
        return styles

    norm = mpl.colors.Normalize(v_min, v_max)
    
    for col_index, val in numeric_rates.items():
        rgba = cmap(norm(val))
        
        style_color = f'background-color: rgba({int(rgba[0]*255)}, {int(rgba[1]*255)}, {int(rgba[2]*255)}, 1.0); text-align: center;'

        col_loc = row.index.get_loc(col_index)
        styles[col_loc] = style_color
    
    return styles


def style_table(df_display):
    """Inicializa el Styler y aplica todos los formatos."""
    
    tasa_cols = df_display.columns[2:].tolist()
    
    styler = df_display.style
    
    # 1. Aplicar el gradiente fila por fila (HEATMAP)
    styler = styler.apply(
        apply_gradient_by_row, 
        axis=1, 
        subset=df_display.columns
    )

    # 2. Aplicar formato de texto y negritas a las celdas de datos
    styler = styler.set_properties(
        **{'text-align': 'center'},
        subset=tasa_cols 
    ).set_properties(
        # Negrita y alineación para Mes de Apertura (Columna 0)
        **{'font-weight': 'bold', 'text-align': 'left'},
        subset=[df_display.columns[0]] 
    ).set_properties(
        # Negrita y alineación para Saldo Capital Total (Columna 1)
        **{'font-weight': 'bold', 'text-align': 'right'},
        subset=[df_display.columns[1]] 
    )
    
    # 3. Estilo para las Filas de Resumen
    def highlight_summary_rows(row):
        is_avg = (row.name == 'PROMEDIO')
        is_max = (row.name == 'MÁXIMO')
        is_min = (row.name == 'MÍNIMO')
        
        if is_avg or is_max or is_min:
            # Color gris claro para Máximo/Mínimo
            color = '#F0F0F0' if is_max or is_min else '#E6F3FF' # Azul claro para Promedio
            return [f'font-weight: bold; background-color: {color};'] * len(row) 
        return [''] * len(row)

    styler = styler.apply(highlight_summary_rows, axis=1)

    return styler

# --- CARGA PRINCIPAL DEL DATAFRAME ---
df_master = load_and_transform_data(FILE_PATH)


# --- 2. INTERFAZ DE STREAMLIT ---

st.set_page_config(layout="wide")

# 🚨 SOLUCIÓN PARA EL ENCABEZADO: INYECTAR CSS GLOBALMENTE
HEADER_CSS = """
<style>
div.stDataFrame {
    width: 100%;
}
.stDataFrame th {
    background-color: #ADD8E6 !important; /* Celeste */
    color: black !important;
    font-weight: bold !important; /* Negritas */
    text-align: center !important;
}
.stDataFrame div[data-testid="stDataframeHeaders"] th {
    background-color: #ADD8E6 !important; 
}
</style>
"""
st.markdown(HEADER_CSS, unsafe_allow_html=True)
st.title("📊 Análisis Vintage")

if df_master.empty:
    st.error("No se pudo cargar y procesar el DataFrame maestro.")
    st.stop()


# --- 🛑 FILTRO PARA VISUALIZACIÓN: ÚLTIMAS 24 COHORTES DE APERTURA ---
if not df_master['Mes_BperturB'].empty:
    unique_cohort_dates = df_master['Mes_BperturB'].dropna().unique()
    sorted_cohort_dates = pd.Series(pd.to_datetime(unique_cohort_dates)).sort_values(ascending=False)
    last_24_cohorts = sorted_cohort_dates.iloc[:24]
    df_master = df_master[df_master['Mes_BperturB'].isin(last_24_cohorts)].copy()
    
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

st.header("1. Vintage Mora 30-150")

try:
    # Calcular la Tabla Consolidada y las Tasas (Incluye 30-150 y 8-90)
    df_tasas_mora_full = calculate_saldo_consolidado(df_filtered) 
    
    # ----------------------------------------------------------------------------------
    # --- 1. MOSTRAR VINTAGE MORA 30-150 (Principal) ---
    # ----------------------------------------------------------------------------------

    if not df_tasas_mora_full.empty:
        
        # 1. AISLAR DATOS: Seleccionar solo columnas 30-150
        cols_30150 = ['Mes de Apertura', 'Saldo Capital Total (Monto)'] + [
            col for col in df_tasas_mora_full.columns if '(30-150)' in col
        ]
        df_display_raw_30150 = df_tasas_mora_full[cols_30150].copy()
        
        # 2. RENOMBRAR COLUMNAS DE REPORTE: Eliminar el sufijo (30-150)
        rename_map_30150 = {col: col.replace(' (30-150)', '') 
                            for col in df_display_raw_30150.columns if '(30-150)' in col}
        df_display_raw_30150.rename(columns=rename_map_30150, inplace=True)
        
        
        # --- LÓGICA DE VISUALIZACIÓN COMPARTIDA ---
        
        # Formato de moneda para los montos y porcentaje para las tasas
        def format_currency(val):
            return f'{val:,.0f}'
        def format_percent(val):
            return f'{val:,.2f}%'
            
        # Aplicamos corte, formato y resumen para 30-150
        df_display_30150 = df_display_raw_30150.copy()
        tasa_cols_30150 = df_display_30150.columns[2:]

        for index, row in df_display_30150.iterrows():
            cohort_date = row['Mes de Apertura']
            df_display_30150.loc[index, 'Mes de Apertura'] = cohort_date.strftime('%Y-%m') # Formatear fecha de cohorte
            
            for col in tasa_cols_30150:
                col_date_str = col.split(' ')[0] 
                
                try:
                    col_date = pd.to_datetime(col_date_str + '-01')
                except:
                    continue

                if col_date <= cohort_date: 
                    df_display_30150.loc[index, col] = '' 
                else:
                    df_display_30150.loc[index, col] = format_percent(row[col])

        df_display_30150.iloc[:, 1] = df_display_30150.iloc[:, 1].apply(format_currency)

        # --- CÁLCULO DE RESUMEN 30-150 ---
        
        # Para el cálculo de resumen usamos df_display_raw_30150 (sin strings y sin NaN del corte)
        saldo_col_raw = df_display_raw_30150['Saldo Capital Total (Monto)']
        rate_cols_raw = df_display_raw_30150.iloc[:, 2:]
        
        avg_row = pd.Series(index=df_display_30150.columns)
        max_row = pd.Series(index=df_display_30150.columns)
        min_row = pd.Series(index=df_display_30150.columns)
        
        avg_row.iloc[1] = format_currency(saldo_col_raw.mean())
        max_row.iloc[1] = format_currency(saldo_col_raw.max())
        min_row.iloc[1] = format_currency(saldo_col_raw.min())
        
        for i, col in enumerate(tasa_cols_30150):
            rate_values = rate_cols_raw.iloc[:, i]
            avg_row.iloc[i + 2] = format_percent(rate_values.mean())
            max_row.iloc[i + 2] = format_percent(rate_values.max())
            min_row.iloc[i + 2] = format_percent(rate_values.min())
        
        avg_row.iloc[0] = 'PROMEDIO'
        max_row.iloc[0] = 'MÁXIMO'
        min_row.iloc[0] = 'MÍNIMO'
        
        df_display_30150.loc['MÁXIMO'] = max_row
        df_display_30150.loc['MÍNIMO'] = min_row
        df_display_30150.loc['PROMEDIO'] = avg_row
        
        # APLICAR ESTILOS
        styler_30150 = style_table(df_display_30150)
        st.dataframe(styler_30150, hide_index=True)
        
        # ----------------------------------------------------------------------------------
        # --- 2. MOSTRAR NUEVA TABLA VINTAGE MORA 8-90 ---
        # ----------------------------------------------------------------------------------
        st.header("2. Vintage Mora 8-90")

        # 1. AISLAR DATOS: Seleccionar solo columnas 8-90
        cols_890 = ['Mes de Apertura', 'Saldo Capital Total (Monto)'] + [
            col for col in df_tasas_mora_full.columns if '(8-90)' in col
        ]
        df_display_raw_890 = df_tasas_mora_full[cols_890].copy()
        
        # 2. RENOMBRAR COLUMNAS DE REPORTE: Eliminar el sufijo (8-90)
        rename_map_890 = {col: col.replace(' (8-90)', '') 
                          for col in df_display_raw_890.columns if '(8-90)' in col}
        df_display_raw_890.rename(columns=rename_map_890, inplace=True)
        
        
        # --- LÓGICA DE VISUALIZACIÓN COMPARTIDA (PARA 8-90) ---

        df_display_890 = df_display_raw_890.copy()
        tasa_cols_890 = df_display_890.columns[2:]

        for index, row in df_display_890.iterrows():
            cohort_date = row['Mes de Apertura']
            # La columna 'Mes de Apertura' ya fue formateada a string en el paso anterior, 
            # pero aquí necesitamos el valor Datetime original para la comparación. 
            # Como df_display_raw_890 es una copia de df_tasas_mora_full (cuyas columnas de fecha no se modificaron),
            # usamos el valor de la columna 'Mes de Apertura' para la comparación.
            
            # Formatear la fecha de cohorte a string para la visualización
            df_display_890.loc[index, 'Mes de Apertura'] = cohort_date.strftime('%Y-%m')
            
            for col in tasa_cols_890:
                col_date_str = col.split(' ')[0] 
                
                try:
                    col_date = pd.to_datetime(col_date_str + '-01')
                except:
                    continue

                if col_date <= cohort_date: 
                    df_display_890.loc[index, col] = '' 
                else:
                    df_display_890.loc[index, col] = format_percent(row[col])

        df_display_890.iloc[:, 1] = df_display_890.iloc[:, 1].apply(format_currency)
        
        # --- CÁLCULO DE RESUMEN 8-90 ---
        
        saldo_col_raw = df_display_raw_890['Saldo Capital Total (Monto)']
        rate_cols_raw = df_display_raw_890.iloc[:, 2:]
        
        avg_row = pd.Series(index=df_display_890.columns)
        max_row = pd.Series(index=df_display_890.columns)
        min_row = pd.Series(index=df_display_890.columns)
        
        avg_row.iloc[1] = format_currency(saldo_col_raw.mean())
        max_row.iloc[1] = format_currency(saldo_col_raw.max())
        min_row.iloc[1] = format_currency(saldo_col_raw.min())
        
        for i, col in enumerate(tasa_cols_890):
            rate_values = rate_cols_raw.iloc[:, i]
            avg_row.iloc[i + 2] = format_percent(rate_values.mean())
            max_row.iloc[i + 2] = format_percent(rate_values.max())
            min_row.iloc[i + 2] = format_percent(rate_values.min())
        
        avg_row.iloc[0] = 'PROMEDIO'
        max_row.iloc[0] = 'MÁXIMO'
        min_row.iloc[0] = 'MÍNIMO'
        
        df_display_890.loc['MÁXIMO'] = max_row
        df_display_890.loc['MÍNIMO'] = min_row
        df_display_890.loc['PROMEDIO'] = avg_row
        
        # APLICAR ESTILOS
        styler_890 = style_table(df_display_890)
        st.dataframe(styler_890, hide_index=True)


    else:
        st.warning("No hay datos que cumplan con los criterios de filtro para generar la tabla.")

except Exception as e:
    st.error(f"Error al generar la tabla de Tasas de Mora: {e}")