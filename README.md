# 现货研究工作台

个人本机使用的加密资产现货研究与手动交易工作台。默认仅监听 `127.0.0.1`。

开发环境：Python 3.12。安装依赖：`python3.12 -m venv .venv && .venv/bin/pip install -e '.[test]'`。启动：`.venv/bin/python -m crypto_app`。运行数据默认位于 `.runtime/`，不会提交到 Git。

研究结论和历史回测都不是未来收益保证。真实交易功能默认关闭，并且每笔订单需要单独确认。

钱包连接使用 MetaMask Connect（© ConsenSys Software Inc.）。它按[非商业许可](crypto_app/static/vendor/METAMASK-CONNECT-LICENSE)提供，本项目及其衍生版本使用该组件时均须遵守该许可和显著署名要求。前端依赖通过 `npm ci && npm run build:wallet` 构建；仓库保留本地构建后的脚本，运行时无需 npm。

资产页可合并查看币安现货余额与 Ethereum、BNB Smart Chain 钱包余额。钱包只需公开地址，可手动粘贴或通过 MetaMask Connect 选择。先用 `python3.12 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'` 生成主密钥，启动前将结果置于环境变量 `CRYPTO_MASTER_KEY`；在设置页录入仅有读取权限的币安 API Key 和 Secret。凭证只在本机加密保存，服务重启仍需同一主密钥。无可信新鲜价格的资产标为“未计价”，不会当作零估值；NFT、借贷债务等不在首版汇总范围。价格来自 CoinGecko 或币安公开行情，来源和时间在每项资产旁显示。
