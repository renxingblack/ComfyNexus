/**
 * QuickLinksBar 组件
 * 首页「启动环境 / 管理配置」下方的常用工具快速跳转栏
 *
 * 功能：
 * - 一行紧凑链接按钮，点击直接调用 open_url 在浏览器打开
 * - 内置常用工具预设（Python / Git / NVIDIA / AMD / CUDA / VS / HIP / VC++ / 运行库 / PyStandalone / Watt / 脚本猫 / Comfy 官方软件 …）
 * - 末尾「添加链接」按钮：粘贴链接可自动识别名称与图标（后端 get_link_meta），
 *   也支持手动编辑名称、链接、图标
 * - 自定义链接持久化到 localStorage
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Plus, Globe, Pencil, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { toast } from '@/utils/toast'
import { cn } from '@/lib/utils'

export interface QuickLink {
  id: string
  name: string
  url: string
  icon: string // favicon url，可为空（渲染时按域名自动推导）
  preset?: boolean
}

/**
 * 内置常用工具预设
 *
 * icon：显式指定的图标地址（留空则由后端按域名抓取并缓存到本地）。
 *
 * 注意：部分站点（AMD / aka.ms / mefcl）自身 favicon 不可达或不存在，
 * 这里用 jsDelivr 上的 simple-icons 官方 logo 直链兜底——该 CDN 在国内可直连，
 * 且 simple-icons 的 logo 多为**长条形**（如 AMD / Microsoft），符合"长 logo 也要能显示"。
 */
const PRESET_LINKS: QuickLink[] = [
  { id: 'p-python', name: 'Python 环境', url: 'https://www.python.org/downloads/windows/', icon: '', preset: true },
  { id: 'p-git', name: '版本控制 (Git)', url: 'https://git-scm.com/download/win', icon: '', preset: true },
  { id: 'p-nvidia', name: 'NVIDIA（Studio 驱动）', url: 'https://www.nvidia.cn/Download/index.aspx?lang=cn', icon: '', preset: true },
  { id: 'p-amd', name: 'AMD（Adrenalin 驱动）', url: 'https://www.amd.com/zh-cn/support/download/drivers.html', icon: 'https://cdn.jsdelivr.net/npm/simple-icons@latest/icons/amd.svg', preset: true },
  { id: 'p-cuda', name: 'CUDA Toolkit', url: 'https://developer.nvidia.com/cuda-toolkit-archive', icon: 'https://cdn.jsdelivr.net/npm/simple-icons@latest/icons/nvidia.svg', preset: true },
  { id: 'p-vs2026', name: 'Visual Studio (2026)', url: 'https://visualstudio.microsoft.com/zh-hans/downloads/', icon: 'https://cdn.jsdelivr.net/npm/simple-icons@latest/icons/visualstudio.svg', preset: true },
  { id: 'p-vs2022', name: 'Visual Studio (2022)', url: 'https://aka.ms/vs/17/release/vs_community.exe', icon: 'https://cdn.jsdelivr.net/npm/simple-icons@latest/icons/visualstudio.svg', preset: true },
  { id: 'p-hip', name: 'HIP SDK (AMD)', url: 'https://www.amd.com/zh-cn/developer/resources/rocm-hub/hip-sdk.html', icon: 'https://cdn.jsdelivr.net/npm/simple-icons@latest/icons/amd.svg', preset: true },
  { id: 'p-vcredist', name: 'Microsoft Visual C++', url: 'https://learn.microsoft.com/zh-cn/cpp/windows/latest-supported-vc-redist?view=msvc-170#latest-supported-redistributable-version', icon: 'https://cdn.jsdelivr.net/npm/simple-icons@latest/icons/microsoft.svg', preset: true },
  { id: 'p-runtime', name: '软件常用运行库', url: 'https://www.mefcl.com/srlpackage.html', icon: 'https://cdn.jsdelivr.net/npm/simple-icons@latest/icons/windows.svg', preset: true },
  { id: 'p-pystandalone', name: 'Python Build Standalone', url: 'https://github.com/astral-sh/python-build-standalone/releases', icon: 'https://cdn.jsdelivr.net/npm/simple-icons@latest/icons/github.svg', preset: true },
  { id: 'p-watt', name: 'Watt Toolkit', url: 'https://steampp.net/', icon: '', preset: true },
  { id: 'p-scriptcat', name: '脚本猫', url: 'https://scriptcat.org/zh-CN/search', icon: '', preset: true },
  { id: 'p-comfy', name: 'Comfy官方软件', url: 'https://comfy.org/zh-CN/download', icon: '', preset: true },
]

