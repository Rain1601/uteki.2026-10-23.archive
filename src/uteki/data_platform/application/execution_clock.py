"""Observed worker exit bounds execution time; it never resumes an SDK loop."""
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

from ..contracts.common import CatalogError, canonical, utc_now
from ..contracts.content import ObjectRef
from .session import Session


def _boot_metadata():
    try:
        if sys.platform=='darwin':
            return subprocess.check_output(['/usr/sbin/sysctl','-n','kern.boottime'],timeout=5,stderr=subprocess.PIPE)
        elif sys.platform.startswith('linux'):
            return Path('/proc/sys/kernel/random/boot_id').read_bytes()
        else:
            raise CatalogError('CAPABILITY_UNSUPPORTED','no verified monotonic clock domain on this platform')
    except (OSError,subprocess.SubprocessError) as error:
        raise CatalogError('RECOVERY_REQUIRED','cannot establish the local monotonic clock domain') from error


def _domain(boot,version):
    if type(version) is not int or version not in (1,2):
        raise CatalogError('RECOVERY_REQUIRED','unsupported execution clock domain version')
    if version==2:
        if sys.platform=='darwin':
            match=re.match(rb'^\{\s*sec\s*=\s*(\d+)\s*,\s*usec\s*=\s*(\d+)\s*\}',boot)
            if not match or int(match[1])<=0 or not 0<=int(match[2])<1000000:
                raise CatalogError('RECOVERY_REQUIRED','invalid numeric boot metadata')
            boot=f'{int(match[1])}:{int(match[2])}'.encode('ascii')
        else:
            boot=boot.strip()
            if not boot:
                raise CatalogError('RECOVERY_REQUIRED','empty boot identity')
        boot=b'\x00boot-v2\x00'+boot
    return hashlib.sha256(sys.platform.encode()+boot+time.get_clock_info('monotonic').implementation.encode()).hexdigest()


def clock_domain(*,version=2):
    """Compare only the same boot/clock kind; retain the exact legacy algorithm."""
    return _domain(_boot_metadata(),version)


def start_clock(started, initial_wall_seconds):
    value=dict(started_monotonic=started,initial_wall_seconds=initial_wall_seconds,domain_version=2)
    try:
        value['domain']=clock_domain()
    except CatalogError as error:
        # In-process deadlines still work without access to boot metadata.
        # Only cross-process reconciliation needs the comparable clock domain.
        value.update(domain=None,domain_unavailable=str(error))
    return value


def _members(pgid):
    rows=subprocess.check_output(['/bin/ps','-axo','pid=,pgid=,stat='],text=True,timeout=5)
    return [dict(pid=int(pid),state=state) for pid,group,state in
            (line.split() for line in rows.splitlines()) if int(group)==pgid]


