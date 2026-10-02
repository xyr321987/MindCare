# MindCare 文案表 v1.1

> ⚠️ **当前底座是契约 v1.0（11 端点）**。本表按 v1.1 编写，是**超集**：
> §1.8（撤回同意）、§1.6.5（`consent_revoked` 结束页）、§2（校方反馈）、§1.4 的 Q2.5 与
> `material_*` 相关条目描述的是 **v1.1 才有的能力，现行底座下界面不引用它们**
> （学生端已降级到 v1.0，见 `docs/转向决策记录-v2.md` §3）。
> 保留这些条目是为了"文案不丢"，**不代表功能存在**——讲解时不要据此声称已实现。
>
> 规则：禁用词清单见 `mindcare/copywriting.json` 的 `_meta.word_ban`（10 词）；**正文零命中**，扫描命令见交付汇报
>       统一称"你"，不用"用户 / 患者 / 受试者"这类称呼
>       所有结束语走「被接住」的话术；不用感叹号施压
>
> 维护：B（内容设计）｜消费方：`mindcare/copywriting.json`（`/tips` 读它）、学生端/教师端 PySide6 界面
> 依据：`mindcare新版/contracts/api-contract.md`（**v1.0，唯一依据**）、`mindcare新版/docs/学生端接口协议说明.md`、`docs/UI约定.md`
> ℹ️ **2026-10-02 位置修正**：运行时 JSON 原在 `mindcare/server/copywriting.json`，已移到
> **`mindcare/copywriting.json`**（与本文同级）——文案表是 **B 线资产**，不该放在需与上游逐字节一致的
> 后端目录里（那会形成"前端资源依赖后端目录"的耦合，后端一恢复原样前端就静默丢 58 条文案）。
> 引用方式：代码里只写 ID，不硬编码文案（例：`COPY["s.q1.title"]`）

## 0. 场景映射（ID 前缀 ↔ 契约枚举）

| 契约枚举 | 取值 | 对应文案段落 |
|---|---|---|
| `enums.mood` | `happy` / `plain` / `down` | §1.1（选项） |
| `enums.cause_category` | `study` / `relationship` / `family` | §1.4.2 |
| `enums.material_related` | `yes` / `no` / `skip` | §1.4.3 + §2 |
| `enums.result_scene` | `happy_end` / `plain_tips` / `help_sent` / `self_care` / **`consent_revoked`** | §1.6（五个结束页） |
| `enums.tips_scene` | `plain` / `down` | §1.6.2、§1.6.4（同时同步到 `copywriting.json`） |
| `enums.ticket_action` | `accept` / `done` | §3.4 |
| `enums.consent_action` | `revoke` | §1.8（撤回同意） |
| `enums.submission_record_type` | `submission` / `submission_revoked` | §1.8（事件溯源，仅服务端语义；**界面不得出现这类技术词**） |
| `enums.priority` | `1` / `2` / `3` | §3.2.2 |
| `enums.feedback_category` | `canteen` / `dormitory` / `facility` / `schedule` / `campus_env` / `other` | §2 |
| `enums.feedback_status` | `pending` / `in_progress` / `resolved` / `void` | §2 |
| `error_codes` | `1001` / `1002` / `2001` / `2002` / `3001` / `4001` | §4.1 |

---

## 1. 学生端 · 问卷流程

### 1.1 Q1 心情

| ID | 文案 |
|----|------|
| s.q1.title | 今天的你，感觉怎么样？ |
| s.q1.subtitle | 没有对错，按第一感觉选就好。 |
| s.q1.option.happy | 高兴 |
| s.q1.option.happy.emoji | ☀️ |
| s.q1.option.plain | 平淡 |
| s.q1.option.plain.emoji | ☁️ |
| s.q1.option.down | 沮丧 |
| s.q1.option.down.emoji | 😣 |
| s.q1.hint.optional | 这一题选了就好，不用想太久。 |

### 1.2 A 分支（高兴）—— 对应 `result_scene=happy_end`

| ID | 文案 |
|----|------|
| s.branch.a.title | 今天挺好的。 |
| s.branch.a.next | 看看接下来 → |
| s.branch.a.toast.saving | 正在保存… |

### 1.3 B 分支（平淡）—— 原因选填页 / `plain_tips`

| ID | 文案 |
|----|------|
| s.branch.b.title | 今天平平淡淡的，也挺好。 |
| s.branch.b.question | 如果愿意，可以说说是因为什么。 |
| s.branch.b.optionalTag | 选填 |
| s.branch.b.placeholder | 可以不填，直接跳过就好。 |
| s.branch.b.skip | 先跳过 |
| s.branch.b.submit | 写好了，继续 → |
| s.branch.b.hint.skip | 不想写也没关系，跳过一样可以往下走。 |

### 1.4 C 分支（沮丧）—— Q2 原因 / Q2.5 物质条件 / Q3 详述

#### 1.4.1 进入 C 分支

| ID | 文案 |
|----|------|
| s.branch.c.title | 谢谢你愿意说出来。 |
| s.branch.c.subtitle | 接下来几句话，可以慢慢选、慢慢写。 |

#### 1.4.1b 情绪探索（`mood=down` 时进入，多选）

> 仅沮丧分支：Q1 之后先进「情绪探索」多选页，让学生圈出几个更贴近的来源，
> 再进 Q3 详述。本页的 7 个选项会**映射**到契约枚举 `cause_category`
> （`study` / `relationship` / `family`）再落库——多选只取优先级最高的一桶：
> `家庭` > `同学关系` > 其余（`学习` / `考试` / `睡眠` / `对未来的担心` / `其他` 归入 `study`）。
> 更细的差异由 Q3 的自由文本承载，教师看到的是正文，不是这个粗分桶。

| ID | 文案 |
|----|------|
| s.explore.title | 情绪探索 |
| s.explore.subtitle | 最近是什么让你有这种感觉？ |
| s.explore.hint | 可以多选，选最贴近的几个就好。 |
| s.explore.option.study | 学习 |
| s.explore.option.exam | 考试 |
| s.explore.option.relationship | 同学关系 |
| s.explore.option.family | 家庭 |
| s.explore.option.sleep | 睡眠 |
| s.explore.option.future | 对未来的担心 |
| s.explore.option.other | 其他 |

#### 1.4.2 Q2 原因（`cause_category`，**仅平淡分支**）

| ID | 文案 |
|----|------|
| s.q2.title | 你是因为什么原因？ |
| s.q2.subtitle | 选一个最接近的就好，之后还可以再补充。 |
| s.q2.option.study | 学业 |
| s.q2.option.relationship | 人际关系 |
| s.q2.option.family | 家庭矛盾 |

#### 1.4.3 Q2.5 物质条件相关（`material_related`，仅 `mood=down`）

