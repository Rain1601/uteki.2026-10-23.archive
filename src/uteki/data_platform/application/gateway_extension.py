"""Explicit allowance continuation of an existing batch, with no ledger reset."""
from copy import deepcopy
from decimal import Decimal
import json
import math

from .gateway_batch import _open_batch, _plan, _root_policy, validate_execution_policy
from .session import Session
from ..contracts.common import CatalogError, canonical, digest, new_id, utc_now
from ..contracts.content import ObjectRef


def _observed_inactive_failure(session):
    """A prior-boot exit can prove inactivity without claiming recovery succeeded."""
    native=session.data['native_execution']
    if (native.get('phase')!='recovery_required'
            or native.get('outcome',{}).get('status')!='failed'
            or any(o['status']!='completed' for o in session.data['operations'].values())
            or any(r['status']=='active' for r in native.get('recovery_attempts',[]))):
        return False
    try:
        raw=session.catalog.content.read_object(ObjectRef.model_validate(native['exit_observation']))
        observed=json.loads(raw);clock=native['execution_clock']
        expected=dict(schema_version='uteki-observed-exit-v1',context_ref=session.data['context']['context_ref'],
            native_session_id=native['native_session_id'],owner_pid=native['owner_pid'],clock=clock,
            clock_domain=clock['domain'],process_group_empty=True)
        times=[observed['launched_monotonic'],clock['started_monotonic'],observed['exited_monotonic']]
        return (canonical(observed)==raw and all(observed.get(k)==v for k,v in expected.items())
            and observed['process_group_empty'] is True and type(observed.get('returncode')) is int
            and all(type(t) in (int,float) and math.isfinite(t) and t>=0 for t in times)
            and times[0]<=times[1]<=times[2])
    except (KeyError,TypeError,ValueError,OSError):
        return False


def _validate_profile_revision(policy, profile, revision):
    """Only an explicitly fingerprinted prompt/Skill revision may change guidance."""
    proposed = policy | {'profile': profile}
    if revision is None:
        validate_execution_policy(policy, proposed)
        return
    expected = dict(previous_sha256=digest(canonical(policy['profile'])),
                    current_sha256=digest(canonical(profile)))
    if revision != expected:
        raise ValueError('profile revision must identify the exact previous and current profiles')
    from ..agent.profiles import Profile
    Profile.model_validate_json(json.dumps(profile))
    # This approval covers instructions only: model, route, capabilities and
    # output controls still obey the original execution-policy restrictions.
    unchanged = deepcopy(profile)
    for field in ('prompt', 'skills'):
        unchanged.pop(field, None)
        if field in policy['profile']:
            unchanged[field] = deepcopy(policy['profile'][field])
    validate_execution_policy(policy, policy | {'profile': unchanged})


