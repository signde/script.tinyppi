import importlib.util,json,sys,types,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class AdapterTest(unittest.TestCase):
 def setUp(self):
  self.labels={'VideoPlayer.HDRType':'dolbyvision','Player.Process(firetvsource)':json.dumps({'video.dovi.profile':'7','video.bit.depth':'10'}),'Player.Process(firetvfelstatus)':'FEL decoder active','Player.Process(audioqueuelevel)':'68'}
  self.props={}
  sys.modules['xbmc']=types.SimpleNamespace(getInfoLabel=lambda n:self.labels.get(n,''),getCondVisibility=lambda n:True)
  sys.modules['xbmcgui']=types.SimpleNamespace(Window=lambda n:types.SimpleNamespace(setProperty=self.props.__setitem__))
  spec=importlib.util.spec_from_file_location('firetv',ROOT/'resources/lib/info/firetv.py');self.m=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.m)
  self.m.read=lambda p:''
 def test_source_and_active_are_separate(self):
  self.assertEqual(self.m.process('video.bit.depth'),'10')
  self.assertEqual(self.m.process('video.dovi.el.type'),'full')
  self.assertEqual(self.m.process('firetv.fel.status'),'FEL decoder active')
 def test_queue_mapping(self):self.assertEqual(self.m.label('Player.Process(audio.queue.level)'),'68')
 def test_unreadable_hdmi_is_not_guessed(self):self.assertEqual(self.m.process('amlogic.pixformat'),'')
 def test_unknown_rpu_not_fabricated(self):self.assertEqual(self.m.process('video.dovi.l1.max.nits'),'')
 def test_stream_change_clears_old_fields(self):
  self.m.refresh();self.labels['Player.Process(firetvsource)']='{}';self.labels['VideoPlayer.HDRType']='hdr10';self.labels['Player.Process(firetvfelstatus)']=''
  self.m.refresh();self.assertEqual(self.props['SigndeTinyPPI.Process.video.dovi.profile'],'');self.assertEqual(self.m.process('firetv.fel.status'),'Not active')
 def test_invalid_snapshot(self):
  self.labels['Player.Process(firetvsource)']='Player.Process(firetvsource)';self.assertEqual(self.m.process('video.dovi.profile'),'')
 def test_mel_is_not_fel(self):
  self.labels['Player.Process(firetvfelstatus)']='MEL base layer';self.assertEqual(self.m.process('video.dovi.el.type'),'minimum')
 def test_cpu_is_kodi_process_fraction_of_all_cores(self):
  self.m.time=types.SimpleNamespace(monotonic=lambda:10.0,process_time=lambda:3.0)
  self.m.os=types.SimpleNamespace(cpu_count=lambda:8)
  self.assertEqual(self.m.cpu_usage(),'Measuring…')
  self.m.time=types.SimpleNamespace(monotonic=lambda:11.0,process_time=lambda:5.0)
  self.assertEqual(self.m.cpu_usage(),'Kodi 25.0%')
 def test_received_metadata_is_exposed_without_guessing(self):
  self.labels['Player.Process(firetvsource)']=json.dumps({'video.dovi.l1.max.pq':'3079','video.hdr.max.cll':'1000'})
  self.assertEqual(self.m.process('video.dovi.l1.max.pq'),'3079')
  self.assertEqual(self.m.process('video.hdr.max.cll'),'1000')
  self.assertEqual(self.m.process('video.dovi.l6.max.fall'),'')
unittest.main()