| ID | 文案 |
|----|------|
| s.q25.title | 这次的低落，和学校的物质条件有关系吗？ |
| s.q25.subtitle | 比如食堂、宿舍、教室设施、校园环境这些。没有的话，直接跳过就好。 |
| s.q25.option.yes | 有关系 |
| s.q25.option.no | 没关系 |
| s.q25.option.skip | 不确定 / 先跳过 |
| s.q25.followup.title | 方便说一下具体是什么情况吗？ |
| s.q25.followup.subtitle | 写清楚「哪里」和「什么问题」就好，不用写自己的名字，也不用写同学的。 |
| s.q25.followup.placeholder | 例如：宿舍晚上十一点后就没有热水了；食堂午餐排队太久来不及吃…… |
| s.q25.followup.error.empty | 选了这个选项，就多写一句吧，一句话也可以。 |
| s.q25.followup.action.submit | 提交给学校相关部门 |
| s.q25.followup.action.back | 上一步 |

（同屏匿名告知语见 **§2**，必须与本节同屏出现，不得折叠、不得只在提交后显示。）

#### 1.4.4 Q3 详细阐述（`detail`，必填、不限字数）

| ID | 文案 |
|----|------|
| s.q3.title | 请你详细阐述一下原因 |
| s.q3.subtitle | 想到多少写多少，不限字数。你写下的内容默认只有你自己能看到。 |
| s.q3.placeholder | 慢慢写，写给自己看也可以。 |
| s.q3.guide.1 | 可以是一件小事 |
| s.q3.guide.2 | 想到什么就写什么 |
| s.q3.guide.3 | 如果觉得乱也没关系 |
| s.q3.error.empty | 写一点点也可以，哪怕只有一句话。 |
| s.q3.counter.hidden | （不显示字数上限、不显示"还剩 X 字"、不做倒计时） |

### 1.5 求助选择页

> 契约约束：这一步**只有一个开关**（`request_help` → `consent_share = request_help`）。
> 归档 v1 的"要不要让心理老师看到？/ 给心理老师看 / 先不给老师看"三态分享控件在 v1.1 **已不存在**，不得复用（见 §7 变更登记）。

| ID | 文案 |
|----|------|
| s.help.title | 要不要让心理老师陪你一起看看？ |
| s.help.body | 选「请求帮助」，你这次写下的内容会带给心理老师，老师会尽快看到。选「不用帮助」，内容就留在你这里，一样会被好好保存。 |
| s.help.option.request | 请求心理老师帮助 |
| s.help.option.no | 不用帮助 |
| s.help.option.request.note | 老师会看到你这次写的内容。 |
| s.help.option.no.note | 只有你自己能看到。如果之后想让老师知道，也可以随时改主意。 |
| s.help.selected.request | 已选择：老师可以看到你这次写的内容。 |
| s.help.selected.no | 已选择：内容只留在你这里。 |
| s.help.hint | 怎么选都可以，两种选择都不会让你被追问。 |

#### 1.5.1 预约时间选择（request_help=true 时进入）

> 学生在「求助选择页」选了「请求心理老师帮助」后，跳转到本页的**课表**选具体预约时间
> （年份 → 月份 → 星期几 → 第几节），并可选地一并分享个人信息（测评内容 / 树洞）。
> 数据落到**预约时间数据库**（见 `docs/预约时间-数据库与接口契约.md`）。
>
> 课表的节次定义、星期口径与网格文案在 §4.9（**双端共用**）。

| ID | 文案 |
|----|------|
| s.appointment.title | 挑一个方便来找老师的时间 |
| s.appointment.subtitle | 横着是星期，竖着是第几节课。点一个小方块就选好了。 |
| s.appointment.year | 年份 |
| s.appointment.month | 月份 |
| s.appointment.day | 日期 |
| s.appointment.time | 时间段 |
| s.appointment.share.title | 除了基本信息，还想一起给老师看哪些？（可选） |
| s.appointment.share.questionnaire | 我这次的测评内容 |
| s.appointment.share.treehole | 我的树洞记录 |
| s.appointment.share.hint | 不选也没关系，老师只会看到你的班级、学号和预约时间。 |
| s.appointment.confirm | 确认预约 |
| s.appointment.profile.title | 预约人信息 |
| s.appointment.profile.name | 姓名 |
| s.appointment.profile.class | 班级 |
| s.appointment.profile.sid | 学号 |
| s.appointment.profile.none | 还没有读到你的班级学号，登录后会自动带上。 |
| s.appointment.selected | 已选：{date} {weekday} 第{period}节 {start}-{end} |
| s.appointment.selected.none | 还没选时间 |
| s.appointment.error.none | 先点一个小方块，选好时间再来确认。 |
| s.appointment.error.blocked | 老师把这段时间设成了不可预约，换一个吧。 |
| s.appointment.error.taken | 这个时间已经有同学约了，换一个吧。 |
| s.appointment.error.past | 这个时间已经过去了，选一个还没到的时间。 |
| s.appointment.hint.grid | 红框是老师这节课不方便的时间，点不了。 |
| s.appointment.success | 预约好了，老师会在这个时间看到你。 |

### 1.6 五个结束页（`result_scene`）

#### 1.6.1 `happy_end`

| ID | 文案 |
|----|------|
| s.end.happy.title | 恭喜你今天有个好心情 🌿 |
| s.end.happy.body | 愿这份轻松多待一会儿。想留个纪念的话，可以去树洞写一句，以后翻到会很暖。 |
| s.end.happy.action.treehole | 去树洞写一句 |
| s.end.happy.action.close | 先这样，再见 |
| s.end.happy.footer | 明天也欢迎你再来看看自己。 |

#### 1.6.2 `plain_tips`（小贴士文案 `scene=plain`）

| ID | 文案 |
|----|------|
| s.end.plain.title | 今天平平淡淡的，也很好。 |
| s.end.plain.tips | 可以出去走走，晒到一点光；也可以和朋友随便聊两句，或者把今天记一句在树洞里。不用勉强自己"应该开心"。 |
| s.end.plain.action.treehole | 去树洞写一句 |
| s.end.plain.action.close | 先这样，再见 |
| s.end.plain.footer | 如果哪天心里有点沉，随时回来和我说说。 |

#### 1.6.3 `help_sent`

| ID | 文案 |
|----|------|
| s.end.help.title | 已经送到老师那里了。 |
| s.end.help.body | 你写的这段内容，心理老师会尽快看到，并且会以让你舒服的方式来找你。现在可以先把这件事放一放。 |
| s.end.help.action.close | 知道了 |
| s.end.help.footer | 如果此刻很难受，随时可以打 12356，有人会接。 |

#### 1.6.4 `self_care`（自助建议；`scene=down`）

