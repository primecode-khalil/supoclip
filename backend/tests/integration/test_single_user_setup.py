"""Exercise the installer's optional guard on isolated real PostgreSQL schemas."""
import asyncio
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest

SQL = (Path(__file__).resolve().parents[3] / "deploy/vps/single-user.sql").read_text()


@pytest.fixture
async def setup_database(test_database_url):
    if not test_database_url:
        pytest.skip("TEST_DATABASE_URL must point to a dedicated PostgreSQL database")
    dsn = test_database_url.replace("postgresql+asyncpg://", "postgresql://")
    schema = "setup_" + uuid4().hex
    connection = await asyncpg.connect(dsn)
    await connection.execute(f'CREATE SCHEMA "{schema}"')
    await connection.execute(f'SET search_path TO "{schema}"')
    await connection.execute("CREATE TABLE users (id TEXT PRIMARY KEY, is_admin BOOLEAN NOT NULL DEFAULT FALSE)")
    try:
        yield connection, dsn, schema
    finally:
        await connection.execute("ROLLBACK")
        await connection.execute("SET search_path TO public")
        await connection.execute(f'DROP SCHEMA "{schema}" CASCADE')
        await connection.close()


async def test_initial_owner_becomes_admin_and_signup_stays_closed_after_deletion(setup_database):
    connection, _, _ = setup_database
    await connection.execute(SQL)
    assert await connection.fetchval("INSERT INTO users(id) VALUES ('owner') RETURNING is_admin") is True
    with pytest.raises(asyncpg.RaiseError, match="Registration is unavailable"):
        await connection.execute("INSERT INTO users(id) VALUES ('other')")
    await connection.execute("DELETE FROM users")
    with pytest.raises(asyncpg.RaiseError, match="Registration is unavailable"):
        await connection.execute("INSERT INTO users(id) VALUES ('replacement')")


async def test_two_concurrent_first_signups_cannot_both_succeed(setup_database):
    first, dsn, schema = setup_database
    await first.execute(SQL)
    second = await asyncpg.connect(dsn)
    await second.execute(f'SET search_path TO "{schema}"')
    transaction = first.transaction()
    await transaction.start()
    try:
        await first.execute("INSERT INTO users(id) VALUES ('first')")
        contender = asyncio.create_task(second.execute("INSERT INTO users(id) VALUES ('second')"))
        await asyncio.sleep(0.05)
        assert not contender.done(), "Second signup must wait for the first transaction"
        await transaction.commit()
        with pytest.raises(asyncpg.RaiseError, match="Registration is unavailable"):
            await contender
        assert await first.fetchval("SELECT count(*) FROM users") == 1
    finally:
        await second.close()


async def test_existing_owner_is_preserved_and_multiple_owner_install_is_rejected(setup_database):
    connection, _, _ = setup_database
    await connection.execute("INSERT INTO users(id) VALUES ('existing')")
    await connection.execute(SQL)
    assert await connection.fetchval("SELECT is_admin FROM users WHERE id='existing'") is True
    await connection.execute(SQL)  # Reapplying setup preserves the claimed guard.
    with pytest.raises(asyncpg.RaiseError, match="Registration is unavailable"):
        await connection.execute("INSERT INTO users(id) VALUES ('later')")


async def test_multiple_owner_database_is_never_silently_promoted(setup_database):
    connection, _, _ = setup_database
    await connection.execute("INSERT INTO users(id) VALUES ('one'), ('two')")
    with pytest.raises(asyncpg.RaiseError, match="multiple owners"):
        await connection.execute(SQL)
    await connection.execute("ROLLBACK")
    assert await connection.fetchval("SELECT count(*) FROM users WHERE is_admin") == 0
