"""Central authorization and separate application state for each portal user."""
import json
import os
from pathlib import Path
import re
import threading
from urllib.parse import unquote, urlsplit

import requests
from werkzeug.wrappers import Request, Response

from .app import create_app


class PortalWorkspace:
    def __init__(self, runtime_dir, identity_url, public_origin, *, identity_get=None, app_factory=create_app):
        self.runtime_dir = Path(runtime_dir)
        self.identity_url = identity_url.rstrip('/') + '/api/auth/access/gate/crypto'
        self.public_origin = public_origin.rstrip('/')
        self.identity_get = identity_get or requests.get
        self.app_factory = app_factory
        self.apps = {}
        self.lock = threading.Lock()

    def __call__(self, environ, start_response):
        request = Request(environ)
        if request.path == '/health' and request.method in ('GET', 'HEAD'):
            return Response('{"status":"ok"}', content_type='application/json', headers={'Cache-Control':'no-store'})(environ, start_response)
        token = request.cookies.get('ops_workspace_session', '')
        headers = {'Cookie':'ops_workspace_session=' + token,
                   'Accept':request.headers.get('Accept','application/json'),
                   'X-Forwarded-Uri':request.path, 'X-Forwarded-Method':request.method}
        try:
            result = self.identity_get(self.identity_url, headers=headers, timeout=5, allow_redirects=False)
        except requests.RequestException:
            return self.error('统一登录服务暂时不可用，请稍后重试。', 503)(environ,start_response)
        if result.status_code != 204:
            if result.status_code in (301,302,303,307,308):
                # The fixed identity service owns login/permissions destinations.
                response = Response(status=302, headers={'Location':result.headers['Location'],'Cache-Control':'no-store'})
            elif result.status_code in (401,403):
                body = result.json()
                response = Response(json.dumps({'error':body.get('detail','请重新登录并检查应用权限。'),
                    **{k:body[k] for k in ('login_url','access_url') if k in body}},ensure_ascii=False),
                    status=result.status_code,content_type='application/json; charset=utf-8',headers={'Cache-Control':'no-store'})
            else:
                response = self.error('统一登录服务暂时不可用，请稍后重试。',503)
            return response(environ,start_response)
        user_id = result.headers.get('X-Workspace-Id','')
        if not re.fullmatch(r'[1-9][0-9]{0,15}',user_id):
            return self.error('统一登录身份响应无效，请稍后重试。',503)(environ,start_response)
        identity = {'id':int(user_id),'name':unquote(result.headers.get('X-Workspace-Name',user_id))}
        with self.lock:
            if user_id not in self.apps:
                app = self.app_factory(self.runtime_dir/'users'/user_id)
                app.config.update(TRUSTED_HOSTS=[urlsplit(self.public_origin).hostname],
                                  PUBLIC_ORIGIN=self.public_origin,CSRF_COOKIE_NAME='crypto_csrf_token')
                self.apps[user_id] = app
            app = self.apps[user_id]
        # This server-owned value never comes from an incoming identity header.
        environ = {**environ,'crypto.identity':identity}
        return app(environ,start_response)

    @staticmethod
    def error(message,status):
        return Response(json.dumps({'error':message},ensure_ascii=False),status=status,
                        content_type='application/json; charset=utf-8',headers={'Cache-Control':'no-store'})


def load_master_key(runtime_dir):
    """Keep the encryption key durable; never replace a missing existing key."""
    from cryptography.fernet import Fernet
    runtime_dir = Path(runtime_dir)
    runtime_dir.mkdir(mode=0o700,parents=True,exist_ok=True)
    key_path = runtime_dir/'master.key'
    if not key_path.exists():
        if any((runtime_dir/'users').glob('*/secrets.bin')):
            raise RuntimeError('凭证加密密钥缺失；请恢复原 master.key')
        try:
            descriptor = os.open(key_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(descriptor,'wb') as stream:
                stream.write(Fernet.generate_key())
    key = key_path.read_bytes().decode().strip()
    Fernet(key.encode())
    return key
