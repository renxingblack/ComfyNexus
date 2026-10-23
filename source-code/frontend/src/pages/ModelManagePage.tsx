/**
 * 模型管理页面
 *
 * 功能：
 * - 本地模型扫描与管理（checkpoints / loras / vae / controlnet 等全部 models 子目录）
 * - 网络模型下载（HuggingFace / HF-Mirror / ModelScope / Civitai / 直链自动识别，
 *   HF 失败自动切换国内镜像重试，支持断点续传）
 *
 * 性能设计（万级模型场景）：
 * - 列表数据一次加载 + 前端过滤（后端全量 stat 扫描很快，缓存防抖落盘）
 * - 卡片网格渐进渲染（IntersectionObserver 追加批次），DOM 数量与总量脱钩
 * - 过滤结果 useMemo 记忆化，输入搜索时不重算全量
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from '@/utils/toast'
import { bridgeService } from '@/services/bridge'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/Select'
import { Progress } from '@/components/ui/progress'
import {
  RefreshCw, Download, Search, PackageOpen, Trash2, X,
  CloudDownload, HardDrive, Loader2, Settings, Link2,
} from 'lucide-react'
import { formatFileSize } from '@/utils/fileReader'
import { cn } from '@/lib/utils'
import { ModelSettingsModal } from '@/components/model/ModelSettingsModal'
import { ModelLinkDialog, ModelLinkTarget } from '@/components/model/ModelLinkDialog'

interface ModelItem extends ModelLinkTarget {
  id: string
  filename: string
  modelType: string
  path: string
  size: number
  modifiedAt: number
}

interface DownloadTaskInfo {
  taskId: string
  filename: string
  modelType: string
  source: string
  status: 'queued' | 'downloading' | 'completed' | 'failed' | 'cancelled'
  error?: string
  downloaded: number
  total: number
  percent: number
  speed: number
}

/** 首屏渲染数与每批追加数（万级渐进渲染，DOM 数与总量脱钩） */
const INITIAL_RENDER_COUNT = 100
const RENDER_BATCH_SIZE = 100

const SOURCE_LABELS: Record<string, string> = {
  huggingface: 'HuggingFace',
  'hf-mirror': 'HF-Mirror (国内镜像)',
  modelscope: 'ModelScope (魔搭)',
  civitai: 'Civitai',
  direct: '直链',
}

