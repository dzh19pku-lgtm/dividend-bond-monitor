# 从本地监控项目到GitHub网站

Git是本地版本记录工具；GitHub仓库存放代码和数据；GitHub Actions按时执行Python；GitHub Pages发布生成的网页。上传后，自动更新在GitHub服务器运行，电脑可以关机。

本次只发布日频监控，使用独立发布包`github-monitor.zip`。不要在包含全部研究的原目录执行`git add .`，也不要将ZIP作为单个文件上传到仓库。要上传解压后的文件。

## 1. 建一个空的GitHub仓库

登录[GitHub新建仓库页面](https://github.com/new)。Repository name建议`dividend-bond-monitor`。

若使用免费GitHub账户并希望免费发布Pages，选Public；这意味着发布包里的监控代码和数据公开。GitHub Free的Pages支持公开仓库，付费计划也支持私有仓库，见[官方说明](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages)。

不要勾选初始化README，不添加.gitignore或License，点击Create repository。项目已经有README和.gitignore，先建空库可避免两套初始提交冲突。复制HTTPS地址，形如`https://github.com/你的用户名/dividend-bond-monitor.git`。[官方上传流程](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github)。

## 2. 解压到独立文件夹

把`github-monitor.zip`解压到桌面新文件夹`dividend-bond-monitor`，与原研究项目并列。进入直接包含README.md、requirements.txt、monitor、site、data、tests、.github的那一层；若解压工具多套了一层，继续进入内层。

`.github`目录不可漏掉，它包含自动更新工作流。发布包不含research、回测脚本、回测测试、账号凭据或本地工作记录。

在该文件夹空白处右键→在终端中打开，使用PowerShell。

## 3. 建立本地版本并上传

Git已在当前开发机器可用。在解压后的独立目录逐段执行：

```powershell
# 先确认这里是发布包根目录
if (-not (Test-Path -LiteralPath '.\RELEASE_MANIFEST.json')) {
    throw '请进入发布包根目录，勿在原研究目录执行后续命令'
}
git init -b main
git config user.name (Read-Host '填写GitHub用户名')
git config user.email (Read-Host '填写GitHub提交邮箱，可用GitHub提供的noreply邮箱')
git add .
git status --short
```

这些命令依次初始化本地仓库、设置本仓库的提交署名、选择待提交文件、显示清单。确认清单只有监控内容后继续：

```powershell
git commit -m 'Initial daily spread monitor'
$MonitorRepoUrl = Read-Host '粘贴刚创建的GitHub仓库HTTPS地址'
git remote add origin $MonitorRepoUrl
git push -u origin main
```

`commit`保存本地版本，`remote`关联远程仓库，`push`才上传。首次推送可能由Git Credential Manager打开浏览器登录GitHub，按提示完成。不要把密码或Token发到聊天里；GitHub账户密码不能用作Git HTTPS密码。提交邮箱可在GitHub个人Settings→Emails中找到，使用noreply邮箱可避免公开个人邮箱。

成功后刷新仓库Code页，应直接看到README、monitor、site、data和.github，而不是只有ZIP或多套一层项目目录。认证问题可参考[GitHub HTTPS凭据说明](https://docs.github.com/en/get-started/git-basics/caching-your-github-credentials-in-git)。

## 4. 开启网站

仓库Settings→Pages→Build and deployment→Source，选**GitHub Actions**。项目已经带工作流，不需要点击GitHub建议的另一个Jekyll/Hugo模板。[官方Pages设置](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site)。

再到Settings→Secrets and variables→Actions→**Variables**→New repository variable：

| Name | Value |
|---|---|
| ENABLE_PAGES | true |

这是普通仓库变量，不是Secret，值用小写`true`。[官方变量设置](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-variables)。

工作流已声明数据写入的`contents: write`以及部署的`pages: write`、`id-token: write`，通常无需额外添加Token。若Actions被账户/组织策略禁用，先在Settings→Actions→General启用；若bot推送403，检查写入权限与main分支保护。不要自行新建PAT替代默认GITHUB_TOKEN。

## 5. 手动跑一次，确认真实上线

仓库Actions→左侧**Daily data and Pages**→Run workflow，选择main，首次勾选bootstrap，然后Run workflow。

首次push只测试和构建随包已有数据；这次手动运行才会实际请求数据源。bootstrap允许在盘中或休市时取最近已收盘日，不代表取未完成的当天数据。

成功应依次看到：

1. Verify data logic before collection通过。
2. Collect public data成功，状态日期正确。
3. Commit validated observations and status按需产生机器人提交；数据没变化时没有新提交也正常。
4. Build、Frontend检查成功。
5. deploy任务成功，输出网站链接。

网址通常是`https://你的用户名.github.io/dividend-bond-monitor/`，以deploy输出或Settings→Pages显示的链接为准。打开后核对指数、数据日期和健康提示；工作流绿色与数据新鲜度要一起看。

采集失败时历史仍保留，网页可能正常发布并显示过期；health任务会标红。这不等于部署文件丢失，应看Collect日志和`data/status.json`。从本机访问成功也不能保证GitHub服务器每次可访问中国数据源，首次运行就是必要的真实环境验证。

## 6. 以后怎样维护

工作流已配置北京时间19:05、20:10、21:10，每个周一到周五触发，代码再过滤A股节假日。GitHub调度可能延迟或漏跑，必要时用Run workflow补跑。[官方调度说明](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)。公开仓库60天没有活动时定时任务可能自动停用，留意通知并在Actions重新启用。[停用与启用说明](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows)。

以后只在这个独立的发布目录更新监控代码。远程每天会有数据提交，本地修改前先在干净工作区执行`git pull --ff-only`；再修改、提交、推送。若出现冲突或无法快进，保留报错排查，不强推覆盖远程历史。

本地研究目录仍保留所有回测，发布目录独立维护。`site/data/`由Actions构建，不需要手工上传网页数据文件。关闭ENABLE_PAGES只停止后续网站部署，不会删除已发布网站；需要暂停采集则在Actions禁用整个工作流。
