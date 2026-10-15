"""Local immutable objects, published with atomic no-overwrite links.

The root must be an explicitly supplied existing directory on a filesystem
supporting hard links and directory fsync. No network filesystem or hostile
concurrent directory replacement guarantee is made. Catalog publication is a
separate transaction: storing an object does not make an asset queryable.
"""
from __future__ import annotations

import hashlib
import errno
import os
from pathlib import Path
import stat
import tempfile

from pydantic import ValidationError

from uteki.data_platform.contracts import InputManifest, ObjectRef, PresentResource


class ContentStoreError(ValueError):
    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(f"{code}: {detail}")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _directory(path: Path, *, create: bool) -> None:
    if create:
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            pass
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        raise ContentStoreError("OBJECT_MISSING", "object directory is missing") from None
    if not stat.S_ISDIR(mode):
        raise ContentStoreError("UNSAFE_OBJECT_PATH", "expected a regular directory")
    if create:
        # Also retry a parent sync which may have failed after an earlier mkdir.
        _fsync_directory(path.parent)


class ContentStore:
    def __init__(self, data_root: Path | str):
        if not isinstance(data_root, (str, Path)) or (isinstance(data_root, str) and not data_root.strip()):
            raise ContentStoreError("INVALID_DATA_ROOT", "an explicit absolute directory is required")
        if not Path(data_root).is_absolute():
            raise ContentStoreError("INVALID_DATA_ROOT", "data_root must be absolute")
        # Resolve the caller's root once; internal links are never followed.
        try:
            self.data_root = Path(data_root).resolve(strict=True)
            is_directory = stat.S_ISDIR(self.data_root.stat().st_mode)
        except (OSError, ValueError, RuntimeError) as error:
            raise ContentStoreError("INVALID_DATA_ROOT", "cannot access data_root") from error
        if not is_directory:
            raise ContentStoreError("INVALID_DATA_ROOT", "data_root must be an existing directory")

    def _path(self, reference: ObjectRef, *, create: bool = False) -> Path:
        current = self.data_root
        _directory(current, create=False)
        for part in ("objects", "sha256", reference.sha256[:2]):
            current = current / part
            _directory(current, create=create)
        return current / reference.sha256

    def read_object(self, reference: ObjectRef) -> bytes:
        try:
            reference = ObjectRef.model_validate(reference)
        except ValidationError as error:
            raise ContentStoreError("INVALID_REFERENCE", "invalid byte reference") from error
        try:
            return self._read_object(reference)
        except FileNotFoundError as error:
            raise ContentStoreError("OBJECT_MISSING", reference.sha256) from error
        except OSError as error:
            code = "UNSAFE_OBJECT_PATH" if error.errno in {errno.ELOOP, errno.ENOTDIR} else "STORAGE_IO_ERROR"
            raise ContentStoreError(code, "cannot read object") from error

    def _read_object(self, reference: ObjectRef) -> bytes:
        path = self._path(reference)
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ContentStoreError("UNSAFE_OBJECT_PATH", reference.sha256)
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ContentStoreError("UNSAFE_OBJECT_PATH", reference.sha256)
            if info.st_size != reference.byte_length:
                raise ContentStoreError("OBJECT_CORRUPT", reference.sha256)
            raw = stream.read(reference.byte_length + 1)
        if len(raw) != reference.byte_length or hashlib.sha256(raw).hexdigest() != reference.sha256:
            raise ContentStoreError("OBJECT_CORRUPT", reference.sha256)
        return raw

    def put_object(self, raw: bytes) -> ObjectRef:
        if not isinstance(raw, bytes):
            raise ContentStoreError("INVALID_OBJECT", "raw must be bytes")
        try:
            return self._put_object(raw)
        except OSError as error:
            raise ContentStoreError("STORAGE_IO_ERROR", "cannot persist object") from error

    def _put_object(self, raw: bytes) -> ObjectRef:
        reference = ObjectRef(sha256=hashlib.sha256(raw).hexdigest(), byte_length=len(raw))
        path = self._path(reference, create=True)
        if path.exists() or path.is_symlink():
            self._verify_existing(reference, raw)
            _fsync_directory(path.parent)
            return reference

        descriptor, temporary_name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fchmod(stream.fileno(), 0o444)
                os.fsync(stream.fileno())
            if temporary.read_bytes() != raw:
                raise ContentStoreError("OBJECT_CORRUPT", "temporary write differs")
            try:
                # Unlike replace/rename, this cannot overwrite an existing object.
                os.link(temporary, path)
            except FileExistsError:
                self._verify_existing(reference, raw)
            _fsync_directory(path.parent)
        except BaseException:
            # Keep the original failure if cleanup also fails. A pending file
            # is never an object and is never adopted by a subsequent write.
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        else:
            temporary.unlink(missing_ok=True)
        return reference

    def _verify_existing(self, reference: ObjectRef, raw: bytes) -> None:
        if self.read_object(reference) != raw:
            raise ContentStoreError("OBJECT_CORRUPT", reference.sha256)

    def verify_manifest(self, manifest: InputManifest) -> None:
        manifest = self._manifest(manifest)
        self.read_object(manifest.main)
        for resource in manifest.resources:
            if isinstance(resource, PresentResource):
                self.read_object(resource.object_ref)

    def put_manifest(self, manifest: InputManifest) -> ObjectRef:
        manifest = self._manifest(manifest)
        self.verify_manifest(manifest)
        return self.put_object(manifest.canonical_bytes())

    def read_manifest(self, reference: ObjectRef) -> InputManifest:
        raw = self.read_object(reference)
        try:
            manifest = InputManifest.model_validate_json(raw)
        except ValidationError as error:
            raise ContentStoreError("INVALID_MANIFEST", "invalid manifest bytes") from error
        if manifest.canonical_bytes() != raw:
            raise ContentStoreError("INVALID_MANIFEST", "expected canonical manifest bytes")
        self.verify_manifest(manifest)
        return manifest

    @staticmethod
    def _manifest(manifest: InputManifest) -> InputManifest:
        try:
            return InputManifest.model_validate(manifest)
        except ValidationError as error:
            raise ContentStoreError("INVALID_MANIFEST", "invalid input manifest") from error
