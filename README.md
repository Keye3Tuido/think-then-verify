# /tv — Think-Then-Verify

用户主动调用一次 `/tv` 后，在当前对话持续执行 Think → Verify → Decide → Output，核验流程、实际行为、授权与证据，直到用户显式关闭。

## 安装

将 `SKILL.md` 复制到对应 IDE 的 skills 目录：

### VS Code（GitHub Copilot）

```bash
mkdir -p .copilot/skills/tv
cp SKILL.md .copilot/skills/tv/SKILL.md
```

或用户级安装：

```bash
mkdir -p ~/.copilot/skills/tv
cp SKILL.md ~/.copilot/skills/tv/SKILL.md
```

### Claude Code

```bash
mkdir -p .claude/skills/tv
cp SKILL.md .claude/skills/tv/SKILL.md
```

或用户级安装：

```bash
mkdir -p ~/.claude/skills/tv
cp SKILL.md ~/.claude/skills/tv/SKILL.md
```

### Cursor

Cursor 自 2.4 版本起支持 Agent Skills（[官方文档](https://cursor.com/docs/context/skills)）。

```bash
mkdir -p .cursor/skills/tv
cp SKILL.md .cursor/skills/tv/SKILL.md
```

或用户级安装：

```bash
mkdir -p ~/.cursor/skills/tv
cp SKILL.md ~/.cursor/skills/tv/SKILL.md
```

> Cursor 也兼容 `.agents/skills/` 目录。

### Kiro

```bash
mkdir -p .kiro/skills/tv
cp SKILL.md .kiro/skills/tv/SKILL.md
```

或用户级安装：

```bash
mkdir -p ~/.kiro/skills/tv
cp SKILL.md ~/.kiro/skills/tv/SKILL.md
```

### DeepSeek TUI

```bash
mkdir -p .deepseek/skills/tv
cp SKILL.md .deepseek/skills/tv/SKILL.md
```

或用户级安装：

```bash
mkdir -p ~/.deepseek/skills/tv
cp SKILL.md ~/.deepseek/skills/tv/SKILL.md
```

## 使用

1. 在当前对话主动调用一次 `/tv`，可在命令后附带任务。
2. 启用后，后续用户回合自动执行流程；上下文恢复和任务结束保持启用状态。
3. 使用 `/tv off`、`/tv 关闭` 或明确要求关闭 TV 流程，结束当前对话中的启用状态。新对话默认关闭。

安装、读取技能和在示例中提到 `/tv` 不会启用流程。

## 执行前提

安装文件后，须按 `SKILL.md` 检查并建立适用宿主的运行时能力：

- 唯一逻辑守卫：`think-then-verify-process-gate`。先在生产拦截关闭时验证必需能力，再按宿主信任要求激活并回读实际状态。
- 宿主任务接口：支持创建、更新和回读任务状态。
- 固定会话注册表与状态目录：切换项目仍能定位原会话记录。
- 输出链路：发布前检查，以及由可信宿主完成事件保存交付回执、更新 Output 任务。

用户启用意图与 Hook 激活分开记录。初次验证缺少能力时，生产拦截保持未激活；运行中能力失效时进入维护状态。两种情况均报告阻塞、暂停原任务，保留显式关闭、必要诊断和已授权的适配器维护入口。关闭先于能力和阶段检查，即使回合标识缺失或状态损坏也须落实，不能按旧启用值自动恢复。技能不提供任务文件或口头自查的替代执行方式。

Hook 注册数量尽量少，并覆盖用户控制、工具执行前、工具执行后、答复发布前及交付结果五项职责。宿主可在同一入口承担多项职责，因此不固定为五个 Hook。恢复检查复用必经入口，结束或中断通知仅在现有交付入口覆盖不足时增加；宿主任务接口不计入 Hook 数量。每个入口及其绕过路径须实测，覆盖不完整时不能激活生产拦截。

## 保障范围

本仓库提供单文件技能规范，复制 `SKILL.md` 不代表 Hook 已安装或生效。运行时适配器须按宿主实际接口建立并验证；宿主无法提供必需拦截或回调能力时，该环境不能执行此流程。

核验面向可观察的流程、行为和证据；阶段标签与任务勾选不能代替执行证明，也不能证明内部思考充分或所有结论正确。
