# RLB operations and recovery

Production has not been configured or certified. Apply these procedures separately to staging first. API and worker must share one environment's database, bucket and credential encryption key. Never copy production credentials into local tests.

## Backup set and owner actions

Before migration or deployment, record the Git commit, migration version, database server version and bucket name. Stop new task admission/imports and drain or stop workers for a consistent application checkpoint. Preserve database state **and** all referenced object bytes; include Auth, public tables, pgmq messages, artifact tombstones and audit roots. Keep the matching `CREDENTIAL_ENCRYPTION_KEY` version in a separate restricted secret vault. Restrict backup access: database exports include encrypted provider credentials and user data.

In Supabase Dashboard → Database → Backups, confirm the current backup/PITR coverage and retention, and record an actual recoverable timestamp. The owner must choose an acceptable recovery point objective and enable coverage accordingly. Database backups contain Storage metadata, not the object bytes: independently copy the private bucket, preserving exact keys and checksums. Do not delete the original objects to test restoration. [Supabase backup scope](https://supabase.com/docs/guides/platform/backups).

Use a `pg_dump` client at least as new as the database server. A 15.x client cannot dump a 17.x server. For an independently managed disposable PostgreSQL rehearsal, provision restricted libpq service entries `rlb_backup` and `rlb_restore` plus a mode-0600 passfile outside the repository. Both entries must use `sslmode=verify-full` and a trusted CA for remote hosts. Commands keep connection secrets out of command arguments:

```sh
umask 077
PGSERVICE=rlb_backup pg_dump --format=custom --file=rlb-checkpoint.dump
pg_restore --list rlb-checkpoint.dump > rlb-checkpoint.manifest
PGSERVICE=rlb_restore pg_restore --exit-on-error --dbname='service=rlb_restore' rlb-checkpoint.dump
```

The restore target must be a fresh **disposable** database with compatible extensions/roles. Never run this generic restore against an existing managed Supabase project. For Supabase-managed Auth/roles/extensions, use its supported [backup/restore procedure](https://supabase.com/docs/guides/platform/migrating-within-supabase/backup-restore) or managed restore-to-new-project workflow. Record any excluded schemas and restore steps; a public-table export alone is not a disaster recovery backup.

## Restore acceptance

1. Keep the replacement API/worker offline. Restore the database and separate bucket copy into the isolated target; configure the matching encryption key in the secret store.
2. Check migration version 5, row counts, canonical snapshot hashes, object checksums, private bucket status, RLS policies, queue access restrictions and credential decryption. Do not print decrypted values.
3. Deploy the exact matching application revision. Verify `/health`; start one worker, then require `/ready` to become healthy. A heartbeat older than 90 seconds must fail readiness.
4. With two disposable users, verify Auth, cross-user denial, workflow evidence and interrupted-task recovery. Queue messages are at least once; an interrupted external AI call can recur but cannot bypass the persisted budget. Examine stale command records and sandbox orphans before retrying expensive work.
5. Run a fresh real sandbox workflow, approval and immutable promotion; retain the acceptance record. Measure restoration duration and data-loss window. Only then consider an owner-approved production cutover.

CI includes a disposable PostgreSQL/pgmq dump-and-restore rehearsal. It does not validate managed Supabase Auth, Storage byte restoration, platform backups or production disaster recovery. This pass saved a restricted pre-migration public-data snapshot, not a complete cloud backup.

## Monitoring and recovery

Alert on API `/ready` HTTP 503, missing worker heartbeat, increasing failed tasks, exhausted queue deliveries, provider failures/budget exhaustion and incomplete artifact cleanup. Correlate `task_id`, workspace ID, agent run, `provider_calls.evidence`, `task_events.sequence`, command ID/sandbox ID, approval and snapshot references. Use Railway/Vercel platform logs with restricted access; never log environment dumps, authorization headers or provider response bodies.

- API restart: durable records remain authoritative. Browser refresh reads current state and resumes event polling.
- Worker loss: session locks release on disconnect; pgmq visibility allows reclaim. Inspect persisted stage/evidence before intervention. Never manually advance an approval or mark failed tests passed.
- Provider rejection: fix the exact API model ID/account permission in RLB settings, retaining encrypted credentials and attempt history. Transient retries and repair attempts are bounded.
- Daytona failure: keep tests failed/unavailable. Supply an owner-trusted image; verify network restrictions, timeout/cancel behavior and auto-stop/delete in that account.
- Retention: the worker uses the private Storage API, bounded passes, locks and permanent deletion tombstones. Canonical, active, published and audit roots remain protected. Do not delete `storage.objects` rows directly. Audit-root deletion requires a separate reviewed retention policy.

## Encryption-key handling

API and worker must use the same `CREDENTIAL_ENCRYPTION_KEY` for one environment. Back it up separately from the encrypted database. Never replace it casually: existing rows cannot be decrypted with a new key. Rotation requires a maintenance window, protected backup, transactional re-encryption of every credential under a separately stored new key, verification, coordinated service restart and tested rollback. No rotation was performed or automated by this pass. If the key is lost, provider credentials must be re-entered through authenticated settings; ciphertext is not recoverable by changing configuration.
