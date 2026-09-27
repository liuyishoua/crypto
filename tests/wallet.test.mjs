import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { selectMetaMaskAddress } from '../crypto_app/static/wallet-connect.js';

test('requests only account access on Ethereum and BNB Smart Chain', async () => {
  let options;
  let requested;
  const createClient = async (value) => {
    options = value;
    return { connect: async (request) => { requested = request; return { accounts: ['0x000000000000000000000000000000000000dEaD'] }; } };
  };
  const address = await selectMetaMaskAddress(createClient, 'http://127.0.0.1:8765/');
  assert.equal(address, '0x000000000000000000000000000000000000dEaD');
  assert.deepEqual(requested, { chainIds: ['0x1', '0x38'] });
  assert.deepEqual(options.dapp, { name: '现货研究工作台', url: 'http://127.0.0.1:8765/' });
  assert.deepEqual(options.api.supportedNetworks, { '0x1': 'https://ethereum-rpc.publicnode.com', '0x38': 'https://bsc-rpc.publicnode.com' });
  assert.equal(options.analytics.enabled, false);
});

test('empty wallet selection is rejected', async () => {
  await assert.rejects(() => selectMetaMaskAddress(async () => ({ connect: async () => ({ accounts: [] }) }), 'http://127.0.0.1:8765/'));
});
