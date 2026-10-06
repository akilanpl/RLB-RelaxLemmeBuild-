"""Durable local adapters for the existing repository ports."""
from datetime import datetime, timezone

from backend.app.storage.sqlite import SQLiteStateStore
from backend.app.repositories.proposal import InMemoryProposalRepository
from backend.app.repositories.testing import InMemoryTestingRepository
from backend.app.repositories.reviewer import InMemoryReviewerReportRepository
from backend.app.repositories.provider import InMemoryProviderRepository


class Checkpoint:
    fields = ()
    namespace = ""

    def open(self, path):
        self._store = SQLiteStateStore(path)

    async def load(self):
        state = await self._store.load(self.namespace, {})
        for name in self.fields:
            if name in state:
                setattr(self, name, state[name])

    async def save(self):
        await self._store.save(self.namespace, {name: getattr(self, name) for name in self.fields})

    async def close(self):
        await self._store.close()


class SQLiteProposalRepository(Checkpoint, InMemoryProposalRepository):
    fields = ("proposals",)
    namespace = "proposals"

    def __init__(self, path):
        super().__init__()
        self.open(path)

    async def add(self, proposal):
        result = await super().add(proposal)
        await self.save()
        return result

    async def update(self, proposal):
        result = await super().update(proposal)
        await self.save()
        return result


class SQLiteTestingRepository(Checkpoint, InMemoryTestingRepository):
    fields = ("plans", "executions")
    namespace = "testing"

    def __init__(self, path):
        super().__init__()
        self.open(path)

    async def add_plan(self, plan):
        result = await super().add_plan(plan)
        await self.save()
        return result

    async def add_execution(self, execution):
        result = await super().add_execution(execution)
        await self.save()
        return result

    async def add_command_result(self, execution_id, evidence):
        await super().add_command_result(execution_id, evidence)
        await self.save()

    async def add_build_result(self, result):
        result = await super().add_build_result(result)
        await self.save()
        return result


class SQLiteReviewerRepository(Checkpoint, InMemoryReviewerReportRepository):
    fields = ("reports",)
    namespace = "reviews"

    def __init__(self, path):
        super().__init__()
        self.open(path)

    async def add(self, report):
        result = await super().add(report)
        await self.save()
        return result


class SQLiteProviderRepository(Checkpoint, InMemoryProviderRepository):
    fields = ("providers", "credentials", "workers", "loadouts", "active_loadouts")
    namespace = "providers"

    def __init__(self, path):
        super().__init__()
        self.open(path)

    async def save_worker(self, record):
        existing = self.workers.get(record["id"], {})
        self.workers[record["id"]] = {**record, "created_at": existing.get("created_at") or datetime.now(timezone.utc)}
        await self.save()

    async def list_workers(self):
        return list(self.workers.values())

    async def get_credential(self, user_id, provider_id):
        return self.credentials.get((user_id, provider_id))

    async def get_loadout(self, user_id, loadout_id):
        record = self.loadouts.get(loadout_id)
        return record if record and (record.get("user_id") == user_id or record.get("is_system_preset")) else None

    async def list_loadouts(self, user_id):
        return [r for r in self.loadouts.values() if r.get("user_id") == user_id or r.get("is_system_preset")]

    async def active_loadout(self, user_id, workspace_id):
        loadout_id = self.active_loadouts.get(workspace_id)
        return await self.get_loadout(user_id, loadout_id) if loadout_id else None

    async def runtime_configuration(self):
        result = await super().runtime_configuration()
        tasks = getattr(getattr(self, "task_repository", None), "tasks", {}).values()
        result["task_overrides"] = [{"id": t.id, "worker_overrides": t.worker_overrides} for t in tasks]
        return result


def _checkpoint_mutation(name):
    async def mutation(self, *args, **kwargs):
        result = await getattr(InMemoryProviderRepository, name)(self, *args, **kwargs)
        await self.save()
        return result
    return mutation


for _name in ("ensure_provider", "save_credential", "delete_credential",
              "delete_worker", "upsert_loadout", "save_loadout", "switch_loadout"):
    setattr(SQLiteProviderRepository, _name, _checkpoint_mutation(_name))
