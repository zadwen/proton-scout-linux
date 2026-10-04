import unittest
from test_core import report, HW, NOW
from core import analyze, normalize, parse_profile, canonical_version, match_gpu

class AccuracyTests(unittest.TestCase):
    def test_single_report_profile_is_visible_without_winner(self):
        r=report();r['responses']['launchOptions']='VKD3D_CONFIG=single_queue %command%'
        a=analyze([r],'123',HW,NOW)
        self.assertIsNone(a['recommendation']);self.assertEqual(len(a['profiles']),1)
        self.assertEqual(a['profiles'][0]['positive'],1)
        self.assertEqual(a['flagStatus'],'Reported launch options found')
    def test_unknown_flags_preserved_for_review(self):
        r=report();r['responses']['launchOptions']='PROTON_NEW_OPTION=1 %command%'
        p=analyze([r],'123',HW,NOW)['profiles'][0]
        self.assertIn('PROTON_NEW_OPTION',p['command']);self.assertFalse(p['copyable'])
    def test_no_data_is_not_no_flags_required(self):
        a=analyze([],'123',HW,NOW)
        self.assertEqual(a['flagStatus'],'Launch-option evidence unavailable')
        self.assertIn('does not mean',a['flagMessage'])
    def test_oob_requires_explicit_field(self):
        a=analyze([report()],'123',HW,NOW)
        self.assertEqual(a['flagStatus'],'Launch-option evidence unavailable')
        r=report();r['responses']['verdictOob']='yes'
        self.assertIn('out-of-box',analyze([r],'123',HW,NOW)['flagStatus'])
    def test_old_hotfix_does_not_outrank_recent_version(self):
        rows=[report('Proton Hotfix',key=str(i),age=70) for i in range(20)]
        rows += [report('11.0-1',key='new1'),report('11.0-1',key='new2')]
        a=analyze(rows,'123',HW,NOW)
        self.assertEqual(a['recommendation'],'11.0-1')
        self.assertFalse(next(g for g in a['ranking'] if g['rolling'])['eligible'])
    def test_rolling_needs_three_recent_matches(self):
        rows=[report('Proton Hotfix',key=str(i)) for i in range(2)]
        self.assertIsNone(analyze(rows,'123',HW,NOW)['recommendation'])
        rows.append(report('Proton Hotfix',key='third'))
        self.assertEqual(analyze(rows,'123',HW,NOW)['recommendation'],'Proton Hotfix')
    def test_conflicting_close_versions_not_forced(self):
        rows=[report(v,key=v+str(i)) for v in ['10.0-3','11.0-1'] for i in range(2)]
        self.assertIsNone(analyze(rows,'123',HW,NOW)['recommendation'])
    def test_contributor_only_latest_counts(self):
        rows=[report(key='old',age=12),report(key='new',age=1)]
        for r in rows:r['contributor']={'id':'same-person'}
        a=analyze(rows,'123',HW,NOW)
        self.assertEqual(a['sample'],1);self.assertEqual(a['reports'][0]['id'],'new')
    def test_ge_architecture_aliases(self):
        self.assertEqual(canonical_version('GE-Proton11-6-x86_64'),'GE-Proton11-6')
        self.assertEqual(canonical_version('proton-hotfix'),'Proton Hotfix')
    def test_hotfix_variant_not_base_version(self):
        r=report();r['responses']['variant']='hotfix'
        self.assertEqual(normalize(r,'123')['version'],'Proton Hotfix')
    def test_gpu_match_not_just_vendor(self):
        self.assertEqual(match_gpu('NVIDIA RTX 4070',HW),'model')
        self.assertEqual(match_gpu('NVIDIA RTX 4070 Ti',HW),'vendor')
        self.assertEqual(match_gpu('AMD Radeon RX 7900 XTX',HW),'other')
    def test_profiles_canonical_environment_order(self):
        rows=[report(key='1'),report(key='2')]
        rows[0]['responses']['launchOptions']='PROTON_NO_FSYNC=1 VKD3D_CONFIG=single_queue %command%'
        rows[1]['responses']['launchOptions']='VKD3D_CONFIG=single_queue PROTON_NO_FSYNC=1 %command%'
        a=analyze(rows,'123',HW,NOW)
        self.assertEqual(len(a['profiles']),1);self.assertEqual(a['profiles'][0]['recent'],2)
    def test_quoted_dll_override_kept(self):
        p=parse_profile('WINEDLLOVERRIDES="version=n,b;winmm=n,b" %command%',HW)
        self.assertIn('winmm=n,b',p['command']);self.assertFalse(p['copyable'])
    def test_discussion_not_automatic_recommendation(self):
        rows=[report(key='1',notes='VKD3D_CONFIG=single_queue %command%'),report(key='2',notes='VKD3D_CONFIG=single_queue %command%')]
        a=analyze(rows,'123',HW,NOW)
        self.assertEqual(a['flags'],'');self.assertFalse(a['profiles'][0]['copyable'])
    def test_specific_report_url(self):
        self.assertTrue(normalize(report(key='abc123'),'123')['source'].endswith('#abc123'))
    def test_duplicate_assignments_not_reordered(self):
        self.assertFalse(parse_profile('PROTON_LOG=0 PROTON_LOG=1 %command%',HW)['copyable'])