| ID | 文案 |
|----|------|
| s.end.selfcare.title | 谢谢你愿意说出来。 |
| s.end.selfcare.body | 内容已经保存好了，只有你自己能看到。可以试一两件小事，也可以什么都不做，先歇一会儿。 |
| s.end.selfcare.action.treehole | 写树洞 |
| s.end.selfcare.action.close | 先这样，再见 |
| s.end.selfcare.tips | 可以跟我做：慢慢呼吸几轮，或者出去走一小圈；也可以去树洞写写心里话。 |
| s.end.selfcare.suggest.breath | 慢慢吸气 4 秒，停 7 秒，缓缓呼 8 秒，做 4 轮。 |
| s.end.selfcare.suggest.walk | 站起来走一走，走到能晒到光的地方，5 分钟就够。 |
| s.end.selfcare.suggest.treehole | 心里的话写进树洞，这里只有你自己能看到。 |
| s.end.selfcare.suggest.friend | 找一个让你放松的人待一会儿，哪怕不说话。 |
| s.end.selfcare.hotline.title | 如果现在很难受，可以打这些电话 |
| s.end.selfcare.hotline.body | 全国统一心理援助热线 12356 ｜ 北京心理援助热线 010-82951332 ｜ 紧急情况拨打 120 / 110 |

> `tips.treehole_entry=true` 时，`s.end.selfcare.action.treehole` / `s.end.plain.action.treehole` 渲染为**深链按钮**：切换到「树洞」Tab 并打开编辑器（`docs/接口约定.md` §4.1）。

#### 1.6.5 `consent_revoked`（撤回同意后的结束页）

> 语气要求：**不能让用户觉得做了一件不好的事**，也不能暗示"你刚刚失去了什么"。
> 契约依据：§2.3.1——撤回只影响"老师能不能看到这条正文"，记录本身保留（留痕，不物理删除）；撤回**不可逆**。

| ID | 文案 |
|----|------|
| s.end.revoked.title | 已经改回只有你自己能看到了。 |
| s.end.revoked.body | 老师那边不会再看到这一段。你写下的内容还留在这里，只是重新回到了你手里。 |
| s.end.revoked.reassure | 改主意是你的权利，什么时候都算数。 |
| s.end.revoked.action.back | 回到我的档案 |
| s.end.revoked.action.close | 知道了 |
| s.end.revoked.footer | 如果之后又想让老师知道，重新填一次、选「请求帮助」就可以。 |
| s.end.revoked.hotline | 如果此刻很难受，随时可以打 12356，有人会接。 |

> ⚠️ 措辞红线：**不得**写"已删除 / 已清除 / 记录已消失 / 抹掉"——记录的留痕是设计的一部分（契约 §5.5）；也**不得**写"老师不会知道你说过什么"——分诊计数仍按原提交记录计算（契约 §2.3.1：撤回不影响分诊计数），教师端仍可能看到该生的关怀排序。

### 1.7 树洞（列表 + 编辑器）

> 隐私纪律：树洞为 **L0 绝对私密**，无分享/授权开关，教师端不存在读它的接口，也不计入任何统计。
> 因此本节**任何文案不得出现"分享 / 公开 / 让老师看 / 可见性选择"字样**（见验收证据）。

| ID | 文案 |
|----|------|
| s.treehole.tab.title | 树洞 |
| s.treehole.entry.title | 树洞 · 说给谁听都可以 |
| s.treehole.entry.subtitle | 有些话说出来，就会轻一点。 |
| s.treehole.list.title | 我的树洞 |
| s.treehole.list.new | 写一句 |
| s.treehole.list.empty | 这里还空着。想写的时候，随时都可以来。 |
| s.treehole.list.privacyNote | 这里只有你自己能看到，别人不会知道你写没写。 |
| s.treehole.list.noReadReceipt | 这里不会显示谁看过，写起来会自在一点。 |
| s.treehole.compose.title | 今天想写点什么 |
| s.treehole.compose.placeholder | 今天想写点什么…… |
| s.treehole.compose.privacyLabel | 只有你自己能看到 |
| s.treehole.compose.privacyNote | 这段话不会出现在任何别的地方，也不会被算进任何统计里。 |
| s.treehole.compose.action.save | 保存 |
| s.treehole.compose.action.cancel | 取消 |
| s.treehole.compose.error.empty | 写一点点也可以，哪怕只有一句话。 |
| s.treehole.save.done | 已经存好了。 |
| s.treehole.save.donePrivate | 已经存好了，只有你自己能看到。 |
| s.treehole.moodtag.label | 给今天加个标记（选填） |
| s.treehole.moodtag.option.happy | 高兴 |
| s.treehole.moodtag.option.plain | 平淡 |
| s.treehole.moodtag.option.down | 沮丧 |
| s.treehole.moodtag.option.none | 不加 |
| s.treehole.list.item.privacyBadge | 仅自己可见 |

---

### 1.8 撤回同意（学生端「我的档案」；契约 §2.3.1）

> 依据：PIPL 第 15 条——个人有权撤回同意，处理者须提供**便捷**的撤回方式。
> 入口位置：学生端「我的档案」中，对**已分享**的记录显示一个操作。
> 措辞纪律：
> ① **主按钮不用"撤回 / 撤销 / 取消同意"这类法律术语**——学生看不懂，因此主按钮用「不让老师看了」；
> ② 二次确认必须同时说清 **老师将看不到这条** + **不能恢复**；
> ③ **不得出现"删除"**——记录留痕保留，撤回的只是可见性（契约 §5.5 事件溯源，不物理删除）；
> ④ 撤回**不可逆**（只接受 `consent_share:false`），界面上不得提供任何"改回老师可见"的按钮。

#### 1.8.1 档案页记录状态标签

| ID | 文案 |
|----|------|
| s.revoke.badge.shared | 老师可以看到 |
| s.revoke.badge.revoked | 只有你自己能看到 |
| s.revoke.badge.private | 只有你自己能看到 |

#### 1.8.2 撤回入口（按钮）

| ID | 文案 |
|----|------|
| s.revoke.entry.action | 不让老师看了 |
| s.revoke.entry.action.revoked | 已经不让老师看了 |
| s.revoke.entry.hint | 点了之后，老师就看不到这一条了。 |
| s.revoke.entry.disabledTip | 这一条本来只有你自己能看到。 |

#### 1.8.3 二次确认弹窗（**必含两条后果告知**）

| ID | 文案 |
|----|------|
| s.revoke.confirm.title | 不让老师看这一条了？ |
| s.revoke.confirm.body | 老师那边就不会再看到这段内容了。 |
| s.revoke.confirm.irreversible | 这一下点了就不能改回来。如果你之后又想告诉老师，需要重新填一次问卷。 |
| s.revoke.confirm.keepNote | 你写下的内容不会消失，只是重新变成只有你自己能看到。 |
| s.revoke.confirm.action.ok | 好，不让老师看了 |
| s.revoke.confirm.action.cancel | 再想想 |