def extend_gateway_batch(catalog, base_ref, profiles, contract, authorization, *, additional_scopes=None, checkpoint=None):
    """Freeze revised contexts, then atomically apply the user's cumulative caps.

    A saved revision intent can be repeated with the same authorization ID after
    interruption; historical native sessions and their contracts remain frozen.
    """
    checkpoint=checkpoint or (lambda phase:None)
    if authorization.get('authorized_by')!='user' or not authorization.get('confirmation'):
        raise ValueError('Explicit user authorization is required')
    base_ref=ObjectRef.model_validate(base_ref)
    original=json.loads(catalog.content.read_object(base_ref));old_plan=original['plan']
    additions=deepcopy(additional_scopes or [])
    old_ids={s['scope_id'] for s in old_plan['scopes']}
    if additions:
        if (not isinstance(additions,list)
                or authorization.get('additional_scopes_sha256')!=digest(canonical(additions))
                or authorization.get('new_scope_ids')!=sorted(s['scope_id'] for s in additions)
                or len({s['scope_id'] for s in additions})!=len(additions)
                or old_ids & {s['scope_id'] for s in additions}):
            raise ValueError('New comparison scopes require an exact authorization fingerprint')
        from ..agent.profiles import Profile
        for item in additions:
            binding = set(item) & {'source_scope_id', 'context_ref'}
            if (len(binding)!=1 or set(item)!={'scope_id','profile','limits','transport','pricing'} | binding
                    or ('source_scope_id' in item and item['source_scope_id'] not in old_ids)
                    or authorization['new_scope_requests'][item['scope_id']]!=item['limits']['max_model_requests']):
                raise ValueError('New scopes require one explicit business context and matching limits')
            if 'context_ref' in item:
                # The host creates this through DataService validation. A new
                # question is never silently inherited from a historical lane.
                context = Session(catalog,item['context_ref']).data['context']
                if context['run_id']!=context['root_run_id']:
                    raise ValueError('New input requires an independent business root')
            Profile.model_validate_json(json.dumps(item['profile']))
    elif authorization.get('new_scope_ids') or authorization.get('additional_scopes_sha256'):
        raise ValueError('Authorized new scopes are missing')
    additional_limit = authorization.get('additional_limit_usd')
    if additional_limit is not None:
        amount = Decimal(str(additional_limit))
        if not additions or not amount.is_finite() or not 0 < amount <= Decimal(authorization['new_limit_usd']):
            raise ValueError('Additional spending limit requires explicit new scopes and a bounded amount')
    revisions=authorization.get('profile_revisions', {})
    preserve = authorization.get('preserve_existing_scopes') is True
    request_revisions=authorization.get('request_limit_revisions',{})
    if (not isinstance(request_revisions,dict) or (request_revisions and (not preserve or additions))
            or set(request_revisions)-old_ids):
        raise ValueError('Request revisions require preserved existing scopes and no additions')
    for lane, revision in request_revisions.items():
        old=next(s for s in old_plan['scopes'] if s['scope_id']==lane)
        if (not isinstance(revision,dict) or set(revision)!={'old_max_requests','new_max_requests'}
                or any(type(v) is not int for v in revision.values())
                or revision['old_max_requests']!=old['max_requests']
                or not old['max_requests']<revision['new_max_requests']<=authorization['new_max_requests']
                or authorization['new_scope_requests'][lane]!=revision['new_max_requests']):
            raise ValueError('Request revision requires exact old/new lane limits')
    if preserve and revisions:
        raise ValueError('Preserving historical scopes cannot change historical profiles')
    if preserve and additions and authorization['new_limit_usd']!=authorization['old_limit_usd']:
        raise ValueError('Revise the monetary pool separately from adding new business scopes')
    spending_limits = deepcopy(old_plan.get('spending_limits', []))
    spending_revisions = authorization.get('spending_limit_revisions', [])
    if not isinstance(spending_revisions,list) or (spending_revisions and not preserve):
        raise ValueError('Spending revisions require preserved contexts and scope policies')
    changed_groups=set()
    for revision in spending_revisions:
        if not isinstance(revision,dict) or set(revision)!={'scope_ids','old_limit_usd','new_limit_usd'}:
            raise ValueError('Spending revision requires exact scopes and old/new monetary limits')
        matches=[bound for bound in spending_limits if bound['scope_ids']==revision['scope_ids']]
        key=canonical(revision['scope_ids'])
        if len(matches)!=1 or key in changed_groups or matches[0]['limit_usd']!=revision['old_limit_usd']:
            raise ValueError('Spending revision must match one unchanged existing scope group')
        revised_amount=Decimal(str(revision['new_limit_usd']))
        if (not revised_amount.is_finite() or not Decimal(revision['old_limit_usd'])<revised_amount
                or revised_amount>Decimal(authorization['new_limit_usd'])):
            raise ValueError('Spending revision must increase the group limit within the cumulative allowance')
        matches[0]['limit_usd']=str(revised_amount)
        changed_groups.add(key)
    if preserve and not additions and not spending_revisions and not request_revisions and authorization['new_limit_usd']==authorization['old_limit_usd']:
        raise ValueError('No monetary or new-scope change was authorized')
    if not isinstance(revisions, dict) or set(revisions)-{s['scope_id'] for s in old_plan['scopes']}:
        raise ValueError('profile revisions must refer to existing lanes')
    budget=_open_batch(catalog,base_ref,original)
    key=authorization['authorization_id']
    inputs=dict(previous_ref=base_ref.model_dump(mode='json'),profiles=profiles,authorization=authorization)
    if additions:inputs['additional_scopes']=additions
    stored=catalog._existing('gateway-batch-revision',key,inputs)
    if stored is None:
        root=budget.inspect_root()
        if root['policy']!=_root_policy(old_plan):raise ValueError('extension must start at the current batch revision')
        if digest(canonical(contract))!=old_plan['execution_contract_sha256']:
            raise ValueError('original execution contract differs')
        # A native worker may be between HTTP requests; its saved exit outcome
        # is required before transferring all lanes to a new allowance revision.
        contexts={s['policy']['context_ref'] for s in old_plan['scopes']}
        contexts.update(r['request'].get('context_ref') for r in budget.inspect_requests())
        for ref in contexts-{None}:
            prior_session=Session(catalog,ref);native=prior_session.data.get('native_execution')
            if native and not native.get('outcome_object'):
                # A new, separately authorized model comparison does not resume
                # this failed native session or rewrite its outcome/clock.
                if not (additions or preserve) or not _observed_inactive_failure(prior_session):
                    raise CatalogError('RECOVERY_REQUIRED','confirm old worker inactivity and business effects before extending allowances')
        revised=deepcopy(contract)
        revised.update(limit_usd=authorization['new_limit_usd'],max_requests=authorization['new_max_requests'],
                       authorization=deepcopy(authorization))
        scopes=[]
        for old in old_plan['scopes']:
            lane=old['scope_id'];policy=old['policy'];profile=profiles[lane]
            if preserve:
                count=request_revisions.get(lane,{}).get('new_max_requests',old['max_requests'])
                if profile!=policy['profile'] or authorization['new_scope_requests'][lane]!=count:
                    raise ValueError('Historical scope profile and allowance must remain unchanged')
                limits=deepcopy(policy['limits'])
                if lane in request_revisions:
                    limits.update(max_model_requests=count,native_max_turns=count)
                    revised['scopes'][lane]['max_requests']=count
                scopes.append(dict(scope_id=lane,context_ref=policy['context_ref'],profile=profile,
                    limits=limits,transport=policy['transport']))
                continue
            _validate_profile_revision(policy,profile,revisions.get(lane))
            context=deepcopy(Session(catalog,policy['context_ref']).data['context'])
            context.update(context_ref=new_id('req'),created_at=utc_now())
            context.pop('run_id');context.pop('root_run_id')
            context['request']['run_policy']['max_usd']=authorization['new_limit_usd']
            session=Session.create(catalog,context,'gateway-extension:'+key+':'+lane,recover=True)
            limits=deepcopy(policy['limits'])
            limits.update(max_model_requests=authorization['new_scope_requests'][lane],
                          native_max_turns=authorization['new_scope_requests'][lane])
            scopes.append(dict(scope_id=lane,context_ref=session.data['context']['context_ref'],
                               profile=profile,limits=limits,transport=policy['transport']))
            revised['scopes'][lane].update(profile=profile,max_requests=limits['max_model_requests'])
        for item in additions:
            lane=item['scope_id']
            source_ref = item.get('context_ref')
            if source_ref is None:
                source=next(s for s in old_plan['scopes'] if s['scope_id']==item['source_scope_id'])
                source_ref=source['policy']['context_ref']
            context=deepcopy(Session(catalog,source_ref).data['context'])
            context.update(context_ref=new_id('req'),created_at=utc_now())
            context.pop('run_id');context.pop('root_run_id')
            context['request']['run_policy']['max_usd']=authorization['new_limit_usd']
            session=Session.create(catalog,context,'gateway-extension:'+key+':'+lane,recover=True)
            scopes.append(dict(scope_id=lane,context_ref=session.data['context']['context_ref'],
                profile=item['profile'],limits=item['limits'],transport=item['transport']))
            revised['scopes'][lane]=dict(profile=item['profile'],transport=item['transport'],
                max_requests=item['limits']['max_model_requests'],pricing=item['pricing'])
            if 'context_ref' in item:
                revised['scopes'][lane]['input_sha256']=digest(canonical(context['request']))
        if preserve:
            # An authorized monetary revision changes the shared pool, not the
            # immutable question/session snapshot or any native scope policy.
            plan=deepcopy(old_plan)
            plan.update(limit_usd=revised['limit_usd'],max_requests=revised['max_requests'],
                        execution_contract_sha256=digest(canonical(revised)))
            for lane,revision in request_revisions.items():
                selected=next(s for s in plan['scopes'] if s['scope_id']==lane)
                selected['max_requests']=revision['new_max_requests']
                selected['policy']['limits'].update(max_model_requests=revision['new_max_requests'],native_max_turns=revision['new_max_requests'])
            if additions:
                # Earlier monetary revisions deliberately retain historical
                # context ceilings. Validate only the new business roots
                # against the current pool; keep old frozen scope policies.
                added=_plan(catalog,old_plan['batch_id'],
                    [s for s in scopes if s['scope_id'] not in old_ids],
                    revised['limit_usd'],revised['max_requests'],
                    old_plan['origin'],digest(canonical(revised)))
                plan['scopes']=sorted(plan['scopes']+added['scopes'],key=lambda s:s['scope_id'])
        else:
            plan=_plan(catalog,old_plan['batch_id'],scopes,revised['limit_usd'],revised['max_requests'],
                       old_plan['origin'],digest(canonical(revised)))
        if additional_limit is not None:
            spending_limits.append(dict(scope_ids=sorted(i['scope_id'] for i in additions),limit_usd=str(amount)))
        if spending_limits: plan['spending_limits'] = spending_limits
        previous_root={k:v for k,v in root.items() if k not in {'cost','request_stages'}}
        descriptor=dict(plan=plan,ledger_image=original['ledger_image'],revision_inputs=inputs,
                        execution_contract=revised,previous_root=previous_root)
        reference=catalog.content.put_object(canonical(descriptor))
        with catalog.database.transaction():
            catalog._register_key('gateway-batch-revision',key,inputs,reference.model_dump_json())
        checkpoint('allowance_intent_saved')
    else:
        reference=ObjectRef.model_validate_json(stored)
        descriptor=json.loads(catalog.content.read_object(reference))
        plan=descriptor['plan'];revised=descriptor['execution_contract']
    previous=descriptor['previous_root']
    new_root={k:v for k,v in previous.items() if k!='stop_reason'}
    new_root.update(limit_usd=plan['limit_usd'],max_requests=plan['max_requests'],policy=_root_policy(plan),
                    scope_ids=[s['scope_id'] for s in plan['scopes']])
    new_scopes=[dict(schema_version='uteki-metered-scope-v1',root_run_id=plan['batch_id'],**s) for s in plan['scopes']]
    budget.extend_root(expected_root=previous,new_root=new_root,new_scopes=new_scopes,authorization=authorization)
    checkpoint('allowance_committed')
    _open_batch(catalog,reference,descriptor)
    return dict(contract=revised,
        scopes=[dict(scope_id=s['scope_id'],context_ref=s['policy']['context_ref'],profile=s['policy']['profile'],
                     limits=s['policy']['limits'],transport=s['policy']['transport']) for s in plan['scopes']],
        bindings={s['scope_id']:dict(batch_ref=reference.model_dump(mode='json'),scope_id=s['scope_id']) for s in plan['scopes']})
