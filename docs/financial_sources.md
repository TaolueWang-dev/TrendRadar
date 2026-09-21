# 金融渠道接入

金融渠道在 `config/config.yaml` 的 `financial_sources` 中独立开关。现有 NewsNow 平台继续使用原配置。无需导入或迁移 realtime_news_analysis；启动 `python -m trendradar` 时会合并渠道，然后使用原有存储、筛选、AI 分析和报告流程。

| 渠道 | 当前数据与前提 | 名次含义 |
| --- | --- | --- |
| 同花顺 | HTTP 港股每日人气榜 | 上游榜单名次 |
| 雪球 | 本机 OpenCLI、Chrome 插件连接、雪球登录；人气榜前 50 中保留港美股 | 原榜名次，筛选后可能不连续 |
| 东方财富 | HTTP 直连 `https://finance.eastmoney.com/a/cywjh.html`，读取“网友点击排行榜”，目前 10 条 | 网页公开榜单名次 |
| 富途 | 本机 OpenD 11111 端口，富途 SDK 查询指数关键词及港美股热门股资讯 | 本次采样、时间窗口内按阅读量排序，不是全站排名 |

东财无需 SSH、a800、数据库、登录或 OpenCLI；新鲜度取决于东财网页更新。公开页面没有提供精确点击次数或统计窗口，因此不推断这些数值。本渠道采用新 ID `finance-dongcai-hotnews`，与此前数据库机构号资讯 `finance-dongcai` 分开存储；原历史样本保留，当前启用平台不会混入旧渠道。本次没有采集雪球评论正文。没有结果或采集失败会进入 failed_ids，不伪造数据、不替换为旧快照。正常 daily 模式仍可展示当日历史记录，这是原报告行为。

股票榜标题保持稳定，热度和涨跌不拼入标题，避免重复采集被误认为新事件。原数据库模型只保存标题、链接与名次，不保存阅读量等原始金融指标；跨平台名次不能解释成统一资金热度。人气榜只能说明股票受关注，不能独立说明原因或方向。主题归纳沿用既有 AI，未新增主题追踪或热度算法。

## 本地测试报告

在项目目录运行（不会推送通知）：

```sh
.venv/bin/python scripts/finance_report.py
```

默认只采集已启用的金融适配渠道，用原 HTML 渲染器生成完整标题预览，不请求 AI。结果在 `output/financial_channels_test/output/html/latest/current.html`；采集状态在 `output/financial_channels_test/collection.json`。

允许把采集标题、股票名称/代码、来源和榜单名次发送给配置的 AI 服务后，可以运行：

```sh
.venv/bin/python scripts/finance_report.py --ai --reuse
```

`--reuse` 只复用当天测试样本；去掉它可重新采集。AI 模式使用已有 `finance_test.txt` 金融关注词和现有总结模板。测试对 DeepSeek 禁用 thinking，避免默认 token 额度被思考耗尽；空响应或截断现在会报错。正式配置如需同样设置，可在现有 `ai` 下设置 `extra_params.extra_body.thinking.type: disabled`。

测试不修改正式筛选策略：正式 `filter.method`、`ai_filter.interests_file` 及调度时间段覆盖仍按原配置运行。默认测试完整预览不等于 AI 已判定这些都是热点。

单元测试：`.venv/bin/python -m unittest discover -s tests -v`。

## 全渠道金融 AI 报告

```sh
.venv/bin/python scripts/finance_report.py --all --ai --output output/all_finance_test
```

采集所有配置中已启用的热榜平台和 RSS，以及新增同花顺、东财。此测试模式将雪球替换为 NewsNow 的 `xueqiu-hotstock`，无需 OpenCLI；仅对本次运行生效。使用原 `finance_test.txt` 金融兴趣描述、现有 AI 总结模板及配置的模型；通知关闭。失败渠道会记录在报告中。`collection.json`、`rss_collection.json`、`filter_result.json`、`report_result.json` 分别记录采集、RSS、筛选和总结结果。