#### 1.8.4 撤回成功提示

| ID | 文案 |
|----|------|
| s.revoke.toast.done | 好，老师那边看不到这一条了。 |
| s.revoke.toast.doneNote | 内容还在这里，你可以随时回来看。 |
| s.revoke.toast.failed | 刚才没改成，再试一次就好。 |
| s.revoke.toast.alreadyRevoked | 这一条已经是不让老师看的状态了。 |
| s.revoke.toast.notShared | 这一条本来就只有你自己能看到。 |
| s.revoke.toast.notFound | 没有找到这一条，可能已经不在档案里了。 |

#### 1.8.5 撤回相关的错误提示（契约 §2.3.1 校验表）

| ID | 契约码 | 文案 |
|----|--------|------|
| s.revoke.error.1002 | 1002 | 这条记录不在你的档案里，所以没法操作。 |
| s.revoke.error.2002 | 2002 | 没有找到这一条，可能已经不在档案里了。 |
| s.revoke.error.2001.notShared | 2001（原本 `consent_share=false`） | 这一条本来就只有你自己能看到，不用再改。 |
| s.revoke.error.2001.restore | 2001（传 `true`，试图恢复） | 这里只能改成不让老师看，不能改回去。想再让老师知道，重新填一次问卷就好。 |
| s.revoke.error.network | （网络层） | 网络好像有点慢，等会儿再试就好。 |

#### 1.8.6 撤回后的档案页提示

| ID | 文案 |
|----|------|
| s.revoke.after.note | 这一条已经不让老师看了。内容还留在这里，你随时可以回来看。 |
| s.revoke.after.relink | 想重新让老师知道，重新填一次问卷、在最后一步选「请求心理老师帮助」就可以。 |
| s.revoke.after.helpEntry | 也可以直接找心理老师当面聊，不需要通过这份问卷。 |

### 1.9 情绪可视化（学生端「我的档案」）

> 「我的档案」页用**面包屑导航**在「档案记录」与「情绪可视化」两个视图间切换。
> 情绪可视化把一段时间内的情绪按「沮丧=1 / 平淡=2 / 高兴=3」画成折线图，横轴为时间、
> 以一周为一个视图；每一天一个点，相邻两天都有记录才连线，中间空一天则断开。

| ID | 文案 |
|----|------|
| c.profile.view.records | 档案记录 |
| c.profile.view.chart | 情绪可视化 |
| c.profile.chart.title | 一周情绪 |
| c.profile.chart.week.prev | 上一周 |
| c.profile.chart.week.next | 下一周 |
| c.profile.chart.empty | 这一周还没有情绪记录，先去心情那一题写写看。 |

---

## 2. 学生端 · 学校问题反馈（Q2.5）

> 走**校方通道**（`school_feedback`），与心理通道文本不同源、互不写入。
> 教师端无读此资源的接口（`counselor_has_no_access: true`）；校方通过离线归档（markdown / JSONL）查看。

### 2.1 同屏告知（**必须原样包含，不得改写、不得拆分、不得折叠**）

| ID | 文案 |
|----|------|
| s.q25.disclosure.anonymous | 你写的内容会以匿名方式转给学校相关部门（不包含你的姓名和班级）。 |
| s.q25.disclosure.extra | 写的时候不用写自己的名字，也不用写同学的。 |
| s.q25.disclosure.materialOnly | 这段内容只会转给学校相关部门，不会转给心理老师。 |

### 2.2 含敏感内容时的提示（契约 §2.8.1 分流纪律：命中即不写入校方通道，转心理通道）

| ID | 文案 |
|----|------|
| s.q25.sensitive.notice | 这段内容会由心理老师来看。 |
| s.q25.sensitive.body | 你写的这些，可能更需要被一位心理老师认真看一看。我们不会把它转给学校相关部门，而是交给心理老师。 |
| s.q25.sensitive.next | 继续 |
| s.q25.sensitive.alt | 如果现在很难受，可以打 12356，随时有人接。 |

### 2.3 反馈分类（`feedback_category`）

| ID | 文案 |
|----|------|
| s.feedback.category.title | 这件事更像哪一类？ |
| s.feedback.category.canteen | 食堂 |
| s.feedback.category.dormitory | 宿舍 |
| s.feedback.category.facility | 教室 / 设施 |
| s.feedback.category.schedule | 作息 / 时间安排 |
| s.feedback.category.campus_env | 校园环境 |
| s.feedback.category.other | 其他 |

### 2.4 反馈附加信息（`scope` / `suggestion`，均可留空）

| ID | 文案 |
|----|------|
| s.feedback.scope.label | 影响范围（选填） |
| s.feedback.scope.placeholder | 比如：整层宿舍楼、我们班、只有我一个人遇到。 |
| s.feedback.suggestion.label | 你的建议（选填） |
| s.feedback.suggestion.placeholder | 比如：希望延长热水供应时间。 |
| s.feedback.submit | 提交 |
| s.feedback.submitted | 已经提交上去了。相关部门会看到这段内容。 |

### 2.5 我提交过的反馈（`GET /feedback/school/mine`）

| ID | 文案 |
|----|------|
| s.feedback.mine.title | 我提交过的反馈 |
| s.feedback.mine.empty | 你还没有提交过学校的反馈。想到了随时可以写。 |
| s.feedback.mine.sanitizedLabel | 实际送出去的文本（已隐去能认出人的部分） |
| s.feedback.mine.sanitizedNote | 姓名、班级、宿舍号这类信息会被隐去，你写的话本身不会被改写。 |
| s.feedback.mine.placeholderToken | 已经隐去的部分会显示成这样：[已隐去] |
| s.feedback.mine.status.pending | 已收到 |
| s.feedback.mine.status.inProgress | 正在看 |
| s.feedback.mine.status.resolved | 已经处理 |
| s.feedback.mine.status.void | 已关闭 |
| s.feedback.mine.categoryPrefix | 分类： |

### 2.6 分流词命中表（**供开发对照，不是界面文案，不进入 UI 与 JSON**）

自伤 / 自杀 / 欺凌 / 家暴 / 性相关。命中即走 §2.2 提示，不写入校方通道。

---

## 3. 教师端

> 基调（架构 §5.2、§10 第 6 条）：教师端不是"监控台"，而是"学生递过来的信的收件箱"。
> 全端不得出现判断性、警报性的词汇（具体清单见 `copywriting.json` 的 `_meta.word_ban`）；不展示任何推断性文字。

### 3.1 登录窗

