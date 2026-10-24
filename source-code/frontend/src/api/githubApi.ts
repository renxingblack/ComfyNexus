export interface GitHubRelease {
  id: number
  tag_name: string
  name: string
  body: string
  published_at: string
  html_url: string
  prerelease: boolean
  draft: boolean
}

/**
 * 读取打包内置的本地更新日志（version.json，由后端从 _internal 解析）
 */
async function getLocalChangelog(): Promise<GitHubRelease | null> {
  try {
    const res = await window.pywebview.api.get_local_changelog()
    if (!res?.success || !res.version) return null
    return {
      id: -1,
      tag_name: res.version,
      name: `ComfyNexus ${res.version}`,
      body: res.release_notes || '',
      published_at: res.published_at || new Date().toISOString(),
      html_url: GITHUB_RELEASES_URL,
      prerelease: false,
      draft: false
    }
  } catch (e) {
    console.warn('[githubApi] 读取本地更新日志失败:', e)
    return null
  }
}

/** 版本号归一：去掉前导 v、忽略大小写、去掉空白，便于跨源比较 */
export function normalizeTag(tag: string | undefined | null): string {
  return (tag || '').trim().toLowerCase().replace(/^v/, '')
}

/**
 * 把「本地版本的整篇日志」拆成多条虚拟 Release
 *
 * 为什么需要拆：应用的 `version.json` 里，`release_notes` 是**一整篇**
 * 文档 —— 顶部是当前版本（v1.3.0）的完整日志，下面接
 * `## 📜 历史版本` 章节，里面用 `**v1.2.6 · 日期**` 这样的粗体行分隔
 * 原作者 31 个版本的原文。
 *
 * 弹窗要的是「一条版本一张卡片」。若不拆，用户只会看到一整块墙，
 * 既没有版本列表，也无法单独收起某个历史版本。所以这里把它还原成
 * 多条 Release，让「历史版本」也变成可折叠的独立条目。
 *
 * 若日志里没有历史段（只有当前版本），就原样返回一条。
 */
export function splitLocalChangelog(
  version: string,
  notes: string,
  publishedAt: string,
  htmlUrl: string
): GitHubRelease[] {
  const body = notes || ''
  const marker = '## 📜 历史版本'
  const at = body.indexOf(marker)

  // 没有历史段：整篇就是当前版本
  if (at < 0) {
    return [
      {
        id: -1,
        tag_name: version,
        name: `ComfyNexus ${version}`,
        body,
        published_at: publishedAt,
        html_url: htmlUrl,
        prerelease: false,
        draft: false,
      },
    ]
  }

  const head = body.slice(0, at).trim()
  const history = body.slice(at)

  const out: GitHubRelease[] = [
    {
      id: -1,
      tag_name: version,
      name: `ComfyNexus ${version}`,
      body: head,
      published_at: publishedAt,
      html_url: htmlUrl,
      prerelease: false,
      draft: false,
    },
  ]

  // 按 `**vX.Y.Z · 日期**` 切分历史段。
  //
  // 两个必须避开的坑（原文里真实存在）：
  //   1. 有一条版本号只写了 `**RC · 2026-02-01**`（没有数字），
  //      正则若要求 `RC` 后必须跟数字，这一条会被吞掉 → 历史少一个版本。
  //   2. 还有 `**首页重构**`、`**Q: 如何退出全屏？**` 这类小标题/FAQ，
  //      它们也是整行粗体，但**没有日期**，绝不能当成版本。
  //
  // 判据：整行粗体 + 含 `· 日期`。用「日期」把版本行和普通粗体彻底分开。
  const re = /^\*\*(.+?)\s*·\s*(\d{4}-\d{2}-\d{2})\*\*\s*$/
  const lines = history.split('\n')
  let curTag = ''
  let curDate = ''
  let curLines: string[] = []
  let idx = 1000
  const flush = () => {
    const text = curLines.join('\n').trim()
    if (curTag && text) {
      out.push({
        id: idx++,
        tag_name: curTag,
        name: `ComfyNexus ${curTag}`,
        body: text,
        published_at: curDate || '',
        html_url: htmlUrl,
        prerelease: false,
        draft: false,
      })
    }
    curTag = ''
    curDate = ''
    curLines = []
  }

  for (const line of lines) {
    const m = line.match(re)
    if (m) {
      flush()
      curTag = m[1].trim()
      curDate = m[2]
      continue
    }
    if (curTag) curLines.push(line)
  }
  flush()

  return out
}

