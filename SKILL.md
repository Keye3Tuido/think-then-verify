---
name: tv
description: 安装或检查 TV 的 AGENTS.md 固定流程，在任务推进与上下文恢复时保持目标、约束、真实证据和有效交付。
metadata:
  tv_contract: agents-workflow-v2
---

# TV 流程安装入口

TV 的完整流程位于同目录 [AGENTS.md](AGENTS.md)。先读取该文件，当前任务直接遵循其中流程。

使用时检查宿主实际加载的全局或项目 AGENTS.md 是否包含当前 `think-then-verify` 标记区块。全局规则已覆盖当前项目时复用；缺失或过期时备份目标文件，合并同目录 AGENTS.md 的完整区块，保留其他规则。标记残缺、重复或存在冲突时先查明，不能覆盖用户内容。使用本入口包含检查与补齐该区块的授权，仍遵守宿主文件权限。

可选安装工具：

```bash
python3 install.py check --agents-file /path/to/AGENTS.md
python3 install.py install --agents-file /path/to/AGENTS.md
```

安装后，流程直接由宿主加载的 AGENTS.md 持续约束任务；不依赖技能再次被选中、Hook、适配器或启停状态。文件存在与宿主实际加载分别核验，只有宿主读取该规则时才会自动应用。只持有 AGENTS.md 时，也可直接合并其区块使用。