| ID | 文案 |
|----|------|
| t.login.window.title | MindCare · 心理老师端 |
| t.login.title | 欢迎回来 |
| t.login.subtitle | 今天也谢谢你愿意多看一眼这些孩子。 |
| t.login.field.id | 工号 |
| t.login.field.password | 口令 |
| t.login.placeholder.id | 请输入工号 |
| t.login.placeholder.password | 请输入口令 |
| t.login.action.submit | 进入 |
| t.login.error.empty | 工号和口令都填一下就好。 |
| t.login.error.401 | 工号或口令对不上，再试一次就好。 |
| t.login.error.network | 暂时连不上服务，稍后再试就好。 |
| t.login.footer | 演示环境 · 请勿填入真实学生信息 |

### 3.2 分诊台

#### 3.2.1 顶部与表头

| ID | 文案 |
|----|------|
| t.triage.title | 分诊台 |
| t.triage.subtitle | 按关怀顺序排好的名单，点开可以看到学生愿意让你看到的内容。 |
| t.triage.sync.last | 最后同步：{time} |
| t.triage.sync.countdown | 下次刷新还有 {seconds} 秒 |
| t.triage.action.refresh | 刷新 |
| t.triage.action.refreshing | 正在刷新… |
| t.triage.col.priority | 关怀顺序 |
| t.triage.col.student | 姓名 / 班级 |
| t.triage.col.flags | 标记 |
| t.triage.col.lastActive | 最后活跃 |
| t.triage.col.daysSince | 距今天数 |
| t.triage.days.today | 今天 |
| t.triage.days.n | {n} 天前 |
| t.triage.days.unknown | 还没有记录 |
| t.triage.params.note | 排序依据：心理老师设置的回看窗口与阈值（当前：近 {window_n} 次记录中出现 {threshold_k} 次低落）。 |

#### 3.2.2 优先级徽标（**柔和表述，禁用词零命中**）

| ID | 文案 |
|----|------|
| t.triage.priority.1 | 需要优先关心 |
| t.triage.priority.1.note | 这类学生有既往病史标记，且最近几次记录里低落出现得比较多，建议早一点约一次聊天。 |
| t.triage.priority.2 | 有待回应 |
| t.triage.priority.2.note | 这位学生选择了请求帮助，还在等一个回应。 |
| t.triage.priority.3 | 常规关注 |
| t.triage.priority.3.note | 最近有记录，可以保持留意。 |
| t.triage.priority.legend | 排序只是提醒你先看谁，不代表学生有什么问题。 |

#### 3.2.3 flags chips

| ID | 文案 |
|----|------|
| t.triage.chip.history | 病史 |
| t.triage.chip.recentDown | 近{n}次低落×{count} |
| t.triage.chip.pendingHelp | 求助待处理 |
| t.triage.chip.none | 暂无标记 |
| t.triage.chip.tooltip.history | 入学档案里有既往病史记录，来自学校既有档案，不是系统算出来的。 |
| t.triage.chip.tooltip.recentDown | 最近 {window_n} 次问卷里，有 {count} 次选了「沮丧」。 |
| t.triage.chip.tooltip.pendingHelp | 这位学生点了「请求心理老师帮助」，还没有人受理。 |

### 3.3 详情抽屉（当日状态）

#### 3.3.1 抽屉骨架

| ID | 文案 |
|----|------|
| t.detail.title | 当日状态 |
| t.detail.close | 关闭 |
| t.detail.date | {date} |
| t.detail.mood.label | 今天的心情 |
| t.detail.mood.happy | 高兴 |
| t.detail.mood.plain | 平淡 |
| t.detail.mood.down | 沮丧 |
| t.detail.mood.none | 今天还没有填写 |
| t.detail.count.label | 今日填写次数 |
| t.detail.count.value | {count} 次 |
| t.detail.pending.label | 待处理求助 |
| t.detail.pending.yes | 有 {count} 条还没有受理 |
| t.detail.pending.no | 没有待处理的求助 |
| t.detail.alert.label | 排序提示 |
| t.detail.alert.body | 近 {window_n} 次记录中低落 {count} 次，因此在名单里排得靠前。这是排序参考，不是对学生的判断。 |
| t.detail.reason.label | 学生选择的原因 |
| t.detail.reason.study | 学业 |
| t.detail.reason.relationship | 人际关系 |
| t.detail.reason.family | 家庭矛盾 |
| t.detail.shared.title | 学生愿意让你看到的内容 |
| t.detail.shared.privacyNote | 这些是学生选择「请求帮助」后带过来的内容。 |

#### 3.3.2 未共享时的占位文案（`has_shared_records = false`，**必须是治愈话术**）

| ID | 文案 |
|----|------|
| t.detail.unshared.title | 该生选择暂不分享，可通过线下方式关心 |
| t.detail.unshared.body | 这次学生把内容留给了自己，这本身也是一种照顾自己的方式。你仍然可以像平常一样，在课间或课后和他聊两句，不用提这份问卷。 |
| t.detail.unshared.reminder | 名单上的排序还在，说明我们早知道要早点留意；但具体发生了什么，等他愿意说的时候再听。 |
| t.detail.unshared.noInference | （此处不展示任何由计数推断出的内容。） |
| t.detail.unshared.revokedNote | 学生也可以在填完之后改主意，让某一条重新变成只有他自己能看到。出现这种情况时，说明他正在按自己的节奏来，不需要追问原因。 |
| t.detail.revoked.title | 这一条学生已经改回只有他自己能看到了 |
| t.detail.revoked.body | 内容不再显示在这里。学生改主意是允许的，也不需要向你解释；名单上的排序不受影响。 |

#### 3.3.3 已共享记录

| ID | 文案 |
|----|------|
| t.detail.shared.item.mood | 当时心情：{mood} |
| t.detail.shared.item.cause | 当时原因：{cause} |
| t.detail.shared.item.time | 填写时间：{time} |
| t.detail.shared.item.detailLabel | 学生写的话 |
| t.detail.shared.disclaimer | 这些内容来自学生自己填写的问卷，只是他当时的一个片段，不能替代你和他当面的了解。 |
| t.detail.shared.action.ticket | 受理这条求助 |
| t.detail.shared.action.ticketDone | 这条求助已经处理完了 |

### 3.4 ack 对话框（`accept` / `done`）

| ID | 文案 |
|----|------|
| t.ack.dialog.accept.title | 受理这条求助？ |
| t.ack.dialog.accept.body | 受理后，这条求助会从"待回应"移到"已受理"，其他老师也能看到你已经在跟进了。 |
| t.ack.dialog.accept.noteLabel | 备注（选填） |
| t.ack.dialog.accept.notePlaceholder | 比如：今天下午课间找她聊了十分钟。 |
| t.ack.dialog.accept.confirm | 受理 |
| t.ack.dialog.done.title | 标记为已处理？ |
| t.ack.dialog.done.body | 确认这次陪伴告一段落。之后学生再提交新的求助，会重新出现在名单里。 |
| t.ack.dialog.done.noteLabel | 备注（选填） |
| t.ack.dialog.done.notePlaceholder | 比如：已经聊过，约了下周再聊一次。 |
| t.ack.dialog.done.confirm | 标记为已处理 |
| t.ack.dialog.cancel | 取消 |
| t.ack.toast.accept | 已受理。辛苦你了。 |
| t.ack.toast.done | 已经记下了。 |
| t.ack.toast.failed | 刚才没记上，再试一次就好。 |

