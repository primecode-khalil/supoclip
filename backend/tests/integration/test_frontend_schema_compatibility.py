"""A fresh backend database must support the generated Prisma client's reads."""
from pathlib import Path
import re
from uuid import uuid4

from sqlalchemy import text
from src.database import get_engine


async def test_prisma_scalar_columns_exist_after_backend_initialization(db_session):
    root = Path(__file__).resolve().parents[3]
    schema = (root / "frontend/prisma/schema.prisma").read_text()
    namespace = "install_schema_" + uuid4().hex
    async with get_engine().begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{namespace}"'))
        await connection.execute(text(f'SET LOCAL search_path TO "{namespace}", public'))
        raw = (await connection.get_raw_connection()).driver_connection
        await raw.execute((root / "init.sql").read_text())
        for migration in sorted((root / "backend/src/migrations/sql").glob("*.sql")):
            await raw.execute(migration.read_text())
        actual = set((await connection.execute(text("""
            SELECT table_name, column_name FROM information_schema.columns
            WHERE table_schema=:namespace
        """), {"namespace": namespace})).all())
        await connection.execute(text(f'DROP SCHEMA "{namespace}" CASCADE'))
    missing = []
    for model, body in re.findall(r"model\s+(\w+)\s*\{(.*?)\n\}", schema, re.S):
        mapping = re.search(r'@@map\("([^"]+)"\)', body)
        table = mapping[1] if mapping else model
        for line in body.splitlines():
            field = re.match(r"\s*(\w+)\s+(?:String|Int|Float|Boolean|DateTime|Json|BigInt|Bytes|Decimal)(?:\?|\[\])?\s", line)
            if field:
                column_map = re.search(r'(?<!@)@map\("([^"]+)"\)', line)
                column = column_map[1] if column_map else field[1]
                if (table, column) not in actual:
                    missing.append(f"{table}.{column}")
    assert not missing, "Prisma reads would fail on missing database columns: " + ", ".join(missing)
