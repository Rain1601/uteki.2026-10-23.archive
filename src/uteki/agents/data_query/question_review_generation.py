"""Model-facing request identity; lossless projection to the historical review contract.

This changes generation only. It cannot infer missing qualifiers from evidence,
merge checks, or exempt any canonical quotation/identity/evidence validation.
"""
from copy import deepcopy
from functools import lru_cache
from typing import Literal

from pydantic import Field, create_model

from uteki.domain.research_data.query_contract import Contract
from .question_coverage_review import (
    QUESTION_REVIEW_PROMPT, QuestionCoverageAssessment, QuestionCoverageCheckV2,
)

PROJECTION = 'question-request-identity-v1'
PROJECTION_FIGURES = 'question-request-identity-v2-figures'


class QualifiedRequestScope(Contract):
    kind: Literal['qualified']
    quotes: tuple[str, ...] = Field(min_length=1, max_length=8,
        description='Separate exact phrases from the original QUESTION identifying each applicable '
        'entity, period or other qualifier of THIS requested result; never derive them from evidence.')


class SelfContainedRequestScope(Contract):
    kind: Literal['self_contained']
    reason: str = Field(min_length=1, max_length=1000, pattern=r'\S',
        description='Explain why the subject anchor identifies the entire requested scope without '
        'separate qualifiers. A collective reference to separately requested entities does not identify '
        'an individual entity. This explanation does not waive any identity or evidence check.')


_IDENTITY_FIELDS = ('question_quote', 'requested_subject', 'requested_dimension')
_FIELDS = QuestionCoverageCheckV2.model_fields
# Reuse canonical field types/constraints rather than maintaining a second schema.
QuestionRequestIdentity = create_model('QuestionRequestIdentity', __base__=Contract,
    **{name: (field.annotation, deepcopy(field)) for name in _IDENTITY_FIELDS
       for field in [_FIELDS[name]]},
    scope=(QualifiedRequestScope | SelfContainedRequestScope,
           Field(description='Required scope decision for this requested identity, before judging evidence.')))
QuestionEvidenceJudgment = create_model('QuestionEvidenceJudgment', __base__=Contract,
    **{name: (field.annotation, deepcopy(field)) for name, field in _FIELDS.items()
       if name not in (*_IDENTITY_FIELDS, 'requested_scope_quotes')})


class QuestionGenerationCheck(Contract):
    request: QuestionRequestIdentity
    judgment: QuestionEvidenceJudgment


class QuestionCoverageGeneration(QuestionCoverageAssessment):
    checks: tuple[QuestionGenerationCheck, ...] = Field(max_length=64)


def project_question_generation(value, projected=None):
    """Move only model-authored fields; leave all canonical validation to the caller."""
    generated = question_generation_schema(projected or {}).model_validate(value).model_dump(mode='json')
    canonical = {k: deepcopy(v) for k, v in generated.items() if k != 'checks'}
    canonical['checks'] = []
    for check in generated['checks']:
        request = check['request']
        scopes = request['scope']['quotes'] if request['scope']['kind'] == 'qualified' else []
        canonical['checks'].append({**{k: deepcopy(request[k]) for k in _IDENTITY_FIELDS},
            'requested_scope_quotes': deepcopy(scopes), **deepcopy(check['judgment'])})
    from .question_coverage_review import question_assessment_schema
    schema = question_assessment_schema(projected) if projected is not None else QuestionCoverageAssessment
    return schema.model_validate(canonical).model_dump(mode='json')


QUESTION_GENERATION_PROMPT = QUESTION_REVIEW_PROMPT.replace(
    'Omit them or use [] when no separate\nscope qualifier is needed.',
    'Explicitly decide whether separate scope qualifiers are needed.'
) + """
MODEL OUTPUT CONTRACT: question-request-identity-v1.
Each check has a required request group FIRST, then a judgment group. Complete the requested
identity from the original question before judging the source. In request, keep question_quote,
requested_subject and requested_dimension with their meanings above. Represent requested_scope_quotes
as request.scope: use kind=qualified and quotes for additional entity/period/other qualifiers;
use kind=self_contained with a reason only when the subject anchor itself specifies the entire scope.
The program converts qualified quotes to requested_scope_quotes and self_contained to an empty list.
It does NOT infer company or period from judgment.source_subject, citations or your reason.
All other per-check fields belong to judgment. Return the supplied nested output schema.
For repair inputs, previous_assessment and diagnostic pointers use the canonical FLAT contract:
checks[i].question_quote/requested_subject/requested_dimension map to checks[i].request fields;
checks[i].requested_scope_quotes maps to checks[i].request.scope; all other check fields map to
checks[i].judgment. Reconsider the same question and return a complete nested assessment. Do not
alter the original question, infer a preferred coverage verdict, merge distinct requests or bypass
any original identity, exact-quotation, scope, citation or completeness checks.
"""


def question_generation_schema(projected):
    """Keep the original generated schema untouched for every historical input."""
    if projected.get('schema_version') != 'question-coverage-input-v3':
        return QuestionCoverageGeneration
    return _figure_generation_schema()


@lru_cache(maxsize=1)
def _figure_generation_schema():
    from .question_coverage_review import FigureQuestionCoverageAssessment, FigureQuestionCoverageCheck
    fields = FigureQuestionCoverageCheck.model_fields
    judgment = create_model('FigureQuestionEvidenceJudgment', __base__=Contract,
        **{name: (field.annotation, deepcopy(field)) for name, field in fields.items()
           if name not in (*_IDENTITY_FIELDS, 'requested_scope_quotes')})
    check = create_model('FigureQuestionGenerationCheck', __base__=Contract,
        request=(QuestionRequestIdentity, ...), judgment=(judgment, ...))
    return create_model('FigureQuestionCoverageGeneration', __base__=FigureQuestionCoverageAssessment,
        checks=(tuple[check, ...], Field(max_length=64)))


def question_generation_prompt(projected):
    if projected.get('schema_version') != 'question-coverage-input-v3':
        return QUESTION_GENERATION_PROMPT
    return QUESTION_GENERATION_PROMPT.replace(PROJECTION, PROJECTION_FIGURES).replace(
        'unselected report content and image contents have not been reviewed. Do not infer unseen facts.',
        'Unselected report content and unselected images have not been reviewed. Only source_figures contains selected, source-bound figure transcription.') + '''
FIGURE CONTRACT figure-evidence-v1: source_figures are source-bound model transcriptions with
independently replayed OCR label coordinates; provenance validation is not a guarantee of visual accuracy.
The independent_acceptance field is preserved as recorded; pending is not a completed acceptance.
Use kind=figure_text with source_snapshot_id, figure_id, text_id and one exact continuous quote
from that text's transcription.texts entry. For a literal scalar use kind=figure_field with
source_snapshot_id, figure_id, field_path and exact string value; supported paths are transcription.kind,
transcription.texts.N.id/role/text, transcription.series.N.legend_id/color, and
transcription.printed_values.N.text_id/series_legend_id/period_text_id. N is a zero-based integer.
Never cite bounding boxes, OCR confidence, inferred curve values, alt text or arbitrary source metadata
as printed observations. Ticks and legends are not point values. Empty printed_values means no
printed point labels were transcribed, not that a disclosure elsewhere is absent. Keep chart type,
series identity, dates, units and original prose assumptions distinct. Figure labels cannot supply
missing context; use block_quote citations for selected original prose. Review the original question's
scope and missing information independently; the program supplies no desired answer or verdict.
'''