### 3.5 预约时间表（与学生端**同一张课表**）

> 教师端读的是和学生端**同一份**预约时间数据库（见 `docs/预约时间-数据库与接口契约.md`）。
> 网格形态、星期与节次口径全部复用 §4.9 —— 学生看到的和老师看到的必须是同一张表。
> 教师可以把某一格设成「不可预约」，学生端**实时**看到红框（同步机制见契约文档 §6.3）。

| ID | 文案 |
|----|------|
| t.schedule.title | 预约时间表 |
| t.schedule.subtitle | 和学生看到的是同一张表。点一个小方块，就能把它设成不可预约，学生那边马上会看到。 |
| t.schedule.action.block | 设为不可预约 |
| t.schedule.action.unblock | 恢复可预约 |
| t.schedule.action.refresh | 刷新 |
| t.schedule.action.blocked | 已设成不可预约，学生那边已经看不到了。 |
| t.schedule.action.unblocked | 已经恢复，学生又能约这一节了。 |
| t.schedule.action.failed | 刚才没改上，再点一次试试。 |
| t.schedule.selected.none | 点一个小方块，看看这段时间谁约了。 |
| t.schedule.detail.title | 这个时间的预约 |
| t.schedule.detail.empty | 这个时间还没有人预约。 |
| t.schedule.detail.count | 共 {count} 人 |
| t.schedule.detail.student | 姓名 |
| t.schedule.detail.class | 班级 |
| t.schedule.detail.sid | 学号 |
| t.schedule.detail.time | 时间 |
| t.schedule.detail.share.q.yes | 愿意让你看 TA 这次的测评内容 |
| t.schedule.detail.share.q.no | 这次的测评内容 TA 没有分享 |
| t.schedule.detail.share.t.yes | 愿意让你看 TA 的树洞记录 |
| t.schedule.detail.share.t.no | 树洞记录 TA 没有分享 |
| t.schedule.detail.noShare | 这位同学只给了班级、学号和预约时间。 |
| t.schedule.hint.toggle | 设成不可预约后，学生端会立刻显示成红框，点不了。 |
| t.tab.schedule | 预约时间 |
| t.login.demo.action | 离线演示（只看本地预约库） |
| t.login.demo.note | 服务端没起时，可以先只看本机的预约库。 |
| t.window.title | MindCare 教师端 |

---

## 4. 通用

### 4.1 错误提示（对应契约 `error_codes`）

| ID | 契约码 | 文案 |
|----|--------|------|
| c.error.1001 | 1001 | 登录状态过期了，重新登录一下就好。 |
| c.error.1002 | 1002 | 这段内容还没有被分享，所以暂时看不到。 |
| c.error.2001 | 2001 | 有一项还没有填写完整，检查一下再提交就好。 |
| c.error.2001.field | 2001（带字段名） | 这一项还需要补一下：{field} |
| c.error.2002 | 2002 | 没有找到这段内容，可能已经被移走了。 |
| c.error.3001 | 3001 | 这里出了点小状况，我们已经在看了，再试一次就好。 |
| c.error.4001 | 4001 | 提交得有点快，歇一分钟再试就好。 |
| c.error.network | （网络层，非业务码） | 网络好像有点慢，等会儿再试就好。 |
| c.error.timeout.retry | （超时重试） | 刚才没送达，我们替你重试了一次，内容还留着。 |
| c.error.unknown | 未知码 | 这里出了点小状况，再试一次就好。 |

> 错误提示一律不暴露"越权""校验失败""内部错误"等技术措辞（契约 §1 只约束 `message` 字段给人读，本表是界面层更柔和的替换）。

### 4.2 空状态（**不得写"暂无数据"**）

| ID | 文案 |
|----|------|
| c.empty.triage.list | 这里还很安静。有学生写下自己的心情时，会出现在这里。 |
| c.empty.triage.filtered | 这个条件下暂时没有学生。换个条件看看也可以。 |
| c.empty.detail.shared | 这次没有学生愿意让你看到的内容，可以先用线下的方式关心。 |
| c.empty.detail.unshared | 该生选择暂不分享，可通过线下方式关心 |
| c.empty.treehole.list | 这里还空着。想写的时候，随时都可以来。 |
| c.empty.profile.submissions | 这一天你还没有留下记录。想写的时候再来。 |
| c.empty.profile.dates | 还没有打过点的日子。今天可以从心情那一题开始。 |
| c.empty.feedback.mine | 你还没有提交过学校的反馈。想到了随时可以写。 |
| c.empty.search | 没有找到对应的同学，换个关键词试试。 |
| c.loading.generic | 稍等一下… |
| c.loading.triage | 正在把这些内容取过来… |

### 4.3 危机资源

| ID | 文案 |
|----|------|
| c.hotline.title | 如果现在很难受，可以打这些电话 |
| c.hotline.national.name | 全国统一心理援助热线 |
| c.hotline.national.number | 12356 |
| c.hotline.beijing.name | 北京心理援助热线 |
| c.hotline.beijing.number | 010-82951332 |
| c.hotline.emergency.name | 紧急情况（急救 / 报警） |
| c.hotline.emergency.number | 120 / 110 |
| c.hotline.line | 全国统一心理援助热线 12356 ｜ 北京心理援助热线 010-82951332 ｜ 紧急情况拨打 120 / 110 |
| c.hotline.footer | 这些电话 24 小时有人接，说"我现在不太好"就可以。 |

### 4.4 通用动作词

| ID | 文案 |
|----|------|
| c.action.next | 下一步 |
| c.action.back | 上一步 |
| c.action.skip | 跳过 |
| c.action.save | 保存 |
| c.action.submit | 提交 |
| c.action.retry | 再试一次 |
| c.action.confirm | 确定 |
| c.action.cancel | 取消 |
| c.action.close | 关闭 |
| c.action.gotIt | 知道了 |
| c.action.logout | 退出登录 |
| c.action.copy | 复制这段文字 |
| c.action.copied | 已经复制好了，可以先存到别处。 |

### 4.5 首次进入问卷的告知页（架构 §7 · PIPL 第 30 条）

