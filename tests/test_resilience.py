import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys, time, json, errno
from pathlib import Path
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from main import Window, Engine
from limits import MAX_PLAYLIST_ITEMS, playlist_items, PlaylistLimitError
from core import save_state, load_state, download_arguments
import main

@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])

def pump(app, predicate):
    until=time.monotonic()+10
    while not predicate() and time.monotonic()<until:
        app.processEvents(); time.sleep(.01)
    app.processEvents(); assert predicate()

def entries(n):
    return [{'id':str(i),'title':f'Tema {i}'} for i in range(n)]

@pytest.mark.parametrize('size',[1001,2000,200000])
def test_large_playlist_rejected_before_changing_queue(app,tmp_path,monkeypatch,size):
    window=Window(tmp_path/'queue.json')
    window.inspected({'id':'saved','title':'Conservar'})
    before=window.items
    errors=[]; monkeypatch.setattr(window,'show_error',errors.append)
    # Only the reported total is needed; the worker never reads all those entries.
    window.inspected({'_type':'playlist','playlist_count':size,'entries':entries(1001)})
    assert window.items is before and window.table.rowCount()==1
    assert load_state(tmp_path/'queue.json')['items'][0]['title']=='Conservar'
    assert errors and '1000' in errors[0]
    assert window.progress.maximum()==100 and window.analyze.isEnabled()
    window.close()

def test_exact_limit_sort_filter_range_and_event_loop(app,tmp_path):
    window=Window(tmp_path/'queue.json')
    window.inspected({'_type':'playlist','playlist_count':1000,'entries':entries(1000)})
    window.show();app.processEvents()
    assert window.table.rowCount()==MAX_PLAYLIST_ITEMS
    window.table.sortItems(1,Qt.DescendingOrder)
    window.search.setText('Tema 999')
    assert sum(not window.table.isRowHidden(i) for i in range(1000))==1
    window.search.clear();window.range_input.setText('1,1000');window.choose_range()
    assert sum(i['selected'] for i in window.items)==2
    window.close()

def test_inspection_requests_only_limit_plus_one(app,tmp_path,monkeypatch):
    window=Window(tmp_path/'queue.json');calls=[]
    window.url.setText('https://www.youtube.com/playlist?list=example')
    monkeypatch.setattr(window,'launch',lambda *args:calls.append(args))
    window.inspect(); args=calls[0][0]
    assert args[args.index('--playlist-end')+1]=='200000'
    assert '--ignore-config' in args
    window.controls(False);window.close()

@pytest.mark.parametrize('info',[None,[],{'_type':'playlist','entries':None},{'_type':'playlist','entries':['bad']},{'id':12},{'id':'ok','title':123}])
def test_malformed_metadata_has_explainable_error(info):
    with pytest.raises(ValueError):playlist_items(info)

def test_legacy_1500_is_preserved_but_cannot_start_download(app,tmp_path,monkeypatch):
    path=tmp_path/'queue.json'
    old=[{'url':'https://youtu.be/'+str(i),'title':str(i),'status':'done' if i<272 else 'pending'} for i in range(1500)]
    save_state(path,{'items':old})
    window=Window(path)
    assert len(window.items)==1500
    monkeypatch.setattr(window,'launch',lambda *args:pytest.fail('Legacy queue must not download'))
    window.start_queue()
    assert not window.running and '1000' in window.status.text()
    window.close();assert len(load_state(path)['items'])==1500

def test_saved_queue_200000_is_bounded_and_preserved(tmp_path,monkeypatch):
    import core
    path=tmp_path/'queue.json'
    path.write_text(json.dumps({'items':[{'title':'x','status':'pending'}]*200000}))
    assert load_state(path)=={}
    save_state(path,{'items':[]})
    assert path.with_name('queue.recovery.json').exists()
    assert path.with_name('queue.recovery.json').stat().st_size>MAX_PLAYLIST_ITEMS

