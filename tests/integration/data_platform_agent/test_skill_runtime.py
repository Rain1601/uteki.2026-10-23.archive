"""Production Skill wiring through real SDKs and synthetic peers; no paid calls."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch

from uteki.data_platform.agent.openai_runtime import run_offline
from uteki.data_platform.agent.profiles import load_profile
from uteki.data_platform.agent.skill_runtime import RuntimeSkills
from uteki.data_platform.agent.skills import get_skill
from uteki.data_platform.agent.binding import ENVELOPES
from uteki.data_platform.application.runtime import RuntimeJournal
from uteki.data_platform.application.execution_clock import ObservedWorker
from uteki.data_platform.application.session import Session
from uteki.data_platform.catalog import Catalog
from uteki.data_platform.contracts.common import CatalogError
from uteki.data_platform.service import DataService

ROOT=Path(__file__).resolve().parents[3]
CONFIG=ROOT/'config/data_platform'
F=runpy.run_path(str(ROOT/'tests/fixtures/data_platform/sdk_fixture.py'))
N=runpy.run_path(str(Path(__file__).with_name('test_native_claude.py')))
DESCRIPTION=next(line.removeprefix('description: ') for line in
    (CONFIG/'skills/financial-data-query/SKILL.md').read_text().splitlines() if line.startswith('description: '))


def profile(sdk,*,config=CONFIG,skills=True):
    variant='fixture-skill-query' if skills else 'fixture-query'
    return load_profile(config/f'model-profiles/{sdk}/{variant}/query.json',config_root=config,
        kernel=sdk,model_id=f'fixture/{sdk}-'+('skill-' if skills else '')+'query-v1',role='query')


class SkillRuntimeTests(unittest.TestCase):
    def case(self):
        c=F['case']();self.addCleanup(c.doCleanups);return c

    def test_openai_discovery_loading_and_business_delivery(self):
        c=self.case();model=F['SkillScriptedModel']()
        result=asyncio.run(run_offline(c.service,c.context,profile('openai'),model=model,limits=F['runtime_limits']()))
        self.assertEqual(result['status'],'completed',result['error'])
        native=Session(c.catalog,c.context).data['native_execution']
        self.assertEqual(len(native['tool_calls']),8)
        self.assertEqual(len(native['skill_tool_calls']),2)
        self.assertEqual(len(model.inputs),10)
        self.assertIn(DESCRIPTION,model.inputs[0]['system'])
        self.assertIn('load_skill',model.inputs[0]['tools'])
        frozen=RuntimeSkills(profile('openai'),self.journal(c),available_tools=ENVELOPES)
        body=frozen.bundles[0].content.split('---',2)[2].strip()
        self.assertNotIn(body,json.dumps(model.inputs[0],ensure_ascii=False))
        self.assertIn(body,next(i['output'] for i in model.inputs[2]['input']
            if i.get('type')=='function_call_output' and i['call_id']=='skill-read'))
        self.assertEqual(result['delivery']['delivery']['calculations'][0]['value'],'-2.250000000000000000')

    def test_openai_explicit_workspace_reads_body_and_completes_business(self):
        for absolute_file in (False,True):
            with self.subTest(absolute_file=absolute_file):
                c=self.case()
                work=c.root/'runs'/Session(c.catalog,c.context).data['context']['run_id']/'skill-runtime/workspace'
                class ExplicitWorkspaceModel(F['SkillScriptedModel']):
                    async def get_response(self,*args,**kwargs):
                        result=await super().get_response(*args,**kwargs)
                        call=result.output[0]
                        if call.name=='exec_command':
                            values=json.loads(call.arguments)
                            values['workdir']=str(work)
                            if absolute_file:values['cmd']='cat '+str(work/'.agents/financial-data-query/SKILL.md')
                            call.arguments=json.dumps(values)
                        return result
                model=ExplicitWorkspaceModel()
                result=asyncio.run(run_offline(c.service,c.context,profile('openai'),model=model,limits=F['runtime_limits']()))
                self.assertEqual(result['status'],'completed',result['error'])
                native=Session(c.catalog,c.context).data['native_execution']
                read=native['skill_tool_calls']['skill-read']['output']
                frozen=RuntimeSkills(profile('openai'),self.journal(c),available_tools=ENVELOPES)
                self.assertIn(frozen.bundles[0].content,read)
                self.assertIn(frozen.bundles[0].content,next(i['output'] for i in model.inputs[2]['input']
                    if i.get('type')=='function_call_output' and i['call_id']=='skill-read'))
                self.assertTrue(next(e for e in native['skill_events'] if e['type']=='skill_file_read')['full_content_returned'])
                self.assertEqual(len(model.inputs),10,'no permission retry needed')

    def test_skill_workdir_is_same_directory_and_never_a_symlink_or_subdirectory(self):
        with tempfile.TemporaryDirectory(prefix='uteki-skill-workdir-') as directory:
            root=Path(directory).resolve();work=root/'workspace';work.mkdir()
            (work/'sub').mkdir();(work/'alias').symlink_to(work,target_is_directory=True)
            for value in (None,'','.',str(work),str(work)+ '/.'):
                self.assertTrue(RuntimeSkills.allow_workdir(value,work),value)
            for value in ('..','sub','alias',str(root),str(work/'missing'),42):
                self.assertFalse(RuntimeSkills.allow_workdir(value,work),value)

    def test_openai_denied_and_truncated_reads_do_not_report_full_body(self):
        c=self.case()
        class ReadBoundaryModel(F['SkillScriptedModel']):
            async def get_response(self,*args,**kwargs):
                result=await super().get_response(*args,**kwargs)
                inputs=self.inputs[-1]['input']
                calls=[i for i in inputs if i.get('type')=='function_call']
                count=sum(i['name']=='exec_command' for i in calls)
                if any(i['name']=='load_skill' for i in calls) and count<3:
                    values=dict(cmd='cat .agents/financial-data-query/SKILL.md',workdir='..' if count==0 else '.',
                        max_output_tokens=1 if count==1 else 12000)
                    call=result.output[0]
                    call.name='exec_command';call.arguments=json.dumps(values)
                    call.call_id='read-boundary-'+str(count);call.id='tool-'+call.call_id
                return result
        model=ReadBoundaryModel()
        result=asyncio.run(run_offline(c.service,c.context,profile('openai'),model=model,limits=F['runtime_limits']()))
        self.assertEqual(result['status'],'completed',result['error'])
        native=Session(c.catalog,c.context).data['native_execution']
        self.assertIn('workdir must resolve',native['skill_tool_calls']['read-boundary-0']['output'])
        reads=[e for e in native['skill_events'] if e['type']=='skill_file_read']
        self.assertEqual([e['full_content_returned'] for e in reads],[False,True])

    @staticmethod
    def journal(c):
        # Read the existing real session, without initializing a second run.
        class Journal:
            catalog=c.catalog
            context=Session(c.catalog,c.context).data['context']
            resuming=True
            checkpoint=staticmethod(lambda phase:None)
            def session(self):return Session(c.catalog,c.context)
        return Journal()

    def test_snapshot_resume_ignores_changed_sources_and_rejects_bad_files(self):
        c=self.case()
        journal=RuntimeJournal(c.service,c.context,profile('openai').metadata(),F['runtime_limits']())
        frozen=RuntimeSkills(profile('openai'),journal,available_tools=ENVELOPES)
        with tempfile.TemporaryDirectory(prefix='uteki-skill-runtime-') as directory:
            root=Path(directory).resolve()
            stage=frozen.stage(root/'selected')
            self.assertTrue(frozen.allow_read(str(stage/'financial-data-query/SKILL.md'),root=root,prefix='selected'))
            (root/'secret.txt').write_text('not a Skill')
            self.assertFalse(frozen.allow_read('secret.txt',root=root,prefix='selected'))
            self.assertFalse(frozen.allow_read(None,root=root,prefix='selected'))
            with patch('uteki.data_platform.agent.skill_runtime.get_skill',side_effect=AssertionError('must use snapshot')):
                restored=RuntimeSkills(profile('openai'),self.journal(c),available_tools=ENVELOPES)
            self.assertEqual(restored.bundles,frozen.bundles)
            (stage/'financial-data-query/SKILL.md').write_text('changed')
            self.assertFalse(frozen.allow_read(str(stage/'financial-data-query/SKILL.md'),root=root,prefix='selected'))
            with self.assertRaises(CatalogError):restored.stage(stage)
        session=Session(c.catalog,c.context)
        session.data['native_execution']['skill_snapshot'][0]['sha256']='0'*64;session.save()
        with self.assertRaises(CatalogError) as caught:
            RuntimeSkills(profile('openai'),self.journal(c),available_tools=ENVELOPES)
        self.assertEqual(caught.exception.code,'RECOVERY_REQUIRED')
        session.data['native_execution'].pop('skill_snapshot');session.save()
        with self.assertRaises(CatalogError):RuntimeSkills(profile('openai'),self.journal(c),available_tools=ENVELOPES)

    def test_openai_process_resume_keeps_skill_and_exact_native_results(self):
        c=self.case();c.catalog.close()
        with (c.root/'skill-worker.log').open('w') as log:
            worker=ObservedWorker([sys.executable,'-I',str(ROOT/'tests/fixtures/data_platform/runtime_openai_worker.py'),
                str(c.root),c.context,str(CONFIG),'model_response_committed@3','skill'],cwd=c.root,
                env={'PATH':'/usr/bin:/bin'},stdout=log,stderr=log)
            observed=worker.wait(timeout=40)
        self.assertEqual(observed['returncode'],79,(c.root/'skill-worker.log').read_text())
        with Catalog.open(c.root) as catalog:
            worker.record(catalog,c.context)
            before=deepcopy(Session(catalog,c.context).data['native_execution'])
            model=F['SkillScriptedModel']()
            with patch('uteki.data_platform.agent.skill_runtime.get_skill',side_effect=AssertionError('must use snapshot')):
                result=asyncio.run(run_offline(DataService(catalog),c.context,profile('openai'),model=model,
                    limits=F['runtime_limits'](),recover=True))
            self.assertEqual(result['status'],'completed',result['error'])
            after=Session(catalog,c.context).data['native_execution']
            self.assertEqual(after['skill_snapshot'],before['skill_snapshot'])
            self.assertEqual(after['skill_tool_calls'],before['skill_tool_calls'])
            self.assertEqual(len(after['openai_requests']),10)
            self.assertEqual(len(model.inputs),7,'three answered requests must replay without a model call')

    def test_claude_discovery_loading_read_and_business_delivery(self):
        report=N['run_scenario']('success',options=dict(skills=True))
        self.assertEqual(report['exit_code'],0,report['stderr'][-3000:])
        self.assertEqual(report['result']['status'],'completed',report['result']['error'])
        self.assertEqual(len(report['requests']),10)
        first=json.dumps(report['requests'][0],ensure_ascii=False)
        selected=get_skill('financial-data-query',config_root=CONFIG,model=profile('claude').profile.model_id,
            sdk='claude',sdk_version=profile('claude').profile.sdk_version,available_tools=tuple(ENVELOPES))
        body=selected.content.split('---',2)[2].strip()
        messages=report['requests'][1]['messages']
        texts='\n'.join(b.get('text','') for m in messages if isinstance(m.get('content'),list)
            for b in m['content'] if b.get('type')=='text')
        self.assertIn(DESCRIPTION,first)
        self.assertNotIn(body,first)
        self.assertIn(body,texts)
        calls=report['journal']['skill_tool_calls']
        self.assertEqual({c['name'] for c in calls.values()},{'Skill','Read'})
        self.assertTrue(all(c['status']=='completed' and 'wire_result' in c for c in calls.values()))
        self.assertEqual(len(report['journal']['tool_calls']),8)
        self.assertEqual(report['result']['delivery']['delivery']['calculations'][0]['value'],'-2.250000000000000000')

    def test_claude_native_resume_keeps_skill_history(self):
        report=N['run_scenario']('success',options=dict(skills=True,stop_phase='claude_post_tool@3',
            recover_after_exit=True,observe_exit=True))
        self.assertEqual(report['exit_code'],79,report['stderr'][-3000:])
        self.assertEqual(report['recovery']['exit_code'],0,report['recovery']['stderr'][-3000:])
        self.assertEqual(report['result']['status'],'completed',report['result']['error'])
        self.assertEqual(len(report['requests']),10)
        self.assertEqual(report['journal']['skill_snapshot'],report['before_recovery']['native_execution']['skill_snapshot'])
        self.assertEqual(report['journal']['skill_tool_calls'],report['before_recovery']['native_execution']['skill_tool_calls'])

    def test_old_profile_identity_and_non_skill_chain(self):
        for sdk in ('openai','claude'):
            old=profile(sdk,skills=False)
            self.assertNotIn('skills',old.metadata())
            self.assertNotIn('model_version',old.metadata())
        c=self.case();model=F['ScriptedModel']()
        result=asyncio.run(run_offline(c.service,c.context,profile('openai',skills=False),
            model=model,limits=F['runtime_limits']()))
        self.assertEqual(result['status'],'completed',result['error'])
        self.assertNotIn('skill_snapshot',Session(c.catalog,c.context).data['native_execution'])

    def test_claude_changed_skill_body_cannot_be_sent_on_resume(self):
        report=N['run_scenario']('success',options=dict(skills=True,stop_phase='claude_post_tool@3',
            recover_after_exit=True,observe_exit=True,history_fault='skill_body'))
        self.assertEqual(report['exit_code'],79,report['stderr'][-3000:])
        self.assertEqual(report['recovery']['exit_code'],0,report['recovery']['stderr'][-3000:])
        self.assertEqual(report['result']['kind'],'recovery_required',report['result']['error'])
        self.assertEqual(len(report['requests']),3)
        self.assertTrue(any(e['type']=='claude_resume_request_rejected' for e in report['journal']['events']))


if __name__=='__main__':unittest.main()
