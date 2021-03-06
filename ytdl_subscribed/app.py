import json
import os
import subprocess

from bottle import (
    TEMPLATE_PATH,
    Bottle,
    HTTPError,
    redirect,
    request,
    response,
    route,
    run,
    static_file,
    view
)

from bottle_json_pretty import JSONPrettyPlugin

from .db import YtdlDatabase
from .download import download
from .log import log
from .pool import WorkPool
from .utils import (
    get_env_override,
    get_env_override_set,
    get_resource_path,
    get_storage_path,
    get_ydl_options
)

db = YtdlDatabase.factory(get_env_override('YDL_DB_BACKEND', default='sqlite', quiet=False))
db.do_migrations()

pool = WorkPool.get_instance()

# Help Bottle find the templates since the
# working directory won't be a reliable guess
TEMPLATE_PATH.insert(0, get_resource_path('views'))
app = Bottle(autojson=False)
app.install(JSONPrettyPlugin())

@app.get('/')
@view('index')
def bottle_index():
    return {
        'format_options': db.get_format_options(),
        'default_format': db.get_settings()['default_format'],
        'failed': db.get_failed_downloads(),
        'queue': db.get_queued_downloads(),
        'history': db.get_recent_downloads(),
    }

@app.get('/collection/<collection_db_id:re:[0-9]*>')
@view('collection')
def bottle_collection_by_id(collection_db_id):
    data = db.get_collection(collection_db_id)

    if (data is None):
        raise HTTPError(404, 'Could not find the requested collection.')

    return {
        'item': data
    }

@app.get('/collection/<extractor>/<collection_online_id>')
@view('collection')
def bottle_collection_by_extractor(extractor, collection_online_id):
    data = db.get_collection_by_extractor_id(extractor, collection_online_id)

    if (data is None):
        raise HTTPError(404, 'Could not find the requested collection.')

    return {
        'item': data
    }

@app.get('/video/<video_db_id:re:[0-9]*>')
@view('video')
def bottle_video_by_id(video_db_id):
    data = bottle_api_get_video(video_db_id)
    return {
        'item': data
    }

@app.get('/video/<video_db_id:re:[0-9]*>/download')
@view('video')
def bottle_video_download(video_db_id):

    # TODO: Using the current directory won't always be accurate
    # For now, this works for the Docker container or if you
    # always run ytdl-subscribed from the same directory
    data = bottle_api_get_video(video_db_id)
    return static_file(data['filepath'], root=os.getcwd(), download=True)

@app.get('/video/<extractor>/<video_online_id>')
@view('video')
def bottle_video_by_extractor(extractor, video_online_id):
    data = db.get_video_by_extractor_id(extractor, video_online_id)

    if (data is None):
        raise HTTPError(404, 'Could not find the requested video.')

    return {
        'item': data
    }

@app.get('/settings')
@view('settings')
def bottle_show_settings():
    settings = db.get_settings()

    return {
        'settings': settings,
        'ydl_options': db.get_ydl_options(),
        'overrides': get_env_override_set(settings)
    }

@app.get('/static/<filename:re:.*>')
def bottle_static(filename):
    return static_file(filename, root=get_resource_path('static'))

@app.get('/api/queue')
def bottle_api_get_queue():
    download_queue = db.result_to_simple_type(db.get_queued_downloads())
    return {
        'count': len(download_queue),
        'items': download_queue
    }

# / is for backwards compatibility with the original project
@app.post('/')
@app.post('/api/queue')
def bottle_api_add_to_queue():
    url = request.forms.get('url')
    do_redirect_str = request.forms.get('redirect')

    request_options = {
        'url': url,
        'format': request.forms.get('format')
    }
    do_redirect = True
    if (not do_redirect_str is None):
        do_redirect = do_redirect_str.lower() != "false" and do_redirect_str != "0"

    if (url is None or len(url) == 0):
        raise HTTPError(400, "Missing 'url' query parameter")

    error = ''
    error = download(url, request_options)
    # pool.pool.apply_async(download, (url, request_options))

    if (len(error) > 0):
        raise HTTPError(500, error)

    if (do_redirect):
        return redirect('/')

    return bottle_api_get_queue()

@app.get('/api/recent')
def bottle_api_get_recent():
    recent = db.result_to_simple_type(db.get_recent_downloads())
    return {
        'count': len(recent),
        'items': recent
    }

@app.get('/api/failed')
def bottle_api_get_failed():
    failed = db.result_to_simple_type(db.get_failed_downloads())
    return {
        'count': len(failed),
        'items': failed
    }

@app.get('/api/video/<video_db_id:re:[0-9]*>')
def bottle_api_get_video(video_db_id):
    data = db.get_video(video_db_id)

    if (data is None):
        raise HTTPError(404, 'Could not find the requested video.')

    return db.result_to_simple_type(data)

# /update is for backwards compatibility with the original project
@app.get('/update')
@app.get('/api/pip/update')
def bottle_pip_update():
    command = ['pip', 'install', '--upgrade', 'youtube-dl']
    proc = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    output, error = proc.communicate()
    return {
        'output': output.decode('UTF-8'),
        'error':  error.decode('UTF-8')
    }