export default function ModelManagePage() {
  const { t } = useTranslation()

  // ---------- 数据 ----------
  const [models, setModels] = useState<ModelItem[]>([])
  const [dirLabels, setDirLabels] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(true)
  const [scanning, setScanning] = useState(false)
  const [lastScanTime, setLastScanTime] = useState<number | null>(null)
  const [loadError, setLoadError] = useState('')

  // ---------- 过滤 ----------
  const [searchQuery, setSearchQuery] = useState('')
  const [typeFilter, setTypeFilter] = useState('all')
  const [sortBy, setSortBy] = useState<'name' | 'size' | 'modifiedAt'>('name')

  // ---------- 查看方式 ----------
  const [viewMode, setViewMode] = useState<'list' | 'loose' | 'compact'>('list')

  /** 修改时间格式化（日期 + 时间，便于万级列表定位） */
  const formatDate = (ts: number) => {
    if (!ts) return '—'
    const d = new Date(ts * 1000)
    const pad = (n: number) => String(n).padStart(2, '0')
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
  }

  // ---------- 渐进渲染 ----------
  const [renderCount, setRenderCount] = useState(INITIAL_RENDER_COUNT)
  const sentinelRef = useRef<HTMLDivElement>(null)

  // ---------- 下载 ----------
  const [downloadOpen, setDownloadOpen] = useState(false)
  const [downloadUrl, setDownloadUrl] = useState('')
  const [downloadType, setDownloadType] = useState('checkpoints')
  const [downloadName, setDownloadName] = useState('')
  const [detectedSource, setDetectedSource] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [tasks, setTasks] = useState<DownloadTaskInfo[]>([])

  // ---------- 设置（本地模型文件夹） ----------
  const [settingsOpen, setSettingsOpen] = useState(false)

  // ---------- 网络链接关联 ----------
  const [linkTarget, setLinkTarget] = useState<ModelItem | null>(null)
  const [syncRunning, setSyncRunning] = useState(false)
  const [syncProgress, setSyncProgress] = useState<{
    total: number; done: number; matched: number; current: string
  }>({ total: 0, done: 0, matched: 0, current: '' })

  const handleOpenLink = useCallback((m: ModelItem) => {
    setLinkTarget(m)
  }, [])

  const handleStartLinkSync = async () => {
    try {
      const res = await bridgeService.modelStartLinkSync()
      if (!res.success) {
        toast.error(res.error_message || t('modelLib.linkSyncStartFail'))
        return
      }
      setSyncRunning(true)
      toast.success(t('modelLib.linkSyncStarted'))
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }

  // 同步进度轮询与进入页面时的状态检查，见 loadModels 定义之后

  const handleStopLinkSync = async () => {
    try {
      await bridgeService.modelStopLinkSync()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }

  // ---------- 加载 ----------
  const loadModels = useCallback(async (force = false) => {
    try {
      if (force) setScanning(true)
      else setLoading(true)
      setLoadError('')
      // pywebview 桥接就绪竞态 + 瞬时失败：最多重试 2 次（间隔递增）
      let res: Awaited<ReturnType<typeof bridgeService.modelGetModels>> | null = null
      let lastErr: unknown = null
      for (let attempt = 0; attempt < 3; attempt++) {
        try {
          res = await bridgeService.modelGetModels(force)
          if (res.success) break
          lastErr = new Error(res.error_message || res.error || '获取模型列表失败')
          res = null
        } catch (e) {
          lastErr = e
        }
        if (attempt < 2) {
          await new Promise((r) => setTimeout(r, 400 * (attempt + 1)))
        }
      }
      if (!res) {
        throw lastErr instanceof Error ? lastErr : new Error('获取模型列表失败')
      }
      setModels(res.models || [])
      setDirLabels(res.dirLabels || {})
      setLastScanTime(res.lastScanTime ?? null)
      setScanning(false)
    } catch (e) {
      setScanning(false)
      setLoadError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadModels(false)
  }, [loadModels])

  // ---------- 链接同步进度轮询（运行中 1.2s 一次；结束后刷新列表里的链接标记） ----------
  useEffect(() => {
    if (!syncRunning) return
    let cancelled = false
    let finished = false
    const poll = async () => {
      try {
        const res = await bridgeService.modelGetLinkSyncStatus()
        if (cancelled || !res.success) return
        setSyncProgress({
          total: res.total || 0,
          done: res.done || 0,
          matched: res.matched || 0,
          current: res.current || '',
        })
        if (!res.running) {
          finished = true
          setSyncRunning(false)
          toast.success(t('modelLib.linkSyncDone', {
            matched: res.matched || 0, total: res.total || 0,
          }))
          loadModels(false)
        }
      } catch {
        // 轮询失败静默（下轮重试）
      }
    }
    const timer = setInterval(() => { if (!finished) poll() }, 1200)
    poll()
    return () => { cancelled = true; clearInterval(timer) }
  }, [syncRunning, loadModels, t])

  // 进入页面时检查是否有正在进行的同步（切页回来恢复进度条）
  useEffect(() => {
    bridgeService.modelGetLinkSyncStatus().then((res) => {
      if (res.success && res.running) setSyncRunning(true)
    }).catch(() => { /* 忽略 */ })
  }, [])

  // ---------- 过滤（记忆化） ----------
  const typeCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const m of models) counts[m.modelType] = (counts[m.modelType] || 0) + 1
    return counts
  }, [models])

  const filteredModels = useMemo(() => {
    const q = searchQuery.trim().toLowerCase()
    let list = models
    if (typeFilter !== 'all') list = list.filter((m) => m.modelType === typeFilter)
    if (q) list = list.filter((m) => m.filename.toLowerCase().includes(q))
    const sorted = [...list]
    sorted.sort((a, b) => {
      if (sortBy === 'size') return b.size - a.size
      if (sortBy === 'modifiedAt') return b.modifiedAt - a.modifiedAt
      return a.filename.localeCompare(b.filename)
    })
    return sorted
  }, [models, typeFilter, searchQuery, sortBy])

  const totalSize = useMemo(
    () => filteredModels.reduce((sum, m) => sum + m.size, 0),
    [filteredModels]
  )

  // 过滤条件变化时渲染游标归位
  useEffect(() => {
    setRenderCount(INITIAL_RENDER_COUNT)
  }, [typeFilter, searchQuery, sortBy, models])

  // 滚动到底追加渲染
  useEffect(() => {
    const sentinel = sentinelRef.current
    if (!sentinel || renderCount >= filteredModels.length) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          setRenderCount((prev) => Math.min(prev + RENDER_BATCH_SIZE, filteredModels.length))
        }
      },
      { rootMargin: '600px' }
    )
    observer.observe(sentinel)
    return () => observer.disconnect()
  }, [renderCount, filteredModels.length])

  // ---------- 下载轮询（仅在有活跃任务时开启） ----------
  const activeTasks = tasks.filter((x) => x.status === 'downloading' || x.status === 'queued')

  useEffect(() => {
    let cancelled = false
    let lastCompletedId = ''

    const poll = async () => {
      try {
        const res = await bridgeService.modelGetDownloadStatus()
        if (cancelled || !res.success || !res.tasks) return
        setTasks(res.tasks)
        const finished = res.tasks.find((x) => x.status === 'completed')
        if (finished && finished.taskId !== lastCompletedId) {
          lastCompletedId = finished.taskId
          loadModels(false)
          toast.success(t('modelLib.downloadDone', { name: finished.filename }))
          bridgeService.modelClearFinishedDownloads()
        }
      } catch {
        // 轮询失败静默
      }
    }

    // 有活跃任务时 1s 轮询；空闲时降到 5s（万级数据 CPU 占用治理：不用时几乎零开销）
    const interval = activeTasks.length > 0 ? 1000 : 5000
    const timer = setInterval(poll, interval)
    poll()
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [activeTasks.length, loadModels, t])

  // ---------- 下载对话框 ----------
  useEffect(() => {
    if (!downloadUrl.trim()) {
      setDetectedSource('')
      return
    }
    const id = setTimeout(async () => {
      try {
        const res = await bridgeService.modelDetectSource(downloadUrl.trim())
        setDetectedSource(res.source || '')
        if (res.suggestFilename) {
          setDownloadName((prev) => prev || res.suggestFilename || '')
        }
      } catch {
        setDetectedSource('')
      }
    }, 300)
    return () => clearTimeout(id)
  }, [downloadUrl])

  const handleStartDownload = async () => {
    const url = downloadUrl.trim()
    if (!url) {
      toast.error(t('modelLib.urlRequired'))
      return
    }
    setSubmitting(true)
    try {
      const res = await bridgeService.modelStartDownload(url, downloadType, downloadName.trim())
      if (!res.success) throw new Error(res.error_message || '下载任务创建失败')
      toast.success(t('modelLib.downloadQueued', { source: SOURCE_LABELS[res.source || 'direct'] || res.source }))
      setDownloadOpen(false)
      setDownloadUrl('')
      setDownloadName('')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setSubmitting(false)
    }
  }

  const handleCancelDownload = async (taskId: string) => {
    try {
      await bridgeService.modelCancelDownload(taskId)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }

  const handleDelete = async (m: ModelItem) => {
    if (!window.confirm(t('modelLib.deleteConfirm', { name: m.filename }))) return
    try {
      const res = await bridgeService.modelDelete(m.path)
      if (!res.success) throw new Error(res.error_message || '删除失败')
      setModels((prev) => prev.filter((x) => x.id !== m.id))
      toast.success(t('modelLib.deleteDone'))
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }

  const dirOptions = useMemo(() => {
    // 已有分类 + 常见目录（便于首次下载归类）
    const base = new Set<string>([
      'checkpoints', 'loras', 'vae', 'controlnet', 'upscale_models',
      'text_encoders', 'diffusion_models', 'embeddings', 'clip', 'clip_vision',
    ])
    Object.keys(typeCounts).forEach((k) => base.add(k))
    return Array.from(base).sort()
  }, [typeCounts])

  const typeLabel = useCallback(
    (dir: string) => dirLabels[dir] || dir,
    [dirLabels]
  )

  // ---------- 渲染 ----------

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="size-8 animate-spin text-primary" />
          <p className="text-muted-foreground text-sm">{t('modelLib.loading')}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col overflow-hidden bg-background font-sans text-foreground">
      {/* 页头 */}
      <div className="z-20 shrink-0 border-b border-border/60 bg-surface p-4 pb-3 shadow-sm">
        <div className="mb-3 flex items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <PackageOpen className="text-primary size-5" />
            <h1 className="text-lg font-semibold">{t('modelLib.title')}</h1>
            <span className="text-muted-foreground text-xs">
              {t('modelLib.totalInfo', {
                count: filteredModels.length,
                size: formatFileSize(totalSize),
              })}
            </span>
            {lastScanTime && (
              <span className="text-muted-foreground/70 text-xs">
                {t('modelLib.lastScan', { time: new Date(lastScanTime * 1000).toLocaleString() })}
              </span>
            )}
          </div>

          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={handleStartLinkSync}
              disabled={scanning || syncRunning}
              title={t('modelLib.linkSyncHint')}
            >
              <Link2 className="size-4" />
              {t('modelLib.linkSync')}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => loadModels(true)}
              disabled={scanning}
            >
              {scanning ? <Loader2 className="animate-spin" /> : <RefreshCw className="size-4" />}
              {scanning ? t('modelLib.scanning') : t('modelLib.rescan')}
            </Button>
            <Button size="sm" onClick={() => setDownloadOpen(true)}>
              <Download className="size-4" />
              {t('modelLib.downloadModel')}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setSettingsOpen(true)}
              title={t("common.title.modelSettings")}
            >
              <Settings className="size-4" />
            </Button>
          </div>
        </div>

        {loadError && (
          <div className="mb-3 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {loadError}
          </div>
        )}

        {/* 活跃下载任务条 */}
        {activeTasks.length > 0 && (
          <div className="mb-3 space-y-2">
            {activeTasks.map((task) => (
              <div key={task.taskId} className="flex items-center gap-3 rounded-md border bg-background px-3 py-2">
                <CloudDownload className="text-primary size-4 shrink-0" />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2 text-xs">
                    <span className="truncate font-medium">{task.filename}</span>
                    <span className="text-muted-foreground shrink-0">
                      {task.percent}%
                      {task.speed > 0 && ` · ${formatFileSize(task.speed)}/s`}
                    </span>
                  </div>
                  <Progress value={task.percent} className="mt-1 h-1.5" />
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-7 shrink-0"
                  onClick={() => handleCancelDownload(task.taskId)}
                >
                  <X className="size-4" />
                </Button>
              </div>
            ))}
          </div>
        )}

        {/* 链接同步进度条 */}
        {syncRunning && (
          <div className="mb-3 flex items-center gap-3 rounded-md border bg-background px-3 py-2">
            <Loader2 className="text-primary size-4 shrink-0 animate-spin" />
            <div className="min-w-0 flex-1">
              <div className="flex items-center justify-between gap-2 text-xs">
                <span className="truncate font-medium" title={syncProgress.current}>
                  {syncProgress.current || t('modelLib.linkSyncPreparing')}
                </span>
                <span className="text-muted-foreground shrink-0 tabular-nums">
                  {t('modelLib.linkSyncProgress', {
                    done: syncProgress.done, total: syncProgress.total, matched: syncProgress.matched,
                  })}
                </span>
              </div>
              <Progress
                value={syncProgress.total > 0 ? Math.round((syncProgress.done / syncProgress.total) * 100) : 0}
                className="mt-1 h-1.5"
              />
            </div>
            <Button
              variant="ghost"
              size="icon"
              className="size-7 shrink-0"
              onClick={handleStopLinkSync}
              title={t('modelLib.linkSyncStop')}
            >
              <X className="size-4" />
            </Button>
          </div>
        )}

        {/* 搜索 + 过滤 */}
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-[220px] flex-1">
            <Search className="text-muted-foreground absolute left-2.5 top-1/2 size-4 -translate-y-1/2" />
            <Input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder={t('modelLib.searchPlaceholder')}
              className="pl-8"
            />
          </div>
          <Select value={typeFilter} onValueChange={setTypeFilter}>
            <SelectTrigger className="w-[200px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">
                {t('modelLib.allTypes', { count: models.length })}
              </SelectItem>
              {Object.keys(typeCounts).sort().map((dir) => (
                <SelectItem key={dir} value={dir}>
                  {typeLabel(dir)} ({typeCounts[dir]})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={sortBy} onValueChange={(v) => setSortBy(v as 'name' | 'size' | 'modifiedAt')}>
            <SelectTrigger className="w-[140px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="name">{t('modelLib.sortName')}</SelectItem>
              <SelectItem value="size">{t('modelLib.sortSize')}</SelectItem>
              <SelectItem value="modifiedAt">{t('modelLib.sortModified')}</SelectItem>
            </SelectContent>
          </Select>

          {/* 查看方式切换 */}
          <div className="ml-auto flex items-center gap-1 rounded-md border border-border/60 bg-background p-0.5">
            <span className="text-muted-foreground px-1.5 text-xs">{t('modelLib.viewMode')}</span>
            {(
              [
                { key: 'list', label: t('modelLib.viewList') },
                { key: 'loose', label: t('modelLib.viewLoose') },
                { key: 'compact', label: t('modelLib.viewCompact') },
              ] as const
            ).map((opt) => (
              <Button
                key={opt.key}
                variant="ghost"
                size="sm"
                className={cn(
                  'h-7 px-2.5 text-xs',
                  viewMode === opt.key
                    ? 'bg-primary text-primary-foreground hover:bg-primary hover:text-primary-foreground'
                    : 'text-muted-foreground hover:text-foreground'
                )}
                onClick={() => setViewMode(opt.key)}
              >
                {opt.label}
              </Button>
            ))}
          </div>
        </div>
      </div>

      {/* 列表 */}
      <div className="flex-1 overflow-y-auto p-5">
        {filteredModels.length === 0 ? (
          <div className="flex h-full items-center justify-center">
            <div className="text-center">
              <HardDrive className="text-muted-foreground/40 mx-auto size-12" />
              <p className="text-muted-foreground mt-3">{t('modelLib.empty')}</p>
            </div>
          </div>
        ) : (
          <>
            {viewMode === 'list' ? (
              /* 详细列表：一行一份，显示名称、路径、大小、日期 */
              <div className="divide-y divide-border/60 overflow-hidden rounded-lg border border-gray-200 bg-white dark:border-dark-border dark:bg-dark-secondary">
                {filteredModels.slice(0, renderCount).map((m) => (
                  <div
                    key={m.id}
                    className="group flex items-center gap-4 px-4 py-2.5 transition-colors hover:bg-muted/40"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium" title={m.filename}>
                        {m.filename}
                      </p>
                      <p className="text-muted-foreground/70 mt-0.5 truncate text-xs" title={m.path}>
                        {m.path}
                      </p>
                    </div>
                    <span className="text-foreground w-24 shrink-0 text-right text-sm tabular-nums">
                      {formatFileSize(m.size)}
                    </span>
                    <span className="text-muted-foreground w-36 shrink-0 text-xs tabular-nums">
                      {formatDate(m.modifiedAt)}
                    </span>
                    <Button
                      variant="ghost"
                      size="icon"
                      className={cn(
                        'size-7 shrink-0 opacity-0 transition-opacity group-hover:opacity-100',
                        m.linkUrl ? 'text-primary opacity-100' : 'text-muted-foreground'
                      )}
                      onClick={() => handleOpenLink(m)}
                      title={m.linkUrl
                        ? t('modelLib.linkEdit')
                        : t('modelLib.linkButton')}
                    >
                      <Link2 className="size-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="text-muted-foreground hover:text-destructive size-7 shrink-0 opacity-0 transition-opacity group-hover:opacity-100"
                      onClick={() => handleDelete(m)}
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  </div>
                ))}
              </div>
            ) : (
              /* 平铺：宽松（2 列）/ 紧凑（4 列），显示完整名称 + 完整路径 */
              <div
                className={cn(
                  viewMode === 'loose'
                    ? 'grid grid-cols-2 gap-6'
                    : 'grid grid-cols-4 gap-2'
                )}
              >
                {filteredModels.slice(0, renderCount).map((m) => (
                  <div
                    key={m.id}
                    className={cn(
                      'group relative rounded-lg border border-gray-200 bg-white transition-shadow hover:shadow-md dark:border-dark-border dark:bg-dark-secondary',
                      viewMode === 'loose' ? 'p-4' : 'p-2'
                    )}
                  >
                    <p
                      className={cn(
                        'break-all font-medium',
                        viewMode === 'loose' ? 'text-sm' : 'text-xs'
                      )}
                      title={m.filename}
                    >
                      {m.filename}
                    </p>
                    <p
                      className={cn(
                        'text-muted-foreground mt-2 break-all',
                        viewMode === 'loose' ? 'text-xs' : 'mt-1 text-[11px] leading-tight'
                      )}
                      title={m.path}
                    >
                      {m.path}
                    </p>
                    <Button
                      variant="ghost"
                      size="icon"
                      className={cn(
                        'absolute right-7 top-1 size-6 shrink-0 opacity-0 transition-opacity group-hover:opacity-100',
                        m.linkUrl ? 'text-primary opacity-100' : 'text-muted-foreground'
                      )}
                      onClick={() => handleOpenLink(m)}
                      title={m.linkUrl ? t('modelLib.linkEdit') : t('modelLib.linkButton')}
                    >
                      <Link2 className="size-3.5" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="text-muted-foreground hover:text-destructive absolute right-1 top-1 size-6 shrink-0 opacity-0 transition-opacity group-hover:opacity-100"
                      onClick={() => handleDelete(m)}
                    >
                      <Trash2 className="size-3.5" />
                    </Button>
                  </div>
                ))}
              </div>
            )}
            {renderCount < filteredModels.length && (
              <div ref={sentinelRef} className="h-px w-full" aria-hidden="true" />
            )}
          </>
        )}
      </div>

      {/* 下载对话框 */}
      <Dialog open={downloadOpen} onOpenChange={setDownloadOpen}>
        <DialogContent className="sm:max-w-[520px]">
          <DialogHeader>
            <DialogTitle>{t('modelLib.downloadModel')}</DialogTitle>
          </DialogHeader>

          <div className="space-y-4">
            <div>
              <label className="text-foreground mb-1.5 block text-sm font-medium">
                {t('modelLib.downloadUrl')}
              </label>
              <Input
                value={downloadUrl}
                onChange={(e) => setDownloadUrl(e.target.value)}
                placeholder={t('modelLib.downloadUrlPlaceholder')}
              />
              {detectedSource && (
                <p className="text-muted-foreground mt-1 text-xs">
                  {t('modelLib.sourceDetected', { source: SOURCE_LABELS[detectedSource] || detectedSource })}
                </p>
              )}
              <p className="text-muted-foreground/70 mt-1 text-xs">{t('modelLib.sourceHint')}</p>
            </div>

            <div>
              <label className="text-foreground mb-1.5 block text-sm font-medium">
                {t('modelLib.modelType')}
              </label>
              <Select value={downloadType} onValueChange={setDownloadType}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {dirOptions.map((dir) => (
                    <SelectItem key={dir} value={dir}>
                      {typeLabel(dir)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div>
              <label className="text-foreground mb-1.5 block text-sm font-medium">
                {t('modelLib.filename')}
              </label>
              <Input
                value={downloadName}
                onChange={(e) => setDownloadName(e.target.value)}
                placeholder={t('modelLib.filenamePlaceholder')}
              />
            </div>

            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setDownloadOpen(false)}>
                {t('common.cancel')}
              </Button>
              <Button onClick={handleStartDownload} disabled={submitting || !downloadUrl.trim()}>
                {submitting ? <Loader2 className="size-4 animate-spin" /> : <Download className="size-4" />}
                {t('modelLib.startDownload')}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* 网络链接关联弹窗（单模型手动关联/移除） */}
      <ModelLinkDialog
        model={linkTarget}
        onClose={() => setLinkTarget(null)}
        onSaved={() => loadModels(false)}
      />

      {/* 本地模型文件夹设置 */}
      <ModelSettingsModal
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        onSaved={(changed) => {
          if (changed) loadModels(true)
        }}
      />
    </div>
  )
}
