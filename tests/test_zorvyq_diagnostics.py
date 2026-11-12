import unittest
from zorvyq.diagnostics import explanation, safe_status, category

class DiagnosticsTests(unittest.TestCase):
 def test_failures_are_distinct_and_unknown_details_never_leak(self):
  kinds=('no_evidence','authorization_denied','model_unavailable','connection_failure','generation_timeout','output_length','invalid_response','citation_rejected','synchronization_failure','gui_worker_failure')
  self.assertEqual(len({explanation(k) for k in kinds}),len(kinds))
  self.assertEqual(category('private exception text'),'gui_worker_failure')
  self.assertNotIn('private',explanation('private exception text'))
 def test_status_rejects_content_and_unknown_stage(self):
  result=safe_status({'status':'failed','failure_category':'citation_rejected','failure_stage':'validation','question':'SECRET','answer':'SECRET','done_reason':'SECRET','elapsed_seconds':1.2})
  self.assertNotIn('SECRET',str(result));self.assertNotIn('question',result)
  self.assertEqual(result['failure_category'],'citation_rejected')
