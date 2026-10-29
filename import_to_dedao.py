#!/usr/bin/env python3
"""
抖音博主作品批量导入到得到大脑工具

用法：
  python import_to_dedao.py <博主主页链接> <得到大脑知识库链接> [博主名称]

示例：
  python import_to_dedao.py "https://www.douyin.com/user/MS4wLjABAAAAjXA1kP2B3Y1V9mZH4Xl5K1J2eWkmK0c9RdgTrekjrss" "https://www.biji.com/subject/YqP6MGkn/DEFAULT" "体德"
"""

import json
import asyncio
import sys
import re
from datetime import datetime

def extract_sec_uid(url):
    """从抖音主页链接提取 sec_uid"""
    match = re.search(r'/user/([^?]+)', url)
    if match:
        return match.group(1)
    return None

async def collect_works(sec_uid, count=20):
    """提取博主全部作品列表（通过浏览器上下文调用抖音 API）"""
    from playwright.async_api import async_playwright
    
    works = []
    seen_ids = set()
    cursor = 0
    
    PAGE_JS = r"""
    async ({sec, mc, count}) => {
        const base = 'https://www.douyin.com/aweme/v1/web/aweme/post/';
        const params = new URLSearchParams({
            device_platform: 'webapp', aid: '6383', channel: 'channel_pc_web',
            sec_user_id: sec, max_cursor: mc, count: String(count),
            publish_video_strategy_type: '2',
            show_live_replay_strategy: '1', need_time_list: '1', time_list_query: '0',
            whale_cut_token: '', cut_version: '1'
        });
        const r = await fetch(base + '?' + params.toString(), {credentials: 'include'});
        return await r.json();
    }
    """
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(locale='zh-CN', viewport={"width": 1600, "height": 900})
        page = await context.new_page()
        
        print('正在打开抖音主页，请登录抖音...')
        await page.goto(f'https://www.douyin.com/user/{sec_uid}', wait_until='domcontentloaded', timeout=60000)
        await page.wait_for_timeout(10000)
        
        page_no = 0
        while page_no < 200:
            page_no += 1
            data = await page.evaluate(PAGE_JS, {"sec": sec_uid, "mc": str(cursor), "count": count})
            awemes = data.get("aweme_list") or []
            added = 0
            for a in awemes:
                aid = str(a.get("aweme_id") or "")
                if aid and aid not in seen_ids:
                    seen_ids.add(aid)
                    works.append(a)
                    added += 1
            
            has_more = bool(data.get("has_more"))
            cursor = int(data.get("max_cursor") or 0)
            if not has_more or cursor <= 0 or added == 0:
                break
            await page.wait_for_timeout(600)
        
        await browser.close()
    
    return works

async def import_works(sec_uid, dedao_url, author_name):
    """批量导入作品到得到大脑"""
    from playwright.async_api import async_playwright
    
    # 1. 提取作品列表
    print(f'正在提取 {author_name} 的作品列表...')
    works = await collect_works(sec_uid, count=20)
    print(f'提取到 {len(works)} 条作品')
    
    # 保存作品列表
    works_file = f'{author_name}_works.json'
    with open(works_file, 'w', encoding='utf-8') as f:
        json.dump(works, f, ensure_ascii=False)
    print(f'作品列表已保存到 {works_file}')
    
    # 生成链接列表
    links = []
    for w in works:
        link = f'https://www.douyin.com/user/{sec_uid}?modal_id={w["aweme_id"]}'
        links.append({
            'aweme_id': w['aweme_id'],
            'title': w['desc'][:50],
            'link': link
        })
    
    # 2. 批量导入到得到大脑
    print(f'\n开始批量导入到得到大脑...')
    print(f'开始时间: {datetime.now().strftime("%H:%M:%S")}')
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(locale='zh-CN')
        page = await context.new_page()
        
        # 打开得到大脑
        await page.goto(dedao_url)
        print('\n浏览器已打开，请登录得到大脑')
        print('等待60秒后自动开始导入...')
        
        # 等60秒让用户登录
        for i in range(60):
            await asyncio.sleep(1)
            print(f'倒计时: {60-i} 秒', end='\r')
        
        print('\n开始导入...')
        
        success_list = []
        fail_list = []
        
        for i, item in enumerate(links):
            try:
                print(f'\n[{i+1}/{len(links)}] 导入: {item["title"]}...')
                
                # 刷新页面
                await page.reload()
                await page.wait_for_timeout(3000)
                
                # 用文本选择器找"添加"按钮，更稳定
                await page.click('button:has-text("添加")')
                await page.wait_for_timeout(1000)
                
                # 点"粘贴链接"
                await page.click('[role="menuitem"]:has-text("粘贴链接")')
                await page.wait_for_timeout(1000)
                
                # 输入链接
                await page.fill('input.n-input__input-el', item['link'])
                await page.wait_for_timeout(500)
                
                # 按 Enter
                await page.press('input.n-input__input-el', 'Enter')
                await page.wait_for_timeout(5000)
                
                success_list.append(item)
                print(f'✅ 成功')
                
            except Exception as e:
                fail_list.append({**item, 'error': str(e)[:100]})
                print(f'❌ 失败: {str(e)[:80]}')
        
        # 保存结果
        result = {
            'author': author_name,
            'total': len(links),
            'success': len(success_list),
            'fail': len(fail_list),
            'success_list': success_list,
            'fail_list': fail_list,
            'finish_time': datetime.now().strftime('%H:%M:%S')
        }
        
        result_file = f'{author_name}_import_result.json'
        with open(result_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        print(f'\n完成！')
        print(f'博主: {author_name}')
        print(f'总数: {len(links)}')
        print(f'成功: {len(success_list)}')
        print(f'失败: {len(fail_list)}')
        print(f'结束时间: {datetime.now().strftime("%H:%M:%S")}')
        print(f'结果已保存到 {result_file}')
        
        await asyncio.sleep(600)
        await browser.close()

def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    
    douyin_url = sys.argv[1]
    dedao_url = sys.argv[2]
    author_name = sys.argv[3] if len(sys.argv) > 3 else '未知博主'
    
    sec_uid = extract_sec_uid(douyin_url)
    if not sec_uid:
        print('错误：无法从抖音链接提取 sec_uid')
        sys.exit(1)
    
    print(f'博主: {author_name}')
    print(f'抖音 sec_uid: {sec_uid}')
    print(f'得到大脑链接: {dedao_url}')
    
    asyncio.run(import_works(sec_uid, dedao_url, author_name))

if __name__ == '__main__':
    main()
