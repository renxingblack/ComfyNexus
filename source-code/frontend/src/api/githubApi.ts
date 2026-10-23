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

export async function fetchReleases(): Promise<GitHubRelease[]> {
  // 更新源自动跟随 dev 文件配置（用户 fork 后无需改前端）
  const result = await window.pywebview.api.get_github_releases()

  if (!result.success || !result.releases) {
    // 拉取远端失败时，本地日志兜底，保证当前版本日志始终可见
    const local = await getLocalChangelog()
    if (local) return [local]
    throw new Error(result.message || '获取 GitHub Releases 失败')
  }

  let releases: GitHubRelease[] = result.releases.filter(
    (release: GitHubRelease) => !release.draft
  )

  // 关键兜底：本应用版本（如 v1.3.0）尚未发布到远端 Releases 时
  // （新版本刚打完包、或上游仓库未同步），把内置 version.json 的日志
  // 作为一条合成 Release 插入，保证「软件内更新日志」始终包含当前版本。
  const local = await getLocalChangelog()
  if (local && !releases.some((r) => r.tag_name === local.tag_name)) {
    releases = [local, ...releases]
  }

  return releases
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
