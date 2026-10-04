import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import analyze, safe_flags, steam_scan, vdf, normalize, DataClient, report_hash
from app import make_handler

NOW = 1790985600
HW = {'gpus': ['NVIDIA GeForce RTX 4070'], 'gamemode': True, 'mangohud': False}
def report(version='10.0-3', success='yes', age=10, gpu='NVIDIA RTX 4070', key='a', notes=''):
    return {'id':key, 'appId':'123', 'timestamp':NOW-age*86400,
            'responses':{'verdict':success,'protonVersion':version,'notes':{'verdict':notes}},
            'device':{'hardwareType':'pc','inferred':{'steam':{'gpu':gpu}}}}

class CoreTests(unittest.TestCase):
    def test_vdf_nested_escaped(self):
        self.assertEqual(vdf('"x" { "y" "A \\"B\\"" "z" { "path" "/a/b" } }')['x']['z']['path'], '/a/b')
    def test_scan_external_flatpak_dedupe(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'.var/app/com.valvesoftware.Steam/.local/share/Steam'; (root/'steamapps').mkdir(parents=True)
            extra=Path(d)/'Games'; (extra/'steamapps').mkdir(parents=True)
            (root/'steamapps/libraryfolders.vdf').write_text('"libraryfolders" { "0" { "path" "'+str(extra)+'" } }')
            (extra/'steamapps/appmanifest_123.acf').write_text('"AppState" { "appid" "123" "name" "Test Game" }')
            (extra/'steamapps/appmanifest_456.acf').write_text('"AppState" { "appid" "456" "name" "Proton Experimental" }')
            got=steam_scan(d, [str(extra)])
            self.assertEqual(len(got['games']),1); self.assertEqual(got['protons'],['Proton Experimental'])
    def test_live_variant_fields(self):
        row=report(); row['responses'].update(variant='experimental', protonVersion='10.0-3')
        self.assertEqual(normalize(row,'123')['version'],'Proton Experimental')
        row['responses'].update(variant='ge',customProtonVersion='GE-Proton11-6')
        self.assertEqual(normalize(row,'123')['version'],'GE-Proton11-6')
        row['responses'].pop('customProtonVersion');row['responses']['variant']='notListed';row['responses']['notes']['variant']='proton-cachyos-11.0'
        self.assertEqual(normalize(row,'123')['version'],'proton-cachyos-11.0')
    def test_launch_field_and_conclusion(self):
        row=report();row['responses']['launchOptions']='PROTON_NO_FSYNC=1 %command% --launcher-skip';row['responses']['concludingNotes']='A real conclusion'
        normalized=normalize(row,'123')
        self.assertIn('A real conclusion',normalized['notes'])
        self.assertEqual(safe_flags(normalized['launchOptions'],HW),['PROTON_NO_FSYNC=1 %command% --launcher-skip'])
    def test_wrong_game_answer_rejected(self):
        row=report();row.pop('appId');row['responses']['answerToWhatGame']='999'
        self.assertIsNone(normalize(row,'123'))
    def test_no_evidence_no_claim(self):
        self.assertIsNone(analyze([], '123', HW, NOW)['recommendation'])
    def test_single_report_not_recommended(self):
        self.assertIsNone(analyze([report()], '123', HW, NOW)['recommendation'])
    def test_old_and_deck_excluded(self):
        deck=report(key='deck');deck['device']['hardwareType']='steamDeck'
        a=analyze([report(age=400),report(age=401,key='b'),deck], '123', HW, NOW)
        self.assertIsNone(a['recommendation']);self.assertEqual(a['sample'],2)
    def test_hardware_matching_wins(self):
        rows=[report('A',key='a'),report('A',key='b'),report('B',gpu='AMD Radeon',key='c'),report('B',gpu='AMD Radeon',key='d')]
        self.assertEqual(analyze(rows,'123',HW,NOW)['recommendation'],'A')
    def test_failures_reduce_score(self):
        rows=[report(key='a'),report(key='b')]+[report(success='no',key=str(i)) for i in range(4)]
        self.assertIsNone(analyze(rows,'123',HW,NOW)['recommendation'])
    def test_dedup(self):
        a=analyze([report(),report()], '123', HW, NOW)
        self.assertEqual(a['sample'],1); self.assertIsNone(a['recommendation'])
    def test_wrong_app_excluded(self):
        self.assertIsNone(normalize(report(),'456'))
    def test_flags_no_shell_or_unknown_or_bad_order(self):
        for s in ['rm -rf / %command%', 'PROTON_NO_FSYNC=1 %command%; reboot', 'FOO=1 %command%', 'gamemoderun PROTON_NO_FSYNC=1 %command%', 'PROTON_LOG=$(whoami) %command%', 'mangohud %command%']:
            self.assertEqual(safe_flags(s,HW),[])
    def test_flags_repeated_and_same_vendor(self):
        f='PROTON_NO_FSYNC=1 gamemoderun %command%'
        a=analyze([report(key='a',notes=f),report(key='b',notes=f)],'123',HW,NOW)
        self.assertEqual(a['flags'],f);self.assertEqual(a['flagReports'],2)
        a=analyze([report(key='a',notes=f),report(key='b',notes=f,gpu='AMD Radeon')],'123',HW,NOW)
        self.assertEqual(a['flags'],'')
    def test_future_and_unknown_date_not_ranked(self):
        self.assertIsNone(analyze([report(age=-100),report(age=-200,key='b')],'123',HW,NOW)['recommendation'])
    def test_nv_flags_not_on_amd(self):
        self.assertEqual(safe_flags('PROTON_ENABLE_NVAPI=1 %command%',{'gpus':['AMD Radeon']}),[])
    def test_cache_marks_stale(self):
        with tempfile.TemporaryDirectory() as d:
            c=DataClient(d)
            class Response:
                def __enter__(self):return self
                def __exit__(self,*args):pass
                def read(self,n):return b'{"ok":true}'
            with patch('urllib.request.urlopen',return_value=Response()): c.get('https://test.invalid')
            with patch('urllib.request.urlopen',side_effect=OSError('offline')):
                data,meta=c.get('https://test.invalid',refresh=True)
                self.assertTrue(data['ok']);self.assertTrue(meta['stale'])
    def test_mock_report_endpoint(self):
        with tempfile.TemporaryDirectory() as d:
            c=DataClient(d)
            def fetch(url,**kwargs):
                if 'summaries' in url:return {'tier':'gold'},{}
                if 'counts' in url:return {'reports':411787,'timestamp':1774011569},{}
                return {'reports':[report(),report(key='b')],'total':2},{}
            with patch.object(c,'get',side_effect=fetch):
                summary,rows,errors,metas=c.reports('123')
            self.assertEqual(len(rows),2); self.assertFalse(errors)

class ServerTests(unittest.TestCase):
    def setUp(self):
        self.server=ThreadingHTTPServer(('127.0.0.1',0),make_handler({'token':'secret','hardware':HW,'steam':{'games':[]}}))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url=f'http://127.0.0.1:{self.server.server_port}'
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
    def test_token_required(self):
        with self.assertRaises(urllib.error.HTTPError) as e:urllib.request.urlopen(self.url+'/api/system')
        self.assertEqual(e.exception.code,403)
    def test_invalid_host_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as e:urllib.request.urlopen(urllib.request.Request(self.url+'/',headers={'Host':'evil.test'}))
        self.assertEqual(e.exception.code,403)
    def test_authorized_and_csp(self):
        req=urllib.request.Request(self.url+'/api/system',headers={'X-Scout-Token':'secret'})
        with urllib.request.urlopen(req) as r:
            self.assertIn("frame-ancestors 'none'",r.headers['Content-Security-Policy'])
            self.assertEqual(json.load(r)['hardware'],HW)
    def test_import_does_not_execute_text(self):
        body=json.dumps({'id':'123','reports':[report(notes='<script>alert(1)</script>')]}).encode()
        req=urllib.request.Request(self.url+'/api/import',data=body,headers={'X-Scout-Token':'secret','Content-Type':'application/json'})
        with urllib.request.urlopen(req) as r:self.assertEqual(json.load(r)['analysis']['flags'],'')

if __name__=='__main__':unittest.main()
