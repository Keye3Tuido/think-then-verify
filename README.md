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

Cursor 不支持 Skill，使用 Rules 代替。在 `.cursor/rules/tv.mdc` 中写入：

```yaml
---
alwaysApply: true
---

```

后接 SKILL.md 的 body 内容。

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

## 使用

在支持 Skill 的 IDE 中，输入 `/tv` 即可激活。
