"""Explicit diagnostic mode: exercise the installed GUI and real bundled workers."""
import json
import os
import subprocess
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from PySide6.QtCore import Qt
from core import binary_directory
from library import DownloadLibrary


def run(api, app, report_path, fixture_path, youtube_url=None):
    report_path=Path(report_path).resolve();report_path.parent.mkdir(parents=True,exist_ok=True)
    root=report_path.parent/'datos de prueba Áé';root.mkdir(exist_ok=True)
    report={'frozen':bool(getattr(sys,'frozen',False)), 'steps':[], 'success':False}
    windows=[];server=None
    gate=threading.Event();gate.set();requests=threading.Event()
    executable_suffix='.exe' if os.name=='nt' else ''
    vendor=binary_directory()
    ffmpeg=vendor/('ffmpeg'+executable_suffix)
    ffprobe=vendor/('ffprobe'+executable_suffix)
    if not ffmpeg.exists() and not getattr(sys,'frozen',False):
        import shutil
        ffmpeg=Path(shutil.which('ffmpeg') or str(ffmpeg));ffprobe=Path(shutil.which('ffprobe') or str(ffprobe))
    def save():report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    def step(name,**details):report['steps'].append({'name':name,'status':'passed',**details});save()
    def pump(predicate,timeout=90):
        deadline=time.monotonic()+timeout
        while not predicate() and time.monotonic()<deadline:
            app.processEvents();time.sleep(.01)
        app.processEvents()
        if not predicate():raise TimeoutError('La operación de prueba no terminó: '+str(report['steps'][-1:] ))
    def probe(filename):
        extra={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
        result=subprocess.run([str(ffprobe),'-v','error','-show_format','-show_streams','-of','json',str(filename)],
                              stdin=subprocess.DEVNULL,capture_output=True,encoding='utf-8',timeout=30,**extra)
        if result.returncode:raise RuntimeError(result.stderr)
        return json.loads(result.stdout)
    def window(name,playlist=None):
        win=api.Window(root/(name+'.json'));windows.append(win)
        win.folder.setText(str(root/'Música y videos'))
        errors=[];win.show_error=errors.append
        if playlist is not None:
            original=win.launch
            def launch(args,success,failure,metadata=False):
                input_file=playlist
                payload=json.loads(playlist.read_text(encoding='utf-8'))
                if not metadata and payload.get('_type')=='playlist':
                    identity=args[-1].split('v=')[-1]
                    entry=next(i for i in payload['entries'] if i['id']==identity)
                    input_file=root/(identity+'.json')
                    input_file.write_text(json.dumps(entry),encoding='utf-8')
                return original(['--no-clean-info-json','--load-info-json',str(input_file)]+args,success,failure,metadata)
            win.launch=launch
        win.show();app.processEvents();return win,errors
    try:
        if os.name=='nt' and getattr(sys,'frozen',False):
            # Compare the inherited-input pattern used before the Windows fix.
            try:
                legacy=subprocess.Popen(api.engine_command()+['--version'],stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
                output,_=legacy.communicate(timeout=15)
                report['legacy_inherited_stdin']={'status':'not_reproduced','exit_code':legacy.returncode,
                                                  'output':output.decode('utf-8',errors='replace')[:500]}
            except OSError as exc:
                report['legacy_inherited_stdin']={'status':'reproduced','winerror':getattr(exc,'winerror',None),'error':str(exc)}
            except subprocess.TimeoutExpired:
                legacy.kill();legacy.communicate(timeout=5)
                report['legacy_inherited_stdin']={'status':'timeout'}
            save()
        fixture=Path(fixture_path).read_bytes()
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.set();gate.wait(15)
                content=b'invalid audio and video' if self.path=='/bad.mp4' else fixture
                self.send_response(200);self.send_header('Content-Type','video/mp4')
                self.send_header('Content-Length',str(len(content)));self.end_headers()
                try:self.wfile.write(content)
                except (BrokenPipeError,ConnectionResetError):pass
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        def info(identity,title,path='/prueba.mp4'):
            return {'id':identity,'title':title,'_type':'video','duration':2,'extractor':'youtube','extractor_key':'Youtube',
                    'webpage_url':'https://www.youtube.com/watch?v='+identity,
                    'formats':[{'format_id':'18','url':f'http://127.0.0.1:{server.server_port}'+path,
                                'ext':'mp4','vcodec':'avc1.42c00b','acodec':'mp4a.40.2','width':256,'height':144,'protocol':'http'}]}
        playlist=root/'playlist.json'
        playlist.write_text(json.dumps({'_type':'playlist','id':'test','title':'Lista sintética','extractor':'youtube:tab','extractor_key':'YoutubeTab','webpage_url':'https://www.youtube.com/playlist?list=prueba','entries':[
            info('testclip001','Canción Áéíóú 1'),info('testclip002','Canción Áéíóú 2'),info('testclip003','Canción Áéíóú 3')]}),encoding='utf-8')
        win,errors=window('cola',playlist);win.url.setText('https://www.youtube.com/playlist?list=prueba')
        win.analyze.click();pump(lambda:win.worker is None)
        assert not errors and len(win.items)==3,errors
        step('metadata_real_worker',loaded=3,engine=api.engine_command()[0])
        gate.clear();requests.clear();win.download.click();pump(requests.is_set)
        for control in (win.table,win.search,win.select_all_check,win.range_input,win.range_button,win.open_folder):
            assert control.isEnabled(),control.objectName()
        win.table.sortItems(2,Qt.DescendingOrder);win.search.setText('3')
        assert sum(not win.table.isRowHidden(r) for r in range(3))==1
        row=next(r for r in range(3) if win.table.item(r,0).data(Qt.UserRole)==2)
        win.table.item(row,0).setCheckState(Qt.Unchecked)
        win.search.clear();win.grab().save(str(report_path.parent/'descarga-activa.png'))
        gate.set();pump(lambda:not win.running and win.worker is None)
        assert [i['status'] for i in win.items]==['done','done','pending'],win.items
        audio_files=[Path(i['file']) for i in win.items[:2]]
        for file in audio_files:
            media=probe(file)
            assert file.suffix=='.mp3' and file.is_file()
            assert any(s['codec_name']=='mp3' for s in media['streams'])
            assert float(media['format']['duration'])>1
            assert '[' not in file.name
        assert not errors,errors
        step('mp3_real_download_and_conversion',files=[f.name for f in audio_files],live_controls=True)
        library=DownloadLibrary(win.folder.text())
        try:
            assert library.contains('testclip001','MP3') and not library.contains('testclip003','MP3')
        finally:library.close()
        win.launch(['--dump-json','--simulate','--flat-playlist','--ignore-config'],win.inspected,win.inspect_failed,True)
        pump(lambda:win.worker is None)
        assert len(win.items)==1 and 'testclip003' in win.items[0]['url'],win.items
        step('next_batch_skips_existing_files',loaded=1)
        win.mode.setCurrentIndex(0);win.format.setCurrentText('MP4');win.download.click()
        pump(lambda:not win.running and win.worker is None)
        assert win.items[0]['status']=='done',win.items
        video=Path(win.items[0]['file']);media=probe(video)
        assert video.suffix=='.mp4' and any(s['codec_type']=='video' for s in media['streams'])
        step('mp4_real_download',filename=video.name)
        cancel_info=root/'cancel.json';cancel_info.write_text(json.dumps(info('cancel00001','Prueba cancelar')),encoding='utf-8')
        cancel,cancel_errors=window('cancelar',cancel_info)
        cancel.inspected(info('cancel00001','Prueba cancelar'))
        gate.clear();requests.clear();cancel.download.click();pump(requests.is_set)
        cancel.cancel.click();pump(lambda:cancel.worker is None and not cancel.running,30)
        gate.set();assert cancel.items[0]['status']=='pending',cancel.items
        assert cancel.analyze.isEnabled() and cancel.table.isEnabled()
        step('cancel_worker_without_hanging')
        bad_info=root/'bad.json';bad_info.write_text(json.dumps(info('badclip0001','Archivo dañado','/bad.mp4')),encoding='utf-8')
        bad,bad_errors=window('fallo',bad_info);bad.inspected(info('badclip0001','Archivo dañado'))
        bad.download.click();pump(lambda:not bad.running and bad.worker is None)
        assert bad.items[0]['status']=='failed' and bad.retry.isEnabled(),bad.items
        assert bad.analyze.isEnabled() and bad.table.isEnabled()
        step('conversion_failure_recovers_controls',error=bad.items[0].get('error','')[:1500])
        if youtube_url:
            live,live_errors=window('youtube');live.url.setText(youtube_url);live.analyze.click()
            pump(lambda:live.worker is None,200)
            if live_errors:
                reason='\n'.join(live_errors)
                if any(text in reason.lower() for text in ("not a bot",'video unavailable','private video','has been removed','sign in to confirm your age')):
                    report['youtube']={'status':'external_service_restriction','reason':reason[:2000]}
                else:raise RuntimeError('Falló el análisis real de YouTube: '+reason)
            else:
                assert live.items,live.status.text();live.download.click()
                pump(lambda:not live.running and live.worker is None,240)
                if live.items[0]['status']!='done':
                    reason=live.items[0].get('error','')
                    if 'not a bot' in reason.lower():report['youtube']={'status':'external_service_restriction','reason':reason[:2000]}
                    else:raise RuntimeError('Falló la descarga real de YouTube: '+reason)
                else:
                    probe(live.items[0]['file']);report['youtube']={'status':'passed','format':'mp3'}
            save()
        else:report['youtube']={'status':'not_requested'}
        report['success']=True
    except Exception as exc:
        report['error']=str(exc);report['traceback']=traceback.format_exc()
    finally:
        gate.set()
        for win in windows:
            if win.worker:
                win.cancel_queue()
                try:pump(lambda:win.worker is None,30)
                except Exception:pass
            win.close()
        if server:server.shutdown();server.server_close()
        save()
    return 0 if report['success'] else 1