## 单独验证东财直连

```sh
.venv/bin/python scripts/finance_report.py --sources dongcai --output output/eastmoney_direct_test
```

报告：`output/eastmoney_direct_test/output/html/latest/current.html`。此命令只生成本地预览；如果页面排行榜结构变化或返回空数据，渠道会明确失败。`financial_sources.dongcai.limit` 当前为 10，只能限制返回条数，不能增加网站榜单长度。该榜包含不同市场的财经事件，港美股相关性继续交由既有筛选流程判断。

## 富途资讯

已在当前 `.venv` 安装 `futu-api==10.10.7008`。新环境可用 `uv pip install '.[futu]'` 安装可选依赖。需要已登录且有资讯权限的 OpenD；本机当前通过 SSH 隧道连接已有服务，隧道断开需重新连接：

```sh
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -L 127.0.0.1:11111:127.0.0.1:11111 a800
```

适配器自身不创建 SSH 隧道，不启动或重启远程服务。仅使用行情资讯接口，无交易接口。

`financial_sources.futu` 默认查询恒生指数、恒生科技指数、纳斯达克100、标普500，再查询港美股综合热度前三只股票的资讯。每个关键词取最新 10 条，仅保留最近 48 小时、发布时间可解析的文章；同链接去重后按阅读量排序，最多 50 条。无时区日期按香港时间解释。这是限定关键词的滚动窗口采样，不等同于原系统的全部成分股及交易日窗口。调节 `keywords`、`top_stocks_per_market`、`per_keyword`、`window_hours` 和 `limit` 可改变范围。

SDK 在独立子进程运行，120 秒超时终止；查询间隔至少 0.3 秒，连续三次资讯请求失败即停止。部分失败会保留成功条目，并在失败渠道列表和采集状态中标明；不自动重试消耗额度。采集状态列出已请求和未请求关键词。原存储仍主要保留标题、链接和排序名次，不把阅读量推断为资金流向。

```sh
.venv/bin/python scripts/finance_report.py --sources futu --output output/futu_test
.venv/bin/python scripts/finance_report.py --sources futu --ai --reuse --output output/futu_test
```

`--all --ai` 也会自动包含已启用的富途渠道。财报日历、价格轨迹、评级独立列表尚未接入本适配器。

## 雪球讨论正文（2026-09-21 新增）

当前配置已调整为 `selection: hk_us_24h`、`top_per_market: 5`、`per_stock: 3`、`sort: reply`、`transport: http`。直接查询雪球港股和美股 24 小时热度榜，各选前五个标的（可能含 ETF）；每个标的请求按评论排序的前三条讨论，并补取正文。这是评论排序，不声称等同于官方综合热门算法。

`window_hours: 0` 表示帖子不另限发布时间，24 小时仅限定股票榜；少于三篇或正文读取失败会记录缺口。同一帖子关联多个标的时正文去重并保留关联关系。最多十个标的、三十次详情请求；遇到会话验证停止，并列出未查询标的。以下“默认”数值是未设置该方案时的兼容默认值。

新增独立渠道 `financial_sources.xueqiu_discussions`，源 ID 为 `finance-xueqiu-discussions`。它与热门股票榜并存，不将股票榜误认为文章。

- 默认从 NewsNow 热门股票中选前 3 只港美股，每只最多 5 条，近 48 小时。可通过 `symbols: ["00700", "AAPL"]` 指定股票，代码请加引号。
- HTTP 获取讨论列表，缺少 text 正文或为长文时请求详情；description 不作为完整正文。保存正文、作者、发布时间、原文 URL、股票代码、点赞/回复/转发数。名次是采样内发布时间顺序，不是热度排名。
- 请求间隔 3 秒，最多 15 次正文详情请求；登录失效、429、风控 HTML 页面均停止，不自动绕过验证。
- 正文保存在当前本地数据目录的 `article_content/YYYY-MM-DD.json`，并随测试 collection.json 保留。此补充存储目前是本地文件，不具备远端存储同步能力。
- AI 筛选和总结读取最多 2000 字正文节选；用户讨论被标记为观点，不是核实事实。AI 模式 HTML 可展开完整接口正文。标题模式目前不会自动加载补充正文。已有分类缓存沿用原机制；正文后续编辑不触发自动重分类。

