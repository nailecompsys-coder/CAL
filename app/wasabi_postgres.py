from __future__ import annotations

import gzip
import os
import shutil
import subprocess


def _docker_cmd() -> list[str] | None:
    if not shutil.which("docker"):
        return None
    probe = subprocess.run(
        ["docker", "inspect", "cal_postgres"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if probe.returncode == 0:
        return ["docker"]
    sudo_probe = subprocess.run(
        ["sudo", "-n", "docker", "inspect", "cal_postgres"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if sudo_probe.returncode == 0:
        return ["sudo", "-n", "docker"]
    return None


def _uses_standalone_postgres(db: dict) -> bool:
    return db.get("host") in {"cal_postgres", "cal_db"} and _docker_cmd() is not None


def dump_database_to_gzip(db: dict, dbfile: str) -> str | None:
    env = os.environ.copy()
    env["PGPASSWORD"] = db["password"] or ""
    docker_cmd = _docker_cmd() if _uses_standalone_postgres(db) else None
    if docker_cmd:
        cmd = [
            *docker_cmd,
            "exec",
            "-e",
            f"PGPASSWORD={db['password'] or ''}",
            "cal_postgres",
            "pg_dump",
            "-U",
            db["user"],
            "--no-owner",
            "--clean",
            "--if-exists",
            db["dbname"],
        ]
    else:
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
    docker_cmd = _docker_cmd() if _uses_standalone_postgres(db) else None
    if docker_cmd:
        cmd = [
            *docker_cmd,
            "exec",
            "-i",
            "-e",
            f"PGPASSWORD={db['password'] or ''}",
            "cal_postgres",
            "psql",
            "-U",
            db["user"],
            "-d",
            db["dbname"],
            "--no-password",
        ]
    else:
        cmd = [
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
        ]
    with gzip.open(local_gz, "rb") as backup:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = proc.communicate(input=backup.read(), timeout=300)
    if proc.returncode != 0:
        return (stderr or stdout).decode("utf-8", errors="replace")[:500]
    return None