| ID | 文案 |
|----|------|
| s.notice.title | 开始之前，想先和你说清楚 |
| s.notice.item1 | 你填的内容只用于学校里的心理支持，不做别的用途。 |
| s.notice.item2 | 内容默认只有你自己能看到。只有你选了「请求心理老师帮助」，老师才会看到这次的内容。 |
| s.notice.item3 | 树洞里的内容永远是私密的，老师看不到，也不会进入任何统计。 |
| s.notice.item4 | 如果和学校的食堂、宿舍、设施有关，你可以写在专门的那一栏，我们会以匿名方式转给学校相关部门。 |
| s.notice.item5 | 你可以随时决定不再填写。如果填完之后改主意了，也可以在「我的档案」里点「不让老师看了」，让这一条重新变成只有你自己能看到。 |
| s.notice.item6 | 撤回之后不能再改回"老师可以看到"，想再让老师知道，重新填一次就可以。 |
| s.notice.action.agree | 我知道了，开始 |
| s.notice.action.exit | 先不填 |

### 4.6 学生端登录与导航

| ID | 文案 |
|----|------|
| c.login.title | 欢迎回来 |
| c.login.subtitle | 今天的你，还好吗？ |
| c.login.demoNote | 首次使用请先注册，填写班级、姓名、号次与密码。 |
| c.login.studentNo | 号次 |
| c.login.studentNo.format | 号次是你的编号，注册后用它登录。 |
| c.login.password | 密码 |
| c.login.className | 班级 |
| c.login.name | 姓名 |
| c.login.toggle.register | 没有账号？去注册 |
| c.login.toggle.login | 已有账号？去登录 |
| c.login.action.submit | 登录 |
| c.login.action.register | 注册并进入 |
| c.tab.questionnaire | 问卷 |
| c.tab.profile | 我的档案 |
| c.tab.appointment | 预约 |
| c.tab.about | 关于 |

> 树洞 Tab 名沿用 `s.treehole.tab.title`，不另立 ID。
>
> 注册制（v1.1 追加件）：学生第一次登录先「注册」（班级/姓名/号次/密码），
> 之后用「号次 + 密码」登录。号次全校唯一，登录原样发送、不做前缀补全。

### 4.7 服务就绪态（`engine_ready=false`）

| ID | 文案 |
|----|------|
| c.engine.notReady | 数据库正在恢复，稍等一下再试就好。 |
| c.engine.notReady.action | 现在还不能提交，等一会儿再试一次。 |

> 由来：学生端协议要求 `engine_ready=false` 时「提示稍后再试」（协议 §2.2 / §5）。
> 原实现**借用了教师端键** `t.login.error.network`（「暂时连不上服务，稍后再试就好。」），
> 有两处不妥：① 语义不准（服务明明连得上，只是数据库在恢复）；② 学生端复用教师端文案。
> 现补专用键，界面同时据 `engine_ready` **禁用提交**，避免学生填完整份问卷才失败。

### 4.8 免责与边界声明（**§6.6 要求的"单独登记"**）

| ID | 文案 |
|----|------|
| c.disclaimer.nondiagnostic | 这里的内容是关怀用的参考，不构成医学诊断。如果一直觉得不太好，可以让家人或老师陪你去找医生聊聊。 |

> **本条是 §6.6「免责表述」规定的唯一例外位置**：该节写明"「不构成诊断」这类**否定式免责**
> 是唯一允许保留相关字样的位置，且**须单独登记**"。此处即那次登记。
>
> 出现位置（`docs/UI约定.md` §6 硬要求：「页脚/关于页必须含：非诊断声明 + 危机热线」）：
> ① **关于页**（`AboutTab`）；② **首次进入问卷的告知页**（`NoticePage`，与热线相邻）。
>
> ⚠️ 措辞纪律：只做**否定式**表述（"不构成诊断"），**不得**出现任何肯定式的判定性用语；
> 且不得命中 `_meta.word_ban` 的 10 个禁用词（本条实测 0 命中）。

### 4.9 预约时间课表（**学生端 / 教师端共用**）

> 这一节是「预约时间」界面的**共享文案**：双端渲染的是同一张课表
> （横轴 = 星期几，纵轴 = 第 1 ~ 第 8 节），因此星期名、节次名、格子状态说明
> **必须同源**，否则学生和老师会看到两张对不上的表。
>
> 节次的时间段（`08:00-08:45` 这种）是**数字格式**，由 `desktop_common/schedule.py`
> 的 `PERIODS` 定义，**不在**文案表里；这里只有"第 N 节"这个名字。

| ID | 文案 |
|----|------|
| c.schedule.year | 年份 |
| c.schedule.monthNav | 月份 |
| c.schedule.col.period | 节次 |
| c.schedule.week.prev | 上一周 |
| c.schedule.week.next | 下一周 |
| c.schedule.week.current | 回到本周 |
| c.schedule.week.range | {start} - {end} |
| c.schedule.weekday.1 | 周一 |
| c.schedule.weekday.2 | 周二 |
| c.schedule.weekday.3 | 周三 |
| c.schedule.weekday.4 | 周四 |
| c.schedule.weekday.5 | 周五 |
| c.schedule.weekday.6 | 周六 |
| c.schedule.weekday.7 | 周日 |
| c.schedule.period.1 | 第1节 |
| c.schedule.period.2 | 第2节 |
| c.schedule.period.3 | 第3节 |
| c.schedule.period.4 | 第4节 |
| c.schedule.period.5 | 第5节 |
| c.schedule.period.6 | 第6节 |
| c.schedule.period.7 | 第7节 |
| c.schedule.period.8 | 第8节 |
| c.schedule.legend.title | 方块说明 |
| c.schedule.legend.free | 可预约 |
| c.schedule.legend.blocked | 老师不方便（红框） |
| c.schedule.legend.taken | 已有同学约了 |
| c.schedule.legend.mine | 我约的 |
| c.schedule.legend.past | 已经过去 |
| c.schedule.cell.blocked | 不可约 |
| c.schedule.cell.taken | 已约 |
| c.schedule.cell.mine | 我的 |
| c.schedule.cell.free | 可约 |
| c.schedule.empty.week | 这一周没有可预约的时间，换一周看看。 |

---

## 5. 运行时数据（`copywriting.json` 同步）

`mindcare/copywriting.json`（**与本文同级**，2026-10-02 从 `mindcare/server/` 移来）是 `GET /api/v1/tips` 的运行时数据源，键名对齐契约 `enums.tips_scene`，另含 `self_care` 供自助建议页使用：

| JSON 键 | 对应本表 ID |
|---|---|
| `plain` | `s.end.plain.tips` |
| `down` | `s.end.selfcare.tips` |
| `self_care` | `s.end.selfcare.body` |
| `revoke.entry_action` | `s.revoke.entry.action` |
| `revoke.confirm_body` | `s.revoke.confirm.body` |
| `revoke.confirm_irreversible` | `s.revoke.confirm.irreversible` |
| `revoke.toast_done` | `s.revoke.toast.done` |
| `revoke.badge_revoked` | `s.revoke.badge.revoked` |
| `revoke.end_title` / `revoke.end_body` | `s.end.revoked.title` / `s.end.revoked.body` |

