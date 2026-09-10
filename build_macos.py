"""
FreePEP macOS 平台打包脚本 (build_macos.py)
功能：
1. 使用 PyInstaller 打包 WebUI 为 macOS 独立可执行文件
2. 内嵌 Playwright Chromium 浏览器内核
3. 生成 FreePEP-macOS-x64.tar.gz 发布包
"""

import os
import sys
import shutil
import subprocess

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PLATFORM = "macos"
OUT_NAME = f"FreePEP-{PLATFORM.title()}-x64"


def check_and_install_pyinstaller():
    try:
        import PyInstaller
        print("[+] PyInstaller 已安装。")
    except ImportError:
        print("[*] 正在安装 PyInstaller...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "pyinstaller",
             "-i", "https://mirrors.aliyun.com/pypi/simple/"]
        )


def find_playwright_browsers_dir():
    """macOS: ~/Library/Caches/ms-playwright"""
    home = os.path.expanduser("~")
    path = os.path.join(home, "Library", "Caches", "ms-playwright")
    if os.path.exists(path):
        return path
    return None


def build_package():
    print("=" * 65)
    print(f"       🚀 FreePEP {OUT_NAME} 打包脚本")
    print("=" * 65)

    check_and_install_pyinstaller()

    dist_dir = os.path.abspath("./dist")
    out_app_dir = os.path.join(dist_dir, "FreePEP")

    if os.path.exists(out_app_dir):
        print(f"[*] 清理旧输出目录: {out_app_dir}")
        shutil.rmtree(out_app_dir, ignore_errors=True)

    # 1. PyInstaller 编译
    print("\n[1/3] 正在使用 PyInstaller 编译 Python 代码与依赖...")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=FreePEP",
        "--onedir",
        "--collect-all=playwright",
        "--hidden-import=uvicorn.logging",
        "--hidden-import=uvicorn.loops",
        "--hidden-import=uvicorn.loops.auto",
        "--hidden-import=uvicorn.protocols",
        "--hidden-import=uvicorn.protocols.http",
        "--hidden-import=uvicorn.protocols.http.auto",
        "--hidden-import=uvicorn.protocols.websockets",
        "--hidden-import=uvicorn.protocols.websockets.auto",
        "--hidden-import=uvicorn.lifespans",
        "--hidden-import=uvicorn.lifespans.on",
        "--clean",
        "-y",
        "webui.py"
    ]
    subprocess.check_call(cmd)
    print("[+] 核心程序 FreePEP 编译成功！")

    # 2. 拷贝 Playwright Chromium
    print("\n[2/3] 正在打包 Chromium 浏览器内核...")
    pw_src = find_playwright_browsers_dir()
    target_browsers = os.path.join(out_app_dir, "browsers")

    if pw_src:
        print(f"[*] 从本机提取 Chromium 内核: {pw_src}")
        os.makedirs(target_browsers, exist_ok=True)
        for item in os.listdir(pw_src):
            if "chromium" in item.lower() or "ffmpeg" in item.lower():
                s = os.path.join(pw_src, item)
                d = os.path.join(target_browsers, item)
                if not os.path.exists(d):
                    print(f"    -> 拷贝: {item}")
                    if os.path.isdir(s):
                        shutil.copytree(s, d)
                    else:
                        shutil.copy2(s, d)
        print("[+] Chromium 内核内嵌完成！")
    else:
        print("[!] 警告: 未找到 Playwright 缓存的 Chromium。")

    for f in ["README.md", "pep_catalog.json"]:
        if os.path.exists(f):
            shutil.copy2(f, os.path.join(out_app_dir, f))

    # 3. 打包 tar.gz
    print("\n[3/3] 正在生成发布压缩包...")
    tar_path = os.path.join(dist_dir, f"{OUT_NAME}.tar.gz")
    if os.path.exists(tar_path):
        os.remove(tar_path)

    import tarfile
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(out_app_dir, arcname="FreePEP")

    size_mb = round(os.path.getsize(tar_path) / (1024 * 1024), 2)
    print("\n" + "=" * 65)
    print(f"🎉 打包完成！")
    print(f"📦 {tar_path} ({size_mb} MB)")
    print("=" * 65)


if __name__ == "__main__":
    build_package()
