import { useState, useCallback, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { RefreshCw, Download, Github, Code2 } from 'lucide-react'
import { toast } from '@/utils/toast'
import { Button } from '@/components/ui/Button'
import { useAppUpdateStore, LocalFileInfo } from '@/stores/useAppUpdateStore'

import { UpdateDialog } from './UpdateDialog'
import { techStackItems } from './TechStackSection'

interface AboutHeaderProps {
  version: string
}

export function AboutHeader({ version }: AboutHeaderProps) {
  const { t } = useTranslation()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [isChecking, setIsChecking] = useState(false)
  const hasAutoOpenedRef = useRef(false)
  const { hasUpdate, hasViewed, setChecking, setHasUpdate, markAsViewed, setLocalFileInfo } = useAppUpdateStore()

  const showBadge = hasUpdate && !hasViewed

  useEffect(() => {
    if (hasUpdate && !hasViewed && !hasAutoOpenedRef.current) {
      hasAutoOpenedRef.current = true
      setDialogOpen(true)
    }
  }, [hasUpdate, hasViewed])

  const handleCheckUpdate = useCallback(async () => {
    if (isChecking) return

    const { updateInfo } = useAppUpdateStore.getState()
    
    if (hasUpdate && updateInfo) {
      setDialogOpen(true)
      return
    }

    setIsChecking(true)
    setChecking(true)

    try {
      const api = (window as any).pywebview?.api
      if (!api) {
        toast.error(t('update.networkError'))
        return
      }

      const result = await api.check_for_update()
      setChecking(false)

      if (!result.success) {
        toast.error(result.error || t('update.updateError'))
        return
      }

      if (result.has_update) {
        setHasUpdate(true, {
          currentVersion: result.current_version,
          latestVersion: result.latest_version,
          downloadUrl: result.download_url,
          releaseNotes: result.release_notes,
          publishedAt: result.published_at,
          fileSize: result.file_size,
          fileHash: result.file_hash
        })
        
        const localResult = await api.check_local_update()
        if (localResult.success) {
          const localInfo: LocalFileInfo = {
            exists: localResult.has_local_file,
            filePath: localResult.file_path,
            hashMatch: localResult.hash_match,
            fileSize: localResult.file_size,
            partialDownload: localResult.partial_download
          }
          setLocalFileInfo(localInfo)
        }
        
        setDialogOpen(true)
      } else {
        setHasUpdate(false, null)
        setLocalFileInfo(null)
        toast.success(t('update.noUpdate'))
      }
    } catch (err) {
      setChecking(false)
      toast.error(err instanceof Error ? err.message : t('update.networkError'))
    } finally {
      setIsChecking(false)
    }
  }, [isChecking, hasUpdate, setChecking, setHasUpdate, setLocalFileInfo, t])

  const handleDialogOpenChange = useCallback((open: boolean) => {
    setDialogOpen(open)
    if (!open && hasUpdate) {
      markAsViewed()
    }
  }, [hasUpdate, markAsViewed])

  return (
    <>
      <header className="border-b border-border pb-4">
        {/* 单行页头：Logo + 标题/版本/副标题 + 项目地址（两行）+ 核心技术栈（自动换行）+ 检查更新（右） */}
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
          <img
            src="/app-icon.png"
            alt="ComfyNexus"
            className="size-14 shrink-0 rounded-xl shadow-lg"
          />

          {/* 标题 + 版本 + 副标题 */}
          <div className="flex shrink-0 flex-col gap-1">
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-bold tracking-wide text-foreground">
                ComfyNexus
              </h1>
              <span className="rounded-full border border-primary/20 bg-primary/10 px-2 py-0.5 font-mono text-xs text-primary">
                {version}
              </span>
            </div>
            <p className="text-sm text-muted-foreground">{t('about.subtitle')}</p>
          </div>

          {/* 项目地址：两行，仅 GitHub 图标 + 文字，点击跳转 */}
          <div className="flex shrink-0 flex-col gap-1">
            <a
              href="https://github.com/Allen-xxa/ComfyNexus"
              target="_blank"
              rel="noopener noreferrer"
              title="https://github.com/Allen-xxa/ComfyNexus"
              className="group inline-flex w-fit items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-primary"
            >
              <Github className="size-3.5 shrink-0 transition-transform group-hover:scale-110" />
              <span className="underline decoration-border underline-offset-2 group-hover:decoration-primary">
                {t('about.originalAuthorRepo')}
              </span>
            </a>
            <a
              href="https://github.com/renxingblack/ComfyNexus"
              target="_blank"
              rel="noopener noreferrer"
              title="https://github.com/renxingblack/ComfyNexus"
              className="group inline-flex w-fit items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-primary"
            >
              <Github className="size-3.5 shrink-0 transition-transform group-hover:scale-110" />
              <span className="underline decoration-border underline-offset-2 group-hover:decoration-primary">
                {t('about.currentRepo')}
              </span>
            </a>
          </div>

          {/* 核心技术栈：标题 + 徽章（放不下自动多行）。
              basis + min-w 是关键：空间不足时整块换行占满一行，
              而不是被 flex-1 压成窄条导致徽章一行一个、页头高度暴涨 */}
          <div className="flex min-w-[280px] flex-1 basis-[340px] flex-col gap-1">
            <span className="flex items-center gap-1 text-[11px] font-medium text-muted-foreground">
              <Code2 className="size-3 text-success" />
              {t('about.techStack.title')}
            </span>
            <div className="flex flex-wrap gap-1.5">
              {techStackItems.map((item) => (
                <span
                  key={item.name}
                  className={`rounded-md border px-2 py-0.5 font-mono text-[11px] leading-5 whitespace-nowrap ${item.bgColor} ${item.borderColor} ${item.textColor}`}
                >
                  {item.name}
                </span>
              ))}
            </div>
          </div>

          {/* 检查更新：靠右，不参与压缩 */}
          <div className="relative ml-auto shrink-0 self-start">
            {hasUpdate ? (
              <Button
                onClick={handleCheckUpdate}
                size="sm"
                className="flex items-center gap-2 bg-success text-success-foreground hover:bg-success/90"
              >
                <Download className="size-4" />
                {t('update.updateNow') || '立即更新'}
              </Button>
            ) : (
              <Button
                onClick={handleCheckUpdate}
                size="sm"
                variant="outline"
                className="flex items-center gap-2"
                disabled={isChecking}
              >
                <RefreshCw className={cn('size-4', isChecking && 'animate-spin')} />
                {isChecking ? t('update.checking') : t('update.checkUpdate')}
              </Button>
            )}
            {showBadge && (
              <span className="absolute -right-1 -top-1 size-2.5 animate-pulse rounded-full border-2 border-background bg-success" />
            )}
          </div>
        </div>
      </header>

      <UpdateDialog
        open={dialogOpen}
        onOpenChange={handleDialogOpenChange}
        currentVersion={version}
      />
    </>
  )
}

function cn(...classes: (string | boolean | undefined)[]) {
  return classes.filter(Boolean).join(' ')
}

export default AboutHeader
