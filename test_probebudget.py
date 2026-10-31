import unittest
from urllib.error import HTTPError
from urllib.request import Request,urlopen
from probebudget import Service,serve,request,diagnose,calibrate,allowed_frame,encode,SECRET,CORE

class Probes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.costs=calibrate()['max_measured_frame_bytes']
    def run_fault(self,fault,budget=170,strategy='information'):
        with serve(Service(fault)) as url:return diagnose(url,self.costs,budget=budget,strategy=strategy)
    def test_actual_http_single_fault_diagnosis(self):
        for fault in ('stale','slow','retry'):
            with self.subTest(fault=fault):
                r=self.run_fault(fault);self.assertEqual(r['diagnosis'],fault)
                self.assertLessEqual(r['emitted_bytes'],170);self.assertTrue(r['secret_absent'])
    def test_compound_and_unmodeled_abstain(self):
        for fault in ('dual','unmodeled'):
            r=self.run_fault(fault);self.assertTrue(r['abstained']);self.assertIsNone(r['diagnosis'])
    def test_zero_budget_and_partial_signature_abstain(self):
        for budget in (0,60,100):
            r=self.run_fault('stale',budget);self.assertTrue(r['abstained']);self.assertLessEqual(r['emitted_bytes'],budget)
    def test_service_actual_serialized_budget_and_allowlist(self):
        with serve(Service('stale')) as url:
            r=request(url,['cache','context'],50)
        self.assertEqual(r['emitted_bytes'],sum(len(encode(f)) for f in r['frames']))
        self.assertNotIn(SECRET,encode(r).decode());self.assertIn('context',r['skipped'])
        self.assertEqual(allowed_frame('cache',{'stale':True,'authorization':SECRET})['values'],{'stale':True})
    def test_all_probe_baseline_spends_more(self):
        selected=self.run_fault('retry');all_probes=self.run_fault('retry',strategy='all')
        self.assertGreater(all_probes['emitted_bytes'],selected['emitted_bytes'])
        self.assertTrue(all_probes['budget_exceeded'])
    def test_invalid_http_probe_request_has_no_service_action(self):
        service=Service('healthy')
        with serve(service) as url:
            for payload in (b'[]',b'{"probes":["secret"],"budget":100}',b'{"probes":[],"budget":true}'):
                with self.assertRaises(HTTPError) as error:urlopen(Request(url+'/checkout',data=payload),timeout=3)
                self.assertEqual(error.exception.code,400)
        self.assertEqual(service.requests,0)
    def test_decorative_probe_cannot_identify(self):
        # Full signature verification is necessary even when a partial model has one candidate.
        r=self.run_fault('unmodeled',100);self.assertIsNone(r['diagnosis'])
    def test_report_has_measured_cpu_request_and_byte_cost(self):
        r=self.run_fault('retry');self.assertGreater(r['service_cpu_ns'],0);self.assertGreater(r['capture_cpu_ns'],0)
        self.assertGreater(r['http_requests'],1);self.assertEqual(r['emitted_bytes'],sum(len(encode(f)) for f in r['frames']))

if __name__=='__main__':unittest.main()
