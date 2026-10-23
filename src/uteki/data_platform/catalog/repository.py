"""Explicit catalog registration and immutable version identity operations."""
from __future__ import annotations

from datetime import date
from functools import wraps
import json
import sqlite3

from pydantic import ValidationError

from .database import Database
from ..content.store import ContentStore, ContentStoreError
from ..contracts.assets import (
    Acquisition, AssetInput, AssetRef, BuildRecipe, CompanyInput, Evidence,
    Representation, SecurityInput, SnapshotRelation, SourceInput,
)
from ..contracts.content import ObjectRef
from ..contracts.common import CatalogError, CatalogView, canonical, digest, new_id, nonblank, utc_now


# 统一目录入口的异常契约；保留已知领域错误，把数据库约束、参数及 I/O 失败分类。
def operation(function):
    # 执行原函数并保留异常因果链，方便上层按稳定错误码决定报错或恢复。
    @wraps(function)
    def call(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (CatalogError, ContentStoreError):
            raise
        except sqlite3.IntegrityError as error:
            raise CatalogError("IDENTITY_CONFLICT", "catalog constraint rejected the operation") from error
        except sqlite3.DatabaseError as error:
            raise CatalogError("CATALOG_INCONSISTENT", "catalog database operation failed") from error
        except (ValidationError, ValueError, TypeError, KeyError) as error:
            raise CatalogError("INVALID_ARGUMENT", str(error)) from error
        except OSError as error:
            raise CatalogError("STORAGE_IO_ERROR", "catalog filesystem operation failed") from error
    return call


# 将值编码为稳定 JSON 文本，供持久化比较及不可变身份检查。
def encoded(value) -> str:
    return canonical(value).decode("utf-8")


# 目录领域入口：登记身份、来源、快照与构建，依靠 Database 持有单一所有权和事务。
class Catalog:
    """Single-owner context. Close before opening another catalog handle."""
    # 复用数据库根目录创建对象存储入口；目录元数据与原始字节共享同一数据根。
    def __init__(self, database: Database):
        self.database = database
        self.root = database.root
        self.content = ContentStore(self.root)

    # 显式建立新目录；遇到已有数据库或产物时由 Database 拒绝覆盖。
    @classmethod
    @operation
    def initialize(cls, data_root):
        return cls(Database(data_root, initialize=True))

    # 打开后先审计已发布数据；recover=True 才处理未完成状态，并在恢复后再次审计。
    @classmethod
    @operation
    def open(cls, data_root, *, recover=False):
        if type(recover) is not bool:
            raise CatalogError("INVALID_ARGUMENT", "recover must be explicit bool")
        catalog = cls(Database(data_root, recover_head=recover))
        try:
            from ..content.recovery import audit_catalog, recover_catalog
            audit_catalog(catalog)
            if recover:
                recover_catalog(catalog)
                audit_catalog(catalog)
            return catalog
        except BaseException:
            catalog.close()
            raise

    # 进入上下文时确认当前句柄仍可用。
    def __enter__(self):
        self.database.assert_open()
        return self

    # 上下文退出时释放 SQLite 连接与目录独占锁。
    def __exit__(self, *args):
        self.close()

    # 把资源清理交给 Database，结束当前目录所有权。
    def close(self):
        self.database.close()

    # 所有 SQL 访问前检查句柄状态，阻止继续使用提交头未确认的连接。
    @property
    def _db(self):
        self.database.assert_open()
        return self.database.connection

    # 获取当前目录视图，供读取方绑定一个明确的目录修订。
    @operation
    def view(self):
        return self.database.view()

    # 调用者携带的视图必须仍等于当前修订，否则要求重新获取游标/视图。
    def _view(self, view):
        if view is not None and CatalogView.model_validate(view) != self.view():
            raise CatalogError("CURSOR_EXPIRED", "catalog view changed; request a new view")

    # 按内部固定表名和字段查询单条记录；不存在时返回明确 NOT_FOUND 错误。
    def _get(self, table, field, identity):
        # table/field are internal constants, never caller-provided SQL fragments.
        nonblank(identity)
        row = self._db.execute(f"SELECT * FROM {table} WHERE {field}=?", (identity,)).fetchone()
        if row is None:
            raise CatalogError("NOT_FOUND", f"unknown {field}")
        return dict(row)

    # 要求写操作归属一个仍在 running 的本地任务。
    def _run(self, run_id):
        row = self._get("runs", "run_id", run_id)
        if row["status"] != "running":
            raise CatalogError("INVALID_STATE", "operation requires a running local task")
        return row

    # 校验证据结构；若引用原件则实际读取验证完整性，此处不判断证据业务内容真伪。
    def _evidence(self, evidence):
        evidence = Evidence.model_validate(evidence)
        if evidence.object_ref:
            self.content.read_object(evidence.object_ref)
        return evidence

    # 为内部插入补齐创建/更新时间；事务边界由调用方法负责。
    def _insert(self, table, values):
        stamp = utc_now()
        values = values | {"created_at": stamp, "updated_at": stamp}
        self._db.execute(f"INSERT INTO {table} ({','.join(values)}) VALUES ({','.join('?' for _ in values)})", tuple(values.values()))

    # 按命名空间和请求键实现幂等：输入指纹相同复用结果，输入变化报冲突。
    def _existing(self, namespace, request_key, value):
        nonblank(request_key)
        fingerprint = digest(canonical(value))
        row = self._db.execute("SELECT * FROM registrations WHERE namespace=? AND request_key=?", (namespace,request_key)).fetchone()
        if row:
            if row["fingerprint"] != fingerprint:
                raise CatalogError("IDEMPOTENCY_CONFLICT", "request key was used for different input")
            return row["result_id"]
        return None

    # 把请求输入指纹与结果身份一起登记，供相同请求安全复用。
    def _register_key(self, namespace, request_key, value, result_id):
        self._insert("registrations", dict(namespace=namespace, request_key=request_key,
                    fingerprint=digest(canonical(value)), result_id=result_id))

    # 创建或复用 build/read 任务，子任务继承 root_run_id 以保留完整运行归属。
    @operation
    def start_run(self, request_key: str, *, purpose: str, kind: str, parent_run_id=None):
        nonblank(request_key); nonblank(purpose)
        if kind not in {"build", "read"}:
            raise CatalogError("INVALID_ARGUMENT", "only local build/read runs are supported")
        row = self._db.execute("SELECT * FROM runs WHERE request_key=?", (request_key,)).fetchone()
        if row:
            if (row["purpose"],row["kind"],row["parent_run_id"]) != (purpose,kind,parent_run_id):
                raise CatalogError("IDEMPOTENCY_CONFLICT", "run request differs")
            return dict(row)
        run_id = new_id("run")
        root_run_id = self._get("runs","run_id",parent_run_id)["root_run_id"] if parent_run_id is not None else run_id
        with self.database.transaction():
            self._insert("runs", dict(run_id=run_id, request_key=request_key, root_run_id=root_run_id,parent_run_id=parent_run_id,
                                    purpose=purpose,kind=kind,status="running"))
        return self._get("runs","run_id",run_id)

    # 确认任务终态；仍持有 collecting/staging 工作时拒绝结束，避免隐藏未决存储状态。
    @operation
    def finish_run(self, run_id, *, status, failure_code=None):
        if status not in {"completed","failed","cancelled"}:
            raise CatalogError("INVALID_ARGUMENT", "unsupported local terminal state")
        if status == "failed":
            nonblank(failure_code)
        elif failure_code is not None:
            raise CatalogError("INVALID_ARGUMENT", "failure code belongs to failed runs")
        row = self._get("runs","run_id",run_id)
        if row["status"] == status:
            if row["failure_code"] != failure_code:
                raise CatalogError("IDEMPOTENCY_CONFLICT", "terminal run failure reason differs")
            return row
        self._run(run_id)
        if (self._db.execute("SELECT 1 FROM asset_builds WHERE run_id=? AND status='staging'", (run_id,)).fetchone()
                or self._db.execute("SELECT 1 FROM asset_snapshots WHERE run_id=? AND status='collecting'", (run_id,)).fetchone()):
            raise CatalogError("INVALID_STATE", "run still owns collecting/staging work")
        with self.database.transaction():
            self._db.execute("UPDATE runs SET status=?,failure_code=?,updated_at=? WHERE run_id=?", (status,failure_code,utc_now(),run_id))
        return self._get("runs","run_id",run_id)

    # 登记不可变策略版本；同名策略只能以完全相同定义重复提交。
    @operation
    def register_policy(self, policy_ref, *, definition, run_id):
        self._run(run_id); nonblank(policy_ref); nonblank(definition)
        value = encoded({"definition": definition})
        row = self._db.execute("SELECT payload FROM policies WHERE policy_ref=?", (policy_ref,)).fetchone()
        if row:
            if row[0] != value:
                raise CatalogError("IDENTITY_CONFLICT", "policy version is immutable")
            return policy_ref
        with self.database.transaction():
            self._insert("policies",dict(policy_ref=policy_ref,payload=value))
        return policy_ref

    # 登记材料类型与 document/dataset 类别的对应关系，拒绝同名异义。
    @operation
    def register_material_type(self, name, *, asset_kind, description, run_id):
        self._run(run_id); nonblank(name); nonblank(description)
        if asset_kind not in {"document","dataset"}:
            raise CatalogError("INVALID_ARGUMENT", "invalid asset kind")
        value = encoded(dict(asset_kind=asset_kind,description=description))
        row = self._db.execute("SELECT payload FROM material_types WHERE name=?", (name,)).fetchone()
        if row:
            if row[0] != value:
                raise CatalogError("IDENTITY_CONFLICT", "material type already registered differently")
            return name
        with self.database.transaction():
            self._insert("material_types", dict(name=name,payload=value))
        return name

    # 基于显式身份依据登记公司，复用一致身份并记录初始名称修订；冲突需显式修订。
    @operation
    def register_company(self, request_key, company: CompanyInput, *, run_id):
        self._run(run_id)
        company = CompanyInput.model_validate(company)
        self._evidence(company.evidence)
        value = company.model_dump(mode="json")
        existing = self._existing("company",request_key,value)
        if existing:
            return existing
        same = self._db.execute("SELECT * FROM companies WHERE identity_basis_kind=? AND identity_basis_value=?",
                                (company.identity_basis_kind,company.identity_basis_value)).fetchone()
        if same and same["payload"] != encoded(value):
            raise CatalogError("IDENTITY_CONFLICT", "identity already registered; use explicit metadata revision")
        identity = same["company_id"] if same else new_id("co")
        with self.database.transaction():
            if not same:
                self._insert("companies",dict(company_id=identity,canonical_name=company.canonical_name,status=company.status,
                    identity_basis_kind=company.identity_basis_kind,identity_basis_value=company.identity_basis_value,payload=encoded(value)))
                self._revision("company",identity,"canonical_name",company.canonical_name,"current","initial registration",company.evidence,None,run_id)
            self._register_key("company",request_key,value,identity)
        return identity

    # 在可选目录视图下读取公司登记记录。
    @operation
    def get_company(self, company_id, *, view=None):
        self._view(view)
        return self._get("companies","company_id",company_id)

    # 登记别名、有效期和证据；未知日期保留为未知，不自动推定历史适用期。
    @operation
    def register_alias(self, request_key, *, company_id, alias, alias_kind, valid_from, valid_to, evidence, run_id):
        self._run(run_id); self.get_company(company_id); nonblank(alias)
        evidence = self._evidence(evidence)
        if alias_kind not in {"former_name","short_name","brand","translation"}:
            raise CatalogError("INVALID_ARGUMENT", "invalid alias kind")
        for value in (valid_from, valid_to):
            if value is not None and type(value) is not date:
                raise CatalogError("INVALID_ARGUMENT", "alias validity must be a date or unknown")
        if valid_from and valid_to and valid_to < valid_from:
            raise CatalogError("INVALID_ARGUMENT", "alias interval reversed")
        value = dict(company_id=company_id,alias=alias,alias_kind=alias_kind,
                     valid_from=valid_from.isoformat() if valid_from else None,
                     valid_to=valid_to.isoformat() if valid_to else None,evidence=evidence.model_dump(mode="json"))
        existing = self._existing("alias",request_key,value)
        if existing:
            return existing
        identity = new_id("alias")
        with self.database.transaction():
            self._insert("company_aliases",{k:v for k,v in value.items() if k!="evidence"} | dict(alias_id=identity,payload=encoded(value)))
            self._register_key("alias",request_key,value,identity)
        return identity

    # 按明确日期返回名称/别名候选；未知有效期仍可进入候选，最终确认由 resolve_company 负责。
    @operation
    def find_companies(self, name, *, as_of: date, view=None):
        self._view(view); nonblank(name)
        if type(as_of) is not date:
            raise CatalogError("INVALID_ARGUMENT", "explicit as_of date required")
        rows = self._db.execute("""SELECT DISTINCT c.* FROM companies c LEFT JOIN company_aliases a USING(company_id)
            WHERE c.canonical_name=? OR (a.alias=? AND (a.valid_from IS NULL OR a.valid_from<=?)
            AND (a.valid_to IS NULL OR a.valid_to>=?)) ORDER BY c.company_id""", (name,name,as_of.isoformat(),as_of.isoformat())).fetchall()
        return [dict(row) for row in rows]

    # 仅返回唯一已确认实体；通过别名解析时还要求已知有效期及已确认内容证据。
    @operation
    def resolve_company(self, name, *, as_of: date, view=None):
        candidates = self.find_companies(name,as_of=as_of,view=view)
        if len(candidates)>1:
            raise CatalogError("AMBIGUOUS_ENTITY", "name/alias matches multiple company candidates")
        if not candidates or candidates[0]["status"] != "confirmed":
            raise CatalogError("NOT_FOUND", "no confirmed company matches; identity may be pending")
        if candidates[0]["canonical_name"] != name:
            known = self._db.execute("""SELECT payload FROM company_aliases WHERE company_id=? AND alias=?
                AND valid_from IS NOT NULL AND valid_to IS NOT NULL AND valid_from<=? AND valid_to>=?""",
                (candidates[0]["company_id"],name,as_of.isoformat(),as_of.isoformat())).fetchall()
            if not known:
                raise CatalogError("UNRESOLVED_TIME", "alias candidate has unknown historical validity")
            if not any(json.loads(row[0])["evidence"]["content_check"]=="confirmed" for row in known):
                raise CatalogError("INVALID_STATE", "alias is only an unconfirmed candidate")
        return candidates[0]

    # 登记交易所内证券代码映射；拒绝时间区间重叠，并禁止未确认公司拥有已确认映射。
    @operation
    def register_security(self, request_key, security: SecurityInput, *, run_id):
        self._run(run_id); security = SecurityInput.model_validate(security)
        company = self.get_company(security.company_id); self._evidence(security.evidence)
        if security.status == "confirmed" and company["status"] != "confirmed":
            raise CatalogError("INVALID_STATE", "pending company cannot have a confirmed security mapping")
        value = security.model_dump(mode="json")
        existing = self._existing("security",request_key,value)
        if existing:
            return existing
        # 未知有效期按开放边界参与冲突检测；不能利用缺日期绕过同代码的重叠映射。
        for row in self._db.execute("SELECT * FROM company_securities WHERE ticker=? AND exchange_mic=?", (security.ticker,security.exchange_mic)):
            a,b = value["valid_from"] or "0001-01-01",value["valid_to"] or "9999-12-31"
            c,d = row["valid_from"] or "0001-01-01",row["valid_to"] or "9999-12-31"
            if max(a,c) <= min(b,d):
                raise CatalogError("IDENTITY_CONFLICT", "security validity overlaps or is unresolved")
        identity = new_id("sec")
        with self.database.transaction():
            self._insert("company_securities",dict(security_id=identity,company_id=security.company_id,ticker=security.ticker,
                exchange_mic=security.exchange_mic,valid_from=value["valid_from"],valid_to=value["valid_to"],status=security.status,payload=encoded(value)))
            self._register_key("security",request_key,value,identity)
        return identity

    # 按代码、交易所和日期解析已确认映射；有效期未知时明确报 UNRESOLVED_TIME。
    @operation
    def resolve_security(self, ticker, exchange_mic, *, as_of: date, view=None):
        self._view(view)
        if type(as_of) is not date:
            raise CatalogError("INVALID_ARGUMENT", "explicit as_of date required")
        rows = self._db.execute("""SELECT s.* FROM company_securities s JOIN companies c USING(company_id)
            WHERE s.ticker=? AND s.exchange_mic=? AND s.status='confirmed' AND c.status='confirmed'
            AND (s.valid_from IS NULL OR s.valid_from<=?) AND (s.valid_to IS NULL OR s.valid_to>=?)""",
            (ticker,exchange_mic,as_of.isoformat(),as_of.isoformat())).fetchall()
        if len(rows)>1:
            raise CatalogError("AMBIGUOUS_ENTITY", "security mapping ambiguous")
        if not rows:
            raise CatalogError("NOT_FOUND", "no confirmed security mapping")
        if rows[0]["valid_from"] is None or rows[0]["valid_to"] is None:
            raise CatalogError("UNRESOLVED_TIME", "security candidate has unknown historical validity")
        return dict(rows[0])

    # 校验来源绑定的策略和可选发布主体，再按请求键登记来源身份。
    @operation
    def register_source(self, request_key, source: SourceInput, *, run_id):
        self._run(run_id); source = SourceInput.model_validate(source)
        self._get("policies","policy_ref",source.policy_ref)
        if source.publisher_company_id:
            self.get_company(source.publisher_company_id)
        value = source.model_dump(mode="json")
        existing = self._existing("source",request_key,value)
        if existing:
            return existing
        identity = new_id("src")
        with self.database.transaction():
            self._insert("sources",dict(source_id=identity,publisher_company_id=source.publisher_company_id,
                policy_ref=source.policy_ref,payload=encoded(value)))
            self._register_key("source",request_key,value,identity)
        return identity

    # 按材料自然键登记资产；同一身份的初始元数据不一致时要求显式版本处理。
    @operation
    def register_asset(self, request_key, asset: AssetInput, *, run_id):
        self._run(run_id); asset = AssetInput.model_validate(asset); self._evidence(asset.evidence)
        material = self._get("material_types","name",asset.material_type)
        if json.loads(material["payload"])["asset_kind"] != asset.asset_kind:
            raise CatalogError("INVALID_ARGUMENT", "material type has a different asset kind")
        value = asset.model_dump(mode="json")
        existing = self._existing("asset",request_key,value)
        if existing:
            return existing
        same = self._db.execute("SELECT * FROM assets WHERE natural_key=?", (asset.natural_key,)).fetchone()
        if same and same["payload"] != encoded(value):
            raise CatalogError("IDENTITY_CONFLICT", "material identity differs; update version or register a distinct amendment")
        identity = same["asset_id"] if same else new_id("as")
        with self.database.transaction():
            if not same:
                self._insert("assets",dict(asset_id=identity,material_type=asset.material_type,asset_kind=asset.asset_kind,
                    title=asset.title,natural_key=asset.natural_key,status="registered",payload=encoded(value)))
                self._revision("asset",identity,"title",asset.title,"current","initial registration",asset.evidence,None,run_id)
            self._register_key("asset",request_key,value,identity)
        return identity

    # 记录带证据的材料间关系；重复关系证据必须一致，并禁止自身关联。
    @operation
    def relate_assets(self, from_asset_id, to_asset_id, *, kind, evidence, run_id):
        self._run(run_id); self._get("assets","asset_id",from_asset_id); self._get("assets","asset_id",to_asset_id)
        evidence = self._evidence(evidence)
        if kind not in {"amends","same_material_other_form","supplements"} or from_asset_id == to_asset_id:
            raise CatalogError("INVALID_ARGUMENT", "invalid material relation")
        raw = encoded(evidence.model_dump(mode="json"))
        row = self._db.execute("SELECT payload FROM asset_relations WHERE from_asset_id=? AND to_asset_id=? AND kind=?",
                               (from_asset_id,to_asset_id,kind)).fetchone()
        if row:
            if row[0] != raw:
                raise CatalogError("IDENTITY_CONFLICT", "existing material relation has different evidence")
            return
        with self.database.transaction():
            self._insert("asset_relations",dict(from_asset_id=from_asset_id,to_asset_id=to_asset_id,kind=kind,payload=raw,run_id=run_id))

    # 读取资产管理元数据及向外关系；是否可查询须通过已发布构建判断。
    @operation
    def get_asset(self, asset_id, *, view=None):
        """Administrative metadata; availability is exposed by list_published."""
        self._view(view)
        asset = self._get("assets","asset_id",asset_id)
        return asset | {"relations":[dict(row) for row in self._db.execute(
            "SELECT * FROM asset_relations WHERE from_asset_id=? ORDER BY to_asset_id,kind", (asset_id,))]}

    # 追加一条元数据修订记录，保留证据、原因、被替代版本及所属运行。
    def _revision(self, object_type, object_id, field, value, status, reason, evidence, supersedes, run_id):
        identity = new_id("rev")
        self._insert("metadata_revisions",dict(revision_id=identity,object_type=object_type,object_id=object_id,
            field=field,value_json=encoded(value),status=status,reason=reason,evidence_json=encoded(evidence.model_dump(mode="json")),
            supersedes_revision_id=supersedes,created_by_run_id=run_id))
        return identity

    # 记录候选/冲突或采纳修订；只有已确认依据且精确指向当前修订时才替换现值。
    @operation
    def record_revision(self, *, object_type, object_id, field, value, status, reason, evidence, supersedes_revision_id, run_id):
        self._run(run_id); nonblank(reason); nonblank(value); evidence = self._evidence(evidence)
        allowed = {("company","canonical_name"):("companies","company_id"), ("asset","title"):("assets","asset_id"),
                   ("asset","status"):("assets","asset_id")}
        if (object_type,field) not in allowed or status not in {"current","candidate","conflict","rejected"}:
            raise CatalogError("INVALID_ARGUMENT", "unsupported metadata revision")
        table,key = allowed[(object_type,field)]; self._get(table,key,object_id)
        if field == "status" and value != "retired":
            raise CatalogError("INVALID_ARGUMENT", "only explicit retirement is a metadata status edit")
        current = self._db.execute("SELECT revision_id FROM metadata_revisions WHERE object_type=? AND object_id=? AND field=? AND status='current'",
                                   (object_type,object_id,field)).fetchone()
        # 采纳新值必须精确替代当前 revision；候选、冲突和拒绝记录只追加历史，不改变主记录。
        if status == "current":
            if evidence.content_check != "confirmed" or supersedes_revision_id != (current[0] if current else None):
                raise CatalogError("IDENTITY_CONFLICT", "confirmed evidence and exact superseded revision required")
        elif supersedes_revision_id is not None:
            raise CatalogError("INVALID_ARGUMENT", "candidate/conflict must not supersede the current value")
        with self.database.transaction():
            if status == "current":
                if current:
                    self._db.execute("UPDATE metadata_revisions SET status='superseded',updated_at=? WHERE revision_id=?", (utc_now(),current[0]))
                self._db.execute(f"UPDATE {table} SET {field}=?,updated_at=? WHERE {key}=?", (value,utc_now(),object_id))
            identity = self._revision(object_type,object_id,field,value,status,reason,evidence,supersedes_revision_id,run_id)
        return identity

    # 按稳定顺序读取指定对象的全部元数据修订，保留历史状态。
    @operation
    def revisions(self, object_type, object_id, *, view=None):
        self._view(view)
        return [dict(row) for row in self._db.execute("SELECT * FROM metadata_revisions WHERE object_type=? AND object_id=? ORDER BY created_at,revision_id", (object_type,object_id))]

    # 登记 collecting 快照并冻结当时的资产/来源元数据，同时保存采集时间及来源时间边界。
    @operation
    def begin_snapshot(self, request_key, *, asset_id, acquisition: Acquisition, completeness,
                       version_consistency, revision_of_snapshot_id, revision_basis, run_id):
        self._run(run_id); asset = self._get("assets","asset_id",asset_id)
        if asset["status"] == "retired":
            raise CatalogError("INVALID_STATE", "retired material cannot acquire new snapshots")
        acquisition = Acquisition.model_validate(acquisition)
        source = self._get("sources","source_id",acquisition.source_id)
        if completeness not in {"complete","partial","unknown"} or version_consistency not in {"consistent","inconsistent","unknown"}:
            raise CatalogError("INVALID_ARGUMENT", "invalid snapshot completeness/consistency")
        if (revision_of_snapshot_id is None) != (revision_basis is None):
            raise CatalogError("INVALID_ARGUMENT", "snapshot revision requires both previous snapshot and basis")
        if revision_of_snapshot_id is not None:
            previous = self.get_snapshot(revision_of_snapshot_id)
            if previous["asset_id"] != asset_id or previous["status"] != "frozen":
                raise CatalogError("IDENTITY_CONFLICT", "snapshot revision must refer to a frozen version of the same asset")
            nonblank(revision_basis)
        value = dict(asset_id=asset_id,acquisition=acquisition.model_dump(mode="json"),completeness=completeness,
                     version_consistency=version_consistency,revision_of_snapshot_id=revision_of_snapshot_id,revision_basis=revision_basis)
        existing = self._existing("snapshot",request_key,value)
        if existing:
            return existing
        identity, record_id = new_id("sn"),new_id("sr")
        # Freeze current metadata into the collecting version; later metadata
        # revisions cannot retroactively alter the source/identity of this input.
        payload = value | dict(source_record_id=record_id,asset_metadata=asset,source_metadata=source)
        # 把来源时间按原精度转成上下界；未知时间保持 None，供截止日判断识别不确定性。
        times = {}
        for name in ("published_at","available_at","source_revised_at"):
            field = getattr(acquisition,name)
            low,high = field.value.bounds() if field.value else (None,None)
            times.update({name+"_value":field.value.value if field.value else None,
                          name+"_precision":field.value.precision if field.value else None,
                          name+"_lower_utc":low,name+"_upper_utc":high})
        with self.database.transaction():
            self._insert("asset_snapshots",dict(snapshot_id=identity,asset_id=asset_id,source_id=acquisition.source_id,
                run_id=run_id,status="collecting",revision_of_snapshot_id=revision_of_snapshot_id,payload=encoded(payload)))
            self._insert("source_records",dict(record_id=record_id,source_id=acquisition.source_id,asset_id=asset_id,
                snapshot_id=identity,run_id=run_id,acquired_at=acquisition.acquired_at,payload=acquisition.canonical_bytes().decode(),**times))
            self._register_key("snapshot",request_key,value,identity)
        return identity

    # 读取快照状态与登记数据，可选校验调用方的目录视图。
    @operation
    def get_snapshot(self, snapshot_id, *, view=None):
        self._view(view)
        return self._get("asset_snapshots","snapshot_id",snapshot_id)

    # 只有尚未封存清单的 collecting 快照可以补充输入和主体关系。
    def _collecting(self, snapshot_id):
        snapshot = self.get_snapshot(snapshot_id)
        if snapshot["status"] != "collecting" or snapshot["manifest_ref"] is not None:
            raise CatalogError("INVALID_STATE", "snapshot inputs already sealed or terminal")
        return snapshot

    # 核验输入清单及原件后，将指定格式表示登记到仍可变的快照中。
    @operation
    def add_representation(self, request_key, *, snapshot_id, format, input_manifest):
        self._collecting(snapshot_id)
        input_manifest = ObjectRef.model_validate(input_manifest)
        self.content.read_manifest(input_manifest)
        value = dict(snapshot_id=snapshot_id,format=format,input_manifest=input_manifest.model_dump())
        existing = self._existing("representation",request_key,value)
        if existing:
            return existing
        identity = new_id("rp")
        Representation(representation_id=identity,format=format,input_manifest=input_manifest)
        with self.database.transaction():
            self._insert("snapshot_representations",dict(representation_id=identity,snapshot_id=snapshot_id,format=format,
                input_ref=input_manifest.model_dump_json()))
            self._register_key("representation",request_key,value,identity)
        return identity

    # 为快照登记带证据的公司角色；确认关系必须指向已确认公司，重复内容不得冲突。
    @operation
    def relate_snapshot(self, snapshot_id, relation: SnapshotRelation):
        self._collecting(snapshot_id); relation = SnapshotRelation.model_validate(relation)
        company = self.get_company(relation.company_id); self._evidence(relation.evidence)
        if relation.status == "confirmed" and company["status"] != "confirmed":
            raise CatalogError("INVALID_STATE", "pending company cannot become a confirmed snapshot relation")
        raw = relation.canonical_bytes().decode()
        row = self._db.execute("SELECT payload FROM snapshot_company_relations WHERE snapshot_id=? AND company_id=? AND role=?",
                               (snapshot_id,relation.company_id,relation.role)).fetchone()
        if row:
            if row[0] != raw:
                raise CatalogError("IDENTITY_CONFLICT", "existing snapshot relation has different evidence")
            return
        with self.database.transaction():
            self._insert("snapshot_company_relations",dict(snapshot_id=snapshot_id,company_id=relation.company_id,
                role=relation.role,payload=raw))

    # 返回稳定排序的快照主体关系，用于封存和后续完整性复核。
    @operation
    def snapshot_relations(self, snapshot_id, *, view=None):
        self._view(view); self.get_snapshot(snapshot_id)
        return [json.loads(row[0]) for row in self._db.execute(
            "SELECT payload FROM snapshot_company_relations WHERE snapshot_id=? ORDER BY company_id,role", (snapshot_id,))]

    # 委托发布层封存快照，统一执行文件验证、移动和数据库确认。
    @operation
    def freeze_snapshot(self, snapshot_id):
        from ..content.publication import Publication
        return Publication(self).freeze_snapshot(snapshot_id)

    # 只读取 frozen 快照，并在返回前重新核验封存文件与登记输入的一致性。
    @operation
    def read_snapshot(self, snapshot_id):
        from ..content.publication import Publication
        snapshot = self.get_snapshot(snapshot_id)
        if snapshot["status"] != "frozen":
            raise CatalogError("INVALID_STATE", "snapshot is not frozen")
        return Publication(self).verify_snapshot(snapshot_id)

    # 为已冻结表示和确定配方登记构建；相同构建键复用有效尝试，失败重试须显式关联原尝试。
    @operation
    def begin_build(self, *, snapshot_id, representation_id, recipe: BuildRecipe, run_id, retry_of_build_id=None):
        self._run(run_id); snapshot = self.get_snapshot(snapshot_id)
        self.read_snapshot(snapshot_id)
        representation = self._get("snapshot_representations","representation_id",representation_id)
        if representation["snapshot_id"] != snapshot_id:
            raise CatalogError("IDENTITY_CONFLICT", "representation belongs to another snapshot")
        recipe = BuildRecipe.model_validate(recipe)
        config_raw = self.content.read_object(recipe.config)
        config = json.loads(config_raw)
        if not isinstance(config,dict) or canonical(config) != config_raw:
            raise CatalogError("INVALID_ARGUMENT", "processor configuration must be canonical JSON object")
        if not {"capabilities","targets","rules","models"} <= config.keys():
            raise CatalogError("INVALID_ARGUMENT", "configuration must explicitly cover capabilities, targets, rules and models")
        identity = new_id("bd")
        ref = AssetRef(asset_id=snapshot["asset_id"],snapshot_id=snapshot_id,representation_id=representation_id,build_id=identity)
        input_ref = ObjectRef.model_validate_json(representation["input_ref"])
        key = recipe.build_key(ref,input_ref)
        # 构建键绑定输入与配方：已有进行中/已发布构建直接复用，失败记录不能自动开启新尝试。
        active = self._db.execute("SELECT * FROM asset_builds WHERE build_key=? AND status IN ('staging','published')", (key,)).fetchone()
        if active:
            return dict(active)
        failures = self._db.execute("SELECT build_id FROM asset_builds WHERE build_key=? AND status='failed'", (key,)).fetchall()
        # 显式重试必须引用同构建键的失败尝试，并继承原 root_run_id，保留运行归属。
        if failures or retry_of_build_id is not None:
            if retry_of_build_id not in {row[0] for row in failures}:
                raise CatalogError("INVALID_STATE", "failed build requires an explicit matching retry_of_build_id")
            failed = self.get_build(retry_of_build_id)
            if self._get("runs","run_id",failed["run_id"])["root_run_id"] != self._run(run_id)["root_run_id"]:
                raise CatalogError("IDENTITY_CONFLICT", "retry must inherit the original root run")
        with self.database.transaction():
            self._insert("asset_builds",dict(build_id=identity,asset_id=ref.asset_id,snapshot_id=snapshot_id,representation_id=representation_id,
                input_ref=input_ref.model_dump_json(),recipe=recipe.canonical_bytes().decode(),build_key=key,job_id=new_id("job"),
                run_id=run_id,retry_of_build_id=retry_of_build_id,status="staging"))
        return self.get_build(identity)

    # 读取构建记录和状态，可选校验目录视图。
    @operation
    def get_build(self, build_id, *, view=None):
        self._view(view)
        return self._get("asset_builds","build_id",build_id)

    # 从构建记录提取 asset/snapshot/representation/build 四级版本引用。
    @staticmethod
    def asset_ref(build):
        return AssetRef(**{key:build[key] for key in ("asset_id","snapshot_id","representation_id","build_id")})

    # 将未发布构建记为失败并保留错误码；published 不可降级，已失败记录直接复用。
    @operation
    def fail_build(self, build_id, *, failure_code):
        nonblank(failure_code)
        build = self.get_build(build_id)
        if build["status"] == "published":
            raise CatalogError("INVALID_STATE", "published build is immutable")
        if build["status"] == "failed":
            return build
        with self.database.transaction():
            self._db.execute("UPDATE asset_builds SET status='failed',failure_code=?,updated_at=? WHERE build_id=?",
                             (failure_code,utc_now(),build_id))
        return self.get_build(build_id)

    # 检查四级引用属于同一构建且状态已发布，再验证最终产物。
    @operation
    def read_published(self, reference: AssetRef, *, view=None):
        self._view(view); reference = AssetRef.model_validate(reference)
        build = self.get_build(reference.build_id)
        if self.asset_ref(build) != reference:
            raise CatalogError("IDENTITY_CONFLICT", "asset reference components do not belong together")
        if build["status"] != "published":
            raise CatalogError("INVALID_STATE", "build has not been published")
        from ..content.publication import Publication
        return Publication(self).verify_build(build, final=True)

    # 只读取冻结清单中的文件；在整体验证后再次校验本次读取字节的哈希和长度。
    @operation
    def read_artifact(self, reference: AssetRef, path: str):
        manifest = self.read_published(reference)
        reference = manifest.asset_ref
        item = next((item for item in manifest.files if item.path==path),None)
        if item is None:
            raise CatalogError("NOT_FOUND", "artifact is not in the frozen manifest")
        from .database import read_regular
        raw = read_regular(self.root / "assets" / reference.asset_id / "builds" / reference.build_id / path)
        if len(raw) != item.object_ref.byte_length or digest(raw) != item.object_ref.sha256:
            raise CatalogError("PUBLICATION_INVALID", "artifact changed during read")
        return raw

    # 按资产/快照/表示分组列出最新已发布构建，过滤退役资产并核验返回的每个版本。
    @operation
    def list_published(self, *, view=None):
        """Small deterministic catalog view, not search or pagination."""
        self._view(view)
        groups = {}
        rows = self._db.execute("""SELECT b.* FROM asset_builds b
            JOIN asset_snapshots s USING(snapshot_id) JOIN assets a ON a.asset_id=b.asset_id
            WHERE b.status='published' AND s.status='frozen' AND a.status!='retired'
            ORDER BY b.asset_id,b.snapshot_id,b.representation_id,b.published_at DESC,b.build_id DESC""").fetchall()
        for row in rows:
            key = (row["asset_id"],row["snapshot_id"],row["representation_id"])
            groups.setdefault(key,[]).append(dict(row))
        items = []
        for versions in groups.values():
            reference = self.asset_ref(versions[0])
            self.read_published(reference)
            items.append(dict(asset_ref=reference.model_dump(),other_builds=len(versions)-1))
        return dict(view=self.view().model_dump(),items=items)

    # 显式收敛中断状态，恢复前后均审计不可变产物，返回实际处理结果。
    @operation
    def recover(self):
        from ..content.recovery import audit_catalog, recover_catalog
        audit_catalog(self)
        result = recover_catalog(self)
        audit_catalog(self)
        return result
