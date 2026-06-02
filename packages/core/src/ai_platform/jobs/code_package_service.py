"""CodePackageService — owns both the catalog row and the blob bytes.

Unlike [[job_definition_service]] and [[artifact_type_service]], a code
package's payload is binary (a `.whl`). The service stores the bytes
via the FileRepository (under the `code_packages/` prefix) and records
the resulting `blob_id` + sha256 in the catalog row.

The runtime selector is validated against `KNOWN_RUNTIMES` (same set
as JobDefinition) so a wheel can't be deployed to a runtime the
platform doesn't know how to install into.
"""
from __future__ import annotations

import hashlib

from ai_platform.jobs.job_definition_service import KNOWN_RUNTIMES
from ai_platform.workspace.storage.blobs.base import FileRepository, PutFilePayload
from ai_platform.workspace.storage.protocols import CodePackageRepository
from ai_platform.workspace.storage.structured.code_package_repository import (
    CodePackageRecord,
)


_BLOB_PREFIX = "code_packages"


class CodePackageService:
    def __init__(self, repo: CodePackageRepository, file_repo: FileRepository):
        self.repo = repo
        self.file_repo = file_repo

    def deploy(
        self,
        *,
        name: str,
        version: str,
        runtime_selector: str,
        filename: str,
        wheel_bytes: bytes,
    ) -> CodePackageRecord:
        """Store the wheel bytes + write the catalog row.

        Idempotent on `(name, version)` — re-deploying the same id
        overwrites the row (and creates a new blob under a deterministic
        name; the old blob is left orphaned, the file repo's GC story
        is separate).
        """
        if not name:
            raise ValueError("CodePackage.name must be non-empty")
        if runtime_selector not in KNOWN_RUNTIMES:
            raise ValueError(
                f"Unknown runtime_selector {runtime_selector!r}; "
                f"expected one of {KNOWN_RUNTIMES}"
            )
        if not filename.endswith(".whl"):
            raise ValueError(f"Expected a .whl filename, got {filename!r}")

        sha256 = hashlib.sha256(wheel_bytes).hexdigest()
        size_bytes = len(wheel_bytes)

        # Deterministic blob id: caller can re-fetch by name@version
        # without inspecting the catalog row.
        blob_id = f"{_BLOB_PREFIX}/{name}-{version}.whl"

        self.file_repo.put_canonical_file(
            PutFilePayload(
                logical_name=blob_id,
                bytes_data=wheel_bytes,
                content_type="application/octet-stream",
                metadata={
                    "package_name": name,
                    "package_version": version,
                    "runtime_selector": runtime_selector,
                    "sha256": sha256,
                },
            )
        )

        record = CodePackageRecord(
            id=CodePackageRecord.make_id(name, version),
            name=name,
            version=version,
            runtime_selector=runtime_selector,
            filename=filename,
            blob_id=blob_id,
            sha256=sha256,
            size_bytes=size_bytes,
        )
        return self.repo.put(record)

    def get(self, package_id: str) -> CodePackageRecord:
        return self.repo.get(package_id)

    def get_by_name(self, name: str) -> CodePackageRecord:
        return self.repo.get_by_name(name)

    def list(self, *, runtime_selector: str | None = None) -> list[CodePackageRecord]:
        return self.repo.list(runtime_selector=runtime_selector)

    def download(self, package_id: str) -> tuple[CodePackageRecord, bytes]:
        """Fetch the record + the underlying bytes. Verifies sha256 to
        catch a divergence between row and blob (e.g. blob corrupted
        in transit, or a redeploy overwrote one but not the other).
        """
        record = self.repo.get(package_id)
        wheel_bytes = self.file_repo.get_canonical_file_bytes(record.blob_id)
        actual_sha = hashlib.sha256(wheel_bytes).hexdigest()
        if actual_sha != record.sha256:
            raise ValueError(
                f"CodePackage {package_id} blob sha256 mismatch: "
                f"row={record.sha256[:12]}… blob={actual_sha[:12]}…"
            )
        return record, wheel_bytes
