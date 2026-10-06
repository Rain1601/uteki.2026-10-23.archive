"""Explicit taxonomy mapping selected by the Alphabet experiment runner."""
from ..financial_records import FinancialMapping

ALPHABET_FINANCIAL_MAPPING = FinancialMapping(
    company_id="alphabet", entity_identifier="0001652044", segment_entity_id="google-cloud",
    segment_axis="us-gaap:StatementBusinessSegmentsAxis", segment_member="goog:GoogleCloudMember",
    consolidation_axis="srt:ConsolidationItemsAxis", consolidation_member="us-gaap:OperatingSegmentsMember",
    fiscal_calendar="calendar",
)
