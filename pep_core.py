"""
人教社电子教材核心处理库 (pep_core.py)
提供：
1. 全量教材目录获取、解密与多维度条件检索过滤
2. 学段、学科、年级自定义排序与别名标准化规范
3. 缓存清理机制与磁盘空间统计
4. Playwright 自动化过 WAF 滑块验证、页面抓取与 PDF 合成
"""

import os
import sys
import re
import time
import json
import random
import shutil
import base64
import binascii
import urllib.request
from typing import List, Dict, Optional, Callable, Tuple
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from PIL import Image
from playwright.sync_api import sync_playwright

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def get_base_dir() -> str:
    """获取程序运行根目录（兼容源码运行与 PyInstaller 打包后的 exe 环境）"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


# 优先加载程序目录下的绿色便携浏览器内核 (browsers/)
_local_browsers = os.path.join(get_base_dir(), "browsers")
if os.path.exists(_local_browsers):
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = _local_browsers


# 1. 规定的学段默认排序与规范化映射
XD_ORDER = [
    "小学（六三学制）",
    "初中（六三学制）",
    "小学（五四学制）",
    "初中（五·四学制）",
    "高中",
    "培智学校",
    "聋校",
    "盲校（盲文版）",
    "盲校（低视力版）"
]

# 2. 规定的学科前置优先排序列表
XK_ORDER_PREFIX = [
    "语文", "数学", "英语", "物理", "化学", "历史",
    "思想政治", "地理", "生物学", "音乐", "道德与法治"
]

# 3. 规定的年级默认排序
NJ_ORDER = [
    "一年级", "二年级", "三年级", "四年级", "五年级", "六年级",
    "七年级", "八年级", "九年级", "三年级;四年级", "三年级和四年级",
    "五年级;六年级", "五年级和六年级", "专项", "必修", "选择性必修"
]


def normalize_xd(raw_xd: str) -> str:
    """标准化学段名称映射"""
    if not raw_xd:
        return "其他"
    raw_xd = raw_xd.strip()
    if raw_xd == "小学":
        return "小学（六三学制）"
    if raw_xd == "初中":
        return "初中（六三学制）"
    if raw_xd in ["小学（五·四学制）", "小学（五四学制）"]:
        return "小学（五四学制）"
    if raw_xd in ["初中（五·四学制）", "初中（五四学制）"]:
        return "初中（五·四学制）"
    return raw_xd


def sort_xd_key(xd: str) -> Tuple[int, int, str]:
    norm = normalize_xd(xd)
    if norm in XD_ORDER:
        return (0, XD_ORDER.index(norm), norm)
    return (1, 999, norm)


def sort_xk_key(xk: str) -> Tuple[int, int, str]:
    if not xk:
        return (2, 999, "")
    xk = xk.strip()
    if xk in XK_ORDER_PREFIX:
        return (0, XK_ORDER_PREFIX.index(xk), xk)
    return (1, 0, xk)


def sort_nj_key(nj: str) -> Tuple[int, int, str]:
    if not nj:
        return (2, 999, "")
    nj = nj.strip()
    if nj in NJ_ORDER:
        return (0, NJ_ORDER.index(nj), nj)
    return (1, 0, nj)


class PepCatalog:
    """人教社教材目录管理器"""
    BASE_URL = "https://jc.pep.com.cn/"
    KEY = b"1234123412ABCDEF"
    IV = b"ABCDEF1234123412"
    LOCAL_CACHE = os.path.join(get_base_dir(), "pep_catalog.json")

    @classmethod
    def fetch_and_decrypt_all(cls, force_refresh: bool = False) -> List[Dict]:
        """获取并解密全量教材元数据，支持本地缓存"""
        if not force_refresh and os.path.exists(cls.LOCAL_CACHE):
            try:
                with open(cls.LOCAL_CACHE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list) and len(data) > 0:
                        # 确保每条记录都包含标准化的学段
                        for b in data:
                            b["xd"] = normalize_xd(b.get("xd", ""))
                        return data
            except Exception:
                pass

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Referer": cls.BASE_URL
        }

        # 1. 下载首页定位 chunk-bfbdf2c4 JS
        req = urllib.request.Request(cls.BASE_URL, headers=headers)
        with urllib.request.urlopen(req) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        chunk_match = re.search(r'src="(/js/chunk-bfbdf2c4\.[a-f0-9]+\.js)"', html)
        if not chunk_match:
            chunk_match = re.search(r'href="(/js/chunk-bfbdf2c4\.[a-f0-9]+\.js)"', html)

        chunk_path = chunk_match.group(1) if chunk_match else "/js/chunk-bfbdf2c4.3782cce3.js"
        chunk_url = urllib.parse.urljoin(cls.BASE_URL, chunk_path)

        # 2. 获取 JS 内容并提取十六进制密文
        js_req = urllib.request.Request(chunk_url, headers=headers)
        raw_js = urllib.request.urlopen(js_req).read()

        m = re.search(rb'var\s+o,\s*c\s*=\s*"([A-F0-9]+)"', raw_js)
        if not m:
            raise ValueError("未能从前端 JS 中匹配到教材数据密文！")

        hex_str = m.group(1).decode("ascii")
        cipher_bytes = binascii.unhexlify(hex_str)

        # 3. AES-128-CBC 解密
        cipher = Cipher(algorithms.AES(cls.KEY), modes.CBC(cls.IV))
        decryptor = cipher.decryptor()
        padded_plain = decryptor.update(cipher_bytes) + decryptor.finalize()

        unpadder = padding.PKCS7(128).unpadder()
        plaintext = unpadder.update(padded_plain) + unpadder.finalize()

        data_json = json.loads(plaintext.decode("utf-8"))
        items = data_json.get("data", [])

        # 标准化学段名称
        for b in items:
            b["xd"] = normalize_xd(b.get("xd", ""))

        # 缓存到本地
        with open(cls.LOCAL_CACHE, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)

        return items

    @classmethod
    def filter_books(cls,
                     xd: Optional[str] = None,
                     xk: Optional[str] = None,
                     nj: Optional[str] = None,
                     keyword: Optional[str] = None) -> List[Dict]:
        """多条件筛选教材"""
        books = cls.fetch_and_decrypt_all()
        results = []
        
        target_xd = normalize_xd(xd) if xd else None

        for b in books:
            book_xd = normalize_xd(b.get("xd", ""))
            if target_xd and target_xd != "全部" and book_xd != target_xd:
                continue
            if xk and xk != "全部" and b.get("xk") != xk:
                continue
            if nj and nj != "全部" and b.get("nj") != nj:
                continue
            if keyword:
                kw = keyword.strip().lower()
                full_text = f"{b.get('title','')} {book_xd} {b.get('xk','')} {b.get('nj','')} {b.get('cc','')}".lower()
                if kw not in full_text:
                    continue
            results.append(b)
        return results

    @classmethod
    def get_structure(cls) -> Dict:
        """获取各学段下的所有学科和年级分类结构（按要求精细排序）"""
        books = cls.fetch_and_decrypt_all()
        structure = {}
        
        # 初始化规定排序中的所有学段
        for xd in XD_ORDER:
            structure[xd] = {"subjects": set(), "grades": set()}

        for b in books:
            xd = normalize_xd(b.get("xd", "其他"))
            xk = b.get("xk", "").strip()
            nj = b.get("nj", "").strip()
            if xd not in structure:
                structure[xd] = {"subjects": set(), "grades": set()}
            if xk:
                structure[xd]["subjects"].add(xk)
            if nj:
                structure[xd]["grades"].add(nj)

        # 转换为按照规范严格排序的列表
        output = {}
        for xd in sorted(structure.keys(), key=sort_xd_key):
            val = structure[xd]
            if len(val["subjects"]) == 0 and len(val["grades"]) == 0:
                continue
            output[xd] = {
                "subjects": sorted(list(val["subjects"]), key=sort_xk_key),
                "grades": sorted(list(val["grades"]), key=sort_nj_key)
            }
        return output

    @classmethod
    def clear_cache_files(cls) -> Dict:
        """清理临时缓存目录 temp_pages"""
        temp_dir = os.path.join(get_base_dir(), "temp_pages")
        deleted_count = 0
        total_freed_bytes = 0

        if os.path.exists(temp_dir):
            for root, dirs, files in os.walk(temp_dir):
                for f in files:
                    fp = os.path.join(root, f)
                    try:
                        total_freed_bytes += os.path.getsize(fp)
                        deleted_count += 1
                    except Exception:
                        pass
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass

        os.makedirs(temp_dir, exist_ok=True)
        freed_mb = round(total_freed_bytes / (1024 * 1024), 2)
        return {
            "status": "ok",
            "deleted_count": deleted_count,
            "freed_mb": freed_mb,
            "message": f"成功清理 {deleted_count} 个临时缓存文件，释放 {freed_mb} MB 磁盘空间。"
        }


class PepDownloader:
    """电子教材下载与 PDF 合成器"""

    def __init__(self, headless: bool = True, output_dir: Optional[str] = None):
        self.headless = headless
        if not output_dir or output_dir == "./downloads":
            self.output_dir = os.path.join(get_base_dir(), "downloads")
        else:
            self.output_dir = os.path.abspath(output_dir)
        os.makedirs(self.output_dir, exist_ok=True)

    def _solve_slider(self, page, log_cb: Optional[Callable[[str], None]] = None) -> bool:
        """检测并破解阿里云 WAF 滑块"""
        time.sleep(1)
        slider = page.query_selector(".btn_slide")
        if not slider:
            return True

        msg = "[*] 检测到阿里云 WAF 滑块验证码，正在自动滑动破解..."
        if log_cb: log_cb(msg)
        else: print(msg)

        box = slider.bounding_box()
        scale = page.query_selector(".nc_scale")
        scale_box = scale.bounding_box() if scale else None

        if not (box and scale_box):
            return False

        start_x = box["x"] + box["width"] / 2
        start_y = box["y"] + box["height"] / 2
        target_x = scale_box["x"] + scale_box["width"] + 20

        page.mouse.move(start_x, start_y)
        page.mouse.down()

        curr_x = start_x
        while curr_x < target_x:
            curr_x += random.randint(12, 28)
            curr_y = start_y + random.randint(-2, 2)
            page.mouse.move(curr_x, curr_y)
            time.sleep(random.uniform(0.01, 0.025))

        page.mouse.move(target_x, start_y)
        page.mouse.up()
        time.sleep(3)

        success = page.query_selector(".btn_slide") is None
        res_msg = "[+] 滑块验证通过！" if success else "[-] 滑块验证未通过。"
        if log_cb: log_cb(res_msg)
        else: print(res_msg)
        return success

    def download_book(self,
                      book_id: str,
                      custom_title: Optional[str] = None,
                      progress_cb: Optional[Callable[[int, int, str], None]] = None,
                      log_cb: Optional[Callable[[str], None]] = None) -> Optional[str]:
        """
        下载单本教材
        :param book_id: 教材 ID（如 1284001101241）
        :param custom_title: 自定义书名
        :param progress_cb: 进度回调 (current_page, total_pages, status_text)
        :param log_cb: 日志回调 (log_text)
        :return: 生成的 PDF 绝对路径
        """
        book_url = f"https://book.pep.com.cn/{book_id}/"
        init_msg = f"[*] 准备加载教材: {book_url}"
        if log_cb: log_cb(init_msg)
        else: print(init_msg)

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=self.headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-infobars"
                ]
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                viewport={"width": 1366, "height": 768},
                extra_http_headers={"Referer": "https://jc.pep.com.cn/"}
            )
            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                window.navigator.chrome = { runtime: {} };
            """)
            page = context.new_page()

            # 打开阅读器，必须带 Referer 防盗链
            page.goto(book_url, referer="https://jc.pep.com.cn/", wait_until="networkidle")

            # 处理可能的滑块验证
            if page.query_selector(".btn_slide"):
                self._solve_slider(page, log_cb)
                time.sleep(2)

            # 等待阅读器配置完全加载
            for _ in range(15):
                has_config = page.evaluate("""() => {
                    return typeof window.bookConfig !== 'undefined' || 
                           typeof window.totalPageCount !== 'undefined' ||
                           document.querySelector('#bookContainer') !== null;
                }""")
                if has_config:
                    break
                time.sleep(1)

            # 读取元数据与总页数
            config_info = page.evaluate("""() => {
                const descMeta = document.querySelector('meta[name="Description"]');
                const ogMeta = document.querySelector('meta[property="og:title"]');
                const title = (descMeta ? descMeta.content : '') || 
                              (ogMeta ? ogMeta.content : '') || 
                              (window.bookConfig && window.bookConfig.bookTitle) || 
                              document.title || 
                              '教材';
                const total = window.totalPageCount || 
                              (window.bookConfig && window.bookConfig.totalPageCount) || 
                              0;
                return { title, total };
            }""")

            final_title = custom_title or config_info.get("title", f"book_{book_id}")
            safe_title = re.sub(r'[\/:*?"<>|]', '_', final_title).strip()
            total_pages = config_info.get("total", 0)

            if total_pages == 0:
                err = f"[-] 无法读取教材总页数 (URL: {page.url})"
                if log_cb: log_cb(err)
                else: print(err)
                browser.close()
                return None

            info_msg = f"[+] 教材: 《{safe_title}》 | 总页数: {total_pages} 页"
            if log_cb: log_cb(info_msg)
            else: print(info_msg)

            temp_dir = os.path.join(".", "temp_pages", book_id)
            os.makedirs(temp_dir, exist_ok=True)
            image_files = []

            for page_num in range(1, total_pages + 1):
                img_url = f"https://book.pep.com.cn/{book_id}/files/mobile/{page_num}.jpg"
                img_path = os.path.join(temp_dir, f"{page_num}.jpg")

                # 本地已有合法 JPEG 则跳过
                if os.path.exists(img_path) and os.path.getsize(img_path) > 15000:
                    with open(img_path, "rb") as f:
                        if f.read(2) == b"\xff\xd8":
                            image_files.append(img_path)
                            if progress_cb: progress_cb(page_num, total_pages, f"第 {page_num}/{total_pages} 页已存在")
                            continue

                download_success = False
                for retry in range(3):
                    res = page.evaluate("""async (url) => {
                        try {
                            const resp = await fetch(url);
                            const ctype = resp.headers.get('content-type') || '';
                            const blob = await resp.blob();
                            return new Promise((resolve) => {
                                const reader = new FileReader();
                                reader.onloadend = () => resolve({ 
                                    status: resp.status, 
                                    ctype: ctype, 
                                    data: reader.result 
                                });
                                reader.readAsDataURL(blob);
                            });
                        } catch (e) {
                            return { status: 500, error: e.toString() };
                        }
                    }""", img_url)

                    data_uri = res.get("data", "")
                    if res.get("status") == 200 and data_uri and ("image" in res.get("ctype", "") or data_uri.startswith("data:image")):
                        raw_data = base64.b64decode(data_uri.split(",")[1])
                        if raw_data[:2] == b"\xff\xd8":
                            with open(img_path, "wb") as f:
                                f.write(raw_data)
                            image_files.append(img_path)
                            size_kb = len(raw_data) // 1024
                            log_text = f"  -> [{page_num}/{total_pages}] 下载成功 ({size_kb} KB)"
                            if log_cb: log_cb(log_text)
                            else: print(log_text)
                            if progress_cb: progress_cb(page_num, total_pages, f"正在下载: 第 {page_num}/{total_pages} 页")
                            download_success = True
                            break

                    # 触发 WAF 验证码拦截
                    warn_msg = f"  [!] 第 {page_num} 页触发验证码，自动刷新破解..."
                    if log_cb: log_cb(warn_msg)
                    else: print(warn_msg)
                    page.goto(book_url, referer="https://jc.pep.com.cn/", wait_until="networkidle")
                    self._solve_slider(page, log_cb)
                    time.sleep(2)

                if not download_success:
                    fail_msg = f"  -> [{page_num}/{total_pages}] 下载失败！"
                    if log_cb: log_cb(fail_msg)
                    else: print(fail_msg)

                time.sleep(random.uniform(0.15, 0.3))

            browser.close()

            if not image_files:
                return None

            output_pdf = os.path.join(self.output_dir, f"{safe_title}.pdf")
            merge_msg = f"[*] 正在合成 PDF: {os.path.basename(output_pdf)} ..."
            if log_cb: log_cb(merge_msg)
            else: print(merge_msg)
            if progress_cb: progress_cb(total_pages, total_pages, "正在合成 PDF 文件...")

            pil_images = []
            for img_p in image_files:
                try:
                    im = Image.open(img_p)
                    if im.mode != "RGB":
                        im = im.convert("RGB")
                    pil_images.append(im)
                except Exception as e:
                    pass

            if not pil_images:
                return None

            first_im = pil_images[0]
            rest_images = pil_images[1:]
            first_im.save(output_pdf, "PDF", resolution=100.0, save_all=True, append_images=rest_images)

            done_msg = f"[✔] PDF 生成成功: {output_pdf}"
            if log_cb: log_cb(done_msg)
            else: print(done_msg)
            if progress_cb: progress_cb(total_pages, total_pages, "下载与合成完成！")

            return output_pdf
