#!/usr/bin/env bash
# yachiyo-tts-router 服务器部署脚本（Ubuntu 24.04，幂等，可重复执行=升级）。
# 用法：
#   sudo ./deploy_server.sh                # 部署/升级：拷文件、生成配置、装服务、探活
#   sudo ./deploy_server.sh --rollback     # 回滚：停用服务，删程序与单元文件（保留配置/状态/日志）
#   sudo ./deploy_server.sh --rollback --purge  # 彻底清除：连 /etc /var/lib /var/log 一起删
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${0}")" && pwd)"
SERVICE_NAME="yachiyo-tts-router"
OPT_DIR="/opt/yachiyo-tts-router"
ETC_DIR="/etc/yachiyo-tts-router"
STATE_DIR="/var/lib/yachiyo-tts-router"
LOG_DIR="/var/log/yachiyo-tts-router"
UNIT_SRC="${SCRIPT_DIR}/yachiyo-tts-router.service"
UNIT_DST="/etc/systemd/system/${SERVICE_NAME}.service"
CONFIG_DST="${ETC_DIR}/config.json"
HEALTH_URL="http://172.19.0.1:8800/health"

ROLLBACK=0
PURGE=0
for arg in "$@"; do
  case "${arg}" in
    --rollback) ROLLBACK=1 ;;
    --purge) PURGE=1 ;;
    *) printf '[deploy] 未知参数: %s\n' "${arg}" >&2; exit 2 ;;
  esac
done

log() { printf '[deploy] %s\n' "$*"; }
die() { printf '[deploy] 错误: %s\n' "$*" >&2; exit 1; }
require_root() { [ "$(id -u)" -eq 0 ] || die "请用 root 运行：sudo $0"; }

do_rollback() {
  log "回滚 ${SERVICE_NAME}（stop + disable + 删文件）"
  systemctl stop "${SERVICE_NAME}.service" 2>/dev/null || true
  systemctl disable "${SERVICE_NAME}.service" 2>/dev/null || true
  systemctl daemon-reload || true
  log "删除文件清单："
  local f
  for f in "${UNIT_DST}" "${OPT_DIR}/yachiyo_router.py" \
           "${OPT_DIR}/config.example.json" "${OPT_DIR}/test_router.py"; do
    rm -f -- "${f}" && log "  已删 ${f}"
  done
  rmdir "${OPT_DIR}" 2>/dev/null || log "  保留（非空） ${OPT_DIR}"
  if [ "${PURGE}" -eq 1 ]; then
    local d
    for d in "${ETC_DIR}" "${STATE_DIR}" "${LOG_DIR}"; do
      rm -rf -- "${d}" && log "  已删(含数据) ${d}"
    done
  else
    log "保留配置/状态/日志：${ETC_DIR} ${STATE_DIR} ${LOG_DIR}（彻底清除请加 --purge）"
  fi
  log "回滚完成。"
}

probe_once() {
  local url="$1"
  if command -v curl >/dev/null 2>&1; then
    curl -fsS --max-time 3 "${url}" && echo
  else
    python3 -c 'import sys,urllib.request;sys.stdout.write(urllib.request.urlopen(sys.argv[1],timeout=3).read().decode("utf-8"))' "${url}" && echo
  fi
}

health_probe() {
  local url="$1" i out
  for i in $(seq 1 10); do
    if out="$(probe_once "${url}" 2>/dev/null)"; then
      printf '%s\n' "${out}"
      return 0
    fi
    sleep 1
  done
  return 1
}

main() {
  require_root
  [ -f "${SCRIPT_DIR}/yachiyo_router.py" ] || die "缺少 ${SCRIPT_DIR}/yachiyo_router.py（请在 router/ 目录内运行）"
  [ -f "${UNIT_SRC}" ] || die "缺少 ${UNIT_SRC}"
  [ -f "${SCRIPT_DIR}/config.example.json" ] || die "缺少 ${SCRIPT_DIR}/config.example.json"

  log "创建目录 ${OPT_DIR} ${ETC_DIR} ${STATE_DIR} ${LOG_DIR}"
  install -d -m 0755 "${OPT_DIR}" "${ETC_DIR}" "${STATE_DIR}" "${LOG_DIR}"

  log "安装文件 -> ${OPT_DIR}"
  install -m 0644 "${SCRIPT_DIR}/yachiyo_router.py" "${OPT_DIR}/yachiyo_router.py"
  install -m 0644 "${SCRIPT_DIR}/config.example.json" "${OPT_DIR}/config.example.json"
  if [ -f "${SCRIPT_DIR}/test_router.py" ]; then
    install -m 0644 "${SCRIPT_DIR}/test_router.py" "${OPT_DIR}/test_router.py"
  fi

  if [ -f "${CONFIG_DST}" ]; then
    log "已存在 ${CONFIG_DST}，保持不动（如需重置：备份后删除再重跑本脚本）"
  else
    install -m 0600 "${SCRIPT_DIR}/config.example.json" "${CONFIG_DST}"
    log "已从 example 生成 ${CONFIG_DST}"
  fi

  log "安装 systemd 单元并启用"
  install -m 0644 "${UNIT_SRC}" "${UNIT_DST}"
  systemctl daemon-reload
  systemctl enable "${SERVICE_NAME}.service" >/dev/null
  if systemctl is-active --quiet "${SERVICE_NAME}.service"; then
    log "服务已在运行，restart 以加载新代码"
    systemctl restart "${SERVICE_NAME}.service"
  else
    systemctl start "${SERVICE_NAME}.service"
  fi

  log "探活 ${HEALTH_URL}（最多 10 次，间隔 1s）"
  if health_probe "${HEALTH_URL}"; then
    log "部署完成，服务健康。"
  else
    log "探活失败。排查："
    log "  systemctl status ${SERVICE_NAME}.service"
    log "  journalctl -u ${SERVICE_NAME}.service -n 50"
    log "  ip addr show   # 确认 172.19.0.1 存在（需 astrbot 所在 docker 自定义网络已拉起）"
    exit 1
  fi

  if grep -q "CHANGE_ME" "${CONFIG_DST}" 2>/dev/null; then
    log "[警告] ${CONFIG_DST} 中 bridge_token 仍是 CHANGE_ME。"
    log "  请手工编辑注入真实 token（与 Windows 侧 yachiyo-tts-bridge 同值），"
    log "  然后：systemctl restart ${SERVICE_NAME}.service"
  fi
}

if [ "${ROLLBACK}" -eq 1 ]; then
  require_root
  do_rollback
else
  main
fi
