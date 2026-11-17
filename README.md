# 息差观察：红利指数股债收益差

Python采集 + GitHub Actions定时更新 + GitHub Pages中文静态看板。本发布仓库只包含日频监控，不含交易策略、回测或候选股息率历史。

计算：指数股息率 − 中国10年期国债收益率；收益率单位为%，息差单位为百分点。

## 功能与数据

- 中证红利000922、上证红利000015、沪深300 000300、中证500 000905切换。
- 指数采用中证官网D/P2（计算用股本）；年度分红窗口未获充分确认，不称为已验证TTM。
- 债券唯一来源为中债国债收益率曲线10年点，不混用CFETS或活跃券收益率。
- 交互图、时间范围切换、CSV下载、滚动统计、缺失和过期提示。官方股息率历史较短，样本不足的统计显示NA。
- 同一市场日期两源都有数据才计算息差，缺失不填充。每个版本保留来源、实际采集和可用时间。

数据口径、已验证范围和局限见[数据说明](docs/DATA_SOURCES.md)。

## 首次部署

按[中文GitHub部署教程](docs/GITHUB_DEPLOYMENT.md)操作：上传到main → Pages来源选GitHub Actions → 设置仓库变量ENABLE_PAGES=true → 手动运行Daily data and Pages并勾选bootstrap。

首次push只测试和构建已有数据；手动或定时运行才采集。尚未在目标GitHub仓库验证前，不应将本地通过测试称为已经上线。

## 每日更新

北京时间19:05、20:10、21:10，对应UTC cron为`5 11 * * 1-5`、`10 12 * * 1-5`、`10 13 * * 1-5`。程序再次筛选已核验A股交易日与收盘时间。GitHub调度可能延迟。

采集失败保留历史；重复运行不新增重复记录。采集、自动提交、构建和Pages部署在同一工作流完成，不依赖机器人提交触发另一次工作流。降级状态也尽量发布，最后health任务标红。日志见Actions和`data/status.json`。

## 本地运行

使用自己确认的Python 3.10+环境；CI固定Python 3.12。先在选定环境安装`requirements.txt`，无需付费API或手填Token。以下`python`代表已选定的解释器。

```text
python -m monitor build
python -m http.server 8765 --bind 127.0.0.1 --directory site
```

打开 http://127.0.0.1:8765 ，不要直接双击HTML。

```text
python -m monitor update
python -m monitor update --bootstrap
python -m unittest discover -s tests -v
node --check site/app.mjs
node --test tests/frontend.test.mjs
```

`update`正常成功或非交易时段跳过返回0；过期、缺源、需要审核返回2。bootstrap只取最近已收盘日期，不会将昨日数值伪装成今日。

## 维护约定

`data/observations/<series>/<year>.jsonl`是按年保存的正式版本；`site/data/`是构建产物，不重复提交。首次打包附带已有官方历史，部署不需要重新下载全部债券长历史。`RELEASE_MANIFEST.json`记录首次发布包文件清单，后续每日更新以Git提交为准。

交易日历使用上交所年度休市表，11–12月自动尝试核验下一年；格式不匹配、未知年份、冲突均提示错误，不猜测节假日。可手动执行`python -m monitor refresh-calendar`。

下载CSV是当前修订快照，不是过去某时点已经知道的数据。源实际发布时间未知时为空；回补不会改写为历史已知。历史时点导出可用`python -m monitor build --as-of '2026-11-17T09:00:00+08:00' --output artifacts/asof`。

异常跳变进入隔离表，应核对原始来源后才使用`accept-quarantine`命令接纳，不能为消除页面提示直接填值。
