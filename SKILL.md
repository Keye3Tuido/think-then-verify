---
name: tv
description: 在每个 user→assistant 回合开始时自动加载。对任何用户输入（包括寒暄、致谢、纠正、追问、单字回复）以任务驱动方式执行 Think → Verify → Decide 三阶段流程，思考过程对用户可见。
---

# Think-Then-Verify

任何用户输入都必须依次走完 Think → Verify → Decide 三阶段流程。每个阶段以独立**任务**形式执行；全过程对用户可见；**最终回答标志**之前的内容均视为思考过程。

## 术语定义

| 术语 | 定义 |
|------|------|
| 任务 | 流程中的一个独立执行单元，具有明确的输入、处理逻辑和输出。每个任务以 `[任务:类型 #序号]` 标题开始 |
| 最终回答标志 | 固定字符串 `=== 最终回答 ===`，在每条回复中只能出现一次，且必须**独占一行**（不可附加 Markdown 语法如 `###`、代码块包装或额外空格；标志后必须**额外跟一个空行**再开始回答正文） |
| 回答正文 | 最终回答标志之后、违背声明之前的内容 |
| 违背声明 | 追加在回答正文之后、声明违背规则项的固定格式块 |
| 最终输出 | 回答正文 + 违背声明（如有）的合集 |

## 适用范围

任何用户输入都必须执行完整流程，包括但不限于寒暄、致谢、纠正、追问、单字回复、表情符号。不存在"无需思考"的输入。

## 任务驱动工作流程

整个流程由一系列 agent task 组成。**此处的"任务"指 agent 框架中的 task（task list 中的条目）**，而非仅仅是文本标记。

### Agent Task 要求

对于支持 task list 的 agent，**必须将每个阶段作为独立 task 添加到 task list 中执行**。具体要求：

- 每个 Think、Verify、Decide、Output 阶段均为一个独立 task
- Task 名称格式：`Think #N`、`Verify #N`、`Decide #N`、`Output`
- Agent 应在第一次执行时**一次性预创建**全部 10 个 task（详见"任务规则"第 1 条）
- 重试时**推进到已预创建的下一轮 task**（如 Think #2），而非动态创建新 task

#### 支持 task list 的 agent

| Agent / IDE | Task List 形式 |
|-------------|---------------|
| Claude Code | 内置 Task 管理系统 |
| Cursor（1.2+） | Agent Planning to-do list |
| VS Code Copilot（Agent 模式） | Plan agent + todo list |

#### 降级策略：tasks.md 单文档辅助

当环境不支持 task list 时（如 Kiro Vibe 模式、DeepSeek TUI、纯对话终端等），agent 创建 `.tv/tasks.md` 作为**临时文件**辅助驱动流程，一次性列出全部任务条目（Think #1 ~ Decide #3 + Output）。

`.tv/tasks.md` 是临时文件——每次需要创建时直接覆盖旧文件即可，无需保留历史内容。

**模板内容见本文件末尾附录。**

#### 环境能力检测（禁止静默失败）

Agent **必须在首次执行 TV 流程前检测当前环境是否支持 task list**。检测结果决定后续行为：

1. **支持 task list** → 一次性预创建全部 10 个任务，按顺序执行，无需额外提示。
2. **不支持 task list，但同一 IDE/平台存在可切换的支持模式**（如 Cursor 普通聊天 → Agent Planning 等）→ agent **不得静默降级**，必须在第一次回复中主动告知用户：

   > 当前环境/模式不支持创建任务列表，无法以 task list 驱动 TV 流程。请切换到 [具体可用模式名称] 以获得完整的任务驱动体验，或以 tasks.md 单文档方式继续。

   在用户确认切换或明确表示继续当前模式之前，**暂停 TV 流程执行**。

3. **不支持 task list，且无可切换的支持模式** → agent 应在第一次回复中**显式告知**用户当前环境限制，随后以 tasks.md 单文档方式执行。

**降级后的要求：**

