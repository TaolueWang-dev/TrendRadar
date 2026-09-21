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
