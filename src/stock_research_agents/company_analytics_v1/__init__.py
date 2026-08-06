"""Outer analytics profile that composes base research research with sidecars."""

from .contracts import (
    COMPANY_ANALYTICS_RESULT_SCHEMA_VERSION,
    COMPANY_ANALYTICS_SCHEMA_VERSION,
    COMPANY_ANALYTICS_WORKFLOW_ID,
    CompanyAnalyticsResultV1,
    CompanyAnalyticsSubmissionV1,
    analytics_run_id,
    base_request_digest,
    base_submission_digest,
    canonical_stage_ids,
    canonical_workflow_digest,
    parse_company_analytics_result_v1,
    parse_company_analytics_submission_v1,
)
from .provider import CompanyAnalyticsV1Provider
from .source_lineage import (
    SOURCE_LINEAGE_SCHEMA_VERSION,
    SourceLineageBindingV1,
    SourceLineageCrosswalkV1,
)

__all__ = [
    "COMPANY_ANALYTICS_SCHEMA_VERSION",
    "COMPANY_ANALYTICS_RESULT_SCHEMA_VERSION",
    "COMPANY_ANALYTICS_WORKFLOW_ID",
    "CompanyAnalyticsResultV1",
    "CompanyAnalyticsV1Provider",
    "CompanyAnalyticsSubmissionV1",
    "SOURCE_LINEAGE_SCHEMA_VERSION",
    "SourceLineageBindingV1",
    "SourceLineageCrosswalkV1",
    "analytics_run_id",
    "base_request_digest",
    "base_submission_digest",
    "canonical_stage_ids",
    "canonical_workflow_digest",
    "parse_company_analytics_submission_v1",
    "parse_company_analytics_result_v1",
]
