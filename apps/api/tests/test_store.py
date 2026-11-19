"""The scenarios store's SQL adapter, without a database: what Postgres is sent for the DuckDB-style SQL we write."""

from gridify_api.storage.scenarios import Cursor


def test_postgres_gets_percent_signs_escaped_and_placeholders_converted():
    """Regression: a literal % (LIKE 'CR-%') reached psycopg unescaped and every hand-placed connection failed."""
    sql = Cursor(None, "postgres")._sql("SELECT request_id FROM connections WHERE request_id LIKE 'CR-%' AND branch_id = ?")
    assert sql == "SELECT request_id FROM connections WHERE request_id LIKE 'CR-%%' AND branch_id = %s"
    assert Cursor(None, "postgres")._sql("CREATE TABLE t (x DOUBLE)") == "CREATE TABLE t (x DOUBLE PRECISION)"


def test_duckdb_sql_is_sent_as_written():
    sql = "SELECT 1 FROM connections WHERE request_id LIKE 'CR-%' AND branch_id = ?"
    assert Cursor(None, "duckdb")._sql(sql) == sql
