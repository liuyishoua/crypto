"""Isolated browser preview: synthetic identities, public-data fixtures, no orders."""
from datetime import datetime, timezone
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading

from cryptography.fernet import Fernet
from werkzeug.serving import make_server

from crypto_app.app import create_app
from crypto_app.binance_public import SymbolInfo
from crypto_app.market import Candle, MarketData, INTERVALS, checksum_candles
from crypto_app.workspace import PortalWorkspace


class Market:
    catalog_stale = False
    def symbols(self,query,quote='USDT'):
        rows=[SymbolInfo('BTCUSDT','BTC','USDT','TRADING',Decimal('1000000'),Decimal('2.5')),SymbolInfo('ETHUSDT','ETH','USDT','TRADING',Decimal('500000'),Decimal('-1.2'))]
        return [row for row in rows if query.upper() in row.symbol and (not quote or row.quote==quote)]
    def candles(self,symbol,interval,start,end):
        bars=[]
        while start < end:
            price=Decimal(70000+len(bars)*30)
            bars.append(Candle(start,price,price+100,price-90,price+25,Decimal(200)))
            start+=INTERVALS[interval]
        bars=tuple(bars)
        return MarketData('binance','spot',symbol,interval,bars,'browser-fixture',datetime.now(timezone.utc),checksum_candles(bars))
    def live_snapshot(self,symbol,interval,after_id=None):
        now=int(datetime.now(timezone.utc).timestamp()*1000)
        return {'snapshot':{'lastUpdateId':1,'bids':[['70000','1'],['69990','2']],'asks':[['70001','1'],['70010','2']]},'trades':[],
                'kline':{'E':now,'s':symbol,'k':{'t':now,'o':'70000','h':'70100','l':'69900','c':'70025','v':'200','x':False,'i':interval}},'fetchedAt':now}


class Catalog:
    def sources(self):
        item={'name':'StudyExample','path':'user_data/strategies/StudyExample.py','revision':'a'*40,'engine':'freqtrade','license':'GPL-3.0','url':'https://github.com/freqtrade/freqtrade-strategies/'}
        return {'items':[item],'daily':item,'stale':False,'fetched_at':datetime.now(timezone.utc).isoformat()}


class Identity(BaseHTTPRequestHandler):
    allowed=True
    def log_message(self,*args): pass
    def do_GET(self):
        if self.path=='/revoke':
            type(self).allowed=False; self.send_response(204);self.end_headers();return
        cookie=self.headers.get('Cookie','')
        user_id='3' if 'fixture-bob' in cookie else '2' if 'fixture-alice' in cookie else None
        if user_id and type(self).allowed:
            self.send_response(204)
            self.send_header('X-Workspace-Id',user_id)
            self.send_header('X-Workspace-Name','fixture-alice' if user_id=='2' else 'fixture-bob')
            self.end_headers()
        else:
            self.send_response(403 if user_id else 401)
            self.send_header('Content-Type','application/json');self.end_headers()
            self.wfile.write(json.dumps({'detail':'应用权限已被收回','access_url':'https://d.58nft.net/permissions?app=crypto'}).encode())


def main():
    identity=ThreadingHTTPServer(('127.0.0.1',0),Identity)
    threading.Thread(target=identity.serve_forever,daemon=True).start()
    with tempfile.TemporaryDirectory(prefix='crypto-browser-') as temporary:
        os.environ['CRYPTO_MASTER_KEY']=Fernet.generate_key().decode()
        app=PortalWorkspace(temporary,f'http://127.0.0.1:{identity.server_port}','https://d.58nft.net:9466',
            app_factory=lambda directory:create_app(directory,market_client=Market(),strategy_catalog=Catalog()))
        server=make_server('127.0.0.1',0,app,threaded=True)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            subprocess.run(['node',str(Path(__file__).with_name('browser_check.cjs'))],check=True,env={**os.environ,
                'CRYPTO_QA_BASE':f'http://127.0.0.1:{server.server_port}','CRYPTO_QA_IDENTITY':f'http://127.0.0.1:{identity.server_port}'})
        finally:
            server.shutdown(); identity.shutdown()


if __name__=='__main__': main()
