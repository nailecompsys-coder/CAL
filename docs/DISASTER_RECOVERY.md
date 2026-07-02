# CAL Disaster Recovery

CAL recovery uses GitHub for application code and Wasabi for database backups.

## What Is Backed Up

Each portal backup writes a Wasabi folder:

```text
cal-backups/YYYYMMDD-HHMMSS/
  db.sql.gz
  manifest.json
```

`db.sql.gz` is the PostgreSQL database dump.

`manifest.json` records the app version, Git remote, Git commit, branch, database dump key, dump size, and which secret keys were present at backup time. Secret values are not stored in Wasabi or Git.

The Git metadata is stamped into the Docker image during build so portal-created backups can still record the exact commit even though the running container does not contain the `.git` directory.

## What Is Not Backed Up

The backup does not contain plaintext secrets, nginx config, DNS records, SSL certificates, operating-system packages, or the VM itself.

Keep a secure copy of the production `.env` outside Git. Without `.env`, a fresh server cannot connect to Wasabi, Aprima, OTP/email/SMS providers, or the CAL database with the intended credentials.

## Fresh Server Restore

1. Provision an Ubuntu server.
2. Point DNS/load balancer only after validation.
3. Install packages:

```bash
sudo apt-get update
sudo apt-get install -y git curl ca-certificates docker.io docker-compose-plugin python3 python3-pip
sudo usermod -aG docker "$USER"
```

Log out and back in if Docker group membership changed, or run Docker commands with `sudo`.

4. Clone CAL:

```bash
git clone git@github.com:nailecompsys-coder/CAL.git /opt/cal
cd /opt/cal
```

5. Place production `.env` at:

```text
/opt/cal/.env
```

6. Restore the selected backup:

```bash
cd /opt/cal
server/scripts/dr-restore-from-wasabi.sh cal-backups/YYYYMMDD-HHMMSS
```

The script downloads `db.sql.gz`, pulls Git, starts `cal_postgres`, restores the database, builds `cal_api`, starts it, and verifies `http://127.0.0.1:3005/health`.

## After Restore

Validate:

```bash
curl -fsS http://127.0.0.1:3005/health
docker ps
docker logs --tail=100 cal_api
```

Then restore or recreate nginx/SSL routing for the public domain.

## Current Status

The portal backup and restore cover the database. The DR script covers Git-based app rebuild plus database restore on a prepared server. Full one-click infrastructure recovery still requires separate secure handling for `.env`, nginx/SSL, DNS, and server provisioning.