class ObservedWorker:
    """Host-only owner of a real process group. Call record after wait succeeds."""
    def __init__(self, command, *, cwd, env, stdout, stderr):
        if (not isinstance(command,(list,tuple)) or not command or any(not isinstance(v,str) or not v for v in command)
                or not Path(command[0]).is_absolute() or not Path(cwd).is_absolute() or not isinstance(env,dict)):
            raise CatalogError('INVALID_REQUEST','explicit absolute executable/cwd and environment required')
        boot=_boot_metadata()
        self.domains={version:_domain(boot,version) for version in (1,2)}
        self.domain=self.domains[2]
        _members(os.getpgrp())  # Fail before spawning if membership cannot be inspected.
        self.launched=time.monotonic()
        self.child=subprocess.Popen(command,cwd=cwd,env=env,stdout=stdout,stderr=stderr,start_new_session=True)
        self.observation=None
        self.cleanup=None

    def wait(self, *, timeout):
        if self.observation is not None:
            return deepcopy(self.observation)
        if type(timeout) not in (int,float) or not math.isfinite(timeout) or timeout<=0:
            raise CatalogError('INVALID_REQUEST','positive finite supervisor timeout required')
        timed_out=False
        try:
            self.child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out=True
        except BaseException:
            try:os.killpg(self.child.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            self.child.wait(timeout=5)
            raise
        before=_members(self.child.pid)
        for sig in (signal.SIGTERM,signal.SIGKILL):
            if not _members(self.child.pid):break
            try:os.killpg(self.child.pid,sig)
            except ProcessLookupError:pass
            deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                self.child.poll()
                if not _members(self.child.pid):break
                time.sleep(.05)
        remaining=_members(self.child.pid)
        if remaining or self.child.poll() is None:
            raise CatalogError('RECOVERY_REQUIRED','owned worker group exit is not confirmed')
        self.cleanup=dict(pgid=self.child.pid,before=before,after=[])
        self.observation=dict(schema_version='uteki-observed-exit-v1',owner_pid=self.child.pid,
            clock_domain=self.domain,launched_monotonic=self.launched,exited_monotonic=time.monotonic(),
            observed_at=utc_now(),returncode=self.child.returncode,timed_out=timed_out,process_group_empty=True)
        return deepcopy(self.observation)

    def record(self, catalog, context_ref):
        if self.observation is None:
            raise CatalogError('RECOVERY_REQUIRED','worker exit has not been observed')
        session=Session(catalog,context_ref)
        native=session.data.get('native_execution')
        from .recovery_clock import pending_recoveries
        attempts=[item for item in pending_recoveries(native or {}) if item['owner_pid']==self.child.pid]
        if len(attempts)>1:
            raise CatalogError('RECOVERY_REQUIRED','observed host has multiple unclosed recovery intervals')
        target=attempts[0] if attempts else native
        clock=target.get('execution_clock') if target else None
        version=clock.get('domain_version',1) if clock else None
        if type(version) is not int or version not in self.domains:
            raise CatalogError('RECOVERY_REQUIRED','unsupported observed clock domain version')
        observed=dict(self.observation,clock_domain=self.domains[version])
        if (not clock or target['owner_pid']!=self.child.pid or clock['domain']!=observed['clock_domain']
                or not observed['launched_monotonic']<=clock['started_monotonic']<=observed['exited_monotonic']):
            raise CatalogError('RECOVERY_REQUIRED','observed process does not own this native execution clock')
        value=dict(observed,context_ref=context_ref,native_session_id=native['native_session_id'],clock=clock)
        if attempts:value['recovery_attempt_id']=target['attempt_id']
        reference=catalog.content.put_object(canonical(value)).model_dump(mode='json')
        previous=target.get('exit_observation')
        if previous is not None and previous!=reference:
            raise CatalogError('IDEMPOTENCY_CONFLICT','native execution already has a different exit observation')
        if previous is None:
            target['exit_observation']=reference
            session.save()
        return reference


class TimeObservationError(CatalogError):
    def __init__(self, diagnostic):
        self.diagnostic = deepcopy(diagnostic)
        super().__init__('RECOVERY_REQUIRED', 'execution time observation could not be verified: '+diagnostic['reason'])


def begin_segment(session, *, started, prior_elapsed):
    """Transfer the reconciled clock to a new, explicitly authorized worker."""
    native = session.data['native_execution']
    from .recovery_clock import pending_recoveries
    if pending_recoveries(native):
        raise CatalogError('RECOVERY_REQUIRED','recovery interval must finish before native continuation')
    if native.get('execution_time_uncertain') or not native.get('time_reconciliation'):
        raise CatalogError('RECOVERY_REQUIRED','previous execution time has not been reconciled')
    native.setdefault('execution_segments',[]).append({k:deepcopy(native[k]) for k in
        ('owner_pid','execution_started_at','execution_clock','exit_observation','time_reconciliation',
         'elapsed_seconds','prior_elapsed_seconds','recovery_attempts','completion_clock') if k in native})
    native.update(owner_pid=os.getpid(),execution_started_at=utc_now(),
        execution_clock=start_clock(started,session.data['wall_seconds']),prior_elapsed_seconds=prior_elapsed,
        elapsed_seconds=prior_elapsed,phase='active',outcome=None,execution_time_uncertain=False)
    native.pop('exit_observation',None)
    native.pop('time_reconciliation',None)
    native.pop('recovery_attempts',None)
    native.pop('completion_clock',None)
    session.save()


def reconcile_time(session, *, active_recovery_id=None):
    """Consume an actual supervisor observation, not a caller-supplied duration."""
    native=session.data['native_execution']
    from .recovery_clock import reconcile_recoveries, recovery_seconds
    reconcile_recoveries(session,active_id=active_recovery_id)
    reference=native.get('exit_observation')
    if reference is None:return None
    diagnostic=dict(reason='observation_unreadable',observation_ref=reference,
        context_ref=session.data['context']['context_ref'],native_session_id=native['native_session_id'],
        owner_pid=native['owner_pid'],clock=deepcopy(native.get('execution_clock')),
        known_wall_seconds=session.data['wall_seconds'])
    try:
        raw=session.catalog.content.read_object(ObjectRef.model_validate(reference))
        observed=json.loads(raw)
        clock=native['execution_clock']
        diagnostic['reason']='observation_format_invalid'
        if canonical(observed)!=raw or observed['schema_version']!='uteki-observed-exit-v1':
            raise ValueError('exit observation format differs')
        diagnostic['reason']='observation_binding_differs'
        expected=dict(context_ref=session.data['context']['context_ref'],native_session_id=native['native_session_id'],
            clock=clock,owner_pid=native['owner_pid'],clock_domain=clock['domain'],process_group_empty=True)
        diagnostic['mismatched_fields']=[k for k,v in expected.items() if observed.get(k)!=v]
        if diagnostic['mismatched_fields'] or observed['process_group_empty'] is not True:
            raise ValueError('exit observation binding differs')
        diagnostic['reason']='current_clock_domain_unavailable'
        diagnostic['current_clock_domain']=clock_domain(version=clock.get('domain_version',1))
        diagnostic['reason']='clock_domain_changed'
        if diagnostic['current_clock_domain']!=clock['domain']:
            raise ValueError('current clock domain differs')
        diagnostic['reason']='invalid_clock_values'
        values=[observed['launched_monotonic'],observed['exited_monotonic'],clock['started_monotonic'],clock['initial_wall_seconds']]
        if any(type(v) not in (int,float) or not math.isfinite(v) or v<0 for v in values):
            raise ValueError('invalid clock values')
        diagnostic.update(launched_monotonic=observed['launched_monotonic'],exited_monotonic=observed['exited_monotonic'],
                          reason='clock_outside_process_lifetime')
        if not observed['launched_monotonic']<=clock['started_monotonic']<=observed['exited_monotonic']:
            raise ValueError('clock lies outside observed process lifetime')
        uncertain=session.data.get('execution_time_uncertain')
        diagnostic['reason']='unrelated_operation_uncertainty'
        if uncertain:
            operation=session.data['operations'][uncertain['operation_id']]
            if not any(c['request_key']==operation['request_key'] for c in native['tool_calls'].values()):
                raise ValueError('observation cannot reconcile an earlier deterministic operation')
        upper=clock['initial_wall_seconds']+observed['exited_monotonic']-clock['started_monotonic']
        host_seconds=recovery_seconds(native)
        known_native_wall=session.data['wall_seconds']-host_seconds
        diagnostic.update(recovery_seconds=host_seconds,known_native_wall_seconds=known_native_wall)
        diagnostic.update(observed_wall_upper=upper,reason='different_prior_observation')
        previous=native.get('time_reconciliation')
        if previous is not None and previous['observation_ref']!=reference:
            raise ValueError('execution was already reconciled against a different observation')
        if previous is None:
            diagnostic['reason']='upper_below_recorded_execution'
            if upper<known_native_wall:
                raise ValueError('observed upper bound is below recorded execution time')
            native['time_reconciliation']=dict(kind='supervised_upper_bound',observation_ref=reference,
                known_wall_seconds=known_native_wall,charged_wall_seconds=upper,
                original_tool_uncertainty=deepcopy(uncertain),reconciled_at=utc_now())
            session.data.setdefault('time_reconciliations',[]).append(dict(
                context_ref=session.data['context']['context_ref'],native_session_id=native['native_session_id'],
                **deepcopy(native['time_reconciliation'])))
        diagnostic['reason']='reconciliation_commit_failed'
        session.data['wall_seconds']=max(session.data['wall_seconds'],upper+host_seconds)
        session.data['execution_time_uncertain']=None
        native['execution_time_uncertain']=False
        completion=native.get('completion_clock')
        if completion and completion.get('status')=='pending':
            if completion.get('owner_pid')!=native['owner_pid'] or completion.get('started_monotonic')!=clock['started_monotonic']:
                raise ValueError('completion clock belongs to another native execution')
            completion.update(status='observed',observation_ref=reference,wall_seconds=session.data['wall_seconds'])
        session.save()
        return dict(wall_seconds=session.data['wall_seconds'],native_elapsed_upper=upper-clock['initial_wall_seconds'],
                    timed_out=observed['timed_out'])
    except (OSError,ValueError,KeyError,TypeError) as error:
        diagnostic['cause_type']=type(error).__name__
        raise TimeObservationError(diagnostic) from error
