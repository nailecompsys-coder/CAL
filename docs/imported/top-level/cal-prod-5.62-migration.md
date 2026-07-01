# CAL Production Migration to 192.168.5.62

Last verified: 2026-05-18

## Current State

- Legacy CAL host: `192.168.20.10` (`llm-core`)
- Legacy app root: `/home/dnaile748/cal`
- Legacy running container: `cal_api`, healthy, version `1.3.5-beta.1+20260429T205635Z`
- Edge nginx for the `.5.x` app VMs lives on `192.168.5.75` and serves routes for `192.168.5.60`, `192.168.5.61`, and `192.168.5.62`
- Current `.75` CAL vhost already proxies `cal.midfloridasurgical.com` to `http://192.168.5.62:3005/`
- Target host: `192.168.5.62` (`cal-prod-vm`)
- Target app root: `/opt/cal`
- Target containers: `cal_api` and `cal_postgres`, both from `docker-compose.standalone.yml`
- Target health: `http://192.168.5.62:3005/health`
- Public health currently returns version `1.3.5-beta.1+20260429T205635Z`

Observed row counts on 2026-05-18:

| Table | Legacy `20.10` | Target `.62` |
|---|---:|---:|
| `surgeons` | 16 | 16 |
| `surgeon_devices` | 33 | 33 |
| `call_rotations` | 374 | 374 |
| `days_off` | 95 | 105 |
| `meetings` | 36 | 39 |
| `surgical_cases` | 5 | 5 |
| `patient_assignments` | 0 | 0 |

The target VM is not simply stale-empty; it currently has more `days_off` and `meetings` rows than the legacy database. Do not overwrite `.62` blindly without deciding which database is authoritative.

## Target Production Shape

- CAL app code deploys from `/opt/cal`
- `cal_api` runs FastAPI on container port `3005`
- `cal_postgres` owns the CAL database locally on the VM
- `.env` keeps `BASE_URL=https://cal.midfloridasurgical.com`
- `DATABASE_URL` points at `cal_postgres:5432`
- Edge nginx on `192.168.5.75` proxies `cal.midfloridasurgical.com` to `http://192.168.5.62:3005/`

## Verification Checklist

1. Confirm public edge routing on `.75`:
   `sudo grep -R "192.168.5.62:3005" -n /etc/nginx/sites-enabled`
2. Verify target health:
   `curl -sf http://192.168.5.62:3005/health`
3. Verify public health:
   `curl -sk https://cal.midfloridasurgical.com/health`
4. Verify target tables and row counts for core tables: `surgeons`, `days_off`, `call_rotations`, `surgical_cases`, `surgeon_devices`.
5. Smoke test admin login and surgeon schedule through `https://cal.midfloridasurgical.com`.
6. Confirm RVU still has the same `SECRET_KEY`/auth contract if RVU remains coupled to CAL login.

## Cutover

### Phase 1: Edge routing

As of 2026-05-18, this appears complete: edge `.75` already proxies CAL to `.62`.

If it ever needs to be re-applied, run from the edge nginx host (`192.168.5.75`) after target checks pass. If the CAL repo is not present on the edge host, copy `deploy/cutover_to_cal_vm.sh` there first and run it with sudo:

```bash
sudo ./deploy/cutover_to_cal_vm.sh 192.168.5.62
```

Then verify:

```bash
curl -skI https://cal.midfloridasurgical.com/health
curl -sk https://cal.midfloridasurgical.com/health
```

This phase moves public CAL traffic to the `.62` app VM while keeping `.75` as the shared edge/TLS host for the `.5.x` app VMs.

### Phase 2: Retire legacy CAL on `20.10`

After `.75` points CAL at `.62` and production smoke tests pass:

1. Leave the `20.10` CAL container stopped but recoverable during the rollback window.
2. Keep the `20.10` database/app backup until one business day of clean `.62` production use.
3. Remove scheduled deploy habits and docs that target `/home/dnaile748/cal` on `20.10`.
4. Do not remove unrelated `20.10` services; it still hosts other workloads.

## Rollback

The cutover script saves the previous nginx config on the edge host under:

```text
/root/cal-cutover-backups/<timestamp>/cal.midfloridasurgical.com.conf
```

Restore that file to `/etc/nginx/sites-available/cal.midfloridasurgical.com.conf`, run `nginx -t`, and reload nginx.

## Do Not Do

- Do not run `docker compose down` on the old Atlas stack.
- Do not point edge traffic to `.62` until the final database restore/data parity check is complete.
- Do not rotate `SECRET_KEY` during the move unless RVU and existing surgeon sessions are handled at the same time.
