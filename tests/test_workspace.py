from pathlib import Path
import re
from types import SimpleNamespace

from cryptography.fernet import Fernet
import pytest
import requests
from werkzeug.test import Client
from werkzeug.wrappers import Response

from crypto_app.app import create_app
from crypto_app.secrets import SecretStore
from crypto_app.workspace import PortalWorkspace, load_master_key

ORIGIN = 'https://crypto.example.com:9466'


class Gate:
    allowed = {'alice':'2','bob':'3'}

    def __init__(self):
        self.allowed = dict(self.allowed)
        self.outage = False

    def __call__(self,url,headers,**kwargs):
        assert url == 'http://identity.local/api/auth/access/gate/crypto'
        if self.outage:
            raise requests.Timeout()
        token = headers['Cookie'].split('=',1)[1]
        if token not in self.allowed:
            status = 403 if token else 401
            return SimpleNamespace(status_code=status,headers={},json=lambda:{'detail':'拒绝访问','access_url':'https://portal.example.com/permissions?app=crypto'})
        return SimpleNamespace(status_code=204,headers={'X-Workspace-Id':self.allowed[token],'X-Workspace-Name':token})


@pytest.fixture
def workspace(tmp_path,monkeypatch):
    key = Fernet.generate_key()
    monkeypatch.setenv('CRYPTO_MASTER_KEY',key.decode())
    gate = Gate()
    def app_factory(directory):
        class Account:
            def __init__(self): self.secrets = SecretStore(directory,key)
            def connect(self,key,secret): self.secrets.save('binance_read',{'key':key,'secret':secret})
            def balances(self): return []
        return create_app(directory,account_source=Account())
    app = PortalWorkspace(tmp_path,'http://identity.local',ORIGIN,identity_get=gate,app_factory=app_factory)
    return app,gate


def client(app,token='alice'):
    value = Client(app,Response)
    if token: value.set_cookie('ops_workspace_session',token,domain='crypto.example.com')
    return value


def write(client,path,payload):
    cookie = client.get_cookie('crypto_csrf_token',domain='crypto.example.com')
    return client.post(path,json=payload,base_url=ORIGIN,headers={'Origin':ORIGIN,'X-App-Request':'1','X-CSRF-Token':cookie.value})


def test_authorization_cannot_be_forged_and_revoke_is_immediate(workspace,tmp_path):
    app,gate = workspace
    anonymous = client(app,'')
    assert anonymous.get('/api/session',base_url=ORIGIN,headers={'X-Workspace-Id':'2','X-Workspace-Role':'admin'}).status_code == 401
    assert not (tmp_path/'users').exists()
    alice = client(app)
    assert alice.get('/api/session',base_url=ORIGIN).json['user']['id'] == 2
    gate.allowed.pop('alice')
    assert alice.get('/api/backtests',base_url=ORIGIN).status_code == 403
    assert alice.get('/static/app.js',base_url=ORIGIN).status_code == 403
    gate.outage = True
    assert alice.get('/',base_url=ORIGIN).status_code == 503


def test_private_notes_credentials_orders_and_csrf_are_separate(workspace):
    app,_ = workspace
    alice,bob = client(app),client(app,'bob')
    for value in (alice,bob):
        page = value.get('/',base_url=ORIGIN)
        assert page.status_code == 200
        assert 'Secure' in page.headers['Set-Cookie']
        assert '个人空间' in page.text and 'no-store' in page.headers['Cache-Control']
    payload={'path':'user_data/strategies/Test.py','revision':'a'*40,'note':'仅属于 Alice'}
    assert write(alice,'/api/strategy-notes',payload).status_code == 201
    assert bob.get('/api/strategy-notes',base_url=ORIGIN).json['items'] == []
    assert alice.get('/api/strategy-notes',base_url=ORIGIN).json['items'][0]['note'] == payload['note']
    assert write(alice,'/api/binance/read-credentials',{'key':'synthetic-key','secret':'synthetic-secret'}).status_code == 200
    assert app.apps['2'].extensions['account_source'].secrets.load('binance_read')['key'] == 'synthetic-key'
    assert app.apps['3'].extensions['account_source'].secrets.load('binance_read') is None
    assert alice.get('/api/trade/settings',base_url=ORIGIN).json['enabled'] is False
    assert bob.get('/api/trade/orders',base_url=ORIGIN).json['items'] == []
    db = app.apps['2'].extensions['store']
    db.execute("INSERT INTO trade_orders(client_order_id,preview_id,symbol,side,type,quantity,estimated_exposure,status,created_at,updated_at) VALUES('synthetic-order','synthetic-preview','BTCUSDT','BUY','LIMIT','1','1','CANCELED','2026-10-30','2026-10-30')")
    db.commit()
    assert len(alice.get('/api/trade/orders',base_url=ORIGIN).json['items']) == 1
    assert bob.get('/api/trade/orders/synthetic-order',base_url=ORIGIN).status_code == 404
    assert alice.post('/api/strategy-notes',json=payload,base_url=ORIGIN,headers={'Origin':'https://foreign.example','X-App-Request':'1','X-CSRF-Token':'wrong'}).status_code == 403


def test_versioned_assets_are_public_content_but_pages_are_private(workspace):
    app,_ = workspace
    alice=client(app)
    html=alice.get('/',base_url=ORIGIN).text
    asset=re.search(r'(/static/portal.css\?v=[a-f0-9]+)',html)[1]
    assert 'immutable' in alice.get(asset,base_url=ORIGIN).headers['Cache-Control']
    assert 'no-store' in alice.get('/static/portal.css',base_url=ORIGIN).headers['Cache-Control']
    assert f'data-user-id="2"' in html


def test_master_key_is_durable_and_missing_key_cannot_destroy_credentials(tmp_path):
    key=load_master_key(tmp_path)
    assert load_master_key(tmp_path) == key
    assert (tmp_path/'master.key').stat().st_mode & 0o777 == 0o600
    store=SecretStore(tmp_path/'users'/'2',key.encode())
    store.save('binance_read',{'key':'synthetic','secret':'synthetic'})
    (tmp_path/'master.key').unlink()
    with pytest.raises(RuntimeError,match='密钥缺失'): load_master_key(tmp_path)
