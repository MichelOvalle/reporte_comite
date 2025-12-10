import pandas as pd
import numpy as np

# Definir la ruta del archivo (corregida según su indicación)
# NOTA: Asegúrate de que esta ruta sea correcta en tu entorno.
file_path = r'C:\Users\Gerente Credito\Desktop\reporte_comite\master_comite_automatizacion.xlsx'

# Definir los nombres de las pestañas
sheet_master = 'master_comite_automatizacion'
sheet_ejercicio = 'ejercicio'

# --- 1. IMPORTACIÓN DE DATOS ---
try:
    # 1.1 Cargar df_master
    df_master = pd.read_excel(file_path, sheet_name=sheet_master)
    
    # 1.2 Cargar df_ejercicio (solo E y F) y preparar la tabla de búsqueda (lookup_table)
    # Se asume que las columnas E y F se cargan con nombres 'MENSUAL S/IVA' y 'FP'
    df_ejercicio = pd.read_excel(file_path, sheet_name=sheet_ejercicio, usecols='E:F', header=0)
    df_ejercicio.columns = ['MENSUAL S/IVA', 'FP']
    lookup_table = df_ejercicio.set_index('MENSUAL S/IVA')['FP'].to_dict()
    
    # Mapeo de Buckets (para columnas x, y, y banderas)
    bucket_mapping = {
        "000-000": 0, "001-007": 1, "008-030": 2, "031-060": 3, 
        "061-090": 4, "091-120": 5, "121-150": 6, "151-999": 7
    }

    print("--- 1. Importación de datos completada ---")

except Exception as e:
    print(f"Error en la carga de datos. Verifica la ruta y los nombres de las pestañas: {e}")
    df_master = None
    df_ejercicio = None

