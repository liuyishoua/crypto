import { createEVMClient } from '@metamask/connect-evm';
import { selectMetaMaskAddress } from './wallet-connect.js';

window.cryptoWallet = {
  selectAddress: () => selectMetaMaskAddress(createEVMClient, window.location.origin),
};
