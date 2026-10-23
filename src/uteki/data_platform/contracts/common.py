"""Small, strict shared storage contracts; no agent or provider dependencies."""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import secrets
import time
from typing import Annotated, Literal
import unicodedata

from pydantic import BaseModel, ConfigDict, Field, AfterValidator, create_model, model_validator


# 存储契约的共同基类：禁止额外字段与隐式类型转换，实例冻结，并在再次使用时重新校验。
class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, revalidate_instances="always")

    # 先重新校验实例，再按 JSON 模式序列化；得到可用于内容寻址和一致性比较的 UTF-8 字节。
    def canonical_bytes(self) -> bytes:
        return canonical(type(self).model_validate(self).model_dump(mode="json"))


# 固定键顺序、空白和编码，拒绝 NaN，避免同一数据因普通 JSON 格式差异产生不同摘要。
def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


# 只计算传入字节的 SHA-256；摘要本身不证明这些字节对应的业务事实正确。
def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


# 保留原文本，不自动 strip；仅拒绝空白文本、控制字符与代理码位。
def nonblank(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or any(unicodedata.category(c) in {"Cc", "Cs"} for c in value):
        raise ValueError("nonblank UTF-8 text without control characters required")
    return value


Text = Annotated[str, AfterValidator(nonblank)]


# 为不同实体生成带类型前缀的 ID 约束，避免混用公司、快照或构建标识。
def id_type(prefix: str):
    return Annotated[str, Field(pattern=rf"^{prefix}_[0-7][0-9A-HJKMNP-TV-Z]{{25}}$", min_length=len(prefix)+27, max_length=len(prefix)+27)]


# 以毫秒时间戳和随机数生成带前缀的 ULID；同一毫秒内不承诺生成顺序。
def new_id(prefix: str) -> str:
    """ULID binary layout, encoded in Crockford base32; not monotonic within ms."""
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    stamp = time.time_ns() // 1_000_000
    if not 0 <= stamp < 2**48:
        raise ValueError("clock outside ULID timestamp range")
    value = (stamp << 80) | secrets.randbits(80)
    return prefix + "_" + "".join(alphabet[(value >> shift) & 31] for shift in range(125, -1, -5))


# 返回显式带 UTC 时区的 ISO 时间，供记录创建和提交时间使用。
def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# 保留来源时间及其精度；日期或月份不擅自补成某一个确定时刻。
class TemporalValue(Contract):
    value: Text
    precision: Literal["datetime", "date", "month"]

    # 在契约创建时即验证时间可解析、可归一化，溢出统一变成输入校验错误。
    @model_validator(mode="after")
    def valid_time(self):
        try:
            self.bounds()
        except OverflowError as error:
            raise ValueError("time interval exceeds supported UTC range") from error
        return self

    # 返回可能时间的 UTC 上下界；精确时间是一个点，粗粒度时间保留时区不确定性。
    def bounds(self) -> tuple[str, str]:
        if self.precision == "datetime":
            parsed = datetime.fromisoformat(self.value)
            if parsed.tzinfo is None or "T" not in self.value:
                raise ValueError("datetime must have an explicit timezone")
            lower = upper = parsed.astimezone(timezone.utc)
        else:
            if self.precision == "month":
                if len(self.value) != 7:
                    raise ValueError("month must be YYYY-MM")
                start = date.fromisoformat(self.value + "-01")
                end = date(start.year, start.month, calendar.monthrange(start.year, start.month)[1]) + timedelta(days=1)
            else:
                if len(self.value) != 10:
                    raise ValueError("date must be YYYY-MM-DD")
                start = date.fromisoformat(self.value)
                end = start + timedelta(days=1)
            # 粗粒度日期覆盖从 UTC+14 当日零点到 UTC-12 下一周期零点的可能范围；
            # 历史截止检查因此不能把未知来源时区当成已知。
            lower = datetime.combine(start, datetime.min.time(), timezone(timedelta(hours=14))).astimezone(timezone.utc)
            upper = datetime.combine(end, datetime.min.time(), timezone(timedelta(hours=-12))).astimezone(timezone.utc)
        return lower.isoformat(), upper.isoformat()


# 区分已知来源时间和未知原因；已知时间必须附说明依据，不能同时标为未知。
class SourceTime(Contract):
    value: TemporalValue | None
    basis: Text | None
    unknown_reason: Literal["not_disclosed_by_source", "not_processed", "not_applicable", "conflict"] | None

    # 保证“有值且有依据”和“无值且有原因”两类状态的必要字段一致。
    @model_validator(mode="after")
    def explained(self):
        if self.value is None:
            if self.unknown_reason is None:
                raise ValueError("unknown time requires an explicit reason")
        elif self.basis is None or self.unknown_reason is not None:
            raise ValueError("known time requires basis and no unknown reason")
        return self


# 显式保存财年、季度与起止日期及其依据，不根据标签推造缺失日期。
class FiscalPeriod(Contract):
    label: Text | None
    fiscal_year: Annotated[int, Field(ge=1, le=9999)] | None
    fiscal_quarter: Annotated[int, Field(ge=1, le=4)] | None
    start: date | None
    end: date | None
    basis: Literal["source", "derived_from_fiscal_year_end", "unknown"]

    # 只检查已提供的起止日期顺序；未提供的期间边界仍保留为空。
    @model_validator(mode="after")
    def interval(self):
        if self.start and self.end and self.end < self.start:
            raise ValueError("fiscal period end precedes start")
        return self


# 目录视图身份：目录 ID、修订号和 token 共同描述调用方观察到的版本。
class CatalogView(Contract):
    catalog_id: id_type("cat")
    revision: Annotated[int, Field(ge=0)]
    token: id_type("rev")


# 携带稳定业务错误码的异常，供上层区分范围、版本、就绪与恢复问题。
class CatalogError(ValueError):
    # 保留机器可读 code，同时将 code 与详情组合成人可读异常消息。
    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(f"{code}: {detail}")


# 从规范契约选取字段生成面向模型的投影，复用默认值与说明，不宣传不可用的选项。
def project(name, source, fields, **overrides):
    selected = {key: (source.model_fields[key].annotation, source.model_fields[key]) for key in fields}
    return create_model(name, __base__=Contract, **(selected | overrides))
