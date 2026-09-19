# AstrBot 容器内补丁（compose 重建后必重放）

容器重建（docker-compose up -d / recreate）会丢容器可写层，两个补丁须重放：

```
scp patch*.py ubuntu@110.40.182.106:/tmp/
ssh 后：sudo docker cp /tmp/patch1_components_record_path_first.py astrbot-astrbot-1:/tmp/
       sudo docker cp /tmp/patch2_adapter_get_record_b64.py astrbot-astrbot-1:/tmp/
       sudo docker exec astrbot-astrbot-1 python3 /tmp/patch1_components_record_path_first.py
       sudo docker exec astrbot-astrbot-1 python3 /tmp/patch2_adapter_get_record_b64.py
       sudo docker restart astrbot-astrbot-1
```

- patch1（2026-09-19）：Record._resolve_file_source path 优先（防御层，base64 生效后冗余但无害）
- patch2（2026-09-19）：adapter record 段经 napcat get_record 解密转 wav base64（QQ 语音加密体的唯一活路）
- 重放前提：镜像 soulter/astrbot:v4.26.5（.env 已固定）；napcat HTTP API 在 http://napcat:3000
- 补丁前自动备份到容器内 /AstrBot/data/patches_backup/（宿主卷，重建不丢）
