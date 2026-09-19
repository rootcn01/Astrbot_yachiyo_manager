# 八千代（月見ヤチヨ / CV:早見沙織）微调数据集 · 2026-09-19

GPT-SoVITS v2ProPlus 训练用。**108 片 / 298.1s（~5 分钟）干净 solo + 3 条推理 prompt。**

## 来源与语域

| 前缀 | 来源 | 语域 | 条数/秒数 |
|---|---|---|---|
| `p2_*` | 闹钟 App 全语音展示（BV1eUem6yE3x P2） | 角色（撒娇/元气/优雅混合，**生产同域**） | 51 / ~140s |
| `bd_*` | BD 角色评论轨（BV1Jhe16EELF，早見席） | 谈话（角色口吻漫谈，设定解说） | 49 / ~135s |
| `bc_*` | 迎宾广播×5（BV1nZjz6REQK main+P2-P5） | 正式（播报员） | 8 / ~20s |

音频全部 16kHz/mono/16bit wav（GPT-SoVITS 数据处理步骤会自行重采样去噪）。

## 归人方法（勿信单一信号）

- **ECAPA-TDNN 声纹**（speechbrain/spkrec-ecapa-voxceleb，CPU int8）：对锚=`candidates/alarmP2_yachiyo_solo_v1.wav`（9 条人工核验 solo 拼接）。阈值 utterance≥0.40，≥3.2s 片最差 1.6s 块≥0.35（块纯度剔串音，校准集：solo 块 0.51-0.78 / 他人+串音块多 <0.35）。
- k-means 聚类交叉验证：BD 三簇=三位 CV 各一，早見簇=c2 被锚认领（0.613）。
- faster-whisper large-v3-turbo（language=ja）出训练转写；MiMo ASR auto 会中日英乱漂、language 强制码全 400，勿用于训练文本。

## 关键事实（本窗翻案）

1. **P2 整包=八千代单人语音包**：所谓「かぐや线」（カグヤの宝物/圣诞/情人节问候）实为八千代第三人称谈かぐや——ECAPA 对锚 0.665 >> 早見本人跨语域基线 0.331。resemblyzer 在本域无区分度（同包不同人也能 0.9），弃用。
2. 迎宾广播主体是三人对话，仅 ~20s 段落是八千代独白（ECAPA 逐片筛出）。
3. BD 评论轨早見份额（ECAPA c2）≈135s 高置信 solo；c0/c1=另两位 CV（夏吉ゆうこ/永瀬アンナ），未挖。

## 训练用法（整合包 WebUI）

1. 数据集格式工具指向本目录（`yachiyo.list` 已是 `wav/xx.wav|yachiyo|JP|文本` 格式）。
2. 训练参数按交接简报 §3.2：4060Ti 8G，SoVITS bs1 / GPT bs2，不开 DPO，2-3h。
3. 推理参考 prompt 用 `prompt_map.json` 三条（happy/tender/default，对应部署方案 §2.3 的 style 映射种子；文本以 whisper 为准）。

## 扩量路径（按性价比序）

1. **买 BD 特装版**（SNCL-00119/120/121，¥330 通常版起）：本篇旁白+台词 10min+，LPCM 无损——研究文档 Stage 1 立项即为此。
2. BD 评论轨 c2 边界带放宽（sy 0.35-0.40）再人工听审，预计 +30-60s。
3. 广播轨 1.0-1.5s 短片回收（本窗 MIN_DUR=1.5 挡掉 ~10 片）。

## 再生性

管线脚本在 `tools_p2_mining/`：`bd_segment/bd_score`（切分+双锚评分）→ `asr_full`（MiMo 粗转写归人线索）→ `ecapa_verify`（区分度+聚类认领）→ `bc_mine`（广播轨全链）→ `build_finetune_dataset`（终选+whisper 转写+组包）。中间产物在 `_tmp/bili_dl/*.json`（gitignored）。
