"""Disposable PostgreSQL/pgvector only. No production DSN or credentials are read."""

from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import pytest


@pytest.fixture(scope="session")
def pg_dsn():
    import pgserver

    root = Path(tempfile.mkdtemp(prefix="im19-test-postgres-"))
    root.chmod(0o755)
    binaries = Path(pgserver.__file__).parent / "pginstall"
    kwargs = {}
    if os.geteuid() == 0:
        uid_map = (
            Path("/proc/self/uid_map").read_text().splitlines()
            if Path("/proc/self/uid_map").exists()
            else []
        )
        if uid_map and all(int(line.split()[2]) == 1 for line in uid_map):
            shutil.rmtree(root)
            pytest.skip(
                "PostgreSQL requires non-root; runtime maps only UID 0. Run database tests in CI."
            )
        # Use an existing nonprivileged OS identity, never create accounts or expose /root.
        copied = root / "pginstall"
        shutil.copytree(binaries, copied)
        binaries = copied
        kwargs = {"user": 65534, "group": 65534}
    data = root / "data"
    data.mkdir()
    socket = root / "socket"
    socket.mkdir()
    if kwargs:
        os.chown(data, 65534, 65534)
        os.chown(socket, 65534, 65534)

    def run(name, args):
        return subprocess.run(
            [str(binaries / "bin" / name), *args],
            capture_output=True,
            text=True,
            check=True,
            **kwargs,
        )

    run(
        "initdb", ["-D", str(data), "-U", "postgres", "--auth=trust", "--encoding=UTF8"]
    )
    run(
        "pg_ctl",
        [
            "-D",
            str(data),
            "-l",
            str(data / "log"),
            "-o",
            f"-k {socket} -c listen_addresses=''",
            "-w",
            "start",
        ],
    )
    dsn = f"host={socket} dbname=postgres user=postgres"
    try:
        yield dsn
    finally:
        run("pg_ctl", ["-D", str(data), "-w", "stop", "-m", "immediate"])
        shutil.rmtree(root)


@pytest.fixture()
def database(pg_dsn):
    import psycopg
    from im19.storage.postgres import PostgresStore

    with psycopg.connect(pg_dsn) as conn:
        conn.execute("DROP SCHEMA IF EXISTS im19 CASCADE")
        conn.execute("CREATE SCHEMA IF NOT EXISTS extensions")
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector SCHEMA extensions")
        conn.execute(
            Path(
                "supabase/migrations/20261025010000_im19_knowledge_intelligence.sql"
            ).read_text()
        )
    return PostgresStore(pg_dsn, allow_local_test=True)
