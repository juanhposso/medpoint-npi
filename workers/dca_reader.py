import pandas as pd
df = pd.read_excel("./data/medical_board.xlsx", nrows=10, engine="openpyxl")

print(df.columns.to_list())
print(df.head(2))