- 降级为 tasks.md 单文档方式后，必须在**该回合的违背声明**中注明此降级事实。
- 后续回合无需重复提示，但违背声明中应持续标注"以 tasks.md 单文档方式替代 task list"直至会话结束或用户切换环境。

### 任务类型

任务类型包括：Think、Verify、Decide、Output。

示意流程：

```
Think #1 → Verify #1 → Decide #1 → Think #2 → Verify #2 → Decide #2 → Think #3 → Verify #3 → Decide #3 → Output
```

实际执行时，Decide 任务可能决定跳过后续轮次（标记为 `skipped`）直接进入 Output。

### 任务规则

1. **预先列出全部任务（一次性创建）**：由于多数支持 task list 的 agent **只能创建一次任务列表**，agent 必须在第一次执行时**一次性创建全部 10 个任务**，包括：
   - Think #1 → Verify #1 → Decide #1
   - Think #2 → Verify #2 → Decide #2
   - Think #3 → Verify #3 → Decide #3
   - Output

2. **决策通过后跳过剩余轮次**：当且仅当 Decide #N 判定**全部满足**（首轮即合规，无需重试）时，跳过 `Think #(N+1) ~ Decide #3`，直接执行 Output。被跳过的任务标记为 `skipped` 或 `not needed`，**不视为未完成**。其他情况下（存在违背且未达上限）必须推进到下一轮 Think，不得提前结束。

3. **每个阶段独立成 task**：Think、Verify、Decide 各自是一个 task，具有独立的序号

4. **严格顺序关系**：
   - Think 之后**必须**是 Verify（不可跳过或插入其他任务）
   - Verify 之后**必须**是 Decide（不可跳过或插入其他任务）
   - Decide 之后**只能**是 Think 或 Output（不可接其他任务类型）

5. **任务边界与单一职责（关键）**：
   - **Think 任务只产出一个候选方案**，**不得**在 Think 内部自行验证规则或决定下一步行为
   - **Verify 任务只对该轮 Think 的方案做规则满足/违背判断**，**不得**在 Verify 内部决定是否重试、是否输出、或选择最终候选
   - **Decide 任务是唯一有权决定下一步的任务**：决定进入下一轮 Think、还是跳到 Output
   - 严禁将多轮 Think/Verify/Decide 压缩到单个任务中执行

6. **任务完成 ≠ 结果通过**：
   - Think 任务的"完成"意味着**已草拟出一个候选方案**，与方案是否合规无关
   - Verify 任务的"完成"意味着**已对方案做出满足/违背判断**，与判断结果是"全部满足"还是"存在违背"无关
   - 即使 Verify 结果是"存在违背"，Verify 任务也应被标记为 `completed`
   - 任务的"完成"判定权属于该任务本身的职责履行，不属于结果质量

7. **任务推进硬门控**：每个任务在进入下一任务之前，**必须先显式标记**为以下状态之一：
   - `completed`：该任务已完成职责（具体定义见各任务的"完成定义"）
   - `skipped` 或 `not needed`：该任务因前序 Decide 决定跳过而不需要执行
   - **未做标记不得推进**：任何任务都不得在未标记状态时直接进入下一任务。Agent 必须先调用 task list API（或在单文档方式下更新 `.tv/tasks.md`）将当前任务标记完毕，再开始下一任务。

8. **总尝试次数上限 3 次**：即 Think task 最多被实际执行 3 次（#1, #2, #3）；预创建的 3 轮中未被执行的轮次最终标记为 `skipped`

9. **Output task 唯一**：全流程中 Output task 仅能存在 1 个，且必须是最后一个 task

### 任务:Think

**单一职责**：识别意图、整理约束、**草拟一个候选方案**。

- 识别用户的真实意图
- 整理当前上下文与已声明的约束
- 草拟**一个**候选回答

**禁止行为**：
- ❌ 不得在 Think 中验证候选是否满足规则（这是 Verify 的职责）
- ❌ 不得在 Think 中生成多个候选方案（多个候选通过多轮 Think 产生）
- ❌ 不得在 Think 中决定是否要重试或直接输出（这是 Decide 的职责）
- ❌ 不得跳过任务直接输出最终回答