/**
 * 把「本地日志」与「远端 Releases」增量合并
 *
 * 语义（用户明确要求）：**在保存的原仓库日志基础上，不断增量保存日志**。
 *   - 本地 version.json 是权威源：随包发布、离线可读、不受远端写错影响；
 *   - 远端只作增量：本地没有的版本补进来；远端正文更长时才覆盖正文；
 *   - 远端删掉的版本**不删本地**（否则历史会莫名消失）。
 */
export function mergeReleases(
  localList: GitHubRelease[],
  remote: GitHubRelease[]
): GitHubRelease[] {
  // 用归一化 tag 建索引，解决 "1.3.0" vs "v1.3.0" 的重复问题
  const merged: GitHubRelease[] = []
  const index = new Map<string, number>()

  const push = (rel: GitHubRelease) => {
    const key = normalizeTag(rel.tag_name)
    const found = index.get(key)
    if (found === undefined) {
      index.set(key, merged.length)
      merged.push(rel)
    } else {
      // 同一版本出现两次：保留正文更完整的那个
      const exist = merged[found]
      if ((rel.body || '').length > (exist.body || '').length) {
        merged[found] = { ...rel }
      }
    }
  }

  // 本地条目优先入表（保证本地版本排版/顺序稳定）
  for (const rel of localList) push(rel)
  // 远端增量补充
  for (const rel of remote) push(rel)

  // 当前版本必须排第一，其余保持「本地历史 → 远端补充」的顺序
  if (localList.length > 0) {
    const curKey = normalizeTag(localList[0].tag_name)
    merged.sort((a, b) => {
      const aCur = normalizeTag(a.tag_name) === curKey ? 0 : 1
      const bCur = normalizeTag(b.tag_name) === curKey ? 0 : 1
      return aCur - bCur
    })
  }

  return merged
}

/** 拉取远端 Releases；任何失败（离线 / 超时 / 风控）都返回 null，不抛异常 */
async function fetchRemoteReleases(): Promise<GitHubRelease[] | null> {
  try {
    const result = await window.pywebview.api.get_github_releases()
    if (!result?.success || !result.releases) return null
    return (result.releases as GitHubRelease[]).filter(r => !r.draft)
  } catch (e) {
    console.warn('[githubApi] 拉取远端 Releases 失败（保留本地日志）:', e)
    return null
  }
}

/**
 * 读取更新日志（本地优先 + 远端后台增量）
 *
 * **为什么不能「先等远端、失败了再用本地兜底」**（本轮实测踩到的真实问题）：
 *   原实现是 `await get_github_releases()` → 失败才读本地。
 *   而 `api.github.com` 在部分网络下根本连不通，后端 `timeout=15`，
 *   于是「关于 → 更新日志」会先转 15 秒圈才显示内容 ——
 *   用户看到的是「日志没了」，实际只是被网络卡住。
 *   本应用的设计前提是「本地 version.json 是权威源、离线也要看得全」，
 *   所以正确顺序是：**本地立刻渲染 → 远端在后台补增量 → 有新增再刷新**。
 *
 * @param onIncrement 远端增量到达时的回调（可用来刷新已渲染的列表）。
 *                    不传则完全不等远端，纯本地渲染。
 */
export async function fetchReleases(
  onIncrement?: (list: GitHubRelease[]) => void
): Promise<GitHubRelease[]> {
  const local = await getLocalChangelog()
  const localList =
    local && (local.body || '').trim()
      ? splitLocalChangelog(
          local.tag_name, local.body, local.published_at, local.html_url
        )
      : null

  // 本地有日志：立刻返回，网络只在后台补增量
  if (localList) {
    if (onIncrement) {
      fetchRemoteReleases().then((remote) => {
        if (!remote || remote.length === 0) return
        const merged = mergeReleases(localList, remote)
        // 只有真的「增量」了才刷新，避免无意义重渲染
        const grew = merged.length > localList.length
        const richer = merged.some((m, i) =>
          (m.body || '').length > (localList[i]?.body || '').length)
        if (grew || richer) onIncrement(merged)
      }).catch(() => {})
    }
    return localList
  }

  // 本地完全没有日志（极少数：version.json 缺失）→ 只能等远端
  const remote = await fetchRemoteReleases()
  if (remote) return remote
  throw new Error('获取 GitHub Releases 失败')
}

export function parseReleaseBody(body: string): string[] {
  const lines = body.split('\n')
  const changes: string[] = []
  
  for (const line of lines) {
    const trimmed = line.trim()
    if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
      const change = trimmed.substring(2).trim()
      if (change) {
        changes.push(change)
      }
    }
  }
  
  return changes.slice(0, 5)
}

export function formatReleaseDate(dateString: string): string {
  const date = new Date(dateString)
  return date.toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  })
}

export const GITHUB_RELEASES_URL = 'https://github.com/renxingblack/ComfyNexus/releases'
