"""Fixed, content-free failure vocabulary shared by model and knowledge paths."""
CATEGORIES = frozenset({
    'model_unavailable', 'provider_failure', 'connection_failure', 'generation_timeout', 'output_length',
    'malformed_json', 'invalid_structure', 'citation_rejected', 'missing_citation',
    'retrieval_failure', 'authorization_denied', 'synchronization_failure',
    'residency_conflict', 'residency_timeout', 'source_changed', 'context_budget',
    'incomplete_output', 'invalid_response', 'backend_failure', 'invalid_request',
    'evidence_budget', 'no_evidence', 'cancelled', 'model_mismatch', 'vector_timeout',
})


def safe_category(value, default):
    return value if type(value) is str and value in CATEGORIES else default