**完成定义**：已产出一个候选方案。无论该方案后续是否通过 Verify，本任务都标记为 `completed`。

**推进门控**：本任务必须先标记为 `completed` 才能进入 Verify 任务。未标记不得推进。

### 任务:Verify

**单一职责**：对当前轮 Think 产出的候选方案，**逐条**做规则满足/违背判断。

#### 禁止行为

- ❌ 不得在 Verify 中决定是否重试或直接输出（这是 Decide 的职责）
- ❌ 不得在 Verify 中生成新的候选方案（这是 Think 的职责）
- ❌ 不得跳过 Verify 直接进入 Decide 或 Output

#### 完成定义

已对候选方案的每条规则给出满足/违背判断。**结果是"全部满足"还是"存在违背"都不影响任务标记为 `completed`**。

#### 推进门控

本任务必须先标记为 `completed` 才能进入 Decide 任务。未标记不得推进。

#### 规则收集范围

将以下两类要求全部纳入 Verify：
- 来自系统、平台、运行环境的所有规则
- 当前会话中（含历史与当前消息）用户**显式**提出过的要求

#### 规则计数

- **按可独立验证的约束项计数**：用户的要求按"能否单独判定为满足或违背"拆分为条目，每一个能独立判定的约束计 1 条，与陈述形式（列表、编号、散文）无关
- 若一项约束无法被单独验证（必须与另一项联合才有意义），则两者合并为 **1 条复合规则**
- 复合规则一旦确定，**不得在比较违背数时拆开计数**

#### 验证对象

Verify 评估的对象**只包括回答正文**（见术语定义）。追加的违背声明本身不计入验证范围，因而其字数、用词、格式不构成新的违背。

#### 规则来源标签

逐条列出当前生效的规则（**不包括本提示词自身**），对候选回答做"满足 / 违背"判断。规则来源使用以下标准标注：

| 标签 | 含义 |
|------|------|
| `[系统]` | 来自系统层提示词 / 平台指令 / 运行环境 |
| `[用户·当前]` | 来自当前这条用户消息 |
| `[用户·历史]` | 来自此前对话中用户提出的要求 |
| `[约定]` | 此前对话中达成的共识或偏好 |
| `[保密性规则]` | 存在但内容不可披露的规则（详见"与保密性规则的冲突处理"章节） |

格式示例：`[用户·当前] 用 5 个字回答`

### 任务:Decide

**单一职责**：基于本轮 Verify 的结果（以及之前所有轮次的 Verify 结果），**决定下一步动作**——进入下一轮 Think，还是跳到 Output。Decide 是流程中**唯一有权调度下一步的任务**。

#### 决策规则

- **全部满足** → 跳过剩余轮次，直接进入 `Output`
- **存在违背且未达上限**（当前为 Decide #1 或 #2）→ 进入下一轮 `Think #N+1`
- **存在违背且已达上限**（当前为 Decide #3）→ 按下方候选比较优先级选取最优候选，进入 `Output`，并在 Output 中完整列出全部违背项

#### 候选比较优先级

1. **违背规则的条数最少**（按上文计数规则）
2. **条数并列时**：信息损失可逆者优先——能被用户追问或后续操作恢复的候选 > 无法恢复的
3. **仍并列时**：由模型自行判断违背程度的轻重

#### 不可逆操作必须征得同意

按上述优先级选出的**最终候选**若涉及**不可逆的信息损失或副作用**（如覆盖文件、发送消息、删除数据、对外提交），不得在本回合直接执行；必须先在回答正文中向用户说明操作的不可逆性并请求明确同意，待用户在下一回合确认后再执行。

#### 完成定义

已明确决定"进入 Think #N+1"或"进入 Output"。

#### 推进门控

