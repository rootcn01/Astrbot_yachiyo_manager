#!/usr/bin/env python
"""八千代插件打包脚本。

固化 zip 打包逻辑：自动加顶层目录条目（AstrBot 网页上传要求 _resolve_archive_root_dir 识别根目录）。
不依赖对比老 zip——直接用此脚本打包即可。

背景：python zipfile.write(file, arc) 不写目录条目，导致 AstrBot 网页上传报 NotADirectoryError
（_resolve_archive_root_dir 取 namelist 首条目当 root_dir，首条目是文件则 listdir(文件) 报错）。
解法：zf.writestr(plugin_name + '/', '') 先写顶层目录条目。

用法: python build_zip.py
产出: ../yachiyo_manager_upload.zip
"""
import zipfile
import os

SRC = os.path.dirname(os.path.abspath(__file__))  # 插件目录本身
PARENT = os.path.dirname(SRC)
PLUGIN_NAME = os.path.basename(SRC)
DST = os.path.join(PARENT, 'yachiyo_manager_upload.zip')

EXCLUDE_DIRS = {'__pycache__', '.git', '.pytest_cache'}
EXCLUDE_FILES = {'token.json', 'credentials.json'}


def build():
    if os.path.exists(DST):
        os.remove(DST)
    count = 0
    with zipfile.ZipFile(DST, 'w', zipfile.ZIP_DEFLATED) as zf:
        # 关键：先写顶层目录条目（以 / 结尾）
        zf.writestr(PLUGIN_NAME + '/', '')
        for root, dirs, files in os.walk(SRC):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for f in files:
                if f.endswith('.pyc') or f in EXCLUDE_FILES:
                    continue
                full = os.path.join(root, f)
                arc = os.path.relpath(full, PARENT)
                zf.write(full, arc)
                count += 1
    # 验证首条目是目录
    with zipfile.ZipFile(DST, 'r') as zf:
        first = zf.namelist()[0]
        assert first.endswith('/'), f'首条目非目录: {first!r}'
    print(f'打包完成: {count} 文件 + 顶层目录条目')
    print(f'首条目: {first!r} (目录条目)')
    print(f'产出: {DST} ({os.path.getsize(DST):,} bytes)')


if __name__ == '__main__':
    build()