**当前实测状态：公开会话返回风控 HTML，真实正文采集尚未成功。** 模拟接口测试已经通过，不能将它解释为线上接口已可用。

如有本人授权且有效的雪球会话，可将 Cookie 保存在项目外的本地私有文件，在 `cookie_file` 填绝对路径；或运行进程中设置 `XUEQIU_COOKIE`。不要在聊天中发送 Cookie，也不要提交到 Git。遇到网站验证码，应在网站正常登录并人工完成验证；Cookie 不保证能消除风控。

```sh
.venv/bin/python scripts/finance_report.py --sources xueqiu_discussions --output output/xueqiu_discussions_test
```

有正文后，再加 `--ai --reuse` 验证金融筛选。该渠道已启用，后续 `--all` 会尝试采集；失败会明确列出，不影响其他渠道成功结果。

### 可选的浏览器会话模式

2026-09-21 核对了以下专用采集项目：

| 项目 | 实际方式 | 适用性 |
| --- | --- | --- |
| [NickchenzZ/xueqiu-spyder](https://github.com/NickchenzZ/xueqiu-spyder) | Chrome 会话请求股票讨论接口，打开帖子详情页提取正文 | 接近本项目需求；仓库未发现许可证，不直接复制代码 |
| [zcker/xueqiu-crawler](https://github.com/zcker/xueqiu-crawler) | Cookie + HTTP，采集指定用户动态/专栏，REST API | MIT；适合跟踪指定作者，仍依赖登录态 |
| [16pk/snowball_crawler](https://github.com/16pk/snowball_crawler) | Cookie + HTTP，股票讨论/用户发帖、数据库和 Markdown 导出 | 可参考接口；仓库未发现许可证，不直接复制代码 |

上述源码存在不代表当前可正常采集。本项目独立实现了可选浏览器传输，不引入这些项目的代码或其完整依赖。默认 HTTP 模式保持不变。浏览器模式使用单独的 Chrome profile，不读取日常浏览器的 Cookie；默认路径为 `~/.local/share/trendradar/xueqiu-browser`。该目录包含登录状态，不应提交或分享。

安装依赖（需要已安装 Google Chrome）：

```sh
uv pip install --python .venv/bin/python -r requirements-xueqiu-browser.txt
```

首次运行登录命令，在打开的浏览器中正常登录并完成人工验证，然后回到终端按回车：

```sh
.venv/bin/python -m trendradar.crawler.xueqiu_browser --login
```

先采集腾讯最多两条讨论，验证真实正文和时间：

```sh
.venv/bin/python -m trendradar.crawler.xueqiu_browser --symbol 00700
```

结果保存在 `output/xueqiu_browser_test.json`，没有正文时退出码为 1。浏览器会话不会把 Cookie 写入报告。正文缺失或长文会打开帖子详情页读取 `.article__bd__detail`，无法定位正文、遇到验证或限流就停止；不会将登录页或摘要当作完整正文。

确认成功后，在 `config/config.yaml` 的现有 `financial_sources.xueqiu_discussions` 下添加 `transport: browser`，必要时设置 `headless: false`。`browser_profile` 可指定独立会话目录。采集仍使用原来的限量、48 小时时间窗口和正文处理流程；浏览器采集需要在同步执行环境运行，勿同时占用同一 profile。

本次验证：15 项相关单元测试通过；Playwright 已安装。临时无登录 Chrome 会话实测在页面就绪检查处停止（“雪球页面未就绪，请先正常登录”），没有获取讨论正文。记录见 `output/xueqiu_browser_smoke.json`。这不能代替有效登录后的实测，也不能证明登录后一定成功。
