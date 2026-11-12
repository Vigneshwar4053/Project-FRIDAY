"""Fixed safe desktop diagnostics. Never include arbitrary exception messages."""
MESSAGES = {
 'stt_unavailable':'Offline speech recognition is not configured. Provisioning needs owner approval; microphone remains OFF.',
 'local_voice_failed':'Local capture or transcription failed. Check the configured ALSA device, permissions and offline model. Microphone is OFF.',
 'no_evidence':'No relevant approved evidence was found within the retrieval budget.',
 'authorization_denied':'Knowledge permission was denied. No answer was generated.',
 'model_unavailable':'The selected model is unavailable. Select an installed model explicitly; no fallback was used.',
 'model_mismatch':'This model is not approved for RAG. Select Qwen3:4b or Specialist Chat.',
 'connection_failure':'Cannot reach local Ollama. Check the local service and retry.',
 'provider_failure':'The local model provider failed. No complete answer was returned.',
 'generation_timeout':'Generation timed out. Try a smaller request or another response depth.',
 'vector_timeout':'The existing vector worker timed out. No verified answer was returned; retry the knowledge request.',
 'output_length':'Generation reached its token limit. The incomplete answer was withheld.',
 'incomplete_output':'The model did not confirm a complete response. The answer was withheld.',
 'malformed_json':'The provider returned invalid JSON. No verified answer was returned.',
 'invalid_response':'The response schema was invalid. The answer was withheld.',
 'invalid_structure':'The structured answer schema was invalid. The answer was withheld.',
 'invalid_answer':'The structured answer schema was invalid. The answer was withheld.',
 'citation_rejected':'Citation verification rejected the answer. No unsupported citations were displayed.',
 'missing_citation':'The answer lacked required citations and was withheld.',
 'source_changed':'Approved source revisions changed. Request fresh authorization and retry.',
 'synchronization_failure':'The model synchronization gate failed. No parallel inference was started.',
 'residency_conflict':'Another model is resident. Review AI Models; no unrelated workload was stopped.',
 'backend_failure':'The knowledge backend or verified index is unavailable. Check dependencies and index status.',
 'retrieval_failure':'Knowledge retrieval or index verification failed. No verified answer was generated.',
 'residency_timeout':'The embedding model did not finish unloading within the residency wait budget. Generation was not started.',
 'dependency_unavailable':'The existing compatible RAG environment is unavailable. Check that environment; any dependency installation requires owner approval.',
 'context_budget':'The request exceeded its bounded context budget. Shorten the request.',
 'invalid_request':'The request is outside the allowed input scope.',
 'evidence_budget':'Approved evidence exceeded its bounded context budget.',
 'cancelled':'The request was cancelled.',
 'gui_worker_failure':'The GUI worker failed safely. No answer was accepted.',
 'operation_unavailable':'The operation is unavailable. Check local dependencies or permissions.',
 'audio_cleanup_unconfirmed':'Audio cleanup is unconfirmed. Further actions are disabled.',
 'offline_playback_failed':'Offline speech output failed. Check Voice for the last safe audio category; playback is unverified.',
}

def category(value):
    return value if type(value) is str and value in MESSAGES else 'gui_worker_failure'

def explanation(value):
    return MESSAGES[category(value)]

def safe_status(status):
    """Allowlisted scalars only; never copy provider dictionaries wholesale."""
    status = status if type(status) is dict else {}
    result = {}
    for key in ('status','failure_stage','citation_validation_status','done_reason'):
        value = (status or {}).get(key)
        if type(value) is str and value in {'success','failed','insufficient_evidence','cancelled','request','backend','retrieval','authorization','pre_inference','generation','validation','verified','rejected','not_run','no_claims','stop','length','unspecified'}:
            result[key] = value
    if (status or {}).get('failure_category'):
        result['failure_category'] = category(status['failure_category'])
    for key in ('retrieved_evidence_count','output_token_count','elapsed_seconds'):
        value = (status or {}).get(key)
        if type(value) in (int,float) and 0 <= value <= 1e9:
            result[key] = value
    return result
