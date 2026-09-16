import pandas as pd

df = pd.read_excel("data/maritime_dataset_final_corrige_v3_cancelled.xlsx")

print("\n" + "="*60)
print("          PROFILING DU DATASET")
print("="*60)

# 1. Dimensions
print("\n--- DIMENSIONS ---")
print(f"Nombre de lignes    : {df.shape[0]}")
print(f"Nombre de colonnes  : {df.shape[1]}")

# 2. Types
print("\n--- TYPES DES VARIABLES ---")
print(df.dtypes)

# 3. Valeurs manquantes
print("\n--- VALEURS MANQUANTES ---")
missing = df.isnull().sum()
missing = missing[missing > 0]

if len(missing) == 0:
    print("Aucune valeur manquante.")
else:
    print(missing)

# 4. Valeurs uniques
print("\n--- NOMBRE DE VALEURS UNIQUES ---")
print(df.nunique().sort_values())

# 5. Doublons
print("\n--- DOUBLONS ---")
print(f"Nombre de doublons : {df.duplicated().sum()}")

# 6. Statistiques numériques
print("\n--- STATISTIQUES DES VARIABLES NUMERIQUES ---")
print(df.describe())

# 7. Variables catégorielles
print("\n--- VARIABLES CATEGORIELLES ---")

categorical_cols = df.select_dtypes(include="object").columns

for col in categorical_cols:
    print(f"\n{col}")
    print(f"Nombre de modalités : {df[col].nunique()}")
    print(df[col].value_counts().head(10))

print("\n" + "="*60)
print("          FIN DU PROFILING")
print("="*60)