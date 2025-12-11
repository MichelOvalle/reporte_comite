import streamlit as st
import pandas as pd
import numpy as np
from dateutil.relativedelta import relativedelta
import matplotlib as mpl 
import altair as alt 

# --- CONFIGURACIÓN DE RUTAS Y DATOS ---
FILE_PATH = r'C:\Users\Gerente Credito\Desktop\reporte_comite\master_comite_automatizacion.xlsx'
SHEET_MASTER = 'master_comite_automatizacion'
SHEET_EJERCICIO = 'ejercicio'

# --- 1. FUNCIÓN DE CARGA Y TRANSFORMACIÓN COMPLETA ---
@st.cache_data
def load_and_transform_data(file_path):
    """Carga los datos y aplica las transformaciones necesarias, incluyendo la nueva columna 'nombre_sucursal'."""
    try:
        # Nota: pd.read_excel cargará automáticamente la columna W ('nombre_sucursal')
        df_master = pd.read_excel(file_path, sheet_name=SHEET_MASTER)
        
        buckets_mora_30_150 = ["031-060", "061-090", "091-120", "121-150"]
        buckets_mora_08_90 = ["008-030", "031-060", "061-090"]

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
        # Aseguramos que Mes_BperturB sea el día 1 del mes para una comparación limpia
        df_master['Mes_BperturB'] = df_master['mes_apertura'].dt.normalize().dt.to_period('M').dt.to_timestamp()
        
        df_master['Mora_30-150'] = np.where(df_master['bucket'].isin(buckets_mora_30_150), 'Sí', 'No')
        df_master['Mora_08-90'] = np.where(df_master['bucket'].isin(buckets_mora_08_90), 'Sí', 'No')

        digital_origenes = ["Promotor Digital", "Chatbot"]
        df_master['PR_Origen_Limpio'] = np.where(df_master['origen'].isin(digital_origenes), "Digital", "Físico")

        def get_month_diff(date1, date2):
            if pd.isna(date1) or pd.isna(date2):
                return np.nan
            return (date2.year - date1.year) * 12 + (date2.month - date1.month)

        df_master['dif_mes'] = df_master.apply(
            lambda row: get_month_diff(row['Mes_BperturB'], row['fecha_cierre']), axis=1
        )

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
        # Añadimos una columna para contar el número de operaciones (cada fila es una)
        df_master['operaciones'] = 1
        
        df_master['saldo_capital_total'] = pd.to_numeric(df_master['saldo_capital_total'], errors='coerce').fillna(0)
        
        
        # --- COLUMNAS DE SEGUIMIENTO DE MORA 30-150 (C1 a C25) ---
        
        # C1 (Mes de Antigüedad 0): APLICAMOS LÓGICA DE DIF_MES=0
        df_master['saldo_capital_total_c1'] = np.where(
            df_master['dif_mes'] == 0,
            df_master['saldo_capital_total_30150'], 
            0
        ) 
        
        for n in range(1, 25):
            col_index = n + 1 
            col_name = f'saldo_capital_total_c{col_index}'
            
            df_master[col_name] = np.where(
                df_master['dif_mes'] == n,
                df_master['saldo_capital_total_30150'], 
                0
            )

        # --- NUEVAS COLUMNAS DE SEGUIMIENTO DE MORA 8-90 (890_C1 a 890_C25) ---
        
        df_master['saldo_capital_total_890_c1'] = np.where(
            df_master['dif_mes'] == 0,
            df_master['saldo_capital_total_890'],
            0
        )
        
        for n in range(1, 25):
            col_index = n + 1 
            col_name = f'saldo_capital_total_890_c{col_index}'
            
            df_master[col_name] = np.where(
                df_master['dif_mes'] == n,
                df_master['saldo_capital_total_890'], 
                0
            )

        # --- COLUMNAS DE CAPITAL (CAPITAL_C1 a CAPITAL_C25) ---
        
        df_master['capital_c1'] = np.where(
            df_master['dif_mes'] == 0,
            df_master['saldo_capital_total'],
            0
        )

        for n in range(1, 25):
            col_index = n + 1 
            col_name = f'capital_c{col_index}'
            
            df_master[col_name] = np.where(
                df_master['dif_mes'] == n,
                df_master['saldo_capital_total'], 
                0
            )
            
        # Limpieza de la nueva columna (por si acaso)
        df_master['nombre_sucursal'] = df_master['nombre_sucursal'].astype(str).str.strip().replace('nan', np.nan)
        
        return df_master

    except Exception as e:
        st.error(f"Error al cargar o transformar los datos. Detalle: {e}. Por favor, verifique la ruta del archivo y el formato de la columna 'mes_apertura'.")
        return pd.DataFrame()


