# 网易模组发布器

网易《我的世界》开发者平台（mcdev.webapp.163.com）的第三方发布效率工具。
按官方编辑页的结构完整复刻界面并优化体验，底层通过平台接口直连，
把「更新模组 → 打包 → 上传 → 填表 → 提审」压缩成几次点击，同时开放
本地 Agent 接口供脚本 / AI 直接驱动。

> 本工具仅操作开发者本人账号下的作品，提审等不可逆动作均需人工确认。
> 界面为自制实现，与网易官方无关；平台接口形态参考开源项目
> [BitterLemonn/McDevManager](https://github.com/BitterLemonn/McDevManager)（BNCL-1.0）的逆向成果。

## 功能

**界面（单窗口，Edge 渲染，明暗主题）**

- 启动自动恢复登录会话；过期自动进入登录流程（人工输密码/验证码一次，约十天免登录）
- 作品列表 / 搜索 / 状态标签 / 本地映射标记；点选作品**秒读**全部表单（平台 165 字段）
- **详情介绍编辑器**（PE/PC 共用）：富文本直接编辑，**拖拽 / 粘贴图片自动上传插入**，
  落点跟随光标——解决官方页图片不能拖、长图排版乱的痛点
- **图片槽位**：组件 ICON、手机图片位×6、PC 图片位×2，拖拽或点击即上传保存
- **视频**：拖入 mp4 + 封面图，一键上传保存（H264/AAC 规范同官方要求）
- **全部字段**（高级折叠区）：平台完整字段可编辑，改动自动标绿
- 底部自动化条：建议名称 / 生成纪要 / 打包上传+提升版本 / 一键保存 / 提交审核
- 改动自动标绿（脏值跟踪），没改的字段提交平台原值，绝不静默覆盖

**发布自动化**

| 官方手工步骤 | 本工具 |
|---|---|
| 手动打包（压缩双包目录） | 自动：扫描 `*_behavior_pack` / `*_resource_pack` 合并压缩，排除 `__pycache__`/`.pyc` |
| 手动改 manifest 版本 | 自动：版本号=当天日期 `[yy,m,d]` |
| — | 自动：manifest 内全部 uuid 重新生成（防身份碰撞） |
| 删除旧 zip | 自动删除旧时间戳包 |
| 网页大文件上传 | 接口直传（fp.ps.netease.com），带进度显示 |
| 分块表单逐项保存 | 一次 `update` 提交全部改动 |
| 手动提审 | 确认后自动提交 |

**Agent 接口**（exe 运行时常驻开放）

- HTTP：`http://127.0.0.1:8765`，`POST /list /read /set /add-image /publish /submit`
- CLI：`网易模组发布器.exe --cmd ...`（自动优先代理到常驻实例的活会话）

示例：

```bash
# 列出作品
网易模组发布器.exe --cmd list
# 读取当前表单（165 字段 + 详情 HTML）
网易模组发布器.exe --cmd read "趣味附魔 - 共162个附魔"
# 修改字段并保存
网易模组发布器.exe --cmd set "趣味附魔 - 共162个附魔" --json "{\"item_name\":\"趣味附魔 - 共242个附魔\"}"
# 插入图片到详情末尾
网易模组发布器.exe --cmd add-image "趣味附魔 - 共162个附魔" --img D:/pics/1.png
# 打包+上传+保存（可选 --submit 一并提审）
网易模组发布器.exe --cmd publish "趣味附魔 - 共162个附魔" --note "26.10.26更新：..."
```

## 快速开始

```
1. 下载或构建 exe（见下）
2. 双击运行 → 自动打开登录页 → 人工登录一次（勾选「十天免登录」）
3. 选择作品 → 编辑/勾选自动化项 → 一键保存 → 提交审核
```

多模组：编辑 `发布配置.json`（首次运行自动生成，含本机路径故不入库），
模板见 `发布配置.example.json`：

```json
{
  "id": "显示名",
  "project_dir": "D:/MCModDve/你的项目",
  "resource_keyword": "平台作品名里能唯一匹配的关键字",
  "name_template": "xxx - 共{n}个yyy",
  "count_glob": "xxx_behavior_pack/xxx/*.json",
  "changelog": "更新日志.md"
}
```

## 构建

依赖：Python 3.12+、系统 Edge（无需下载浏览器内核）。

```bash
py -3 -m pip install playwright requests
py -3 -m PyInstaller --onefile --windowed --name 网易模组发布器 ^
    --collect-all playwright --hidden-import=PIL.ImageTk ^
    --add-data "ui.html;." mod_publisher.py
```

## 项目结构

| 文件 | 说明 |
|---|---|
| `mod_publisher.py` | 宿主：引擎线程、页面 RPC、Agent HTTP、CLI、发布编排 |
| `ui.html` | 界面（官方结构复刻、主题、脏值跟踪、文档编辑器） |
| `publish_api.py` | 平台接口（停靠页 fetch 传输 / 直传 / update 构造 / 本地打包） |
| `publish_core.py` | 浏览器引擎（登录 / 兜底自动化） |
| `tests/e2e_v12.py` | 真会话端到端回归 |
| `tests/serve_once.py` | 无头常驻实例（调试 Agent API 用） |
| `tests/do_publish.py` | 趣味附魔发布脚本；`--dry-run` 只读自检详情配方（字数/图数），不带则真实发布 |
| `tests/probe_detail_state.py` | 只读探针：作品级字段 + 详情段结构/字数，导出 `live_detail_dump.html` |
| `tests/test_detail_recipe.py` | 离线单测：详情组装配方（历史标题剥离、幂等） |
| `tests/gen_detail_images.py` | 详情长图素材生成（附魔介绍瀑布流、更新日志紧凑渲染） |

## 端点与实现备忘

- API host：`mc-launcher.webapp.163.com`（列表带尾斜杠；detail/update/apply_review 不带）
- 上传：`filepicker/file_token` 取 token（Policy 内含实际上传地址）→
  `fp.ps.netease.com` multipart 直传 → 响应 JSON + `x-ntes-signature` 头
- update 请求体 = detail 原样透传 + 字段矫正（mc_version 字符串转数组等）
- 提升版本 = `res[0].add_version`
- 详情字数：编辑器按 Quill 长度计（**图片占 1 字**），PE 详情上限≈405-420 字、图片≤10 张；
  超字数静默截断（吞图不报错），超图数报错；富文本白名单 `p/strong/span/br/img`（`<b>` 报非法字符）
- 发布管线护栏（publish_api/mod_publisher）：发布前 `<b>`→`<strong>` 矫正 + 字数/图数校验，
  超限**直接报错不发布**（不再静默截断）；update/提审对 5xx/429/网络抖动自动重试 ×2；
  update 后回读验证（详情被截断/包未替换立即报错），`DetailValidationError` 不走浏览器兜底
- 鉴权为轮换票据：所有请求经常驻平台域的停靠页 `fetch` 发出，
  由浏览器原生管理 cookie 轮换（静态导出 cookie 会被轮换挤掉失效）

## 已知限制

- 仅支持 PE（add_ons，含双端同步）类资源；皮肤/联机商品页结构不同未支持
- 模组攻略为平台独立文章系统，本工具只读展示
- 平台改版导致接口失效时自动回退浏览器自动化流程并记录日志

## 免责声明

仅供个人开发效率用途，请遵守《网易MC开发者协议》及相关平台规则；
自动化仅限本人账号低频操作，提交审核永远需要人工确认。
