# Sold / available / likely-sold ledger (Postgres on OCI)

Database: `bluey-db` — Always-Free Ubuntu VM in OCI ap-sydney-1
(address 140.238.200.46, SSH key only, port 5432 not exposed publicly).

## Access (SSH tunnel from the Windows host)

```
ssh -i C:\Users\James Love\.oci\oci_bluey_id -N -L 5434:127.0.0.1:5432 ubuntu@140.238.200.46
$env:DATABASE_URL='postgresql://bluey:bluey@localhost:5434/bluey'
```

## Run

```
python db/seed_from_json.py   # idempotent: imports ebay_cache + manual_ebay_sales.json
python db/daily_check.py      # snapshots active listings via /api/buy-options,
                              # flips vanished ones to likely_sold_queue (with links)
```

Daily 9am automation (trigger 7c4e7282) runs `daily_check.py` through the
tunnel after the pricing/affiliate/cost check, then pg_dumps a fresh backup.
See `daily_check.py` docstring. Manual uploads (eBay pasted sold results) go
through `manual_ebay_sales.json`, then re-run `seed_from_json.py`.

## Backup (3 stages)

- OCI VM: `pg_dump -Fc` on the host (`/tmp/stageN.dump`)
- Local Docker: `docker exec bluey-db pg_dump ... -f /tmp/stageN.dump`
- Workspace: `blueyco-in/db/bluey-db-*-stageN.dump` (attached in chat on request)