const STORAGE_KEY = 'comfynexus_quick_links'

/**
 * 链接图标：由后端抓取并缓存到本地（/icons/xxx），一次下载长期复用。
 *
 * - 优先用 link.icon 指定的地址（走后端缓存），否则按目标页地址抓取
 * - 抓取失败回退 Globe 占位
 * - logo 允许是长条形（如 AMD / Microsoft），故用 object-contain + 限高不限宽，
 *   不做正方形裁剪
 */
function LinkIcon({ link }: { link: QuickLink }) {
  const [src, setSrc] = useState<string>('')

  useEffect(() => {
    let cancelled = false
    setSrc('')
    const target = link.icon?.trim() || link.url
    const api = (window as any).pywebview?.api
    if (!api?.get_cached_icon) return
    api.get_cached_icon(target)
      .then((res: any) => {
        if (cancelled) return
        if (res?.success && res.icon) setSrc(res.icon)
      })
      .catch(() => { /* 保持占位 */ })
    return () => { cancelled = true }
  }, [link.icon, link.url])

  if (!src) {
    // 抓取失败：退化为名称首字母（比通用地球图标更易辨识）
    const initial = (link.name || link.url || '?').trim().charAt(0).toUpperCase()
    return (
      <span
        className="bg-primary/15 text-primary flex size-4 shrink-0 items-center justify-center rounded-sm text-[10px] font-bold"
        title={link.name}
      >
        {initial}
      </span>
    )
  }
  return (
    <img
      src={src}
      alt=""
      className="max-h-4 max-w-[88px] shrink-0 object-contain"
      loading="lazy"
      onError={() => setSrc('')}
    />
  )
}

function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '') || url
  } catch {
    return url
  }
}

/** 归一化 URL 用于去重比较（忽略协议大小写、末尾斜杠、hash） */
function normalizeUrl(url: string): string {
  try {
    const u = new URL(url.trim())
    u.hash = ''
    return u.toString().replace(/\/$/, '').toLowerCase()
  } catch {
    return (url || '').trim().replace(/\/$/, '').toLowerCase()
  }
}

function openLink(url: string) {
  try {
    const api = (window as any).pywebview?.api
    if (api?.open_url) {
      api.open_url(url)
      return
    }
  } catch {
    /* 忽略，走下方兜底 */
  }
  // 开发环境 / API 不可用：浏览器新标签打开
  window.open(url, '_blank', 'noopener,noreferrer')
}

function QuickLinkButton({
  link,
  onEdit,
}: {
  link: QuickLink
  onEdit?: () => void
}) {
  const { t } = useTranslation()
  return (
    <div className="group relative">
      <button
        type="button"
        onClick={() => openLink(link.url)}
        title={link.url}
        className={cn(
          'flex h-8 items-center gap-1.5 rounded-lg border px-2.5 text-xs font-medium',
          'border-border-subtle bg-surface-hover text-foreground',
          'transition-colors hover:border-primary/40 hover:bg-primary/5',
          'max-w-[200px]'
        )}
      >
        <LinkIcon link={link} />
        <span className="truncate">{link.name}</span>
      </button>
      {onEdit && (
        <button
          type="button"
          onClick={onEdit}
          title={t('home.editLink')}
          className={cn(
            'absolute -right-1.5 -top-1.5 size-5 rounded-full border border-border-subtle',
            'bg-surface text-muted-foreground shadow-sm',
            'flex items-center justify-center opacity-0 transition-opacity',
            'group-hover:opacity-100 hover:text-primary'
          )}
        >
          <Pencil className="size-3" />
        </button>
      )}
    </div>
  )
}

