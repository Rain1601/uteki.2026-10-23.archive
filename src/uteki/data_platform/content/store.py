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


# 对象存储的领域异常：保留稳定 code，供目录层和恢复流程区分缺失、损坏与 I/O 失败。
class ContentStoreError(ValueError):
    # 保存错误码，并把可读详情组合进异常消息。
    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(f"{code}: {detail}")


# 同步目录项变更，确保新增、链接或重命名在文件内容写稳后也得到持久化确认。
def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


# 按需建立私有目录，并用 lstat 拒绝符号链接和非目录路径。
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


# 以 SHA-256 寻址不可变字节对象；这里只保证原件存储，不负责资产发布或可查询状态。
class ContentStore:
    # 要求调用方显式提供已存在的绝对目录；仅在入口解析根路径，内部路径逐层校验。
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

    # 按 objects/sha256/哈希前两位分桶；create 控制是否创建缺失的目录。
    def _path(self, reference: ObjectRef, *, create: bool = False) -> Path:
        current = self.data_root
        _directory(current, create=False)
        for part in ("objects", "sha256", reference.sha256[:2]):
            current = current / part
            _directory(current, create=create)
        return current / reference.sha256

    # 校验对象引用并读取字节，将缺失、危险路径及底层 I/O 异常转成稳定错误码。
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

    # 打开前后都确认普通文件，再校验长度和哈希；文件名匹配并不足以证明内容完整。
    def _read_object(self, reference: ObjectRef) -> bytes:
        path = self._path(reference)
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ContentStoreError("UNSAFE_OBJECT_PATH", reference.sha256)
        # O_NOFOLLOW 防止最终路径跳转；fstat 再核验真正打开的对象，避免只信打开前的路径检查。
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ContentStoreError("UNSAFE_OBJECT_PATH", reference.sha256)
            if info.st_size != reference.byte_length:
                raise ContentStoreError("OBJECT_CORRUPT", reference.sha256)
            # 多读一个字节可以识别超出声明长度的内容，而不是截断后误判通过。
            raw = stream.read(reference.byte_length + 1)
        if len(raw) != reference.byte_length or hashlib.sha256(raw).hexdigest() != reference.sha256:
            raise ContentStoreError("OBJECT_CORRUPT", reference.sha256)
        return raw

    # 只接受原始 bytes，返回含 SHA-256 和字节长度的不可变引用。
    def put_object(self, raw: bytes) -> ObjectRef:
        if not isinstance(raw, bytes):
            raise ContentStoreError("INVALID_OBJECT", "raw must be bytes")
        try:
            return self._put_object(raw)
        except OSError as error:
            raise ContentStoreError("STORAGE_IO_ERROR", "cannot persist object") from error

    # 先把临时文件写稳，再以不覆盖目标的硬链接发布；重复内容复用前必须重新核验。
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
            # 目标被其他写入先行建立时只允许复用完全相同字节，绝不以当前文件覆盖它。
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

    # 同哈希地址已有对象时仍比较实际字节，发现损坏即报错，不覆盖或自动修复。
    def _verify_existing(self, reference: ObjectRef, raw: bytes) -> None:
        if self.read_object(reference) != raw:
            raise ContentStoreError("OBJECT_CORRUPT", reference.sha256)

    # 核验主文档及所有标为 present 的资源；显式 missing 条目保留缺口，不尝试读取。
    def verify_manifest(self, manifest: InputManifest) -> None:
        manifest = self._manifest(manifest)
        self.read_object(manifest.main)
        for resource in manifest.resources:
            if isinstance(resource, PresentResource):
                self.read_object(resource.object_ref)

    # 先证实清单引用的已获取原件完整，再将规范化清单作为普通对象持久化。
    def put_manifest(self, manifest: InputManifest) -> ObjectRef:
        manifest = self._manifest(manifest)
        self.verify_manifest(manifest)
        return self.put_object(manifest.canonical_bytes())

    # 读取清单后同时验证模型、规范化字节和所引用原件，返回可用的输入清单。
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

    # 统一输入清单的模型校验与错误码，避免上层依赖 Pydantic 的异常细节。
    @staticmethod
    def _manifest(manifest: InputManifest) -> InputManifest:
        try:
            return InputManifest.model_validate(manifest)
        except ValidationError as error:
            raise ContentStoreError("INVALID_MANIFEST", "invalid input manifest") from error