> `_meta.revoke_supported: true` 声明撤回机制已落地（对应契约 §2.3.1）。`/tips` 接口本身不涉及撤回；撤回文案由学生端本地渲染，放进 JSON 只是为了让 C 与 B 共用一份真相。

> `/tips` 的 `tips.treehole_entry` 是**接口字段**（是否提供树洞深链），不是文案；深链按钮文案取 `s.end.selfcare.action.treehole`。

---

## 6. 设计约束（写给实现者）

1. **树洞零分享**：契约 v1.1 §2.6/§2.7 明确"树洞没有分享/授权开关"。§1.7 的文案里出现"分享/公开/让老师看"即为**错误**，需回退。
   ⚠️ **撤回机制不适用于树洞**：§1.8 的撤回只作用于**问卷记录**（`/questionnaire/submissions/{record_id}`）。树洞本来就没有可撤回的授权，因此树洞不得出现任何撤回/分享按钮。
2. **两个通道不混用**：`detail`（心理倾诉）不出现"转给学校相关部门"；`material_detail`（校方问题）不出现"心理老师会看到"（唯一例外：命中分流词时走 `s.q25.sensitive.*`）。
3. **不给孩子贴标签**：教师端只用"需要优先关心 / 有待回应 / 常规关注"，不用任何判断性词汇；未共享态不展示任何由计数推断的内容。
4. **不用感叹号施压**：全文以句号和逗号收束，鼓励性语气靠措辞而非标点。
5. **不显示倒计时/剩余字数**：`s.q3` 不限字数，界面不设字数上限提示与分钟倒计时。
6. **免责表述**：本系统输出的是关怀排序参考，不是医学诊断。若需在界面出现，"不构成诊断"这类**否定式免责**是唯一允许保留相关字样的位置，且须单独登记（当前文案表未使用任何此类字样）。
7. **撤回的三条措辞纪律**（§1.8）：
   - **撤回 ≠ 删除**：只用"不让老师看了 / 只有你自己能看到"；**禁止**"删除 / 清除 / 抹掉 / 记录消失"。
   - **撤回 ≠ 撤销同意曾存在**：记录的留痕保留（事件溯源），分诊计数不因撤回而改变。因此**禁止**"老师不会知道你说过什么 / 这次填写不算数"。
   - **撤回不可逆**：二次确认必须出现"不能再改回来"；界面上**不得**提供"改回老师可见"的按钮，也**不得**承诺"可以随时恢复"——想恢复只能重新填一次问卷。
8. **教师端不解释个人原因**：学生撤回后，教师端只显示中性说明（`t.detail.unshared.revokedNote`），**不得**出现"学生拒绝了你 / 撤回了对你的信任"这类表述。

---

## 7. 变更登记：归档 v1 文案的可采用性判定

来源 `_archive-v1-web/web/src/content/copy.ts`（v1 微信小程序时代，场景名 `neutral/sad`，与契约 `plain/down` 不同）。

> **本次（撤回机制进契约后）的重要修正**：v1.1 首版曾把「可随时收回」类表述整类判为**作废**（理由：契约无撤销接口）。
> 契约现已补上 `PATCH /questionnaire/submissions/{record_id}`（PIPL 第 15 条），**撤回能力成立**，故**该类文案已恢复采用**——但**措辞必须改**：
> 契约用词是「**撤回同意**（revoke consent）」，不是"收回/删除"。撤回的是**可见性**（老师能否看到这条正文），**记录仍然保留**（事件溯源留痕，契约 §5.5）。
> **区分要点**：`treehole.*` 的分享/收回体系仍然**作废**（树洞从来没有分享开关，也就没有可撤回的授权）；恢复的只有**问卷分享**语境下的那两条。

### 7.1 已恢复采用（**改措辞**）

| 归档条目 | 归档原文 | 恢复后的措辞（本表 ID） | 与归档的差异 |
|---|---|---|---|
| `moodCheckin.endings.shared.visibilityNotice` | 已分享给心理老师 · 可随时收回 | `s.revoke.badge.shared`「老师可以看到」/ `s.revoke.entry.action`「不让老师看了」 | 原句承诺"可随时收回"过于笼统；现改为**明确的入口 + 状态标签**，并在二次确认里说清后果与不可逆 |
| `common.disclaimers.d4` | 你随时可以收回分享，收回后老师立刻看不到。 | `s.revoke.confirm.body`「老师那边就不会再看到这段内容了。」+ `s.revoke.toast.done`「好，老师那边看不到这一条了。」 | ① 用词由"收回"改为"不让老师看了"（不用法律术语做主按钮）；② **删去"随时"**——撤回不可逆，恢复只能重新填写；③ 明确"不会再看到这段内容"而非暗示记录消失 |

### 7.2 判定为**不可采用**的归档条目

| 归档条目 | 归档原文 | 不可采用原因 |
|---|---|---|
| `treehole.compose.visibilityOptions.shared` | 公开 —— 心理老师可以看到 | 契约 §2.6/§2.7：树洞为 L0 绝对私密，**无分享/授权开关** |
| `treehole.compose.visibilityLabel` | 这条想让谁看到？ | 同上，隐含了不存在的可见性选择 |
| `treehole.actions.toggleToShared` | 让老师看 | 同上 |
| `treehole.actions.toggleToPrivate` | 转为私密 / 已收回，老师那边看不到了。 | 同上，隐含"曾经共享过"；**树洞不适用新的撤回机制** |
| `treehole.compose.confirmOptions` | 确定让心理老师看到吗？你随时可以收回。 | 同上 |
| `moodCheckin.shareConfirm.*` | 要不要让心理老师看到？/ 给心理老师看 / 先不给老师看 | 改为单一 `request_help` 布尔开关，`consent_share=request_help`，**没有独立的三态分享控件**（撤回是**事后**在档案页操作，不是填答时选择） |
| `moodCheckin.endings.private.teacherEntry` | 如果你希望有人陪你一起想，随时可以点这里找心理老师。 | 只在 Q3 之后提供一次求助选择；事后入口是**档案页的撤回**，不是"再找老师"（"重新找老师"须重新填问卷，见 `s.revoke.after.relink`） |
| `counselor.feed.filters.treehole` / `card.sourceTag.treehole` | 仅树洞 / 树洞 | 契约 §2.9：教师端**不存在**读树洞的接口 |
| `copy.ts` 文件头禁用词清单及注释中的 `诊断` 三处例外 | — | 本表禁用词为 10 个（不含 `诊断`）；已按项目要求统一为 10 词口径 |

> 仍可复用（已按契约改写）：`s.q1.*`、`s.branch.b.*`、`s.q2.*`、`s.q25.*`（告知语已改写为"转给学校相关部门"）、`s.q3.*`、`s.end.happy.*`、`s.treehole.list.*`、`c.error.network`、`c.hotline.*` 等。
