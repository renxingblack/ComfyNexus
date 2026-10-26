import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Clock, ExternalLink, RefreshCw, ChevronRight, Github } from 'lucide-react'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { cn } from '@/lib/utils'
import {
  fetchReleases,
  formatReleaseDate,
  GitHubRelease,
} from '@/api/githubApi'
import { MarkdownRenderer } from '@/components/ai/MarkdownRenderer'
import { ScrollArea } from '@/components/ui/scroll-area'

// 两个 Releases 页面链接（需求：查看原项目 / 当前项目）
const ORIGINAL_REPO_RELEASES = 'https://github.com/Allen-xxa/ComfyNexus/releases'
const CURRENT_REPO_RELEASES = 'https://github.com/renxingblack/ComfyNexus/releases'

interface ChangelogSectionProps {
  className?: string
}

export function ChangelogSection({ className }: ChangelogSectionProps) {
  const { t } = useTranslation()
  const [releases, setReleases] = useState<GitHubRelease[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<Error | null>(null)
  // 各版本默认全部展开（需求：各类标题不折叠、默认全部展开）
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const loadReleases = async () => {
    setIsLoading(true)
    setError(null)
    try {
      // 本地 version.json 立刻出结果；远端在后台补增量，到了再刷新。
      // 不能先等远端：api.github.com 不可达时后端要等 15s 超时，
      // 用户会以为「更新日志没了」（本轮实测的真实问题）。
      const data = await fetchReleases((incremental) => {
        setReleases(incremental)
      })
      setReleases(data)
      // 默认展开全部版本（当前版本 + 自有历史 + 原仓库历史）
      setExpanded(new Set(data.map((r) => r.tag_name)))
    } catch (err) {
      setError(err instanceof Error ? err : new Error('Unknown error'))
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    loadReleases()
  }, [])

  const toggle = (tagName: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(tagName)) next.delete(tagName)
      else next.add(tagName)
      return next
    })
  }

  const renderLoading = () => (
    <div className="flex items-center justify-center py-8">
      <RefreshCw className="size-5 animate-spin text-muted-foreground" />
      <span className="ml-2 text-sm text-muted-foreground">
        {t('about.changelog.loading')}
      </span>
    </div>
  )

  const renderError = () => (
    <div className="flex flex-col items-center justify-center gap-3 py-8">
      <p className="text-sm text-muted-foreground">{t('about.changelog.error')}</p>
      <Button variant="outline" size="sm" onClick={loadReleases}>
        <RefreshCw className="mr-2 size-4" />
        {t('about.changelog.retry')}
      </Button>
    </div>
  )

  const renderEmpty = () => (
    <div className="flex items-center justify-center py-8">
      <p className="text-sm text-muted-foreground">{t('about.changelog.noData')}</p>
    </div>
  )

  const renderReleases = () => (
    // 版块内独立上下滚动：不撑高整页，铺满当前窗口剩余空间即可
    <ScrollArea className="h-full pr-3">
      <div className="space-y-3">
        {releases.map((release, index) => {
          const isExpanded = expanded.has(release.tag_name)
          const isLatest = index === 0
          // 当前版本（fetchReleases 已排第一）用正常字号，历史版本压字号
          const mdClass = isLatest
            ? 'changelog-markdown'
            : 'changelog-markdown changelog-history'

          return (
            <div
              key={release.id}
              className={cn(
                'rounded-lg border border-border',
                isLatest ? 'bg-primary/5' : 'bg-background'
              )}
            >
              <button
                type="button"
                onClick={() => toggle(release.tag_name)}
                className="flex w-full items-center justify-between gap-2 px-4 py-3 text-left hover:bg-muted/40"
              >
                <div className="flex min-w-0 items-center gap-2">
                  <ChevronRight
                    className={cn(
                      'size-4 shrink-0 text-muted-foreground transition-transform duration-200',
                      isExpanded && 'rotate-90'
                    )}
                  />
                  <span className="truncate font-semibold text-foreground">
                    {release.name || release.tag_name}
                  </span>
                  {isLatest && (
                    <span className="shrink-0 rounded-full bg-primary px-2 py-0.5 text-xs font-medium text-primary-foreground">
                      {t('about.changelog.latest')}
                    </span>
                  )}
                </div>
                <span className="shrink-0 text-xs text-muted-foreground">
                  {formatReleaseDate(release.published_at)}
                </span>
              </button>

              {isExpanded && (
                <div className="border-t border-border px-4 pb-4 pt-0">
                  <div className="mt-3 text-sm">
                    <MarkdownRenderer
                      content={release.body || ''}
                      className={mdClass}
                    />
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </ScrollArea>
  )

  return (
    /*
      高度策略：**组件内不写死高度**，完全由调用方通过 className 决定。
      原因：Tailwind 里 h-full 与 h-[420px] 是同一属性的冲突类，
      最终谁生效取决于生成 CSS 的先后顺序，而不取决于 JSX 里 className 的书写顺序
      （cn() 只是字符串拼接）。曾经想「让 className 覆盖 h-full」，那是错的。
      现在默认不带高度类，about 页在两种布局下各自显式给高度即可。

      内部链路保持不变：Card(flex-col) → 中部 div(min-h-0 flex-1) → ScrollArea(h-full)，
      只要外层有确定高度，中间区就会撑满并把滚动交给 ScrollArea。
    */
    <Card className={cn('flex flex-col p-5', className)}>
      <h2 className="flex shrink-0 items-center gap-2 text-base font-semibold text-foreground">
        <Clock className="size-4 text-primary" />
        {t('about.changelog.title')}
      </h2>

      <div className="mt-3 min-h-0 flex-1">
        {isLoading && renderLoading()}
        {!isLoading && error && renderError()}
        {!isLoading && !error && releases.length === 0 && renderEmpty()}
        {!isLoading && !error && releases.length > 0 && renderReleases()}
      </div>

      {/* 两个独立链接按钮：原项目日志 / 当前项目日志 */}
      <div className="mt-3 flex shrink-0 flex-wrap items-center gap-3 border-t border-border/50 pt-3">
        <a
          href={ORIGINAL_REPO_RELEASES}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-xs text-primary transition-colors hover:text-primary/80"
        >
          <Github className="size-3.5" />
          {t('about.viewOriginalLog')}
          <ExternalLink className="size-3" />
        </a>
        <a
          href={CURRENT_REPO_RELEASES}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-xs text-primary transition-colors hover:text-primary/80"
        >
          <Github className="size-3.5" />
          {t('about.viewCurrentLog')}
          <ExternalLink className="size-3" />
        </a>
      </div>
    </Card>
  )
}

export default ChangelogSection
