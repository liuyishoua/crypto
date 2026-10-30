const {chromium}=require('/home/ubuntu/leo-project/.local/leke-research/tools/rea-cli/node_modules/playwright-core');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');

(async()=>{
  const browser=await chromium.launch({executablePath:'/usr/bin/google-chrome',headless:true,args:['--no-sandbox']});
  const origin='https://d.58nft.net:9466',results=[],out=path.resolve(__dirname,'../.runtime/checks');
  fs.mkdirSync(out,{recursive:true});
  try {
    for (const width of [1440,390,320]) {
      const context=await browser.newContext({viewport:{width,height:1000}});
      await context.addCookies([{name:'ops_workspace_session',value:'fixture-alice',url:origin,secure:true,httpOnly:true}]);
      await context.route('**/*',async route=>{
        const req=route.request(),url=new URL(req.url());
        if (url.origin!==origin) return route.abort();
        const headers=await req.allHeaders(); headers.host='d.58nft.net:9466';
        const response=await route.fetch({url:process.env.CRYPTO_QA_BASE+url.pathname+url.search,headers,timeout:30000,maxRedirects:0});
        await route.fulfill({response});
      });
      const page=await context.newPage(),errors=[];
      page.on('pageerror',error=>errors.push(error.message));
      await page.goto(origin,{waitUntil:'domcontentloaded'});
      await page.waitForFunction(()=>document.querySelector('#stat-count').textContent!=='—');
      assert.equal(await page.locator('.portal-return').getAttribute('href'),'https://d.58nft.net/');
      assert.ok((await page.locator('.account-name').innerText()).includes('个人空间'));
      for (const theme of ['light','dark']) {
        await page.evaluate(theme=>{document.documentElement.dataset.theme=theme;window.dispatchEvent(new Event('workspace-theme-change'));},theme);
        for (const name of ['market','strategy','records','assets','trade','settings']) {
          await page.locator(`.navlink[data-page=${name}]`).click();
          await page.waitForTimeout(100);
          assert.ok(await page.locator(`#page-${name}`).isVisible());
          const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1);
          assert.equal(overflow,false,`${width}/${theme}/${name} must fit the viewport`);
          if (name==='trade') assert.ok(await page.locator('#trade-preview').isDisabled());
        }
        await page.locator('[data-page=market]').click();
        await page.screenshot({path:path.join(out,`crypto-${width}-${theme}.png`),fullPage:true});
      }
      await page.locator('.theme-toggle').click();
      const theme=await page.evaluate(()=>localStorage.getItem('workspace-theme'));
      assert.equal(theme,'light');
      await page.locator('[data-page=strategy]').click();
      await page.locator('#daily-strategy').click();
      await page.locator('#external-strategy-note').fill('fixture private note');
      await page.locator('#save-external-note').click();
      await page.getByText('fixture private note',{exact:false}).first().waitFor();
      await page.locator('[data-page=market]').click();
      await page.locator('.market-favorite').first().click();
      assert.ok(await page.evaluate(()=>localStorage.getItem('crypto-market-favorites:2')));
      await context.addCookies([{name:'ops_workspace_session',value:'fixture-bob',url:origin,secure:true,httpOnly:true}]);
      await page.reload();
      await page.locator('[data-page=strategy]').click();
      await page.locator('#strategy-source-status').filter({hasText:'1 个策略文件'}).waitFor();
      await page.waitForTimeout(250);
      assert.ok(!(await page.locator('#saved-source-notes').innerText()).includes('fixture private note'));
      assert.deepEqual(await page.evaluate(()=>state.favorites),[]);
      assert.deepEqual(errors,[]);
      results.push({width,themes:2,pages:6,overflow:false,personalIsolation:true,errors});
      if (width===320) {
        await fetch(process.env.CRYPTO_QA_IDENTITY+'/revoke');
        await page.evaluate(()=>api('/api/session').catch(()=>{}));
        await page.locator('.auth-notice').waitFor();
        assert.ok(await page.locator('.shell').isHidden());
        assert.equal(await page.locator('.auth-notice a').getAttribute('href'),'https://d.58nft.net/permissions?app=crypto');
      }
      await context.unrouteAll({behavior:'ignoreErrors'}); await context.close();
    }
    fs.writeFileSync(path.join(out,'browser-verification.json'),JSON.stringify(results,null,2));
    console.log(JSON.stringify(results,null,2));
  } finally {
    for (const context of browser.contexts()) await context.unrouteAll({behavior:'ignoreErrors'});
    await browser.close();
  }
})().catch(error=>{console.error(error);process.exit(1)});
