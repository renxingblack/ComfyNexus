/**
 * 更新日志弹窗组件
 * 
 * 功能：
 * - 首次打开或版本更新后首次打开自动弹出
 * - 显示最近3个版本的更新日志
 * - 支持 Markdown 格式渲染
 * - 从 GitHub Releases 获取数据
 */

import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/Button'
import { Loading } from '@/components/ui/Loading'
import { MarkdownRenderer } from '@/components/ai/MarkdownRenderer'
import { fetchReleases, normalizeTag, GitHubRelease, formatReleaseDate } from '@/api/githubApi'
import { ScrollArea } from '@/components/ui/scroll-area'
import { ChevronRight, ExternalLink, RefreshCw } from 'lucide-react'
import { GITHUB_RELEASES_URL } from '@/api/githubApi'

interface ChangelogDialogProps {
  open: boolean
  onClose: () => void
  currentVersion: string
  onVersionRecorded: (version: string) => void
}

/**
 * 单条 Release 的正文
 *
 * 日志较长时（当前版本内联了原作者 31 个历史版本，约 47KB）：
 * - 第一个章节（本版更新）默认渲染；
 * - 其余章节折叠，点击标题才渲染。
 * 这样首屏只解析一小段 Markdown，弹窗打开瞬间不卡。
 */