export interface QuickLinksBarProps {
  className?: string
}

export const QuickLinksBar: React.FC<QuickLinksBarProps> = ({ className }) => {
  const { t } = useTranslation()
  const [customLinks, setCustomLinks] = useState<QuickLink[]>([])
  const [showDialog, setShowDialog] = useState(false)
  const [editing, setEditing] = useState<QuickLink | null>(null)
  const [form, setForm] = useState({ name: '', url: '', icon: '' })
  const [nameTouched, setNameTouched] = useState(false)
  const [iconTouched, setIconTouched] = useState(false)
  const detectTimer = useRef<number | undefined>(undefined)

  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      if (raw) setCustomLinks(JSON.parse(raw))
    } catch {
      /* 忽略解析错误 */
    }
  }, [])

  const persist = (links: QuickLink[]) => {
    setCustomLinks(links)
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(links))
    } catch {
      /* 忽略存储错误 */
    }
  }

  /** 粘贴链接后自动识别名称与图标（仅在用户未手动修改过对应字段时回填） */
  const handleUrlChange = (url: string) => {
    setForm((f) => ({ ...f, url }))
    if (detectTimer.current) window.clearTimeout(detectTimer.current)
    if (!url.trim()) return
    detectTimer.current = window.setTimeout(async () => {
      try {
        const api = (window as any).pywebview?.api
        if (!api?.get_link_meta) return
        const res = await api.get_link_meta(url.trim())
        if (res?.success) {
          setForm((f) => ({
            ...f,
            name: nameTouched ? f.name : (res.name || f.name),
            icon: iconTouched ? f.icon : (res.icon || f.icon),
          }))
        }
      } catch {
        /* 自动识别失败不影响手动输入 */
      }
    }, 500)
  }

  const openAdd = () => {
    setEditing(null)
    setForm({ name: '', url: '', icon: '' })
    setNameTouched(false)
    setIconTouched(false)
    setShowDialog(true)
  }

  const openEdit = (link: QuickLink) => {
    setEditing(link)
    setForm({ name: link.name, url: link.url, icon: link.icon })
    setNameTouched(true)
    setIconTouched(true)
    setShowDialog(true)
  }

  const handleSave = () => {
    const url = form.url.trim()
    if (!url) {
      toast.error(t('home.linkUrlRequired'))
      return
    }
    if (!/^https?:\/\//i.test(url)) {
      toast.error(t('home.linkUrlRequired'))
      return
    }
    const name = form.name.trim() || hostOf(url)
    const icon = form.icon.trim()
    if (editing) {
      persist(
        customLinks.map((l) =>
          l.id === editing.id ? { ...editing, name, url, icon } : l
        )
      )
    } else {
      persist([
        ...customLinks,
        { id: `custom_${Date.now()}`, name, url, icon, preset: false },
      ])
    }
    toast.success(t('home.linkSaved'))
    setShowDialog(false)
  }

  const handleDelete = (link: QuickLink) => {
    if (!window.confirm(t('home.confirmDeleteLink'))) return
    persist(customLinks.filter((l) => l.id !== link.id))
    // 同步清理后端已缓存的本地图标（避免删了链接却留下孤儿缓存文件）
    try {
      const api = (window as any).pywebview?.api
      api?.remove_cached_icon?.(link.icon?.trim() || link.url)
    } catch { /* 忽略清理失败 */ }
    toast.success(t('home.linkDeleted'))
  }

  // 去重：若某个「自定义链接」的 URL 与内置预设相同（例如早期手动添加过「脚本猫」，
  // 后来它变成了预设），则不再重复显示，只保留预设那一个。
  const presetUrlSet = useMemo(
    () => new Set(PRESET_LINKS.map((l) => normalizeUrl(l.url))),
    []
  )
  const allLinks = useMemo(
    () => [
      ...PRESET_LINKS,
      ...customLinks.filter((l) => !presetUrlSet.has(normalizeUrl(l.url))),
    ],
    [customLinks, presetUrlSet]
  )

  return (
    <div
      className={cn(
        'rounded-2xl p-[18px] border shadow-lg shadow-border-subtle/50',
        'bg-surface border-border-subtle',
        className
      )}
    >
      <div className="mb-2.5 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Globe className="text-muted-foreground size-4" />
          <h2 className="text-foreground text-sm font-semibold">{t('home.quickLinks')}</h2>
        </div>
        <span className="text-muted-foreground text-[11px]">
          {t('home.autoDetectHint')}
        </span>
      </div>

      <div className="flex flex-wrap gap-2">
        {allLinks.map((link) =>
          link.preset ? (
            <QuickLinkButton key={link.id} link={link} />
          ) : (
            <div key={link.id} className="group relative">
              <QuickLinkButton
                link={link}
                onEdit={() => openEdit(link)}
              />
              <button
                type="button"
                onClick={() => handleDelete(link)}
                title={t('home.deleteLink')}
                className={cn(
                  'absolute -right-1.5 -top-1.5 size-5 rounded-full border border-border-subtle',
                  'bg-surface text-muted-foreground shadow-sm',
                  'flex items-center justify-center opacity-0 transition-opacity',
                  'group-hover:opacity-100 hover:text-destructive'
                )}
              >
                <Trash2 className="size-3" />
              </button>
            </div>
          )
        )}

        <Button
          variant="outline"
          size="sm"
          className="h-8 gap-1"
          onClick={openAdd}
        >
          <Plus className="size-3.5" />
          {t('home.addLink')}
        </Button>
      </div>

      {showDialog && (
        <Dialog open={showDialog} onOpenChange={setShowDialog}>
          <DialogContent className="sm:max-w-[480px]">
            <DialogHeader>
              <DialogTitle>
                {editing ? t('home.editLink') : t('home.addLink')}
              </DialogTitle>
            </DialogHeader>

            <div className="space-y-3">
              <div>
                <label className="text-foreground mb-1.5 block text-sm font-medium">
                  {t('home.linkName')}
                </label>
                <Input
                  value={form.name}
                  onChange={(e) => {
                    setNameTouched(true)
                    setForm((f) => ({ ...f, name: e.target.value }))
                  }}
                  placeholder={t('home.linkNamePlaceholder')}
                />
              </div>

              <div>
                <label className="text-foreground mb-1.5 block text-sm font-medium">
                  {t('home.linkUrl')}
                </label>
                <Input
                  value={form.url}
                  onChange={(e) => handleUrlChange(e.target.value)}
                  placeholder={t('home.linkUrlPlaceholder')}
                />
              </div>

              <div>
                <label className="text-foreground mb-1.5 block text-sm font-medium">
                  {t('home.linkIcon')}
                </label>
                <div className="flex items-center gap-2">
                  {form.url.trim() && (
                    <LinkIcon
                      link={{ id: 'preview', name: '', url: form.url, icon: form.icon }}
                    />
                  )}
                  <Input
                    value={form.icon}
                    onChange={(e) => {
                      setIconTouched(true)
                      setForm((f) => ({ ...f, icon: e.target.value }))
                    }}
                    placeholder={t('home.linkIconPlaceholder')}
                    className="flex-1"
                  />
                </div>
              </div>

              <div className="flex justify-end gap-2 pt-1">
                <Button variant="outline" onClick={() => setShowDialog(false)}>
                  {t('common.cancel')}
                </Button>
                <Button onClick={handleSave}>
                  {editing ? t('common.save') : t('home.addLink')}
                </Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      )}
    </div>
  )
}

export default QuickLinksBar