@pytest.mark.parametrize('kind',['invalid_title','invalid_settings','invalid_url','invalid_selection'])
def test_corrupted_saved_fields_restore_previous_good_queue(tmp_path,kind):
    path=tmp_path/'queue.json'
    good={'items':[{'title':'Conservar','status':'done'}]}
    save_state(path,good)
    bad={'title':'Tema','status':'pending'}
    if kind=='invalid_title':bad['title']=None
    if kind=='invalid_settings':bad['settings']=[]
    if kind=='invalid_url':bad['url']='file:///test'
    if kind=='invalid_selection':bad['selected']='yes'
    save_state(path,{'items':[bad]})
    assert load_state(path)==good

@pytest.mark.parametrize('activity',[False,True])
def test_worker_timeout_ends_silent_or_busy_process(app,tmp_path,monkeypatch,activity):
    script='import time\nwhile True:\n print("waiting",flush=True);time.sleep(.03)' if activity else 'import time;time.sleep(30)'
    monkeypatch.setattr(main,'engine_command',lambda:[sys.executable,'-c',script])
    worker=Engine([],metadata=True,timeout=.25,inactivity_timeout=.12)
    errors=[];worker.problem.connect(errors.append);worker.start()
    pump(app,lambda:not worker.isRunning())
    assert errors and 'tardó demasiado' in errors[0]
    assert worker.process.poll() is not None

def test_worker_bounds_output(app,tmp_path,monkeypatch):
    monkeypatch.setattr(main,'MAX_OUTPUT_BYTES',1024)
    monkeypatch.setattr(main,'engine_command',lambda:[sys.executable,'-c','print("x"*2000)'])
    worker=Engine([],metadata=True);errors=[];worker.problem.connect(errors.append);worker.start()
    pump(app,lambda:not worker.isRunning())
    assert errors and 'demasiado grande' in errors[0]

def test_invalid_json_does_not_leave_worker_running(app,monkeypatch):
    monkeypatch.setattr(main,'engine_command',lambda:[sys.executable,'-c','print("{broken")'])
    worker=Engine([],metadata=True);errors=[];worker.problem.connect(errors.append);worker.start()
    pump(app,lambda:not worker.isRunning())
    assert errors and worker.process.poll() is not None

def test_full_disk_pauses_before_launch(app,tmp_path,monkeypatch):
    from collections import namedtuple
    usage=namedtuple('usage','total used free')
    monkeypatch.setattr(main.shutil,'disk_usage',lambda path:usage(100,100,0))
    monkeypatch.setattr(main.shutil,'which',lambda name:'mock-ffmpeg')
    window=Window(tmp_path/'queue.json');window.folder.setText(str(tmp_path))
    window.inspected({'_type':'playlist','entries':entries(2)})
    window.start_queue();pump(app,lambda:not window.running and window.worker is None)
    assert [i['status'] for i in window.items]==['failed','pending']
    assert 'espacio' in window.status.text()
    window.close()

def test_five_consecutive_network_errors_pause_remaining_items(app,tmp_path,monkeypatch):
    monkeypatch.setattr(main,'engine_command',lambda:[sys.executable,'-c','import sys;print("ERROR: offline");sys.exit(1)'])
    monkeypatch.setattr(main.shutil,'which',lambda name:'mock-ffmpeg')
    window=Window(tmp_path/'queue.json');window.folder.setText(str(tmp_path))
    window.inspected({'_type':'playlist','entries':entries(8)})
    window.start_queue();pump(app,lambda:not window.running and window.worker is None)
    assert [i['status'] for i in window.items]==['failed']*5+['pending']*3
    assert '5 fallos' in window.status.text()
    window.close()

def test_missing_engine_releases_controls(app,tmp_path,monkeypatch):
    monkeypatch.setattr(main,'engine_command',lambda:['missing-component-that-does-not-exist'])
    monkeypatch.setattr(main.shutil,'which',lambda name:'mock-ffmpeg')
    window=Window(tmp_path/'queue.json');window.folder.setText(str(tmp_path))
    window.inspected({'id':'a','title':'Tema'})
    window.start_queue();pump(app,lambda:not window.running and window.worker is None)
    assert window.download.isEnabled() and not window.cancel.isEnabled()
    assert 'componente' in window.status.text()
    window.close()

