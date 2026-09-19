import shutil

P = '/AstrBot/astrbot/core/message/components.py'
BAK = '/AstrBot/data/patches_backup/components.py.orig.20260919'

shutil.copy2(P, BAK)
print('backup ->', BAK)

src = open(P, encoding='utf-8').read()

# 补丁：Record._resolve_file_source 里，url 判断之前插入 path 优先分支
# （napcat 的 QQ 直链下载不可靠——67 字节垃圾；本地挂载 path 是真文件）
anchor = '''        # 2) 尝试 url（可能是 file:/// 或 http 链接）
        if self.url:'''
patch = '''        # 1.5) Yachiyo patch 20260919: napcat 容器内本地路径已挂载可见时优先
        # （QQ 官方直链下载得到 67B 错误体；path 指向挂载卷里的真实 .amr）
        if self.path:
            try:
                if os.path.exists(self.path):
                    return self.path
            except OSError:
                pass

        # 2) 尝试 url（可能是 file:/// 或 http 链接）
        if self.url:'''

assert anchor in src, 'anchor not found'
assert 'Yachiyo patch 20260919' not in src, 'already patched'
src = src.replace(anchor, patch, 1)
open(P, 'w', encoding='utf-8').write(src)
print('patched: Record._resolve_file_source path-first')

# 语法自检
import py_compile
py_compile.compile(P, doraise=True)
print('syntax OK')