# --- FUNCIÓN DE CÁLCULO DE SALDO CONSOLIDADO POR COHORTE (¡CALCULA LA TASA DE MORA!) ---
def calculate_saldo_consolidado(df, time_column='Mes_BperturB'):
    
    df_filtered = df.dropna(subset=[time_column]).copy()
    
    if df_filtered.empty:
        return pd.DataFrame()

    agg_dict = {'saldo_capital_total': 'sum', 'operaciones': 'sum'} # Añadimos 'operaciones'
    
    for n in range(1, 26):
        agg_dict[f'saldo_capital_total_c{n}'] = 'sum'
        agg_dict[f'saldo_capital_total_890_c{n}'] = 'sum'
        agg_dict[f'capital_c{n}'] = 'sum'

    df_summary = df_filtered.groupby(time_column).agg(agg_dict).reset_index()
    
    # Normalizar Mes de Apertura a Datetime limpio
    df_summary['Mes de Apertura'] = pd.to_datetime(df_summary[time_column].dt.strftime('%Y-%m') + '-01')
    
    df_tasas = df_summary[['Mes de Apertura', 'saldo_capital_total', 'operaciones']].copy()
    
    max_fecha_cierre = df_filtered['fecha_cierre'].max()
    
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

    df_tasas = df_tasas.sort_values('Mes de Apertura', ascending=True)
    
    df_tasas.rename(columns={'saldo_capital_total': 'Saldo Capital Total (Monto)', 'operaciones': 'Total Operaciones'}, inplace=True)

    return df_tasas


# --- FUNCIÓN DE ESTILIZADO DE DATAFRAME (FORMATO CONDICIONAL) ---

def clean_cell_to_float(val):
    if isinstance(val, str) and val.endswith('%'):
        try:
            return float(val.replace('%', '').replace(',', ''))
        except ValueError:
            return np.nan 
    # Asegurarse de que los valores numéricos también sean tratados
    try:
        return float(val)
    except (ValueError, TypeError):
        return np.nan 

def apply_gradient_by_row(row):
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
    # tasa_cols se definirá después de la eliminación de la columna temporal
    
    styler = df_display.style
    
    # 1. Aplicar el gradiente fila por fila (HEATMAP)
    # Se debe hacer antes del cálculo de PROMEDIO/MAXIMO/MINIMO
    styler = styler.apply(
        apply_gradient_by_row, 
        axis=1, 
        subset=df_display.columns
    )
    
    # Aseguramos tasa_cols para el styler después de la posible eliminación de columnas
    # En este contexto, usamos solo las columnas de tasas para el formato de gradiente (índice 2 en adelante)
    if len(df_display.columns) > 2:
        # Excluimos Saldo Capital Total y Total Operaciones
        data_cols_for_style = df_display.columns[2:].tolist()
        
        # 2. Aplicar formato de texto y negritas a las celdas de datos
        styler = styler.set_properties(
            **{'text-align': 'center'},
            subset=data_cols_for_style 
        )
        
    styler = styler.set_properties(
        **{'font-weight': 'bold', 'text-align': 'left'},
        subset=[df_display.columns[0]] 
    ).set_properties(
        **{'font-weight': 'bold', 'text-align': 'right'},
        subset=[df_display.columns[1], df_display.columns[2]] 
    )
    
    def highlight_summary_rows(row):
        is_avg = (row.name == 'PROMEDIO')
        is_max = (row.name == 'MÁXIMO')
        is_min = (row.name == 'MÍNIMO')
        
        if is_avg or is_max or is_min:
            color = '#F0F0F0' if is_max or is_min else '#E6F3FF'
            return [f'font-weight: bold; background-color: {color};'] * len(row) 
        return [''] * len(row)

    styler = styler.apply(highlight_summary_rows, axis=1)

    return styler


