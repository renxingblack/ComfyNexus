/**
 * 模型管理 - 单个模型的网络链接关联弹窗
 *
 * 打开时按默认源（魔搭优先/ HF）搜索候选链接供直接选择；
 * 也可以手动输入任意 http(s) 链接；已有关联可一键移除。
 */

import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from '@/utils/toast'
import { bridgeService } from '@/services/bridge'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Link2, Loader2, Trash2, ExternalLink, CheckCircle2 } from 'lucide-react'
import { formatFileSize } from '@/utils/fileReader'
import { cn } from '@/lib/utils'

export interface ModelLinkTarget {
  id: string
  filename: string
  linkUrl?: string
  linkSource?: string
  linkManual?: boolean
}

interface LinkCandidate {
  repoId: string
  repoName: string
  source: string
  downloads?: number
  url: string
  pageUrl?: string
  filePath?: string
  size?: number
}

interface ModelLinkDialogProps {
  model: ModelLinkTarget | null
  onClose: () => void
  /** 关联保存/移除成功后回调（页面刷新列表里的链接标记） */
  onSaved?: () => void
}

const SOURCE_BADGES: Record<string, { label: string; cls: string }> = {
  modelscope: { label: 'ModelScope', cls: 'bg-purple-500/10 text-purple-600 dark:text-purple-400' },
  huggingface: { label: 'HuggingFace', cls: 'bg-amber-500/10 text-amber-600 dark:text-amber-400' },
}

