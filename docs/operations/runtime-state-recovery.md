# 运行数据快照、迁移与整体恢复

AI-WPS 将模型配置、八类任务映射、激活关系、API Key 文件和写作规范数据库视为一组一致性运行数据。不得单独复制或恢复其中某个文件。

## 目录与权限

默认安装布局使用：

- `state/`：正式共享运行状态；
- `backups/`：已生成的快照、脱敏清单和审计记录；
- `var/`：日志、PID 和事务记录，不进入运行数据快照。

`state/`、`backups/` 和每个快照目录使用 `0700`；配置、数据库、Key 文件、清单和审计记录使用 `0600`。清单只记录 Key 引用、存在性和 SHA-256 指纹，不记录 Key 明文；服务地址仅记录不可逆摘要。

## 发布代际与事务日志

安装根目录中的 `releases/<version>/` 保存不可变 Adapter 程序和该版本私有依赖，`current` 指向当前发布目录。三宿主插件、`publish.xml`、Adapter 发布目录、私有依赖、`current` 指针及匹配的数据快照构成一个发布代际。

安装器在 `var/transactions/` 写入权限为 `0600` 的 JSON 事务日志。候选组件先在各自目标父目录下完成校验，再使用同文件系统重命名逐项切换；候选运行状态副本作为 `runtime_state_snapshot` 组件切换，`current` 最后切换。最终健康、版本、候选快照或组件哈希校验失败时，安装器停止候选 Adapter，并按相反顺序恢复上一运行状态目录及全部组件。若安装进程中断，下次安装在创建新候选前恢复未完成事务。事务状态不是 `committed` 时，不得把安装结果登记为成功。

若目标机已安装 `ai-wps-adapter.service`，必须以管理员身份执行升级。七组件终检通过后，事务先进入保留全部反向补偿数据的 `ready_to_commit`；父安装进程随后重新渲染 unit，使 `WorkingDirectory`、`ExecStart` 与 `ExecStop` 均通过稳定的 `current` 指针访问 Adapter，并重新加载、启动服务。只有 systemd 启动成功且组件再次复验通过后，事务才进入 `committed` 并清理备份。handoff 会持久化事务日志、旧 unit 备份位置及升级前服务活动状态。父进程失败或中断时，恢复流程先停止候选 Adapter、回滚七组件，再恢复旧 unit，并仅在升级前服务处于活动状态时重启上一 Adapter。任一补偿步骤失败时保留 handoff 和尚存备份，供下次管理员运行重试，不得把混合代际登记为成功。因此 systemd 重启和主机重启不会回到旧发布目录。

不要手工删除 `switching`、`awaiting_finalization`、`verification_failed` 或 `rolling_back` 状态的事务日志及其同目录隐藏备份。应保持 WPS 与 Adapter 停止，再重新执行安装器完成自动恢复。

## 安装和旧布局迁移

安装器在覆盖 Adapter 程序前先停止 systemd 服务或旧 Adapter 进程，并确认运行端口已经释放；停写状态保持到共享状态完成切换。随后执行以下动作：

1. 若共享状态已经存在，先创建原因标记为 `pre_install` 的快照；
2. 若只有旧版 `config/`、`run/` 布局，先将数据复制到同文件系统的隔离目录；
3. 在副本中迁移并核验八类任务配置、服务地址、Key 引用、激活关系和规范数据库；
4. 在同父目录准备候选状态副本并生成候选快照；事务切换前不改动正式 `state/`。核心失败返回 `recovery`；仅规范数据库失败时原数据库字节保持不变，返回 `degraded`。

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
