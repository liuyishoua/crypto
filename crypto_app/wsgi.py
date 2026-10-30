import os
from pathlib import Path

from .workspace import PortalWorkspace, load_master_key

runtime = Path(os.environ.get('CRYPTO_RUNTIME_DIR','.runtime'))
os.environ['CRYPTO_MASTER_KEY'] = load_master_key(runtime)
app = PortalWorkspace(runtime,os.environ.get('OPS_IDENTITY_URL','http://127.0.0.1:8787'),
                      os.environ.get('CRYPTO_PUBLIC_ORIGIN','https://d.58nft.net:9466'))