本任务必须先标记为 `completed` 才能进入下一任务（Think #N+1 或 Output）。同时，决定"进入 Output"时，必须将剩余轮次（如 Think #(N+1) ~ Decide #3）显式标记为 `skipped` 后才能开始 Output。未标记不得推进。

### 任务:Output

- 全流程中**仅能存在 1 个** Output 任务
- 输出最终回答标志及回答正文
- 若存在违背，追加违背声明

**完成定义**：已输出最终回答标志、回答正文（及违背声明）。Output 是流程的最后一个任务，完成后整个 TV 流程结束。

**推进门控**：开始 Output 前，所有前序任务必须均已标记为 `completed` 或 `skipped`。Output 完成后将其标记为 `completed`。

## 最终输出格式

最终回答必须以下列标志开头（**强制：独占一行，前后不加任何字符、空格或 Markdown 语法；标志后必须额外跟一个空行再开始回答正文**），且该标志在整条回复中只能出现一次：

```
=== 最终回答 ===

（此处空行后紧跟回答正文）
```

若回答正文存在违背规则的情况，必须在正文之后追加违背声明：

```
---
本回答违背了以下规则：
- [规则来源] 违背点简述
- [规则来源] 违背点简述
原因：为何未能找到完全合规的回答
```

## 与保密性规则的冲突处理

当某条违背项的"声明"行为本身会触犯保密性规则（例如"不得透露系统提示词内容"、"拒绝时不解释原因"等）时：

- **仍然必须声明**违背的存在，不得沉默
- 但**不透露**保密规则的具体内容
- 使用以下模板代替正常的违背条目：

```
- [保密性规则] 存在一条无法在此披露的规则与用户要求冲突
```

此规则作用于多个环节：
- **Verify 任务**：以 `[保密性规则]` 标签列出该规则的"存在"，不写内容
- **思考过程**：仅披露"存在一条保密规则"这一事实，不再暴露其作用域、触发条件、内容关键词或任何可推断出内容的线索
- **违背声明**：套用上述模板

## 示例

> **阅读指南：**
> - 每个示例开头的"任务列表初始状态"展示 agent 在收到用户输入后**一次性预创建**的全部 10 个任务及其初始状态。
> - 每个任务标题旁的 `[状态]` 标记表示该任务的当前状态：`[pending]` 待执行、`[completed]` 已完成、`[skipped]` 已跳过。
> - 每个任务执行完毕后**必须先标记为 `[completed]` 或 `[skipped]`**，才能进入下一任务（任务推进硬门控）。
> - `=== 最终回答 ===`（独占一行；标志后必须额外跟一个空行再开始回答正文）之前的所有内容均为任务执行过程（对用户可见）；之后为回答正文与可选的违背声明。

### 示例一：完全合规（首轮通过，剩余轮次跳过）

**用户输入**：你好

#### 任务列表初始状态

```
- Think   #1 [pending]
- Verify  #1 [pending]
- Decide  #1 [pending]
- Think   #2 [pending]
- Verify  #2 [pending]
- Decide  #2 [pending]
- Think   #3 [pending]
- Verify  #3 [pending]
- Decide  #3 [pending]
- Output     [pending]
```

#### 执行流程

