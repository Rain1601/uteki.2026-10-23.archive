"""One metered, synthetic envelope request; never executes a returned action."""
import asyncio
import json
from pathlib import Path

from agents import AgentOutputSchema, ModelSettings
from uteki.agents.data_query.autonomous import AutonomousDecision
from uteki.agents.data_query.artifacts import write_new
from uteki.agents.runtime.claude_messages import ClaudeMessagesModel
from uteki.agents.runtime.local_credentials import load_provider_key
from uteki.agents.runtime.run_budget import RunBudget
from uteki.agents.runtime.call_costs import MeteredModel, pricing_snapshot
from uteki.infrastructure.research_data.financial_records import digest


async def main():
    parent=Path(__file__).resolve().parent
    output=parent/'envelope'
    output.mkdir(exist_ok=False)
    repository=parent.parents[3]
    load_provider_key(repository,'aihubmix')
    budget=RunBudget(parent.parent/'costs.sqlite',None,enforce=False,allow_unknown_reservations=True)
    native=ClaudeMessagesModel('claude-sonnet-5-5',timeout_seconds=180,reasoning_effort='high',
        thinking_type='between_tools',schema_protocol='native_decision_envelope')
    metered=MeteredModel(native,output/'calls','native_decision_envelope_probe','aihubmix','claude-sonnet-5-5',
        pricing_snapshot('aihubmix','claude-sonnet-5-5'),budget)
    kwargs=dict(system_instructions='Choose one host action from the task, using the required native envelope.',
        input='This is a synthetic compatibility test. Inspect the source catalog next: action discover_catalog, catalog kind sources. There are no requirements yet. Do not execute tools.',
        model_settings=ModelSettings(max_tokens=1024),tools=[],handoffs=[],
        output_schema=AgentOutputSchema(AutonomousDecision,strict_json_schema=False))
    write_new(output/'request.json',json.loads(native.request_body(**kwargs)))
    write_new(output/'configuration.json',native.request_configuration(**kwargs))
    result={'status':'started','model':'claude-sonnet-5-5','schema_protocol':'native_decision_envelope',
            'hidden_thinking_saved':False,'returned_action_executed':False}
    try:
        response=await metered.get_response(**kwargs)
        text=response.output[0].content[0].text
        decision=AutonomousDecision.model_validate_json(text)
        write_new(output/'host-decision.json',json.loads(text))
        result.update(status='validated',action=decision.action)
    except Exception as error:
        result.update(status='failed',error_type=type(error).__name__)
    finally:
        await native.aclose()
        write_new(output/'visible-wire-response.json',{'text':native.response_text})
        write_new(output/'response-metadata.json',native.response_metadata)
        write_new(output/'result.json',result)
        write_new(output/'manifest.json',{'files':{str(p.relative_to(output)):digest(p.read_bytes())
            for p in sorted(output.rglob('*')) if p.is_file()}})
        print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':asyncio.run(main())
