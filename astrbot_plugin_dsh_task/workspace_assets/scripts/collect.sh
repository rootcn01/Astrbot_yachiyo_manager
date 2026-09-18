#!/usr/bin/env bash
# scoped 收工提交（LifeOS window-commit 极简迁移）：只 add tasks/<slug>/ 与显式列出的文件。
# 禁止 git add -A —— 收工纪律由宪法第 6 条与 collect 白名单共同保证。
set -euo pipefail
cd "$(dirname "$0")/.."
slug="${1:?用法: collect.sh <任务slug> [额外文件...]}"
shift || true

add=()
while IFS= read -r f; do
  [ -n "$f" ] || continue
  if [[ "$f" == "tasks/"$slug"/*" ]]; then
    add+=("$f")
  fi
done < <(git status --porcelain | awk '{print $2}')

for f in "$@"; do
  [ -e "$f" ] && add+=("$f")
done

if [ ${#add[@]} -eq 0 ]; then
  echo "没有白名单内的变更（tasks/$slug/ 与显式清单均为空），不提交。"
  exit 0
fi

echo "提交清单:"
printf '  %s\n' "${add[@]}"
git add -- "${add[@]}"
git commit -m "task: $slug" --quiet
git log --oneline -1
echo "收工。别忘了 TASKLOG.md 追加一行（时间 | 任务 | 文件 | 结果）。"
