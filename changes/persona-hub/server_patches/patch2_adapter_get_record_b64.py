import shutil

P = '/AstrBot/astrbot/core/platform/sources/aiocqhttp/aiocqhttp_platform_adapter.py'
BAK = '/AstrBot/data/patches_backup/aiocqhttp_platform_adapter.py.orig.20260919'

shutil.copy2(P, BAK)
print('backup ->', BAK)

src = open(P, encoding='utf-8').read()

anchor = '''                        if t not in ComponentTypes:
                            logger.warning(
                                f"不支持的消息段类型，已忽略: {t}, data={m['data']}"
                            )
                            continue
                        a = ComponentTypes[t](**m["data"])'''

patch = '''                        if t not in ComponentTypes:
                            logger.warning(
                                f"不支持的消息段类型，已忽略: {t}, data={m['data']}"
                            )
                            continue
                        if t == "record":
                            # Yachiyo patch 20260919: QQ 语音本体是加密体（本地路径
                            # 与直链均不可解码），经 napcat get_record 解密转码为
                            # wav base64；失败回退原始 record 段构造。
                            try:
                                rr = await self.bot.call_action(
                                    action="get_record",
                                    file=m["data"].get("file", ""),
                                    out_format="wav",
                                    **routing_params,
                                )
                                b64 = (rr or {}).get("base64", "")
                                if b64:
                                    abm.message.append(
                                        ComponentTypes[t](file=f"base64://{b64}")
                                    )
                                    continue
                                logger.warning(
                                    "get_record 未返回 base64，回退原始 record 段"
                                )
                            except BaseException as e:
                                logger.warning(
                                    f"get_record 调用失败，回退原始 record 段: {e}"
                                )
                        a = ComponentTypes[t](**m["data"])'''

assert anchor in src, 'anchor not found'
assert 'Yachiyo patch 20260919' not in src, 'already patched'
src = src.replace(anchor, patch, 1)
open(P, 'w', encoding='utf-8').write(src)
print('patched: adapter record -> get_record base64')

import py_compile
py_compile.compile(P, doraise=True)
print('syntax OK')
