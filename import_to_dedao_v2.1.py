#!/usr/bin/env python3
"""
抖音博主作品批量导入到得到大脑工具（2.1版 - 持久化登录态 + 智能等待）

用法：
  python import_to_dedao_v2.1.py <博主主页链接> <得到大脑知识库链接> [博主名称]

2.1版新增：
- 使用 launch_persistent_context 持久化登录态，第二次起免登录
- 智能等待：轮询检测登录态，已登录立即继续，未登录最多等 30 秒
- 兼容 Python 3.13 + Playwright 1.64
- 修复：抖音登录检测改用 context.cookies() 读取 HttpOnly cookie
"""

import json
import asyncio
import sys
import re
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime

# 持久化浏览器目录（登录态保存在这里，第二次起免登录）
DOUYIN_USER_DATA_DIR = r"D:\豆包的输出结果\2.0流程\browser_data_douyin"
DEDAO_USER_DATA_DIR = r"D:\豆包的输出结果\2.0流程\browser_data_dedao"

# 登录等待上限（秒）
LOGIN_TIMEOUT = 30


class ProgressWindow:
    def __init__(self, total=0):
        self.root = tk.Tk()
        self.root.title("导入进度 - 2.1版")
        self.root.geometry("480x220")
        self.root.attributes('-topmost', True)

        self.status_var = tk.StringVar(value="准备中...")
        self.progress_var = tk.StringVar(value="0 / 0")

        ttk.Label(self.root, textvariable=self.status_var, font=("微软雅黑", 12), wraplength=440).pack(pady=15)
        self.progress = ttk.Progressbar(self.root, length=380, mode='determinate')
        self.progress.pack(pady=10)
        ttk.Label(self.root, textvariable=self.progress_var, font=("微软雅黑", 10)).pack()

        self.total = total

    def set_total(self, total):
        self.total = total
        self.progress['maximum'] = total
        self.progress_var.set(f"0 / {total}")

    def update_status(self, text):
        self.status_var.set(text)
        self.root.update()

    def update_progress(self, current, success=0, fail=0):
        self.progress['value'] = current
        self.progress_var.set(f"{current} / {self.total}  (成功{success} 失败{fail})")
        self.root.update()

    def finish(self, success, fail):
        self.status_var.set(f"导入完成！成功{success} 失败{fail}")
        self.progress['value'] = self.total
        self.root.update()
        messagebox.showinfo("完成", f"导入完成！\n成功：{success}\n失败：{fail}\n\n结果已保存到本地文件。")
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def extract_sec_uid(url):
    match = re.search(r'/user/([^?]+)', url)
    return match.group(1) if match else None


async def wait_for_douyin_login(page, progress_window=None):
    """轮询检测抖音登录态：通过 context.cookies() 读取 HttpOnly cookie，检测到立即继续。"""
    # 抖音的 sessionid 是 HttpOnly cookie，document.cookie 读不到，必须用 context.cookies()
    LOGIN_COOKIE_NAMES = {'sessionid', 'sessionid_ss', 'sid_tt', 'uid_tt'}
    elapsed = 0
    while elapsed < LOGIN_TIMEOUT:
        try:
            cookies = await page.context.cookies()
            for cookie in cookies:
                if cookie['name'] in LOGIN_COOKIE_NAMES and cookie.get('value'):
                    if progress_window:
                        progress_window.update_status("抖音已登录，开始提取作品...")
                    return True
        except Exception:
            pass
        if progress_window:
            progress_window.update_status(f"等待抖音登录... {LOGIN_TIMEOUT - elapsed}秒（未登录请在浏览器中操作）")
        await asyncio.sleep(2)
        elapsed += 2
    if progress_window:
        progress_window.update_status("等待超时，继续尝试提取作品...")
    return False