def test_invalid_stored_settings_fail_before_engine_launch(app,tmp_path,monkeypatch):
    monkeypatch.setattr(main.shutil,'which',lambda name:'mock-ffmpeg')
    window=Window(tmp_path/'queue.json');window.inspected({'id':'a','title':'Tema'})
    window.items[0]['settings']={'mode':'video','format':'MP4','quality':'bad','folder':str(tmp_path)}
    window.start_queue()
    assert not window.running and window.worker is None
    assert window.items[0]['status']=='pending'
    window.close()


def test_successive_batches_skip_real_files_and_include_deleted_ones(app,tmp_path,monkeypatch):
    from library import DownloadLibrary
    import limits
    monkeypatch.setattr(main,'MAX_PLAYLIST_ITEMS',3)
    monkeypatch.setattr(limits,'MAX_PLAYLIST_ITEMS',3)
    data=entries(8)
    script='import json\nfor item in '+repr(data)+':\n print(json.dumps(item),flush=True)'
    monkeypatch.setattr(main,'engine_command',lambda:[sys.executable,'-c',script])
    def process():
        worker=Engine(['--dump-json'],metadata=True)
        worker.library_folder=str(tmp_path)
        result=[];errors=[];worker.result.connect(result.append);worker.problem.connect(errors.append)
        worker.start();pump(app,lambda:not worker.isRunning())
        assert not errors,errors
        return result[0]
    def mark_done(batch):
        library=DownloadLibrary(tmp_path)
        try:
            for item in batch['entries']:
                path=tmp_path/(item['title']+'.mp3');path.write_bytes(b'audio')
                library.remember(item['id'],path)
        finally:library.close()
    first=process();assert [i['id'] for i in first['entries']]==['0','1','2'];mark_done(first)
    second=process();assert [i['id'] for i in second['entries']]==['3','4','5'];mark_done(second)
    third=process();assert [i['id'] for i in third['entries']]==['6','7'];mark_done(third)
    assert process()['entries']==[]
    (tmp_path/'Tema 0.mp3').unlink()
    assert [i['id'] for i in process()['entries']]==['0']

def test_index_only_skips_matching_format_inside_destination(tmp_path):
    from library import DownloadLibrary
    file=tmp_path/'Tema.mp3';file.write_bytes(b'audio')
    index=DownloadLibrary(tmp_path)
    try:
        index.remember('example',file)
        assert index.contains('example','MP3')
        assert not index.contains('example','MP4')
        file.unlink();assert not index.contains('example','MP3')
    finally:index.close()

def test_existing_completed_queue_seeds_folder_index(app,tmp_path,monkeypatch):
    file=tmp_path/'Título sin código.mp3';file.write_bytes(b'audio')
    old=[{'url':'https://www.youtube.com/watch?v=done','file':str(file),'status':'done'}]
    script='import json;print(json.dumps({"id":"done","title":"Video original"}));print(json.dumps({"id":"new","title":"Nueva"}))'
    monkeypatch.setattr(main,'engine_command',lambda:[sys.executable,'-c',script])
    worker=Engine(['--dump-json'],metadata=True);worker.library_folder=str(tmp_path);worker.existing_items=old
    result=[];worker.result.connect(result.append);worker.start();pump(app,lambda:not worker.isRunning())
    assert [i['id'] for i in result[0]['entries']]==['new']
    assert result[0]['skipped']==1


