# 如何把本仓库推送到 GitHub

> 当前这台机器无法访问 github.com，所以推送这一步需要你在能上网的电脑上完成。
> 仓库已经初始化好并完成了首次提交，直接推送即可。

## 方法一：网页 + 命令行（最通用）

1. 在 GitHub 网页上点 **New repository**
   - Repository name：`北京交通大学高铁纵横答题脚本`
   - 可见性：建议 **Private**（见下方风险提示）
   - **不要**勾选 Add README / .gitignore / license（避免冲突）
2. 在本目录打开终端，执行：

```bash
git remote add origin https://github.com/<你的用户名>/北京交通大学高铁纵横答题脚本.git
git push -u origin main
```

如果提示要认证，用 GitHub 的 **Personal Access Token** 当密码（Settings → Developer settings → Tokens，勾选 `repo`）。

## 方法二：GitHub CLI（一条命令）

```bash
gh auth login
gh repo create "北京交通大学高铁纵横答题脚本" --private --source=. --push
```

## 方法三：用我打包好的 bundle

本目录外有一个 `北京交通大学高铁纵横答题脚本.bundle`，它包含完整提交历史，可在任意机器上还原：

```bash
git clone 北京交通大学高铁纵横答题脚本.bundle repo
cd repo
git remote set-url origin https://github.com/<你的用户名>/北京交通大学高铁纵横答题脚本.git
git push -u origin main
```

## 关于仓库名

GitHub 支持中文仓库名，但会生成一串百分号编码的 URL，不太好看。
如果介意，可以：

- 仓库名用 `BJTU-HSR-Quiz-Helper`
- 在 Description 里写「北京交通大学高铁纵横答题脚本」

## 建议把绿色版放进 Release

仓库里只有源码，没有那个 19MB 的内置运行时压缩包。
建议在 GitHub 上 **Releases → Draft a new release**，把 `高铁答题助手.zip` 作为附件上传，
这样同学不用装 Python 也能用，仓库本身也能保持轻量。

## ⚠️ 推送前的风险提醒

1. **公开仓库等于公开署名**：项目名里直接写了「北京交通大学」，任何人（包括老师和学校）搜「北交大 高铁纵横 答题」都可能找到。建议先设为 **Private**，只把链接发给信任的同学。
2. **GitHub 会记录提交者信息**：推送时用的账号邮箱会写进提交历史。如果不想关联个人身份，可在本地先设置一个不常用的邮箱：
   ```bash
   git config user.email "noreply@example.com"
   git commit --amend --reset-author --no-edit
   ```
3. **不要提交任何个人信息**：仓库里已排除 `config.json`（账号密码）、`session.json`（登录 token）和考试答卷数据，`.gitignore` 也做了拦截，推送前可以再 `git status` 确认一次。
