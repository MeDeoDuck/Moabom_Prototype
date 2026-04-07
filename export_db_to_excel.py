"""
PostgreSQL 데이터를 Excel/CSV로 내보내기

사용법:
    python export_db_to_excel.py

출력:
    - db_export_YYYYMMDD_HHMMSS.xlsx (모든 테이블)
    - 각 테이블별 CSV 파일
"""
import os
import sys
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
import pandas as pd
from dotenv import load_dotenv

# Load environment
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://myuser:mypassword@localhost:5432/mydatabase")


def get_connection():
    """PostgreSQL 연결"""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.set_client_encoding('UTF8')
        return conn
    except Exception as e:
        print(f"❌ DB 연결 실패: {e}")
        sys.exit(1)


def get_all_tables(conn):
    """모든 테이블 목록 조회"""
    query = """
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public' 
        AND table_type = 'BASE TABLE'
        ORDER BY table_name;
    """
    with conn.cursor() as cur:
        cur.execute(query)
        return [row[0] for row in cur.fetchall()]


def get_table_count(conn, table_name):
    """테이블 row 개수 조회"""
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {table_name}")
            return cur.fetchone()[0]
    except:
        return 0


def export_table_to_dataframe(conn, table_name):
    """테이블 데이터를 DataFrame으로 변환"""
    try:
        query = f"SELECT * FROM {table_name}"
        df = pd.read_sql_query(query, conn)
        return df
    except Exception as e:
        print(f"  ⚠️  {table_name} 조회 실패: {e}")
        return None


def main():
    print("="*70)
    print("PostgreSQL → Excel/CSV Export")
    print("="*70)
    
    # Connect to DB
    print("\n[1/4] DB 연결 중...")
    conn = get_connection()
    print("  ✅ 연결 성공!")
    
    # Get tables
    print("\n[2/4] 테이블 목록 조회 중...")
    tables = get_all_tables(conn)
    
    if not tables:
        print("  ⚠️  테이블이 없습니다.")
        conn.close()
        return
    
    print(f"  ✅ {len(tables)}개 테이블 발견:")
    for table in tables:
        count = get_table_count(conn, table)
        print(f"     - {table}: {count:,} rows")
    
    # Export to Excel
    print("\n[3/4] Excel 파일로 내보내는 중...")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    excel_filename = f"db_export_{timestamp}.xlsx"
    
    with pd.ExcelWriter(excel_filename, engine='openpyxl') as writer:
        for table in tables:
            print(f"  - {table}...", end='')
            df = export_table_to_dataframe(conn, table)
            
            if df is not None and not df.empty:
                # Sheet 이름은 최대 31자
                sheet_name = table[:31]
                df.to_excel(writer, sheet_name=sheet_name, index=False)
                print(f" ✅ ({len(df)} rows)")
            elif df is not None:
                print(f" ⚠️  (empty)")
            else:
                print(f" ❌ (failed)")
    
    print(f"\n  ✅ Excel 파일 생성: {excel_filename}")
    
    # Export to CSV (개별 파일)
    print("\n[4/4] CSV 파일로 내보내는 중...")
    csv_dir = f"db_export_{timestamp}_csv"
    os.makedirs(csv_dir, exist_ok=True)
    
    for table in tables:
        df = export_table_to_dataframe(conn, table)
        if df is not None and not df.empty:
            csv_filename = os.path.join(csv_dir, f"{table}.csv")
            df.to_csv(csv_filename, index=False, encoding='utf-8-sig')
            print(f"  - {table}.csv ✅ ({len(df)} rows)")
    
    print(f"\n  ✅ CSV 폴더 생성: {csv_dir}/")
    
    # Close connection
    conn.close()
    
    # Summary
    print("\n" + "="*70)
    print("✅ 내보내기 완료!")
    print("="*70)
    print(f"\n생성된 파일:")
    print(f"  1. {excel_filename} (모든 테이블을 Sheet로)")
    print(f"  2. {csv_dir}/ (각 테이블별 CSV)")
    print(f"\n총 {len(tables)}개 테이블 내보냄")
    print("="*70)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  중단됨")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