def test_preparing_1000_keeps_payload_small_and_gui_can_continue(app,tmp_path,monkeypatch):
    data=entries(1001)
    script='import json\nfor item in '+repr(data)+':\n item["unneeded"]="x"*10000;print(json.dumps(item),flush=True)'
    # Write a script instead of exceeding the Windows command-line limit.
    source=tmp_path/'fixture.py';source.write_text(script)
    monkeypatch.setattr(main,'engine_command',lambda:[sys.executable,str(source)])
    worker=Engine(['--dump-json'],metadata=True);worker.library_folder=str(tmp_path)
    result=[];worker.result.connect(result.append);worker.start();pump(app,lambda:not worker.isRunning())
    assert len(result[0]['entries'])==1000
    assert all(set(i)=={'id','title'} for i in result[0]['entries'])
    assert len(json.dumps(result[0]))<100000


def test_live_filter_sort_scroll_and_selection_affect_next_download(app,tmp_path,monkeypatch):
    from PySide6.QtWidgets import QAbstractSlider
    destination=tmp_path/'downloads';destination.mkdir()
    ready=tmp_path/'ready';release=tmp_path/'release'
    source=tmp_path/'download_fixture.py'
    source.write_text('''import sys,time
from pathlib import Path
from urllib.parse import urlparse,parse_qs
identity=parse_qs(urlparse(sys.argv[-1]).query)['v'][0]
root=Path(sys.argv[sys.argv.index('-P')+1])
if identity=='0':
 Path('''+repr(str(ready))+''').write_text('ready')
 while not Path('''+repr(str(release))+''').exists():time.sleep(.02)
file=root/('Tema '+identity+'.mp3');file.write_bytes(b'audio')
print('DF_FILE:'+str(file),flush=True)
''',encoding='utf-8')
    monkeypatch.setattr(main,'engine_command',lambda:[sys.executable,str(source)])
    monkeypatch.setattr(main.shutil,'which',lambda name:'bundled-ffmpeg')
    window=Window(tmp_path/'queue.json');window.folder.setText(str(destination))
    window.inspected({'_type':'playlist','entries':entries(25)})
    window.items[1]['status']='done';window.render();window.show();app.processEvents()
    window.start_queue();pump(app,ready.exists)
    try:
        assert window.running and window.current is window.items[0]
        for control in (window.table,window.search,window.url,window.select_all_check,window.range_input,window.range_button,window.open_folder):
            assert control.isEnabled()
        for control in (window.analyze,window.mode,window.format,window.quality,window.change_folder,window.download,window.retry):
            assert not control.isEnabled()
        window.table.sortItems(2,Qt.DescendingOrder)
        window.search.setText('Tema 24');app.processEvents()
        visible=[r for r in range(window.table.rowCount()) if not window.table.isRowHidden(r)]
        assert len(visible)==1 and window.table.item(visible[0],0).data(Qt.UserRole)==24
        window.search.clear();app.processEvents()
        scroll=window.table.verticalScrollBar();scroll.triggerAction(QAbstractSlider.SliderToMaximum)
        assert scroll.value()==scroll.maximum() and scroll.maximum()>0
        window.select_all_check.click();assert not any(i['selected'] for i in window.items)
        assert window.items[0]['status']=='downloading' and window.items[1]['status']=='done'
        window.range_input.setText('1,3,25');window.range_button.click()
        row=next(r for r in range(25) if window.table.item(r,0).data(Qt.UserRole)==24)
        window.table.item(row,0).setCheckState(Qt.Unchecked)
        assert [i for i,item in enumerate(window.items) if item['selected']]==[0,2]
        saved=load_state(tmp_path/'queue.json')
        assert not saved['items'][24]['selected']
        # Pasting the next link cannot replace an active queue even with Enter.
        window.url.setText('https://youtu.be/next');current_items=window.items
        window.inspect();assert window.items is current_items
        release.write_text('go');pump(app,lambda:not window.running and window.worker is None)
        assert [i for i,item in enumerate(window.items) if item['status']=='done']==[0,1,2]
        assert window.items[24]['status']=='pending'
        assert len(list(destination.glob('*.mp3')))==2
        assert all(control.isEnabled() for control in (window.table,window.mode,window.format,window.change_folder))
    finally:
        release.write_text('go')
        if window.worker:
            window.cancel_queue();pump(app,lambda:window.worker is None)
        window.close()