# --- FUNCIÓN DE CÁLCULO ESPECÍFICO PARA TABLA DE UEN ---
def calculate_uen_summary(df):
    """Calcula las métricas clave (Saldo Capital, Tasa Mora C1 y C2, Operaciones) por Mes de Apertura."""
    
    if df.empty:
        return pd.DataFrame()

    # Seleccionar las columnas relevantes para el cálculo de tasas y capital
    # Capital C1 y Capital C2 (índices c1 y c2)
    df_uen_raw = df.groupby('Mes_BperturB').agg(
        capital_c1=('capital_c1', 'sum'),
        saldo_30150_c1=('saldo_capital_total_c1', 'sum'),
        saldo_890_c1=('saldo_capital_total_890_c1', 'sum'),
        capital_c2=('capital_c2', 'sum'),
        saldo_30150_c2=('saldo_capital_total_c2', 'sum'),
        saldo_890_c2=('saldo_capital_total_890_c2', 'sum'),
        Saldo_Total=('saldo_capital_total', 'sum'),
        Operaciones=('operaciones', 'sum')
    ).reset_index()
    
    # Calcular Tasas
    df_uen_raw['Tasa_30150_C1'] = np.where(
        df_uen_raw['capital_c1'] != 0,
        (df_uen_raw['saldo_30150_c1'] / df_uen_raw['capital_c1']) * 100,
        0
    )
    df_uen_raw['Tasa_890_C1'] = np.where(
        df_uen_raw['capital_c1'] != 0,
        (df_uen_raw['saldo_890_c1'] / df_uen_raw['capital_c1']) * 100,
        0
    )
    df_uen_raw['Tasa_30150_C2'] = np.where(
        df_uen_raw['capital_c2'] != 0,
        (df_uen_raw['saldo_30150_c2'] / df_uen_raw['capital_c2']) * 100,
        0
    )
    df_uen_raw['Tasa_890_C2'] = np.where(
        df_uen_raw['capital_c2'] != 0,
        (df_uen_raw['saldo_890_c2'] / df_uen_raw['capital_c2']) * 100,
        0
    )
    
    # Seleccionar y renombrar las columnas finales
    df_uen_final = df_uen_raw[[
        'Mes_BperturB', 'Saldo_Total', 'Operaciones', 
        'Tasa_30150_C1', 'Tasa_890_C1', 'Tasa_30150_C2', 'Tasa_890_C2'
    ]].sort_values('Mes_BperturB', ascending=False)
    
    df_uen_final.rename(columns={
        'Mes_BperturB': 'Mes de Apertura',
        'Saldo_Total': 'Saldo Capital Total',
        'Operaciones': 'Total Operaciones',
        'Tasa_30150_C1': 'Mora 30-150 (C1)',
        'Tasa_890_C1': 'Mora 8-90 (C1)',
        'Tasa_30150_C2': 'Mora 30-150 (C2)',
        'Tasa_890_C2': 'Mora 8-90 (C2)',
    }, inplace=True)
    
    df_uen_final['Mes de Apertura'] = df_uen_final['Mes de Apertura'].dt.strftime('%Y-%m')
    
    return df_uen_final

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


# --- CREACIÓN DE PESTAÑAS (TABS) ---
tab1, tab2, tab3 = st.tabs(["Análisis Vintage", "Gráficas Clave y Detalle", "Análisis por UEN"])

# Inicializamos variables para almacenar los DataFrames filtrados que se usarán en tab2 y tab3
df_display_raw_30150 = pd.DataFrame()
df_filtered = pd.DataFrame()
df_filtered_master = pd.DataFrame()
selected_uens = [] # Inicializamos para asegurar que esté disponible globalmente


