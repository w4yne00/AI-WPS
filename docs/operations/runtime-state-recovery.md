# 运行数据快照、迁移与整体恢复

AI-WPS 将模型配置、八类任务映射、激活关系、API Key 文件和写作规范数据库视为一组一致性运行数据。不得单独复制或恢复其中某个文件。

## 目录与权限

默认安装布局使用：

- `state/`：正式共享运行状态；
- `backups/`：已生成的快照、脱敏清单和审计记录；
- `var/`：日志、PID 和事务记录，不进入运行数据快照。

`state/`、`backups/` 和每个快照目录使用 `0700`；配置、数据库、Key 文件、清单和审计记录使用 `0600`。清单只记录 Key 引用、存在性和 SHA-256 指纹，不记录 Key 明文；服务地址仅记录不可逆摘要。

## 安装和旧布局迁移

安装器在覆盖 Adapter 程序前先停止 systemd 服务或旧 Adapter 进程，并确认运行端口已经释放；停写状态保持到共享状态完成切换。随后执行以下动作：

1. 若共享状态已经存在，先创建原因标记为 `pre_install` 的快照；
2. 若只有旧版 `config/`、`run/` 布局，先将数据复制到同文件系统的隔离目录；
3. 在副本中迁移并核验八类任务配置、服务地址、Key 引用、激活关系和规范数据库；
4. 核心数据验证通过后整体切换共享状态目录。核心失败返回 `recovery` 且不改动正式状态；仅规范数据库失败时原数据库字节保持不变，返回 `degraded`。

手工迁移前也必须先停止 Adapter。命令会对配置、Key、数据库及 SQLite WAL/SHM 做复制前后稳定性校验；检测到并发写入时最多重试三次，仍不稳定则以 `recovery` 退出且不切换正式状态。

手工迁移命令：

```bash
bash scripts/runtime_state.sh migrate /旧版/adapter-start-kit
```

## 创建快照

```bash
bash scripts/runtime_state.sh snapshot manual_backup
```

每个有效快照包含版本、原因、数量、引用关系、文件校验值和规范数据库完整性结果。系统保留最近三个有效快照；标记为上一已验收版本最后有效快照的快照不参与普通清理。清理先持久化审计意图，再把目标快照原子移动到可回滚的隐藏目录；完成审计写入成功后才物理删除。

上一版本完成目标机验收后，使用保护标记创建该版本最后有效快照：

```bash
bash scripts/runtime_state.sh snapshot accepted_release --protect-last-accepted
```

## 整体恢复

恢复前先停止 Adapter，并从目标快照的 `manifest.json` 确认 `valid` 为 `true`。恢复必须显式给出快照 ID 和固定二次确认文本：

```bash
bash scripts/runtime_state.sh restore snapshot-YYYYMMDDTHHMMSSZ-xxxxxxxxxxxx RESTORE_WHOLE_STATE
```

恢复命令会先为当前正式状态创建 `pre_restore` 快照，再校验目标快照全部文件及引用关系，最后整体切换 `state/`。命令不提供单文件、单配置、单 Key 或单数据库恢复参数。完成后应启动 Adapter，并检查 `/health/live`、`/health/ready` 和 `/health`。
