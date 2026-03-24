import psycopg2
import pandas as pd

conn = psycopg2.connect(
    "postgresql://myuser:mypassword@localhost:5432/mydatabase"
)

df = pd.read_sql("SELECT * FROM videos", conn)
df.to_excel("videos.xlsx", index=False)
conn.close()