with tab1:
    # --- CONTENIDO DE LA PESTAÑA 1: ANÁLISIS VINTAGE ---
    
    # --- 🛑 FILTRO PARA VISUALIZACIÓN: ÚLTIMAS 24 COHORTES DE APERTURA ---
    if not df_master['Mes_BperturB'].empty:
        unique_cohort_dates = df_master['Mes_BperturB'].dropna().unique()
        sorted_cohort_dates = pd.Series(pd.to_datetime(unique_cohort_dates)).sort_values(ascending=False)
        last_24_cohorts = sorted_cohort_dates.iloc[:24]
        # Usamos df_filtered_master para el filtrado de 24 cohortes
        df_filtered_master = df_master[df_master['Mes_BperturB'].isin(last_24_cohorts)].copy()
        
        if not last_24_cohorts.empty:
            max_date = last_24_cohorts.max().strftime('%Y-%m')
            min_date = last_24_cohorts.min().strftime('%Y-%m')
            st.info(f"Filtro aplicado: Mostrando solo las últimas **{len(last_24_cohorts)} cohortes** de apertura, desde **{min_date}** hasta **{max_date}**.")
        
    if df_filtered_master.empty:
        st.warning("El DataFrame maestro está vacío después de aplicar el filtro de las últimas 24 cohortes. Verifique que haya suficientes datos de cohorte.")
        st.stop()
    
    # --- FILTROS LATERALES ---
    st.sidebar.header("Filtros Interactivos")
    st.sidebar.markdown("**Instrucciones:** Las selecciones a continuación filtran los datos mostrados en la tabla.")

    # 1. Filtro por UEN
    uen_options = df_filtered_master['uen'].unique()
    # Capturamos la selección de UEN para usarla en tab3
    selected_uens = st.sidebar.multiselect("Selecciona UEN", uen_options, default=uen_options[:min(2, len(uen_options))])

    # 2. Filtro por Origen Limpio
    origen_options = df_filtered_master['PR_Origen_Limpio'].unique()
    selected_origen = st.sidebar.multiselect("Selecciona Origen", origen_options, default=origen_options)

    # 3. Filtro por Sucursal
    sucursal_options = df_filtered_master['nombre_sucursal'].dropna().unique()
    selected_sucursales = st.sidebar.multiselect("Selecciona Sucursal", sucursal_options, default=sucursal_options)


    if not selected_uens or not selected_origen or not selected_sucursales:
        st.warning("Por favor, selecciona al menos una opción en todos los filtros del panel lateral.")
        st.stop()

    # Aplicar filtros al DataFrame maestro. ESTA VARIABLE df_filtered se usará en tab2 y tab3
    df_filtered = df_filtered_master[
        (df_filtered_master['uen'].isin(selected_uens)) &
        (df_filtered_master['PR_Origen_Limpio'].isin(selected_origen)) &
        (df_filtered_master['nombre_sucursal'].isin(selected_sucursales)) 
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
            # Incluimos 'Total Operaciones' que es la columna 2
            cols_30150 = ['Mes de Apertura', 'Saldo Capital Total (Monto)', 'Total Operaciones'] + [
                col for col in df_tasas_mora_full.columns if '(30-150)' in col
            ]
            df_display_raw_30150 = df_tasas_mora_full[cols_30150].copy() # <--- GUARDAMOS LA COPIA BRUTA AQUÍ
            
            # 2. RENOMBRAR COLUMNAS DE REPORTE: Eliminar el sufijo (30-150)
            rename_map_30150 = {col: col.replace(' (30-150)', '') 
                                for col in df_display_raw_30150.columns if '(30-150)' in col}
            df_display_raw_30150.rename(columns=rename_map_30150, inplace=True)
            
            
            # --- LÓGICA DE VISUALIZACIÓN COMPARTIDA ---
            
            def format_currency(val):
                return f'{val:,.0f}'
            def format_percent(val):
                return f'{val:,.2f}%'
            def format_int(val):
                return f'{val:,.0f}'
                
            df_display_30150 = df_display_raw_30150.copy()
            
            # CREAR COLUMNA TEMPORAL DATETIME PARA LA LÓGICA DE CORTE
            df_display_30150['Fecha Cohorte DATETIME'] = df_display_30150['Mes de Apertura'].apply(lambda x: x.normalize())
            
            # FORMATO DE LA COLUMNA DE DISPLAY A STRING
            df_display_30150['Mes de Apertura'] = df_display_30150['Mes de Apertura'].dt.strftime('%Y-%m')
            
            # Las tasas de mora son las columnas 3 en adelante
            tasa_cols_30150 = [col for col in df_display_30150.columns if col not in ['Mes de Apertura', 'Saldo Capital Total (Monto)', 'Total Operaciones', 'Fecha Cohorte DATETIME']]

            for index, row in df_display_30150.iterrows():
                cohort_date = row['Fecha Cohorte DATETIME'] # Usamos la columna temporal DATETIME para la comparación
                
                for col in tasa_cols_30150:
                    col_date_str = col.split(' ')[0] 
                    
                    try:
                        col_date = pd.to_datetime(col_date_str + '-01')
                    except:
                        continue

                    # LÓGICA DE CORTE: Si la fecha de reporte es estrictamente menor a la de cohorte, es vacío.
                    if col_date < cohort_date: 
                        df_display_30150.loc[index, col] = '' 
                    else:
                        df_display_30150.loc[index, col] = format_percent(row[col])

            df_display_30150.iloc[:, 1] = df_display_30150.iloc[:, 1].apply(format_currency)
            df_display_30150.iloc[:, 2] = df_display_30150.iloc[:, 2].apply(format_int)


            # ELIMINAR LA COLUMNA TEMPORAL DATETIME ANTES DE MOSTRAR
            df_display_30150.drop(columns=['Fecha Cohorte DATETIME'], inplace=True)

            # --- CÁLCULO DE RESUMEN 30-150 ---
            
            saldo_col_raw = df_display_raw_30150['Saldo Capital Total (Monto)']
            ops_col_raw = df_display_raw_30150['Total Operaciones'] # Nueva columna de operaciones
            
            # rate_cols_raw es la data bruta de las tasas (sin las tres primeras columnas)
            rate_cols_raw = df_display_raw_30150.iloc[:, 3:]
            
            avg_row = pd.Series(index=df_display_30150.columns)
            max_row = pd.Series(index=df_display_30150.columns)
            min_row = pd.Series(index=df_display_30150.columns)
            
            # Cálculo de Saldo Capital Total (Columna 1) y Total Operaciones (Columna 2)
            avg_row.iloc[1] = format_currency(saldo_col_raw.mean())
            avg_row.iloc[2] = format_int(ops_col_raw.mean()) 

            max_row.iloc[1] = format_currency(saldo_col_raw.max())
            max_row.iloc[2] = format_int(ops_col_raw.max())
            
            min_row.iloc[1] = format_currency(saldo_col_raw.min())
            min_row.iloc[2] = format_int(ops_col_raw.min())
            
            # Cálculo de Tasas (Columnas 3 en adelante)
            for i, col_name in enumerate(rate_cols_raw.columns):
                # Usamos el índice de la columna en df_display_30150 (i + 3) para insertar el resultado
                rate_values = rate_cols_raw.iloc[:, i]
                
                avg_row.iloc[i + 3] = format_percent(rate_values.mean())
                max_row.iloc[i + 3] = format_percent(rate_values.max())
                min_row.iloc[i + 3] = format_percent(rate_values.min())
            
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
            cols_890 = ['Mes de Apertura', 'Saldo Capital Total (Monto)', 'Total Operaciones'] + [
                col for col in df_tasas_mora_full.columns if '(8-90)' in col
            ]
            df_display_raw_890 = df_tasas_mora_full[cols_890].copy()
            
            # 2. RENOMBRAR COLUMNAS DE REPORTE: Eliminar el sufijo (8-90)
            rename_map_890 = {col: col.replace(' (8-90)', '') 
                              for col in df_display_raw_890.columns if '(8-90)' in col}
            df_display_raw_890.rename(columns=rename_map_890, inplace=True)
            
            
            # --- LÓGICA DE VISUALIZACIÓN COMPARTIDA (PARA 8-90) ---

            df_display_890 = df_display_raw_890.copy()
            
            # CREAR COLUMNA TEMPORAL DATETIME PARA LA LÓGICA DE CORTE
            df_display_890['Fecha Cohorte DATETIME'] = df_display_890['Mes de Apertura'].apply(lambda x: x.normalize())
            
            # FORMATO DE LA COLUMNA DE DISPLAY A STRING
            df_display_890['Mes de Apertura'] = df_display_890['Mes de Apertura'].dt.strftime('%Y-%m')
            
            # Las tasas de mora son las columnas 3 en adelante
            tasa_cols_890 = [col for col in df_display_890.columns if col not in ['Mes de Apertura', 'Saldo Capital Total (Monto)', 'Total Operaciones', 'Fecha Cohorte DATETIME']]


            for index, row in df_display_890.iterrows():
                cohort_date = row['Fecha Cohorte DATETIME'] # Usamos la columna temporal DATETIME para la comparación
                
                for col in tasa_cols_890:
                    col_date_str = col.split(' ')[0] 
                    
                    try:
                        col_date = pd.to_datetime(col_date_str + '-01')
                    except:
                        continue

                    # LÓGICA DE CORTE: Si la fecha de reporte es estrictamente menor a la de cohorte, es vacío.
                    if col_date < cohort_date: 
                        df_display_890.loc[index, col] = '' 
                    else:
                        df_display_890.loc[index, col] = format_percent(row[col])

            df_display_890.iloc[:, 1] = df_display_890.iloc[:, 1].apply(format_currency)
            df_display_890.iloc[:, 2] = df_display_890.iloc[:, 2].apply(format_int)


            # ELIMINAR LA COLUMNA TEMPORAL DATETIME ANTES DE MOSTRAR
            df_display_890.drop(columns=['Fecha Cohorte DATETIME'], inplace=True)
            
            # --- CÁLCULO DE RESUMEN 8-90 ---
            
            saldo_col_raw = df_display_raw_890['Saldo Capital Total (Monto)']
            ops_col_raw = df_display_raw_890['Total Operaciones']

            # rate_cols_raw_890 es la data bruta de las tasas (sin las tres primeras columnas)
            rate_cols_raw_890 = df_display_raw_890.iloc[:, 3:]
            
            avg_row = pd.Series(index=df_display_890.columns)
            max_row = pd.Series(index=df_display_890.columns)
            min_row = pd.Series(index=df_display_890.columns)
            
            # Cálculo de Saldo Capital Total (Columna 1) y Total Operaciones (Columna 2)
            avg_row.iloc[1] = format_currency(saldo_col_raw.mean())
            avg_row.iloc[2] = format_int(ops_col_raw.mean()) 

            max_row.iloc[1] = format_currency(saldo_col_raw.max())
            max_row.iloc[2] = format_int(ops_col_raw.max())
            
            min_row.iloc[1] = format_currency(saldo_col_raw.min())
            min_row.iloc[2] = format_int(ops_col_raw.min())
            
            # Cálculo de Tasas (Columnas 3 en adelante)
            for i, col_name in enumerate(rate_cols_raw_890.columns):
                # Usamos el índice de la columna en df_display_890 (i + 3) para insertar el resultado
                rate_values = rate_cols_raw_890.iloc[:, i]
                
                avg_row.iloc[i + 3] = format_percent(rate_values.mean())
                max_row.iloc[i + 3] = format_percent(rate_values.max())
                min_row.iloc[i + 3] = format_percent(rate_values.min())
            
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
        # 🚨 LÍNEA DE DIAGNÓSTICO: Muestra el error de Python en detalle
        st.error("¡Ha ocurrido un error inesperado al generar las tablas Vintage!")
        st.exception(e)
        
with tab2:
    # --- CONTENIDO DE LA PESTAÑA 2: GRÁFICAS CLAVE Y DETALLE ---
    
    st.header("📈 Gráficas Clave del Análisis Vintage")

    # Revisa si la variable df_display_raw_30150 fue generada y no está vacía
    if df_display_raw_30150.empty or df_filtered.empty:
        st.info("Por favor, aplique los filtros y genere el reporte en la pestaña 'Análisis Vintage' primero.")
        st.stop()
        
    # ----------------------------------------------------------------------------------
    # --- GRÁFICA 1: CURVAS VINTAGE (Múltiples Cohortes) ---
    # ----------------------------------------------------------------------------------
    st.subheader("1. Curvas de Mora Vintage (Mora 30-150)")
    st.write("Muestra la evolución de la tasa de mora de las **últimas 12 cohortes** disponibles a lo largo de su vida (Antigüedad).")

    # 1. Preparar datos para el formato Largo (Long Format)
    df_long = df_display_raw_30150.iloc[:, 0:].copy()
    
    # Las columnas de las tasas comienzan en el índice 3
    vintage_cols = df_long.columns[3:].tolist()
    
    # MODIFICACIÓN 1: Restringir a las últimas 12 cohortes
    cohortes_a_mostrar = df_long['Mes de Apertura'].sort_values(ascending=False).unique()[:12]
    df_long_filtered = df_long[df_long['Mes de Apertura'].isin(cohortes_a_mostrar)].copy()
    
    if not df_long_filtered.empty:
        # Creamos la columna de etiqueta de fecha antes de derretir (melt)
        df_long_filtered['Cohorte Etiqueta'] = df_long_filtered['Mes de Apertura'].dt.strftime('%Y-%m')
        
        df_long_melt = df_long_filtered.melt(
            id_vars=['Mes de Apertura', 'Cohorte Etiqueta'],
            value_vars=vintage_cols,
            var_name='Mes de Reporte',
            value_name='Tasa (%)'
        )
        
        # 2. Limpiar y calcular Antigüedad
        df_long_melt.dropna(subset=['Tasa (%)'], inplace=True)
        
        # Eliminamos filas donde la tasa es 0 o NaN después de la transformación
        df_long_melt['Tasa (%)'] = pd.to_numeric(df_long_melt['Tasa (%)'], errors='coerce')
        df_long_melt.dropna(subset=['Tasa (%)'], inplace=True)

        # Calcular Antigüedad (Mes de Reporte es el nombre de la columna que contiene la fecha YYYY-MM)
        df_long_melt['Fecha Reporte'] = df_long_melt['Mes de Reporte'].apply(lambda x: pd.to_datetime(x.split(' ')[0] + '-01', errors='coerce'))
        
        # Reconvertir Mes de Apertura a Datetime para el cálculo
        df_long_melt['Fecha Apertura'] = df_long_melt['Mes de Apertura'].apply(lambda x: pd.to_datetime(x.strftime('%Y-%m') + '-01'))
        
        # Calcular Antigüedad en meses
        df_long_melt['Antigüedad (Meses)'] = (
            (df_long_melt['Fecha Reporte'].dt.year - df_long_melt['Fecha Apertura'].dt.year) * 12 +
            (df_long_melt['Fecha Reporte'].dt.month - df_long_melt['Fecha Apertura'].dt.month)
        )
        
        df_long_melt.dropna(subset=['Antigüedad (Meses)'], inplace=True)
        df_long_melt['Antigüedad (Meses)'] = df_long_melt['Antigüedad (Meses)'].astype(int)

        # 3. Generar Gráfica Altair
        chart1 = alt.Chart(df_long_melt).mark_line(point=True).encode(
            x=alt.X('Antigüedad (Meses)', type='quantitative', title='Antigüedad de la Cohorte (Meses)', 
                    # Forzar el dominio del eje X a empezar en 0
                    scale=alt.Scale(domainMin=0), 
                    axis=alt.Axis(tickMinStep=1)),
            y=alt.Y('Tasa (%)', type='quantitative', title='Tasa de Mora (%)', 
                    # Usamos zero=True para forzar el inicio del eje Y en 0
                    scale=alt.Scale(zero=True), 
                    axis=alt.Axis(format='.2f')),
            
            color=alt.Color('Cohorte Etiqueta', type='nominal', title='Cohorte (Mes Apertura)'),
            tooltip=['Cohorte Etiqueta', 'Antigüedad (Meses)', alt.Tooltip('Tasa (%)', format='.2f')]
        ).properties(
            title='Curvas Vintage de Mora 30-150'
        ).interactive()
        
        st.altair_chart(chart1, use_container_width=True)
        


    else:
        st.warning("No hay suficientes datos para generar la gráfica de Curvas Vintage.")


    # ----------------------------------------------------------------------------------
    # --- GRÁFICA 2: SERIE TEMPORAL DE UN PUNTO VINTAGE ESPECÍFICO (C2) ---
    # ----------------------------------------------------------------------------------
    st.subheader("2. Evolución Histórica de Tasa de Mora en $C_2$")
    st.write("Muestra la tendencia de la tasa de mora para el **segundo punto vintage** ($C_2$, o punto de reporte 3) para todas las cohortes.")

    # La columna de la segunda tasa de mora (C2) está en el índice 4 del DataFrame bruto (Mes de Apertura, Saldo, Ops, C1, C2)
    target_column_index = 4
    
    if len(df_display_raw_30150.columns) > target_column_index:
        
        rate_column_name = df_display_raw_30150.columns[target_column_index]
        
        # 2. Seleccionar solo las columnas Mes de Apertura y la columna de tasa requerida
        df_chart_data_c2 = df_display_raw_30150.iloc[:, [0, target_column_index]].copy()
        
        new_col_name = f'Tasa Mora Vintage ({rate_column_name})'
        df_chart_data_c2.rename(columns={rate_column_name: new_col_name}, inplace=True)
        
        # 3. Preparar los datos para la gráfica (convertir tasa a float para Altair)
        df_chart_data_c2[new_col_name] = df_chart_data_c2[new_col_name].astype(float)
        
        # --- Generar Gráfica Altair ---
        chart2 = alt.Chart(df_chart_data_c2).mark_line(point=True).encode(
            x=alt.X('Mes de Apertura', type='temporal', title='Mes de Apertura de la Cohorte', axis=alt.Axis(format='%Y-%m')),
            y=alt.Y(new_col_name, type='quantitative', title='Tasa de Mora (%)', axis=alt.Axis(format='.2f')),
            tooltip=['Mes de Apertura', alt.Tooltip(new_col_name, format='.2f')]
        ).properties(
            title=f"Tendencia de Tasa de Mora en punto Vintage: {rate_column_name}"
        ).interactive()
        
        st.altair_chart(chart2, use_container_width=True)

        # Mostrar Tabla de Datos Detallados (se mantiene la lógica anterior)
        st.markdown("### Datos Detallados ($C_2$)")
        df_cohort_column_display = df_chart_data_c2.copy()
        df_cohort_column_display['Mes de Apertura'] = df_cohort_column_display['Mes de Apertura'].dt.strftime('%Y-%m')
        df_cohort_column_display[new_col_name] = df_cohort_column_display[new_col_name].apply(lambda x: f'{x:,.2f}%')
        st.dataframe(df_cohort_column_display, hide_index=True)
        st.markdown(f"**Punto Vintage Mostrado:** La tasa de mora de la cohorte correspondiente al periodo de reporte **{rate_column_name}**.")
        
    else:
        st.warning("El DataFrame de Vintage no tiene suficientes columnas para mostrar el punto C2.")


    # ----------------------------------------------------------------------------------
    # --- GRÁFICA 3: COMPOSICIÓN DEL VOLUMEN POR ORIGEN (Stacked Bar) ---
    # ----------------------------------------------------------------------------------
    st.subheader("3. Composición del Saldo Capital Total por Origen")
    st.write("Muestra cómo se distribuye el volumen de saldo capital por Origen de la Operación a lo largo del tiempo.")
    
    # 1. Preparar datos: Agrupar por Mes de Apertura y Origen Limpio
    df_volumen = df_filtered.groupby(['Mes_BperturB', 'PR_Origen_Limpio'])['saldo_capital_total'].sum().reset_index()
    df_volumen.rename(columns={'Mes_BperturB': 'Mes de Apertura', 'saldo_capital_total': 'Saldo Capital Total'}, inplace=True)
    
    # 2. Formato de fecha para Altair
    # Usamos el formato datetime para el eje X para que Altair lo maneje como una serie temporal
    
    # 3. Generar Gráfica Stacked Bar
    chart3 = alt.Chart(df_volumen).mark_bar().encode(
        # Mes de Apertura es Datetime (temporal) para Altair
        x=alt.X('Mes de Apertura', type='temporal', title='Mes de Apertura', axis=alt.Axis(format='%Y-%m')),
        y=alt.Y('Saldo Capital Total', type='quantitative', title='Saldo Capital Total', axis=alt.Axis(format='$,.0f')),
        color=alt.Color('PR_Origen_Limpio', type='nominal', title='Origen'),
        tooltip=['Mes de Apertura', 'PR_Origen_Limpio', alt.Tooltip('Saldo Capital Total', format='$,.0f')]
    ).properties(
        title='Volumen de Saldo Capital Total por Origen'
    ).interactive()
    
    st.altair_chart(chart3, use_container_width=True)
    


with tab3:
    # --- CONTENIDO DE LA TÁCTICA 3: ANÁLISIS POR UEN ---
    st.header("🏢 Análisis de Desempeño por UEN")
    
    # 1. Filtro interno para seleccionar una sola UEN de las filtradas en tab1
    # Aseguramos que haya opciones si el filtro lateral está activo
    if selected_uens:
        # Si se seleccionaron múltiples UENs en el filtro lateral, permitimos elegir una para el detalle.
        selected_uen_detail = st.selectbox(
            "Seleccione una UEN para el análisis detallado:", 
            options=selected_uens, 
            key='uen_detail_select'
        )
        
        # Filtrar el dataframe general (ya filtrado por cohorte, origen, sucursal) solo para la UEN seleccionada
        df_uen_filtered = df_filtered[df_filtered['uen'] == selected_uen_detail].copy()
        
        if df_uen_filtered.empty:
            st.warning(f"No hay datos para la UEN '{selected_uen_detail}' con los filtros aplicados.")
            st.stop()

        # 2. Generar la tabla de desempeño por UEN
        df_uen_summary = calculate_uen_summary(df_uen_filtered)
        
        st.subheader(f"Métricas Clave por Cohorte para UEN: {selected_uen_detail}")
        st.write("Se muestra el desempeño inicial de las cohortes ($C_1$ y $C_2$) en términos de saldo, operaciones y tasas de mora.")
        
        # Formato de la tabla
        def format_uen_table(df):
            df_styled = df.copy()
            # Formato de moneda
            df_styled['Saldo Capital Total'] = df_styled['Saldo Capital Total'].apply(lambda x: f'${x:,.0f}')
            # Formato de número entero (Operaciones)
            df_styled['Total Operaciones'] = df_styled['Total Operaciones'].apply(lambda x: f'{x:,.0f}')
            # Formato de porcentaje
            for col in df.columns[3:]:
                df_styled[col] = df_styled[col].apply(lambda x: f'{x:,.2f}%')
            return df_styled
        
        df_uen_display = format_uen_table(df_uen_summary)
        st.dataframe(df_uen_display, hide_index=True, use_container_width=True)

        # 3. Gráfica de Tendencia de Mora C1 para la UEN
        st.subheader(f"Tendencia de Mora 30-150 ($C_1$) para {selected_uen_detail}")
        
        df_chart_uen = df_uen_summary[['Mes de Apertura', 'Mora 30-150 (C1)']].copy()
        df_chart_uen['Mes de Apertura'] = pd.to_datetime(df_chart_uen['Mes de Apertura'] + '-01')
        
        chart_uen = alt.Chart(df_chart_uen).mark_line(point=True).encode(
            x=alt.X('Mes de Apertura', type='temporal', title='Mes de Apertura de la Cohorte', axis=alt.Axis(format='%Y-%m')),
            y=alt.Y('Mora 30-150 (C1)', type='quantitative', title='Tasa Mora C1 (%)', axis=alt.Axis(format='.2f')),
            tooltip=['Mes de Apertura', alt.Tooltip('Mora 30-150 (C1)', format='.2f')]
        ).properties(
            title=f"Tendencia de Riesgo Inicial (C1) para {selected_uen_detail}"
        ).interactive()
        
        st.altair_chart(chart_uen, use_container_width=True)
        

    else:
        st.warning("Seleccione al menos una UEN en el panel de filtros de la pestaña 'Análisis Vintage' para ver el detalle aquí.")