from datetime import datetime
from typing import Generic, ClassVar, List, Dict, TypeVar

from ai_platform.workspace.storage.exceptions import ObjectNotFound
from ai_platform.workspace.storage.structured.base import StoredRecord, RecordReference

ItemT = TypeVar("ItemT")
StoreT = TypeVar("StoreT")


class SingleStoreMixin(Generic[ItemT, StoreT]):
    model_cls: ClassVar[type[StoreT]]
    missing_label: ClassVar[str | None] = None
    STORE_KEY: ClassVar[str] = "__store__"

    def _load_store(self) -> StoreT:
        try:
            return super().get_canonical(self.STORE_KEY).data
        except ObjectNotFound:
            return self.model_cls()

    def _save_store(self, store: StoreT) -> StoredRecord[StoreT]:
        store.updated_at = datetime.now()
        return super().put_canonical(self.STORE_KEY, store)

    def put_canonical(self, logical_name: str, data: ItemT) -> StoredRecord[ItemT]:
        store = self._load_store()
        store.items[logical_name] = data

        saved = self._save_store(store)
        ref = RecordReference(
            id=saved.reference.id,
            logical_name=logical_name,
            file_name=saved.reference.file_name,
        )
        return StoredRecord(data=data, reference=ref)

    def get_canonical(self, logical_name: str) -> StoredRecord[ItemT]:
        store = self._load_store()

        if logical_name not in store.items:
            label = self.missing_label or self.model_cls.__name__
            raise ObjectNotFound(f"{label} not found: {logical_name}")

        data = store.items[logical_name]
        store_ref = super().get_canonical(self.STORE_KEY).reference

        ref = RecordReference(
            id=store_ref.id,
            logical_name=logical_name,
            file_name=store_ref.file_name,
        )
        return StoredRecord(data=data, reference=ref)

    def list_canonicals(self) -> List[str]:
        store = self._load_store()
        return sorted(store.items.keys())

    def get_all_items(self, *, limit: int | None = None) -> Dict[str, ItemT]:
        items = self._load_store().items
        if limit is not None:
            return dict(list(items.items())[:limit])
        return items

    def delete_canonical(self, logical_name: str) -> None:
        store = self._load_store()
        if logical_name in store.items:
            del store.items[logical_name]
            self._save_store(store)
