"""Bounded model -> validated plan -> local tools -> model loop.

The planner is injected. The host owns company scope, time, candidate access,
snapshot and result values. No source acquisition, adoption or arbitrary SQL.
"""
import asyncio
import copy
import json
from pathlib import Path

from pydantic import ValidationError

from uteki.domain.research_data.agent_query import AGENT_VERSION, AgentQuery, PlannerDecision
from uteki.domain.research_data.scoped_agent_query import (
    SCOPED_AGENT_VERSION, ScopedAgentQuery, ScopedPlannerDecision,
)
from uteki.domain.research_data.query_contract import DataQuery
from uteki.domain.research_data.evidence_package import EvidencePackage
from uteki.domain.research_data.period_scope import PERIOD_SCOPE_VERSION, explicit_periods, validate_plan_periods
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.evidence_packaging import build_evidence_package


from .prompts import PLANNER_PROMPT, SCOPED_PLANNER_PROMPT, TASK_PLANNER_PROMPT, TASK_PROPOSAL_PROMPT
from .artifacts import write_new


class DataQueryAgent:
    def __init__(self, port, planner, *, max_steps=4, max_packet_bytes=180000, turn_timeout=90):
        if not 1 <= max_steps <= 12 or not 1000 <= max_packet_bytes <= 400000 or not 0 < turn_timeout <= 180:
            raise ValueError("invalid agent execution limits")
        self.port, self.planner = port, planner
        self.max_steps, self.max_packet_bytes, self.turn_timeout = max_steps, max_packet_bytes, turn_timeout

    async def run(self, request, *, output: Path):
        """Legacy v0.2 entry point for existing callers and saved canaries."""
        request = AgentQuery.model_validate(request)
        return await self._run(request, output=output)

    async def run_scoped(self, request, *, output: Path):
        """Validate exact source scope before creating artifacts or asking a model."""
        request = ScopedAgentQuery.model_validate(request)
        port = self.port.scoped(request.scope)
        return await self._run(request, output=output, scoped_port=port)

    async def run_tasks(self, plan, *, output: Path):
        """Execute an explicit task plan using the injected planner and host checks."""
        from uteki.agents.data_query.loop import run_task_loop
        return await run_task_loop(self, plan, output=output)

    async def run_question(self, request, *, output: Path):
        """Natural-language question plus selected scope, without a caller-written plan."""
        from uteki.agents.data_query.loop import run_question_loop
        return await run_question_loop(self, request, output=output)

    async def _run(self, request, *, output: Path, scoped_port=None):
        scoped = scoped_port is not None
        port = scoped_port if scoped else self.port
        scope = request.scope if scoped else request
        version = SCOPED_AGENT_VERSION if scoped else AGENT_VERSION
        decision_type = ScopedPlannerDecision if scoped else PlannerDecision
        if scope.snapshot_id != port.snapshot_id:
            raise ValueError("snapshot mismatch")
        if scope.source_policy_id != port.manifest["source_policy_id"]:
            raise ValueError("source policy mismatch")
        output = Path(output)
        if output.resolve().is_relative_to(port.dataset):
            raise ValueError("agent outputs must be outside the immutable dataset")
        output.mkdir(parents=True, exist_ok=False)
        write_new(output / "request.json", request.model_dump(mode="json"))
        schema = port.get_schema()
        companies = set(scope.company_ids)
        entities = {e["entity_id"]: e for e in schema["entities"] if e["company_id"] in companies}
        discovery = port.discover_data() if scoped else port.discover_data(
            knowledge_cutoff=str(scope.knowledge_cutoff), include_candidates=scope.include_candidates)
        sources = [s for s in discovery["sources"] if s["company_id"] in companies]
        visible_ids = {s["source_snapshot_id"] for s in sources}
        allowed_periods = explicit_periods(request.question)
        period_scope = {"version": PERIOD_SCOPE_VERSION,
                        "periods": [p.model_dump(mode="json") for p in allowed_periods],
                        "basis": "Literal question text only; calendar years/quarters or typed explicit date ranges. Source dates must satisfy the dataset protocol. Other syntax requires clarification."}
        catalog = {"entities": list(entities.values()), "metrics": schema["metrics"],
                   "period_scope": period_scope,
                   "plan_schema": decision_type.model_json_schema(), "sources": sources,
                   "coverage": [c for c in discovery["coverage"] if c["entity_id"] in entities],
                   "capabilities": schema["capabilities"], "unsupported": schema["unsupported"],
                   "notes": schema["notes"], "limits": discovery["limits"]}
        if scoped:
            catalog.update({"scope": scope.model_dump(mode="json"), "scope_id": port.scope_id,
                            "execution_contracts": schema["execution_contracts"],
                            "source_gaps": discovery["gaps"]})
        write_new(output / "catalog.json", catalog)
        trace, history = [], []
        records, computed, contexts, evidence, gaps = {}, {}, {}, {}, {}
        navigation = []

        def finish(status, parts=(), clarification=None, error=None):
            result = {"agent_schema_version": version, "status": status,
                      "request": request.model_dump(mode="json"), "answer_parts": list(parts),
                      "records": list(records.values()), "computed_facts": list(computed.values()),
                      "contexts": list(contexts.values()), "evidence": evidence, "gaps": list(gaps.values()),
                      "clarification": clarification, "error": error, "trace": trace,
                      "period_scope": period_scope,
                      "completion_scope": "Planner-declared question coverage; host validates references/scope, not semantic completeness.",
                      "candidate_data": scope.include_candidates}
            if scoped:
                result.update({"execution_schema_version": scope.execution_schema_version,
                               "scope_id": port.scope_id, "navigation": navigation})
                package = build_evidence_package(port, result)
                write_new(output / "evidence-package.json", package)
                write_new(output / "evidence-package.schema.json", EvidencePackage.model_json_schema())
                result["evidence_package"] = {"schema_version": package["schema_version"],
                    "bundle_id": package["bundle_id"], "path": "evidence-package.json"}
            write_new(output / "result.json", result)
            write_new(output / "manifest.json", {"files": {str(p.relative_to(output)): digest(p.read_bytes())
                      for p in sorted(output.rglob("*")) if p.is_file()}, "agent_schema_version": version})
            return result

        known_companies = {e["company_id"] for e in entities.values()}
        if companies - known_companies:
            return finish("unanswerable", error="company_scope_unavailable")

        def add_context(value):
            cid = "ctx-" + digest([value["source_snapshot_id"], value.get("block_ids"), value.get("blocks")])[:24]
            contexts[cid] = {"context_id": cid, **value}
            return contexts[cid]

        def add_gaps(value):
            for gap in value.get("gaps", []):
                gid = "gap-" + digest(gap)[:24]
                gap["gap_id"] = gid
                gaps[gid] = gap

        for step in range(1, self.max_steps + 1):
            packet = {"request": request.model_dump(mode="json"), "catalog": catalog, "history": history,
                      "steps_remaining": self.max_steps - step + 1}
            if len(json.dumps(packet, ensure_ascii=False).encode()) > self.max_packet_bytes:
                return finish("limited", error="context_budget_exceeded; narrow the research question")
            write_new(output / f"turn-{step:02d}/input.json", packet)
            try:
                raw = await asyncio.wait_for(self.planner.decide(copy.deepcopy(packet)), timeout=self.turn_timeout)
                decision = decision_type.model_validate(raw)
            except ValidationError as error:
                feedback = {"status": "invalid_plan", "errors": error.errors(include_url=False, include_input=False, include_context=False)}
                history.append({"tool": "validate_decision", "result": feedback})
                trace.append({"step": step, "tool": "validate_decision", **feedback})
                write_new(output / f"turn-{step:02d}/feedback.json", feedback)
                continue
            except Exception as error:
                # Provider messages may contain sensitive headers or inputs.
                return finish("failed", error=type(error).__name__)
            action = decision.model_dump(mode="json")
            write_new(output / f"turn-{step:02d}/decision.json", action)
            try:
                if decision.action == "clarify":
                    trace.append({"step": step, "tool": "clarify"})
                    return finish("needs_clarification", clarification=decision.clarification)
                if decision.action == "finish":
                    for part in decision.answer_parts:
                        for ids, available in ((part.record_ids, records), (part.computed_ids, computed),
                                               (part.context_ids, contexts), (part.gap_ids, gaps)):
                            if any(ref not in available for ref in ids):
                                raise ValueError("finish references an ID not returned by tools")
                    # Retain observed gaps conservatively, even after follow-up reads.
                    # Semantic resolution of an earlier gap is a later capability.
                    has_data = bool(records or computed or contexts)
                    status = "partial" if gaps and has_data else "unanswerable" if gaps else "answered"
                    trace.append({"step": step, "tool": "finish"})
                    return finish(status, [p.model_dump(mode="json") for p in decision.answer_parts])
                if decision.action == "query":
                    plan = decision.plan
                    if any(r.entity_id not in entities for r in (*plan.records, *plan.calculations)):
                        raise ValueError("entity is outside the request company scope or catalog")
                    if any(d.company_id not in companies for d in plan.documents):
                        raise ValueError("document company is outside the request scope")
                    if not allowed_periods:
                        trace.append({"step": step, "tool": "scope_guard", "reason": "explicit_period_required"})
                        return finish("needs_clarification", clarification="请明确查询期间（年份或年份 + 季度）；当前不能从数据覆盖猜测期间。 Please specify an explicit year or year and quarter.")
                    validate_plan_periods(plan, allowed_periods)
                    query = DataQuery(query_id=f"agent-step-{step}", question=request.question,
                                      snapshot_id=scope.snapshot_id, source_policy_id=scope.source_policy_id,
                                      knowledge_cutoff=scope.knowledge_cutoff, include_candidates=scope.include_candidates,
                                      **plan.model_dump())
                    value = port.query_data(query)
                    records.update({r["record_id"]: r for r in value["records"]})
                    computed.update({c["computed_id"]: c for c in value["computed_facts"]})
                    evidence.update(value["evidence"])
                    value["contexts"] = [add_context(c) for d in value["documents"] for c in d["contexts"]
                                         if not scoped or (c.get("status") == "read" and c.get("blocks"))]
                    add_gaps(value)
                elif scoped and decision.action in ("outline_source", "read_source", "search_source"):
                    payload = {"outline_source": decision.outline, "read_source": decision.read,
                               "search_source": decision.search}[decision.action]
                    value = getattr(port, decision.action)(payload)
                    add_gaps(value)
                    if decision.action == "read_source" and value.get("blocks"):
                        value = add_context(value)
                    elif decision.action != "read_source":
                        navigation.append({"tool": decision.action, **value})
                elif scoped:
                    context = decision.context
                    value = port.read_context(**context.model_dump())
                    add_gaps(value)
                    if value.get("blocks"):
                        value = add_context(value)
                else:
                    context = decision.context
                    if context.source_snapshot_id not in visible_ids:
                        raise ValueError("source outside company scope or unavailable at cutoff")
                    grounded_sources = {r["source_snapshot_id"] for r in records.values()}
                    grounded_sources.update(s["source_snapshot_id"] for s in sources
                                            if s["period_end"] in {str(p.end) for p in allowed_periods})
                    if context.source_snapshot_id not in grounded_sources:
                        raise ValueError("context source has no grounded reporting period or retrieved record")
                    value = port.read_context(**context.model_dump(), snapshot_id=scope.snapshot_id,
                            knowledge_cutoff=str(scope.knowledge_cutoff), include_candidates=scope.include_candidates)
                    value = add_context(value)
                write_new(output / f"turn-{step:02d}/tool-result.json", value)
                history.append({"action": action, "result": value})
                trace.append({"step": step, "tool": decision.action, "result_file": f"turn-{step:02d}/tool-result.json"})
            except (ValueError, KeyError, PermissionError) as error:
                message = str(error) if isinstance(error, ValueError) else type(error).__name__
                feedback = {"status": "invalid_plan", "message": message}
                history.append({"action": action, "result": feedback})
                trace.append({"step": step, "tool": decision.action, **feedback})
                write_new(output / f"turn-{step:02d}/feedback.json", feedback)
            except Exception as error:
                return finish("failed", error=type(error).__name__)
        return finish("limited", error="max_steps_reached")