export function ModelLinkDialog({ model, onClose, onSaved }: ModelLinkDialogProps) {
  const { t } = useTranslation()
  const [candidates, setCandidates] = useState<LinkCandidate[]>([])
  const [loading, setLoading] = useState(false)
  const [searchError, setSearchError] = useState('')
  const [selectedUrl, setSelectedUrl] = useState('')
  const [manualUrl, setManualUrl] = useState('')
  const [saving, setSaving] = useState(false)
  const [currentLink, setCurrentLink] = useState<{ url: string; source: string; manual?: boolean } | null>(null)

  const open = model !== null

  useEffect(() => {
    if (!model) return
    setSelectedUrl('')
    setManualUrl('')
    setSearchError('')
    setCandidates([])
    setCurrentLink(
      model.linkUrl
        ? { url: model.linkUrl, source: model.linkSource || '', manual: model.linkManual }
        : null
    )

    let cancelled = false
    const run = async () => {
      setLoading(true)
      try {
        const res = await bridgeService.modelGetLinkCandidates(model.filename)
        if (cancelled) return
        if (res.success) {
          setCandidates(res.candidates || [])
          // 默认选中第一个候选（用户可直接保存）
          if (res.candidates && res.candidates.length > 0) {
            setSelectedUrl(res.candidates[0].url)
          }
        } else {
          setSearchError(res.error_message || t('modelLib.linkSearchFail'))
        }
      } catch (e) {
        if (!cancelled) setSearchError(e instanceof Error ? e.message : String(e))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    run()
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [model?.id])

  const handleSave = async () => {
    if (!model) return
    const url = manualUrl.trim() || selectedUrl
    if (!url) {
      toast.error(t('modelLib.linkUrlRequired'))
      return
    }
    setSaving(true)
    try {
      const cand = candidates.find((c) => c.url === url)
      const res = await bridgeService.modelSetLink(
        model.id, url, cand?.source || '', cand?.repoId || ''
      )
      if (!res.success) throw new Error(res.error_message || t('modelLib.linkSaveFail'))
      toast.success(t('modelLib.linkSaved'))
      onSaved?.()
      onClose()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  const handleRemove = async () => {
    if (!model) return
    setSaving(true)
    try {
      const res = await bridgeService.modelRemoveLink(model.id)
      if (!res.success) throw new Error(res.error_message || t('modelLib.linkRemoveFail'))
      toast.success(t('modelLib.linkRemoved'))
      onSaved?.()
      onClose()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) onClose() }}>
      <DialogContent className="sm:max-w-[560px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Link2 className="size-4" />
            {t('modelLib.linkDialogTitle')}
          </DialogTitle>
        </DialogHeader>

        {model && (
          <div className="space-y-4">
            {/* 目标文件 */}
            <div className="bg-muted/40 rounded-md px-3 py-2">
              <p className="truncate text-sm font-medium" title={model.filename}>{model.filename}</p>
              {currentLink && (
                <p className="mt-1 flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400">
                  <CheckCircle2 className="size-3.5 shrink-0" />
                  <span className="truncate" title={currentLink.url}>
                    {t('modelLib.linkCurrent')} {currentLink.url}
                  </span>
                </p>
              )}
            </div>

            {/* 候选链接 */}
            <div>
              <label className="text-foreground mb-1.5 block text-sm font-medium">
                {t('modelLib.linkCandidates')}
              </label>
              {loading ? (
                <div className="flex items-center justify-center py-6">
                  <Loader2 className="text-primary size-5 animate-spin" />
                  <span className="text-muted-foreground ml-2 text-xs">
                    {t('modelLib.linkSearching')}
                  </span>
                </div>
              ) : candidates.length === 0 ? (
                <p className="text-muted-foreground rounded-md border border-dashed px-3 py-4 text-center text-xs">
                  {searchError ? `${t('modelLib.linkSearchFail')}: ${searchError}` : t('modelLib.linkNoCandidates')}
                </p>
              ) : (
                <div className="max-h-[260px] space-y-2 overflow-y-auto pr-1">
                  {candidates.map((c) => {
                    const badge = SOURCE_BADGES[c.source] || { label: c.source, cls: 'bg-muted text-muted-foreground' }
                    const active = selectedUrl === c.url && !manualUrl.trim()
                    return (
                      <button
                        key={c.url}
                        type="button"
                        className={cn(
                          'w-full rounded-md border px-3 py-2 text-left transition-colors',
                          active
                            ? 'border-primary bg-primary/5'
                            : 'border-border/60 hover:bg-muted/40'
                        )}
                        onClick={() => { setSelectedUrl(c.url); setManualUrl('') }}
                      >
                        <div className="flex items-center gap-2">
                          <span className={cn('shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium', badge.cls)}>
                            {badge.label}
                          </span>
                          <span className="min-w-0 flex-1 truncate text-xs font-medium" title={c.repoId}>
                            {c.repoName || c.repoId}
                          </span>
                          {typeof c.downloads === 'number' && c.downloads > 0 && (
                            <span className="text-muted-foreground shrink-0 text-[10px] tabular-nums">
                              ↓ {c.downloads >= 10000 ? `${Math.round(c.downloads / 1000)}k` : c.downloads}
                            </span>
                          )}
                        </div>
                        <div className="text-muted-foreground mt-1 flex items-center gap-2 text-[11px]">
                          <span className="min-w-0 flex-1 truncate" title={c.filePath}>
                            {c.filePath}
                          </span>
                          {c.size ? (
                            <span className="shrink-0 tabular-nums">{formatFileSize(c.size)}</span>
                          ) : null}
                          {c.pageUrl && (
                            <span
                              role="button"
                              tabIndex={0}
                              className="text-primary shrink-0 hover:underline"
                              onClick={(e) => { e.stopPropagation(); window.open(c.pageUrl, '_blank') }}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') { e.stopPropagation(); window.open(c.pageUrl, '_blank') }
                              }}
                              title={c.pageUrl}
                            >
                              <ExternalLink className="size-3.5" />
                            </span>
                          )}
                        </div>
                      </button>
                    )
                  })}
                </div>
              )}
            </div>

            {/* 手动输入 */}
            <div>
              <label className="text-foreground mb-1.5 block text-sm font-medium">
                {t('modelLib.linkManualInput')}
              </label>
              <Input
                value={manualUrl}
                onChange={(e) => setManualUrl(e.target.value)}
                placeholder={t('modelLib.linkManualPlaceholder')}
              />
              <p className="text-muted-foreground/70 mt-1 text-xs">{t('modelLib.linkManualHint')}</p>
            </div>

            <div className="flex items-center justify-between gap-2">
              {currentLink ? (
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-destructive hover:text-destructive"
                  onClick={handleRemove}
                  disabled={saving}
                >
                  <Trash2 className="size-4" />
                  {t('modelLib.linkRemove')}
                </Button>
              ) : <span />}
              <div className="flex gap-2">
                <Button variant="outline" onClick={onClose} disabled={saving}>
                  {t('common.cancel')}
                </Button>
                <Button onClick={handleSave} disabled={saving || (!selectedUrl && !manualUrl.trim())}>
                  {saving ? <Loader2 className="size-4 animate-spin" /> : <Link2 className="size-4" />}
                  {t('modelLib.linkSave')}
                </Button>
              </div>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