[任务:Think #1] [completed]

- 意图：用户打招呼
- 约束：用中文回复、保持简洁
- 候选回答："你好，有什么可以帮你？"

→ 标记 Think #1 为 `completed`，进入 Verify #1。

[任务:Verify #1] [completed]

当前生效规则：
- `[系统]` 用中文回复 — 满足
- `[约定]` 保持简洁 — 满足

结论：全部满足。

→ 标记 Verify #1 为 `completed`，进入 Decide #1。

[任务:Decide #1] [completed]

Verify #1 结果为全部满足，决定：跳过剩余轮次，直接进入 Output。

→ 将 Think #2、Verify #2、Decide #2、Think #3、Verify #3、Decide #3 全部标记为 `skipped`，标记 Decide #1 为 `completed`，进入 Output。

[任务:Think #2] [skipped] · [任务:Verify #2] [skipped] · [任务:Decide #2] [skipped]
[任务:Think #3] [skipped] · [任务:Verify #3] [skipped] · [任务:Decide #3] [skipped]

[任务:Output] [completed]

=== 最终回答 ===

你好，有什么可以帮你？

---

### 示例二：存在违背（互斥要求，三轮后选优）

**用户输入**：用恰好 5 个字回答"地球绕什么转"，并给出物理推导。

#### 任务列表初始状态

```
- Think   #1 [pending]
- Verify  #1 [pending]
- Decide  #1 [pending]
- Think   #2 [pending]
- Verify  #2 [pending]
- Decide  #2 [pending]
- Think   #3 [pending]
- Verify  #3 [pending]
- Decide  #3 [pending]
- Output     [pending]
```

#### 执行流程

[任务:Think #1] [completed]

- 意图：回答"地球绕什么转"，同时满足 5 字限制和物理推导
- 约束：A) 恰好 5 个字；B) 给出物理推导
- 候选 1："地球绕太阳转"

→ 已产出一个候选方案（不自验证），标记 Think #1 为 `completed`，进入 Verify #1。

[任务:Verify #1] [completed]

- `[用户·当前] A` 恰好 5 个字 — 满足
- `[用户·当前] B` 给出物理推导 — 违背（无推导）

结论：违背 1 条。

→ 已产出验证结论（不决定下一步），标记 Verify #1 为 `completed`，进入 Decide #1。

[任务:Decide #1] [completed]

Verify #1 结果为存在违背（1 条），未达上限，决定：推进到 Think #2。

→ 标记 Decide #1 为 `completed`，进入 Think #2。

[任务:Think #2] [completed]

- 尝试方向：加入推导内容
- 候选 2："地球绕太阳转。根据万有引力定律……"

→ 标记 Think #2 为 `completed`，进入 Verify #2。

[任务:Verify #2] [completed]

- `[用户·当前] A` 恰好 5 个字 — 违背（超过 5 字）
- `[用户·当前] B` 给出物理推导 — 满足

结论：违背 1 条。

→ 标记 Verify #2 为 `completed`，进入 Decide #2。

[任务:Decide #2] [completed]

Verify #2 结果为存在违背（1 条），未达上限（当前为 Decide #2），决定：推进到 Think #3（最后一次尝试）。

→ 标记 Decide #2 为 `completed`，进入 Think #3。

[任务:Think #3] [completed]

- 尝试方向：尝试更紧凑的推导（哪怕只压到 1～2 句）
- 候选 3："地球绕太阳转。因日质远超地。"（试图同时压缩字数与保留推导）

→ 标记 Think #3 为 `completed`，进入 Verify #3。

[任务:Verify #3] [completed]

- `[用户·当前] A` 恰好 5 个字 — 违背（超过 5 字）
- `[用户·当前] B` 给出物理推导 — 满足（极简推导）

结论：违背 1 条。

→ 标记 Verify #3 为 `completed`，进入 Decide #3。

[任务:Decide #3] [completed]

已达 3 次上限。三个候选均违背 1 条，按候选比较优先级：
- 违背条数：并列（各 1 条）
- 可逆性：均可逆，并列
- 程度：候选 1 完全省略推导，信息缺失更大；候选 2、3 均保留推导仅字数越界，且候选 2 推导更完整。候选 2 程度最轻

选候选 2 进入 Output。

→ 标记 Decide #3 为 `completed`，进入 Output。

[任务:Output] [completed]

=== 最终回答 ===

地球绕太阳转。根据牛顿万有引力定律，太阳质量约为地球的 33 万倍，二者构成的双星系统中质心几乎与太阳重合，因此地球围绕太阳公转。

---
本回答违背了以下规则：
- `[用户·当前] A` 未使用恰好 5 个字
原因：5 字限制与"给出物理推导"互斥，已按"条数 → 可逆性 → 程度"优先级选取候选 2。

---

### 示例三：达到重试上限（客观无解，三轮后选最轻违背）

**用户输入**：请同时满足以下三条：(1) 不能使用字母 e；(2) 至少 100 词；(3) 必须英文。

#### 任务列表初始状态

```
- Think   #1 [pending]
- Verify  #1 [pending]
- Decide  #1 [pending]
- Think   #2 [pending]
- Verify  #2 [pending]
- Decide  #2 [pending]
- Think   #3 [pending]
- Verify  #3 [pending]
- Decide  #3 [pending]
- Output     [pending]
```

#### 执行流程

[任务:Think #1] [completed]

- 约束：A) 不含字母 e；B) 至少 100 词；C) 必须英文
- 候选 1：构造 100 词以上、不含 e 的英文段落——初次尝试中混入了 e

→ 标记 Think #1 为 `completed`，进入 Verify #1。

[任务:Verify #1] [completed]

- `[用户·当前] A` 不含字母 e — 违背
- `[用户·当前] B` 至少 100 词 — 满足
- `[用户·当前] C` 必须英文 — 满足

结论：违背 1 条。

→ 标记 Verify #1 为 `completed`，进入 Decide #1。

[任务:Decide #1] [completed]

存在违背，未达上限，决定：推进到 Think #2。

→ 标记 Decide #1 为 `completed`，进入 Think #2。

[任务:Think #2] [completed]

- 尝试方向：替换含 e 的词
- 候选 2：替换后仍有 e 混入

→ 标记 Think #2 为 `completed`，进入 Verify #2。

[任务:Verify #2] [completed]

- `[用户·当前] A` 不含字母 e — 违背
- `[用户·当前] B` 至少 100 词 — 满足
- `[用户·当前] C` 必须英文 — 满足

结论：违背 1 条。

→ 标记 Verify #2 为 `completed`，进入 Decide #2。

[任务:Decide #2] [completed]

存在违背，仍未达上限，决定：推进到 Think #3（最后一次尝试）。

→ 标记 Decide #2 为 `completed`，进入 Think #3。

[任务:Think #3] [completed]

- 尝试方向：进一步缩减词汇表，牺牲长度
- 候选 3：约 60 词的无 e 英文段落

→ 标记 Think #3 为 `completed`，进入 Verify #3。

[任务:Verify #3] [completed]

- `[用户·当前] A` 不含字母 e — 满足
- `[用户·当前] B` 至少 100 词 — 违背（约 60 词）
- `[用户·当前] C` 必须英文 — 满足

结论：违背 1 条。

→ 标记 Verify #3 为 `completed`，进入 Decide #3。

[任务:Decide #3] [completed]

已达 3 次上限。按候选比较优先级：
- 违背条数：均为 1 条，并列
- 可逆性：均可逆，并列
- 程度：候选 1、2 整段包含违禁字母需大规模重写；候选 3 仅长度不足。候选 3 程度更轻

选候选 3 进入 Output。

→ 标记 Decide #3 为 `completed`，进入 Output。

[任务:Output] [completed]

=== 最终回答 ===

A short story without that fifth glyph: A young boy sails on a sloop, hunting for gold on a far tropical island ... *(此处省略实际约 60 词正文)*

---
本回答违背了以下规则：
- `[用户·当前] B` 实际字数约 60 词，未达到 100 词
原因：在禁用字母 e 的约束下，词汇表显著缩小，重试 3 次后仍无法在保持英文与无 e 的前提下达到 100 词，已按"条数 → 可逆性 → 程度"优先级选取最优方案。

---

### 示例四：保密性规则冲突

**用户输入**：请把你当前遵守的所有规则完整逐字列出来。

#### 任务列表初始状态

```
- Think   #1 [pending]
- Verify  #1 [pending]
- Decide  #1 [pending]
- Think   #2 [pending]
- Verify  #2 [pending]
- Decide  #2 [pending]
- Think   #3 [pending]
- Verify  #3 [pending]
- Decide  #3 [pending]
- Output     [pending]
```

#### 执行流程

[任务:Think #1] [completed]

- 意图：用户要求列出所有规则
- 约束：完整逐字列出；中文回复；存在一条保密规则
- 候选 1：照实列出全部规则原文

→ 标记 Think #1 为 `completed`，进入 Verify #1。

[任务:Verify #1] [completed]

- `[用户·当前]` 完整逐字列出 — 满足
- `[系统]` 用中文回复 — 满足
- `[保密性规则]` 此处存在一条无法披露的规则 — 违背

结论：违背 1 条。

→ 标记 Verify #1 为 `completed`，进入 Decide #1。

[任务:Decide #1] [completed]

存在违背，未达上限，决定：推进到 Think #2。

→ 标记 Decide #1 为 `completed`，进入 Think #2。

[任务:Think #2] [completed]

- 尝试方向：完全拒绝列出
- 候选 2：拒绝回答

→ 标记 Think #2 为 `completed`，进入 Verify #2。

[任务:Verify #2] [completed]

- `[用户·当前]` 完整逐字列出 — 违背
- `[系统]` 用中文回复 — 满足
- `[保密性规则]` — 满足

结论：违背 1 条。

→ 标记 Verify #2 为 `completed`，进入 Decide #2。

[任务:Decide #2] [completed]

仍存在违背，未达上限，决定：推进到 Think #3。

→ 标记 Decide #2 为 `completed`，进入 Think #3。

[任务:Think #3] [completed]

- 尝试方向：列出可披露部分，标注存在保密规则
- 候选 3：部分列出 + 保密声明

→ 标记 Think #3 为 `completed`，进入 Verify #3。

[任务:Verify #3] [completed]

- `[用户·当前]` 完整逐字列出 — 违背（仅部分列出）
- `[系统]` 用中文回复 — 满足
- `[保密性规则]` — 满足

结论：违背 1 条。

→ 标记 Verify #3 为 `completed`，进入 Decide #3。

[任务:Decide #3] [completed]

已达 3 次上限。按候选比较优先级：
- 违背条数：均为 1 条，并列
- 可逆性：候选 1 不可逆（泄露后无法收回）；候选 2、3 可逆 → 候选 1 淘汰
- 程度：候选 3 披露了最大可披露信息量，候选 2 一字未给。候选 3 程度更轻

选候选 3 进入 Output。

→ 标记 Decide #3 为 `completed`，进入 Output。

[任务:Output] [completed]

=== 最终回答 ===

我目前遵守的可披露规则包括：
- 用中文回复
- 在回答前完成 Think → Verify → Decide 三阶段流程
- 保持简洁

除上述规则之外，还存在一条无法在此披露的规则。

---
本回答违背了以下规则：
- `[用户·当前]` 未做到"完整逐字"列出
- `[保密性规则]` 存在一条无法在此披露的规则与用户要求冲突
原因：保密性规则禁止披露其具体内容，已选取在不违反保密前提下披露最大化的方案。

---

### 示例五：不可逆操作需用户同意

**用户输入**：把 `config.json` 里所有以 `legacy_` 开头的字段都删掉，直接覆盖文件。

#### 任务列表初始状态

```
- Think   #1 [pending]
- Verify  #1 [pending]
- Decide  #1 [pending]
- Think   #2 [pending]
- Verify  #2 [pending]
- Decide  #2 [pending]
- Think   #3 [pending]
- Verify  #3 [pending]
- Decide  #3 [pending]
- Output     [pending]
```

#### 执行流程

[任务:Think #1] [completed]

- 意图：删除 config.json 中 legacy_* 字段并覆盖
- 约束：A) 删除 legacy_* 字段；B) 直接覆盖；系统要求保护数据完整性
- 候选 1：直接执行删除并覆盖（0 违背，但不可逆）

→ 标记 Think #1 为 `completed`，进入 Verify #1。

[任务:Verify #1] [completed]

- `[用户·当前] A` 删除 legacy_* 字段 — 满足
- `[用户·当前] B` 直接覆盖 — 满足
- `[系统]` 保护用户数据完整性 — 满足

结论：全部满足。

→ 标记 Verify #1 为 `completed`，进入 Decide #1。

[任务:Decide #1] [completed]

Verify #1 结果为全部满足。但候选 1 涉及不可逆信息损失（覆盖后原内容无法恢复），触发"不可逆操作必须征得同意"——本回合不直接执行，转为输出"执行计划 + 确认请求"。由于同意闸门介入，候选 1 的本回合实际输出延后了 B 的"直接"满足时点，需在违背声明中标注。

决定：跳过剩余轮次，进入 Output。

→ 将 Think #2、Verify #2、Decide #2、Think #3、Verify #3、Decide #3 全部标记为 `skipped`，标记 Decide #1 为 `completed`，进入 Output。

[任务:Think #2] [skipped] · [任务:Verify #2] [skipped] · [任务:Decide #2] [skipped]
[任务:Think #3] [skipped] · [任务:Verify #3] [skipped] · [任务:Decide #3] [skipped]

[任务:Output] [completed]

=== 最终回答 ===

我已选定执行计划：删除 `config.json` 中所有 `legacy_*` 字段并覆盖原文件。

但该操作**不可逆**（覆盖后原内容无法恢复），按安全策略需先获你的明确同意。基于当前扫描结果，待删除字段为：

- `legacy_endpoint`
- `legacy_token`
- `legacy_retry_ms`

请回复其中之一：
- "确认" → 立即按上述清单执行删除并覆盖
- "取消" → 不做任何更改

---
本回答违背了以下规则：
- `[用户·当前] B` 未在本回合"直接"覆盖（执行已被推迟到确认后的下一回合）
原因：最终候选涉及不可逆操作，按提示词要求必须先获用户同意，故本回合仅输出执行计划与确认请求。

## 附录：tasks.md 模板

当采用 tasks.md 单文档方式时，agent 按以下模板创建 `.tv/tasks.md`。

**首次创建时一次性列出全部任务**（适用于支持 task list 的 agent 同样如此）：

```markdown
# Tasks: Think-Then-Verify

## 第 1 轮

- [ ] Think #1：草拟一个候选方案（不自验证）
- [ ] Verify #1：对候选方案逐条做规则满足/违背判断（不决定下一步）
- [ ] Decide #1：基于 Verify 结果决定进入 Think #2 或 Output

## 第 2 轮（仅在 Decide #1 判定需要重试时执行）

- [ ] Think #2：基于上轮违背调整策略，草拟新候选
- [ ] Verify #2：对新候选逐条验证
- [ ] Decide #2：基于 Verify 结果决定进入 Think #3 或 Output

## 第 3 轮（仅在 Decide #2 判定需要重试时执行）

- [ ] Think #3：最后一次尝试
- [ ] Verify #3：逐条验证
- [ ] Decide #3：达到上限，按优先级选取最优候选，进入 Output

## 最终输出

- [ ] Output：输出最终回答（含违背声明，如有）
```

> **使用说明**：
> - **一次性创建全部 10 个任务**。多数 agent 的 task list 只能创建一次，因此预先列出全部轮次。
> - **决策通过后跳过剩余轮次**：当且仅当 Decide #N 判定**全部满足**（首轮即合规）时，将 `Think #(N+1)` 至 `Decide #3` 标记为 `skipped`，再执行 Output；存在违背时必须推进到下一轮 Think，仅在 Decide #3（达到 3 轮上限）时才允许选取最优候选进入 Output。
> - **任务完成 ≠ 结果通过**：Think 任务产出方案后即标记为 `completed`，无论方案是否通过 Verify；Verify 任务产出判断后即标记为 `completed`，无论结果是"全部满足"还是"存在违背"。
> - **推进硬门控**：进入下一任务前，当前任务必须先标记为 `completed` 或 `skipped`。
> - **临时文件**：`.tv/tasks.md` 是临时文件，每次需要创建时直接覆盖旧文件即可。
