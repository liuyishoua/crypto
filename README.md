# 现货研究工作台

个人本机使用的加密资产现货研究与手动交易工作台。默认仅监听 `127.0.0.1`。

开发环境：Python 3.12。安装依赖：`python3.12 -m venv .venv && .venv/bin/pip install -e '.[test]'`。启动：`.venv/bin/python -m crypto_app`。运行数据默认位于 `.runtime/`，不会提交到 Git。

研究结论和历史回测都不是未来收益保证。真实交易功能默认关闭，并且每笔订单需要单独确认。

钱包连接使用 MetaMask Connect（© ConsenSys Software Inc.）。它按[非商业许可](crypto_app/static/vendor/METAMASK-CONNECT-LICENSE)提供，本项目及其衍生版本使用该组件时均须遵守该许可和显著署名要求。前端依赖通过 `npm ci && npm run build:wallet` 构建；仓库保留本地构建后的脚本，运行时无需 npm。
