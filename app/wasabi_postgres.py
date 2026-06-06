from __future__ import annotations

import gzip
import os
import subprocess


def dump_database_to_gzip(db: dict, dbfile: str) -> str | None:
    env = os.environ.copy()
    env["PGPASSWORD"] = db["password"] or ""
    cmd = [
        "pg_dump",
        "-h",
        db["host"],
        "-p",
        str(db["port"]),
        "-U",
        db["user"],
        "--no-owner",
        "--clean",
        "--if-exists",
        db["dbname"],
    ]
    proc = subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    with gzip.open(dbfile, "wb", compresslevel=6) as gz:
        gz.writelines(proc.stdout)
    stderr = proc.stderr.read().decode("utf-8", errors="replace")
    proc.wait(timeout=300)
    if proc.returncode != 0:
        return stderr[:500]
    return None


def restore_database_from_gzip(db: dict, local_gz: str) -> str | None:
    env = os.environ.copy()
    env["PGPASSWORD"] = db["password"] or ""
    with gzip.open(local_gz, "rb") as backup:
        proc = subprocess.Popen(
            [
                "psql",
                "-h",
                db["host"],
                "-p",
                str(db["port"]),
                "-U",
                db["user"],
                "-d",
                db["dbname"],
                "--no-password",
            ],
            stdin=subprocess.PIPE,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = proc.communicate(input=backup.read(), timeout=300)
    if proc.returncode != 0:
        return (stderr or stdout).decode("utf-8", errors="replace")[:500]
    return None
