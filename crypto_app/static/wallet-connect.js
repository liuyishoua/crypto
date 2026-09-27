export async function selectMetaMaskAddress(createClient, url) {
  const client = await createClient({
    dapp: { name: '现货研究工作台', url },
    api: { supportedNetworks: { '0x1': 'https://ethereum-rpc.publicnode.com', '0x38': 'https://bsc-rpc.publicnode.com' } },
    analytics: { enabled: false },
  });
  const result = await client.connect({ chainIds: ['0x1', '0x38'] });
  const address = result.accounts?.[0];
  if (!address) throw new Error('未选择钱包地址。');
  return address;
}