function ReleaseBody({
  body,
  emptyText,
  splitSections,
  alwaysFull = false,
  historyStyle = false,
}: {
  body: string
  emptyText: string
  splitSections: (body: string) => { title: string; content: string }[]
  /** true = 整段一次性渲染，不做章节折叠（用于「当前版本」，用户要看完整内容） */
  alwaysFull?: boolean
  /** true = 按「历史版本」样式渲染（压字号）。历史版本正文是原作者原文，自带多个 H1 */
  historyStyle?: boolean
}) {
  const sections = splitSections(body)
  const [opened, setOpened] = useState<Set<number>>(() => new Set(sections.map((_, i) => i)))
  const mdClass = historyStyle
    ? 'changelog-markdown changelog-history'
    : 'changelog-markdown'

  if (!body.trim()) {
    return <p className="italic text-muted-foreground">{emptyText}</p>
  }

  // 当前版本：完整渲染。
  // 之前的实现把 1.3.0 的日志按 H2 切成十几片、只展开第 0 片，
  // 用户点开「更新日志」只看到「新增功能」一小段，误以为详细日志没显示。
  //
  // 现在 fetchReleases 已经把「本版日志」和「历史版本」拆成了独立条目，
  // 这里拿到的 body 就是纯粹的当前版本内容，直接整段渲染即可。
  if (alwaysFull) {
    // 兼容：万一 body 里仍带历史段（例如远端 Release 自己写了整篇），
    // 仍然按「本版 + 历史」两段渲染，并给历史段压字号。
    const marker = '## 📜 历史版本'
    const at = body.indexOf(marker)
    if (at > 0) {
      const head = body.slice(0, at)
      const rest = body.slice(at)
      return (
        <div>
          <MarkdownRenderer content={head} className="changelog-markdown" />
          <MarkdownRenderer content={rest} className="changelog-markdown changelog-history" />
        </div>
      )
    }
    return <MarkdownRenderer content={body} className={mdClass} />
  }

  // 章节很少（如远端那几条短日志）时不必折叠，直接整段渲染
  if (sections.length <= 3) {
    return <MarkdownRenderer content={body} className={mdClass} />
  }

  const toggle = (idx: number) => {
    setOpened((prev) => {
      const next = new Set(prev)
      if (next.has(idx)) next.delete(idx)
      else next.add(idx)
      return next
    })
  }

  return (
    <div className="space-y-2">
      {sections.map((sec, idx) => {
        const isOpen = opened.has(idx)
        const isIntro = sec.title === '__intro__'
        return (
          <div key={`${sec.title}-${idx}`} className="rounded-md border border-border/60">
            {!isIntro && (
              <button
                type="button"
                onClick={() => toggle(idx)}
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-[13px] font-medium text-foreground hover:bg-muted/40"
              >
                <ChevronRight
                  className={`size-3.5 shrink-0 text-muted-foreground transition-transform duration-200 ${
                    isOpen ? 'rotate-90' : ''
                  }`}
                />
                <span className="truncate">{sec.title}</span>
              </button>
            )}
            {(isOpen || isIntro) && (
              <div className={isIntro ? 'px-3 py-2' : 'border-t border-border/60 px-3 py-2'}>
                <MarkdownRenderer content={sec.content} className={mdClass} />
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

export function ChangelogDialog({
  open,
  onClose,
  currentVersion,
  onVersionRecorded
}: ChangelogDialogProps) {
  const { t } = useTranslation()
  const [releases, setReleases] = useState<GitHubRelease[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [expandedReleases, setExpandedReleases] = useState<Set<string>>(new Set())

  const pick = (data: GitHubRelease[]): GitHubRelease[] => {
    const curKey0 = normalizeTag(currentVersion)
    const seen = new Set<string>()
    const picked: GitHubRelease[] = []
    for (const rel of data) {
      const key = normalizeTag(rel.tag_name)
      if (seen.has(key)) continue
      seen.add(key)
      picked.push(rel)
    }
    picked.sort((a, b) => {
      const aCur = normalizeTag(a.tag_name) === curKey0 ? 0 : 1
      const bCur = normalizeTag(b.tag_name) === curKey0 ? 0 : 1
      return aCur - bCur
    })
    return picked
  }

  const fetchChangelog = async () => {
    setLoading(true)
    setError(null)
    try {
      // 本地 version.json 立刻出结果；远端增量到了再刷新。
      // 先等远端的话，api.github.com 不可达时后端要等 15s 超时，
      // 弹窗会一直转圈（本轮实测的真实问题）。
      const data = await fetchReleases((incremental) => {
        setReleases(pick(incremental))
      })
      // 展示策略（本轮重写）：
      // 1) 列表已由 fetchReleases 合并完成：本地 version.json 是权威源，
      //    当前版本详细日志 + 原作者全部历史版本都已包含在内；
      // 2) **不再 slice(0, N) 截断** —— 用户明确要求
      //    「原仓库从第一个版本到 1.2.6 的所有历史更新记录都要显示」，
      //    截断正是历史记录丢失的直接原因；
      // 3) 版本号归一化去重，避免 "1.3.0" 与 "v1.3.0" 同时出现；
      // 4) 当前版本排第一并默认展开；历史版本默认**收起**，
      //    否则 31 个版本的正文全部展开，弹窗一打开就是几屏内容。
      const picked = pick(data)
      const curKey = normalizeTag(currentVersion)

      setReleases(picked)
      // 只展开「当前版本」；历史版本收起，点标题再展开
      setExpandedReleases(
        new Set(picked.filter((r) => normalizeTag(r.tag_name) === curKey).map((r) => r.tag_name))
      )
    } catch (err) {
      console.error('[ChangelogDialog] 获取更新日志失败:', err)
      setError(t('about.changelog.error'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (open) {
      fetchChangelog()
    }
  }, [open])

  const handleOpenChange = (open: boolean) => {
    if (!open) {
      onVersionRecorded(currentVersion)
      onClose()
    }
  }

  const toggleRelease = (tagName: string) => {
    setExpandedReleases(prev => {
      const newSet = new Set(prev)
      if (newSet.has(tagName)) {
        newSet.delete(tagName)
      } else {
        newSet.add(tagName)
      }
      return newSet
    })
  }

  const openExternal = (url: string) => {
    window.open(url, '_blank', 'noopener,noreferrer')
  }

  /**
   * 把一条 Release 正文按 H1/H2 切片
   *
   * 当前版本的日志约 47KB（含原作者 31 个历史版本），一次性交给
   * react-markdown + rehype-highlight 解析要几百毫秒并产生上万个 DOM 节点，
   * 弹窗会明显卡住。这里按二级标题切成若干片，默认只渲染第一片
   * （本版更新），其余章节点击才展开，首屏渲染量降到 1/8 左右。
   */
  const splitSections = (body: string): { title: string; content: string }[] => {
    const lines = (body || '').split('\n')
    const sections: { title: string; content: string[] }[] = []
    let current: { title: string; content: string[] } | null = null

    for (const line of lines) {
      // 只按一级/二级标题切片，三级标题留在章节内部
      if (/^#{1,2}\s+/.test(line)) {
        if (current) sections.push(current)
        current = { title: line.replace(/^#{1,2}\s+/, '').trim(), content: [line] }
      } else if (current) {
        current.content.push(line)
      } else {
        // 正文出现在第一个标题之前（如版本号 front matter），单独成片
        current = { title: '__intro__', content: [line] }
      }
    }
    if (current) sections.push(current)

    return sections
      .map((s) => ({ title: s.title, content: s.content.join('\n') }))
      .filter((s) => s.content.trim().length > 0)
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="flex flex-col sm:max-h-[80vh] sm:max-w-[680px]">
        <DialogHeader>
          <DialogTitle>{t('changelog.title')}</DialogTitle>
          <DialogDescription>{t('changelog.subtitle', { version: currentVersion })}</DialogDescription>
        </DialogHeader>

        <div className="min-h-0 flex-1">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loading size="lg" text={t('about.changelog.loading')} />
            </div>
          ) : error ? (
            <div className="flex flex-col items-center justify-center gap-4 py-12">
              <p className="text-destructive">{error}</p>
              <Button variant="outline" onClick={fetchChangelog}>
                <RefreshCw className="mr-2 size-4" />
                {t('about.changelog.retry')}
              </Button>
            </div>
          ) : releases.length === 0 ? (
            <div className="flex items-center justify-center py-12">
              <p className="text-muted-foreground">{t('about.changelog.noData')}</p>
            </div>
          ) : (
            <ScrollArea className="h-[400px] pr-4">
              <div className="space-y-4">
                {releases.map((release, index) => {
                  const isExpanded = expandedReleases.has(release.tag_name)
                  const isLatest = index === 0
                  
                  return (
                    <div
                      key={release.id}
                      className={`
                        rounded-lg border border-border
                        ${isLatest ? 'bg-primary/5' : 'bg-background'}
                      `}
                    >
                      <Button
                        onClick={() => toggleRelease(release.tag_name)}
                        variant="ghost"
                        className="w-full justify-between rounded-t-lg p-4 text-left"
                      >
                        <div className="flex items-center gap-3">
                          <ChevronRight
                            className={`
                              size-4 text-muted-foreground transition-transform duration-200
                              ${isExpanded ? 'rotate-90' : ''}
                            `}
                          />
                          <div>
                            <div className="flex items-center gap-2">
                              <span className="font-semibold text-foreground">
                                {release.name || release.tag_name}
                              </span>
                              {isLatest && (
                                <span className="rounded-full bg-primary px-2 py-0.5 text-xs font-medium text-primary-foreground">
                                  {t('about.changelog.latest')}
                                </span>
                              )}
                              {release.prerelease && (
                                <span className="rounded-full bg-warning/20 px-2 py-0.5 text-xs font-medium text-warning">
                                  {t('about.changelog.beta')}
                                </span>
                              )}
                            </div>
                            <p className="mt-0.5 text-xs text-muted-foreground">
                              {formatReleaseDate(release.published_at)}
                            </p>
                          </div>
                        </div>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={(e) => {
                            e.stopPropagation()
                            openExternal(release.html_url)
                          }}
                          className="shrink-0"
                        >
                          <ExternalLink className="size-4" />
                        </Button>
                      </Button>
                      
                      {isExpanded && (
                        <div className="border-t border-border px-4 pb-4 pt-0">
                          <div className="mt-3 text-sm">
                            <ReleaseBody
                              body={release.body || ''}
                              emptyText={t('update.noReleaseNotes')}
                              splitSections={splitSections}
                              alwaysFull={normalizeTag(release.tag_name) === normalizeTag(currentVersion)}
                              // 历史版本正文来自原作者原文，自带多个 H1，
                              // 需要走 .changelog-history 压字号，否则层级会压过当前版本。
                              historyStyle={normalizeTag(release.tag_name) !== normalizeTag(currentVersion)}
                            />
                          </div>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </ScrollArea>
          )}
        </div>

        <div className="mt-6 flex items-center justify-between border-t border-border pt-4">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => openExternal(GITHUB_RELEASES_URL)}
            className="text-muted-foreground"
          >
            <ExternalLink className="mr-2 size-4" />
            {t('about.viewFullLog')}
          </Button>
          <Button onClick={() => handleOpenChange(false)}>
            {t('common.close')}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

export default ChangelogDialog
