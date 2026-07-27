# /tv — Think-Then-Verify

让 AI 助手在每个回复前强制执行 Think → Verify → Decide 三阶段自查流程。

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

在支持 Skill 的 IDE 中启用该 skill 后即**全局生效**，无需逐条输入 `/tv`：此后每次回复都会自动执行 Think → Verify → Decide 三阶段流程。