async def wait_for_dedao_login(page, progress_window=None):
    """轮询检测得到大脑登录态：检测'添加'按钮是否出现。"""
    check_js = """
    () => {
        const btns = document.querySelectorAll('button');
        for (const b of btns) {
            if (b.textContent && b.textContent.includes('添加')) return true;
        }
        return false;
    }
    """
    elapsed = 0
    while elapsed < LOGIN_TIMEOUT:
        try:
            logged_in = await page.evaluate(check_js)
            if logged_in:
                if progress_window:
                    progress_window.update_status("得到大脑已登录，开始导入...")
                return True
        except Exception:
            pass
        if progress_window:
            progress_window.update_status(f"等待得到大脑登录... {LOGIN_TIMEOUT - elapsed}秒（未登录请在浏览器中操作）")
        await asyncio.sleep(2)
        elapsed += 2
    if progress_window:
        progress_window.update_status("等待超时，继续尝试导入...")
    return False


async def collect_works(sec_uid, count=20, progress_window=None):
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
        context = await p.chromium.launch_persistent_context(
            user_data_dir=DOUYIN_USER_DATA_DIR,
            headless=False,
            locale='zh-CN',
            viewport={"width": 1600, "height": 900}
        )
        page = context.pages[0] if context.pages else await context.new_page()

        if progress_window:
            progress_window.update_status("正在打开抖音主页...")

        await page.goto(f'https://www.douyin.com/user/{sec_uid}', wait_until='domcontentloaded', timeout=60000)

        # 智能等待：已登录立即继续，未登录最多等 30 秒
        await wait_for_douyin_login(page, progress_window)

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

            if progress_window:
                progress_window.update_status(f"正在提取作品... 第{page_no}页，已提取{len(works)}条")

            has_more = bool(data.get("has_more"))
            cursor = int(data.get("max_cursor") or 0)
            if not has_more or cursor <= 0 or added == 0:
                break
            await page.wait_for_timeout(800)

        await context.close()

    return works


async def import_works_async(sec_uid, dedao_url, author_name, progress_window):
    from playwright.async_api import async_playwright

    # 1. 提取作品列表
    works = await collect_works(sec_uid, count=20, progress_window=progress_window)
    print(f'提取到 {len(works)} 条作品')

    works_file = f'{author_name}_works.json'
    with open(works_file, 'w', encoding='utf-8') as f:
        json.dump(works, f, ensure_ascii=False)

    links = []
    for w in works:
        link = f'https://www.douyin.com/user/{sec_uid}?modal_id={w["aweme_id"]}'
        links.append({
            'aweme_id': w['aweme_id'],
            'title': w['desc'][:50],
            'link': link
        })

    # 2. 批量导入到得到大脑
    progress_window.set_total(len(links))
    progress_window.update_status("正在打开得到大脑...")

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=DEDAO_USER_DATA_DIR,
            headless=False,
            locale='zh-CN'
        )
        page = context.pages[0] if context.pages else await context.new_page()

        await page.goto(dedao_url)

        # 智能等待：已登录立即继续，未登录最多等 30 秒
        await wait_for_dedao_login(page, progress_window)

        success_list = []
        fail_list = []

        for i, item in enumerate(links):
            try:
                progress_window.update_status(f"正在导入: {item['title'][:30]}...")

                await page.reload()
                await page.wait_for_timeout(3000)

                await page.click('button:has-text("添加")')
                await page.wait_for_timeout(1000)

                await page.click('[role="menuitem"]:has-text("粘贴链接")')
                await page.wait_for_timeout(1000)

                await page.fill('input.n-input__input-el', item['link'])
                await page.wait_for_timeout(500)

                await page.press('input.n-input__input-el', 'Enter')
                await page.wait_for_timeout(5000)

                success_list.append(item)

            except Exception as e:
                fail_list.append({**item, 'error': str(e)[:200]})

            progress_window.update_progress(i + 1, len(success_list), len(fail_list))

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

        progress_window.finish(len(success_list), len(fail_list))

        await context.close()


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

    progress_window = ProgressWindow()

    def run_async():
        asyncio.run(import_works_async(sec_uid, dedao_url, author_name, progress_window))

    thread = threading.Thread(target=run_async, daemon=True)
    thread.start()

    progress_window.run()


if __name__ == '__main__':
    main()
