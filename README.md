# Think-Then-Verify — IDE 配置指南

将本技巧配置到各主流 IDE 的一键安装命令。每条命令自动从 GitHub 下载 YAML 头文件与主模板并拼接写入对应目录。

> 主模板 `think-then-verify.template.md` 是纯正文（含 5 个完整示例），YAML 头文件仅含各 IDE 的 frontmatter 元数据。

---

## VS Code（GitHub Copilot）

参考文档：[VS Code Custom Instructions](https://code.visualstudio.com/docs/copilot/customization/custom-instructions)

**用户级安装**（Windows/PowerShell）：

```powershell
$dir = "$env:USERPROFILE\.copilot\instructions"; New-Item -ItemType Directory -Force -Path $dir | Out-Null
$header = irm https://raw.githubusercontent.com/Keye3Tuido/think-then-verify/main/vscode/think-then-verify.instructions.md
$body   = irm https://raw.githubusercontent.com/Keye3Tuido/think-then-verify/main/think-then-verify.template.md
"$header`n$body" | Set-Content -Encoding UTF8 "$dir\think-then-verify.instructions.md"
```

**用户级安装**（macOS/Linux/bash）：

```bash
mkdir -p ~/.copilot/instructions
curl -sS https://raw.githubusercontent.com/Keye3Tuido/think-then-verify/main/vscode/think-then-verify.instructions.md >  /tmp/_header.md
curl -sS https://raw.githubusercontent.com/Keye3Tuido/think-then-verify/main/think-then-verify.template.md          >  /tmp/_body.md
cat /tmp/_header.md /tmp/_body.md > ~/.copilot/instructions/think-then-verify.instructions.md
rm /tmp/_header.md /tmp/_body.md
```

**项目级安装**（Windows/PowerShell）：

```powershell
$dir = ".\.github\instructions"; New-Item -ItemType Directory -Force -Path $dir | Out-Null
$header = irm https://raw.githubusercontent.com/Keye3Tuido/think-then-verify/main/vscode/think-then-verify.instructions.md
$body   = irm https://raw.githubusercontent.com/Keye3Tuido/think-then-verify/main/think-then-verify.template.md
"$header`n$body" | Set-Content -Encoding UTF8 "$dir\think-then-verify.instructions.md"
```

**项目级安装**（macOS/Linux/bash）：

```bash
mkdir -p .github/instructions
curl -sS https://raw.githubusercontent.com/Keye3Tuido/think-then-verify/main/vscode/think-then-verify.instructions.md >  /tmp/_header.md
curl -sS https://raw.githubusercontent.com/Keye3Tuido/think-then-verify/main/think-then-verify.template.md          >  /tmp/_body.md
cat /tmp/_header.md /tmp/_body.md > .github/instructions/think-then-verify.instructions.md
rm /tmp/_header.md /tmp/_body.md
```

---

## Cursor

参考文档：[Cursor Rules](https://cursor.com/docs/rules)

**安装**（Windows/PowerShell）：

```powershell
$dir = ".\.cursor\rules"; New-Item -ItemType Directory -Force -Path $dir | Out-Null
$header = irm https://raw.githubusercontent.com/Keye3Tuido/think-then-verify/main/cursor/think-then-verify.mdc
$body   = irm https://raw.githubusercontent.com/Keye3Tuido/think-then-verify/main/think-then-verify.template.md
"$header`n$body" | Set-Content -Encoding UTF8 "$dir\think-then-verify.mdc"
```

**安装**（macOS/Linux/bash）：

```bash
mkdir -p .cursor/rules
curl -sS https://raw.githubusercontent.com/Keye3Tuido/think-then-verify/main/cursor/think-then-verify.mdc >  /tmp/_header.md
curl -sS https://raw.githubusercontent.com/Keye3Tuido/think-then-verify/main/think-then-verify.template.md   >  /tmp/_body.md
cat /tmp/_header.md /tmp/_body.md > .cursor/rules/think-then-verify.mdc
rm /tmp/_header.md /tmp/_body.md
```

---

## Claude Code

参考文档：[Claude Code Memory](https://code.claude.com/docs/en/memory)

**安装**（Windows/PowerShell）：

```powershell
$dir = ".\.claude\rules"; New-Item -ItemType Directory -Force -Path $dir | Out-Null
$header = irm https://raw.githubusercontent.com/Keye3Tuido/think-then-verify/main/claude-code/think-then-verify.md
$body   = irm https://raw.githubusercontent.com/Keye3Tuido/think-then-verify/main/think-then-verify.template.md
"$header`n$body" | Set-Content -Encoding UTF8 "$dir\think-then-verify.md"
```

**安装**（macOS/Linux/bash）：

```bash
mkdir -p .claude/rules
curl -sS https://raw.githubusercontent.com/Keye3Tuido/think-then-verify/main/claude-code/think-then-verify.md >  /tmp/_header.md
curl -sS https://raw.githubusercontent.com/Keye3Tuido/think-then-verify/main/think-then-verify.template.md     >  /tmp/_body.md
cat /tmp/_header.md /tmp/_body.md > .claude/rules/think-then-verify.md
rm /tmp/_header.md /tmp/_body.md
```

---

## Kiro

参考文档：[Kiro Steering](https://kiro.dev/docs/steering)

**安装**（Windows/PowerShell）：

```powershell
$dir = ".\.kiro\steering"; New-Item -ItemType Directory -Force -Path $dir | Out-Null
$header = irm https://raw.githubusercontent.com/Keye3Tuido/think-then-verify/main/kiro/think-then-verify.md
$body   = irm https://raw.githubusercontent.com/Keye3Tuido/think-then-verify/main/think-then-verify.template.md
"$header`n$body" | Set-Content -Encoding UTF8 "$dir\think-then-verify.md"
```

**安装**（macOS/Linux/bash）：

```bash
mkdir -p .kiro/steering
curl -sS https://raw.githubusercontent.com/Keye3Tuido/think-then-verify/main/kiro/think-then-verify.md >  /tmp/_header.md
curl -sS https://raw.githubusercontent.com/Keye3Tuido/think-then-verify/main/think-then-verify.template.md >  /tmp/_body.md
cat /tmp/_header.md /tmp/_body.md > .kiro/steering/think-then-verify.md
rm /tmp/_header.md /tmp/_body.md
```

---

## 文件命名对照

| IDE | 文件名 | 所在目录 |
|-----|--------|---------|
| VS Code | `think-then-verify.instructions.md` | `~/.copilot/instructions/` 或 `.github/instructions/` |
| Cursor | `think-then-verify.mdc` | `.cursor/rules/` |
| Claude Code | `think-then-verify.md` | `.claude/rules/` |
| Kiro | `think-then-verify.md` | `.kiro/steering/`