# --- 2. CREACIÓN DE COLUMNAS (W a BF) ---
if df_master is not None and df_ejercicio is not None:
    
    # Pre-cálculos y Conversiones de tipo:
    df_master['mes_apertura'] = pd.to_datetime(df_master['mes_apertura'], errors='coerce')
    
    # === Bloque 1: Columnas W a AC ===

    # W: Mes_BperturB (FIN.MES(mes_apertura, 0))
    df_master['Mes_BperturB'] = df_master['mes_apertura'] + pd.offsets.MonthEnd(0)
    
    # X: Mora_8-90
    buckets_mora_8_90 = ["008-030", "031-060", "061-090"]
    df_master['Mora_8-90'] = np.where(df_master['bucket'].isin(buckets_mora_8_90), 'Sí', 'No')

    # Y: Mora_30-150
    buckets_mora_30_150 = ["031-060", "061-090", "091-120", "121-150"]
    df_master['Mora_30-150'] = np.where(df_master['bucket'].isin(buckets_mora_30_150), 'Sí', 'No')

    # Z: tasa_SDO y AA: tasa_AP (BUSCAR)
    df_master['tasa_SDO'] = df_master['tasa_nominal_ponderada'].map(lookup_table)
    df_master['tasa_AP'] = df_master['tasa_nominal_apertura'].map(lookup_table)

    # AB: x y AC: y (CAMBIAR)
    df_master['x'] = df_master['bucket'].map(bucket_mapping)
    df_master['y'] = df_master['bucket_mes_anterior'].map(bucket_mapping)

    # === Bloque 2: Columnas AD a AP (DESC, CONTENCION, Saldos y Origen) ===

    # AF: 008-090 (Previo al DESC/CONTENCION para el orden lógico)
    map_008_090 = {"008-030": "SI", "031-060": "SI", "061-090": "SI"}
    df_master['008-090'] = df_master['bucket_mes_anterior'].map(map_008_090).fillna("NO")
    
    # AE: CONTENCION (Depende de x y y)
    conditions_cont = [
        df_master['bandera_castigo'] == "castigo_mes",
        (df_master['x'] == df_master['y']) | (df_master['x'] < df_master['y']), # Mantuvo o Mejoró (CONTENCION)
        df_master['x'] > df_master['y'], # Empeoró
    ]
    choices_cont = ["151-999 SE CASTIGO", "CONTENCION", "EMPEORO"]
    inner_result = np.select(
        conditions_cont, 
        choices_cont, 
        default=df_master['bucket_mes_anterior'].astype(str) + " CASTIGO"
    )
    df_master['CONTENCION'] = np.where(
        df_master['x'].isna() | df_master['y'].isna(), "N/D", inner_result
    )
    
    # AD: DESC (Depende de x y y)
    conditions_desc = [
        df_master['bandera_castigo'] == "castigo_mes",
        df_master['x'] == df_master['y'],
        df_master['x'] > df_master['y'],
        df_master['x'] < df_master['y'],
    ]
    choices_desc = [
        "151-999 SE CASTIGO",
        df_master['bucket_mes_anterior'] + " MANTUVO",
        df_master['bucket_mes_anterior'] + " EMPEORO",
        df_master['bucket_mes_anterior'] + " MEJORO",
    ]
    df_master['DESC'] = np.select(
        conditions_desc, 
        choices_desc, 
        default=df_master['bucket_mes_anterior'].astype(str) + " CASTIGO" # SI(V2="N/D",V2&" CASTIGO")
    )
    
    # AH: act y AI: ant (Dependen de x y y)
    df_master['act'] = np.where(df_master['x'] <= 4, 0, 1) # act (Actual)
    df_master['ant'] = np.where(df_master['y'] <= 4, 0, 1) # ant (Anterior)

    # AJ: DESC1 (Depende de act y ant)
    conditions_desc1 = [
        df_master['act'] == df_master['ant'],
        df_master['ant'] > df_master['act']
    ]
    choices_desc1 = ["Mantiene", "Vencido-Vigente"]
    df_master['DESC1'] = np.select(conditions_desc1, choices_desc1, default="Vigente-Vencido")

    # AK: Rango_Monto y AL: Rango_Saldo
    df_master['Rango_Monto'] = 0
    df_master['Rango_Saldo'] = 0

    # AM: Saldo_Sin_Castigo y AN: Saldo_Apertura_sin_Castigo
    df_master['Saldo_Sin_Castigo'] = np.where(df_master['bandera_castigo'] == "sin_castigo", df_master['saldo_capital_total'], 0)
    df_master['Saldo_Apertura_sin_Castigo'] = np.where(df_master['bandera_castigo'] == "sin_castigo", df_master['monto_otorgado_total'], 0)

    # AO: Saldo_Contencion (Depende de CONTENCION)
    df_master['Saldo_Contencion'] = np.where(df_master['CONTENCION'] == "N/D", 0, df_master['saldo_capital_total'])

    # AP: PR_Origen_Limpio
    digital_origenes = ["Promotor Digital", "Chatbot"]
    df_master['PR_Origen_Limpio'] = np.where(df_master['origen'].isin(digital_origenes), "Digital", "Físico")

    # === Bloque 3: Columnas AQ a BF (Tasa Ponderada y Banderas Finales) ===

    # --- Cálculos de Porcentajes (Transform) ---
    # La función .transform('sum') simula SUMAR.SI.CONJUNTO en pandas

    # AQ: pctNom_x_UEN
    sum_aq = df_master.groupby(['fecha_cierre', 'uen'])['Saldo_Sin_Castigo'].transform('sum')
    df_master['pctNom_x_UEN'] = df_master['tasa_nominal_ponderada'] * df_master['Saldo_Sin_Castigo'] / sum_aq
    df_master['pctNom_x_UEN'] = df_master['pctNom_x_UEN'].fillna(0) # SI.ERROR -> 0
    
    # AR: pctNom_x_UEN_AP
    sum_ar = df_master.groupby(['fecha_cierre', 'Mes_BperturB', 'uen'])['Saldo_Apertura_sin_Castigo'].transform('sum')
    df_master['pctNom_x_UEN_AP'] = df_master['tasa_nominal_apertura'] * df_master['Saldo_Apertura_sin_Castigo'] / sum_ar
    df_master['pctNom_x_UEN_AP'] = df_master['pctNom_x_UEN_AP'].fillna(0) # SI.ERROR -> 0

    # AS: pctNom_x_Tipo_PR
    sum_as = df_master.groupby(['fecha_cierre', 'tipo_cliente'])['Saldo_Sin_Castigo'].transform('sum')
    df_master['pctNom_x_Tipo_PR'] = df_master['tasa_nominal_ponderada'] * df_master['Saldo_Sin_Castigo'] / sum_as
    df_master['pctNom_x_Tipo_PR'] = df_master['pctNom_x_Tipo_PR'].fillna(0)

    # AT: pctNom_x_Tipo_PR_AP (Usando AN2 en lugar de AQ2 por lógica de ponderación)