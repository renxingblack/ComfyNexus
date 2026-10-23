/**
 * LoRA 设置模态框组件
 */

import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Switch } from '@/components/ui/Switch'
import { FolderOpen, Loader2, ExternalLink, Plus, Trash2 } from 'lucide-react'
import { bridgeService } from '@/services/bridge'
import { cn } from '@/lib/utils'

interface LoraPathRow {
  id: string
  path: string
  name: string
  category: string
  enabled: boolean
  isNew: boolean
}

interface LoraSettingsModalProps {
  open: boolean
  onClose: () => void
  onSaved?: (pathsChanged: boolean) => void
}

export function LoraSettingsModal({
  open, onClose, onSaved }: LoraSettingsModalProps) {
  const { t } = useTranslation()
  const [apiKey, setApiKey] = useState('')
  const [pathRows, setPathRows] = useState<LoraPathRow[]>([])
  const [initialPathsSignature, setInitialPathsSignature] = useState('')
  const [previewLimit, setPreviewLimit] = useState(5)
  const [gridColumns, setGridColumns] = useState(2)
  const [previewShortEdge, setPreviewShortEdge] = useState(234)
  const [minimalList, setMinimalList] = useState(false)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [previewLimitFocused, setPreviewLimitFocused] = useState(false)
  const [gridColumnsFocused, setGridColumnsFocused] = useState(false)
  const [previewShortEdgeFocused, setPreviewShortEdgeFocused] = useState(false)

  useEffect(() => {
    if (open) {
      loadConfig()
    }
  }, [open])

  const loadConfig = async () => {
    setLoading(true)
    try {
      const result = await bridgeService.loraGetConfig()
      if (result.success && result.config) {
        setApiKey(result.config.civitai?.api_key || '')
        setPreviewLimit(result.config.civitai?.preview_download_limit ?? 5)
        setGridColumns(result.config.display?.grid_columns ?? 2)
        setPreviewShortEdge(result.config.display?.preview_short_edge ?? 234)
        setMinimalList(result.config.display?.minimal_list ?? false)
        const scanPaths = result.config.scan_paths || []
        if (scanPaths.length > 0) {
          // 展示全部已配置路径（含空路径与禁用项），让用户能看到并管理每一条
          setPathRows(scanPaths.map((p: any) => ({
            id: p.id || crypto.randomUUID(),
            path: p.path || '',
            name: p.name || '',
            category: p.category || 'uncategorized',
            enabled: p.enabled !== false,
            isNew: false
          })))
        } else {
          // 没有任何路径：给一个空行，方便用户直接添加第一个路径
          setPathRows([{
            id: crypto.randomUUID(),
            path: '',
            name: '',
            category: 'uncategorized',
            enabled: true,
            isNew: true
          }])
        }
        setInitialPathsSignature(
          JSON.stringify(
            scanPaths.map((p: any) => ({
              path: (p.path || '').trim(),
              enabled: p.enabled !== false
            }))
          )
        )
      }
    } catch (error) {
      console.error('加载 LoRA 配置失败:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleBrowse = async (index: number) => {
    try {
      const result = await bridgeService.selectDirectory()
      const dir = result.success ? result.path : ''
      if (dir) {
        setPathRows(prev => prev.map((r, i) =>
          i === index ? { ...r, path: dir } : r
        ))
      }
    } catch (error) {
      console.error('[LoraSettingsModal] 浏览文件夹失败:', error)
    }
  }

  const handleAddPath = () => {
    setPathRows(prev => [
      ...prev,
      {
        id: crypto.randomUUID(),
        path: '',
        name: '',
        category: 'uncategorized',
        enabled: true,
        isNew: true
      }
    ])
  }

  const handleRemovePath = (index: number) => {
    setPathRows(prev => prev.filter((_, i) => i !== index))
  }

  const handlePathChange = (index: number, field: 'path' | 'name', value: string) => {
    setPathRows(prev => prev.map((r, i) =>
      i === index ? { ...r, [field]: value } : r
    ))
  }

  const handlePathEnabledChange = (index: number, enabled: boolean) => {
    setPathRows(prev => prev.map((r, i) =>
      i === index ? { ...r, enabled } : r
    ))
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      // 仅保留填写了路径的行；空路径行视为"移除该路径"
      const builtPaths = pathRows
        .filter(r => r.path.trim() !== '')
        .map(r => ({
          id: r.id || crypto.randomUUID(),
          path: r.path.trim(),
          name: (r.name.trim() || r.path.trim().split(/[\\/]/).pop() || 'LoRA Models'),
          category: r.category || 'uncategorized',
          enabled: r.enabled
        }))

      const newSignature = JSON.stringify(
        builtPaths.map(p => ({ path: p.path, enabled: p.enabled }))
      )
      const pathsChanged = newSignature !== initialPathsSignature

      const updates: Record<string, any> = {
        civitai: { 
          api_key: apiKey,
          preview_download_limit: previewLimit
        },
        display: {
          grid_columns: gridColumns,
          preview_short_edge: previewShortEdge,
          minimal_list: minimalList
        },
        // 用完整列表整体替换，支持多路径与移除；空列表 = 不扫描任何路径
        scan_paths: builtPaths,
        // 用户已显式管理路径，关闭"首次自动添加共享 lora/loras"的兜底，
        // 避免自动添加的共享路径覆盖用户清空路径的意图
        sharedLoraPathsInitialized: true
      }

      await bridgeService.loraUpdateConfig(updates)
      
      if ((window as any).__loraGridColumnsUpdated) {
        (window as any).__loraGridColumnsUpdated(gridColumns)
      }
      
      if ((window as any).__loraPreviewShortEdgeUpdated) {
        (window as any).__loraPreviewShortEdgeUpdated(previewShortEdge)
      }
      
      if ((window as any).__loraMinimalListUpdated) {
        (window as any).__loraMinimalListUpdated(minimalList)
      }

      onClose()
      // 路径有变动时通知页面重新扫描，确保"清空/减少路径"会真正移除已显示的模型，
      // "新增路径"会立即扫描到文件
      if (onSaved) {
        onSaved(pathsChanged)
      }
    } catch (error) {
      console.error('保存 LoRA 配置失败:', error)
    } finally {
      setSaving(false)
    }
  }

  const handleOpenChange = (v: boolean) => {
    if (!v) onClose()
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{t("common.title.loraSettings")}</DialogTitle>
        </DialogHeader>
        <div className="space-y-5">
          {loading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="size-6 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <>
              <div>
                <label className="mb-2 block text-sm font-medium text-muted-foreground">
                  {t('lora.settings.loraPath')}
                </label>
                <div className="space-y-2">
                  {pathRows.map((row, index) => (
                    <div key={row.id} className="flex items-center gap-2">
                      <Input
                        type="text"
                        placeholder={t("common.placeholder.loraPath")}
                        value={row.path}
                        onChange={(e) => handlePathChange(index, 'path', e.target.value)}
                        className="flex-1"
                        disabled={saving}
                      />
                      <Button
                        variant="outline"
                        onClick={() => handleBrowse(index)}
                        className="shrink-0"
                        disabled={saving}
                        title={t("common.placeholder.loraPath")}
                      >
                        <FolderOpen className="size-4" />
                      </Button>
                      <Switch
                        checked={row.enabled}
                        onCheckedChange={(checked) => handlePathEnabledChange(index, checked)}
                        disabled={saving}
                        title={t('lora.settings.pathEnabled')}
                      />
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => handleRemovePath(index)}
                        className="h-9 w-9 shrink-0 text-danger hover:bg-danger/10 hover:text-danger"
                        disabled={saving}
                        title={t('lora.settings.removePath')}
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    </div>
                  ))}
                </div>
                <Button
                  variant="outline"
                  className="mt-2 w-full border-dashed"
                  onClick={handleAddPath}
                  disabled={saving}
                >
                  <Plus className="mr-2 size-4" />
                  {t('lora.settings.addPath')}
                </Button>
                {pathRows.filter(r => r.path.trim() !== '').length === 0 && (
                  <p className="mt-2 text-xs text-muted-foreground">
                    {t('lora.settings.noPaths')}
                  </p>
                )}
              </div>
              
              <div>
                <label className="mb-2 block text-sm font-medium text-muted-foreground">
                  {t('lora.settings.civitaiApiKey')}
                </label>
                <div className="flex gap-2">
                  <Input
                    type="password"
                    placeholder={t("common.placeholder.pasteApiKey")}
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    className="flex-1"
                    disabled={saving}
                  />
                  <Button
                    variant="outline"
                    onClick={() => window.open('https://civitai.com/user/account', '_blank')}
                    className="shrink-0"
                    disabled={saving}
                    title={t("common.title.getApiKey")}
                  >
                    <ExternalLink className="size-4" />
                  </Button>
                </div>
              </div>
              
              <div className="flex gap-2">
                <div className="flex flex-1 items-center gap-3">
                  <label className="whitespace-nowrap text-sm font-medium text-muted-foreground">
                    {t('lora.settings.enableMinimalList')}
                  </label>
                  <div className="flex w-16 items-center">
                    <Switch
                      checked={minimalList}
                      onCheckedChange={(checked) => setMinimalList(checked)}
                      disabled={saving}
                    />
                  </div>
                </div>

                <div className="relative flex flex-1 items-center gap-3">
                  <label className={cn("text-sm font-medium whitespace-nowrap", minimalList ? "text-muted-foreground/50" : "text-muted-foreground")}>
                    {t('lora.settings.gridColumns')}
                  </label>
                  <div className="relative">
                    <Input
                      type="number"
                      value={gridColumns}
                      onChange={(e) => setGridColumns(parseInt(e.target.value) || 1)}
                      onBlur={() => {
                        const value = Math.max(1, Math.min(5, gridColumns))
                        setGridColumns(value)
                        setGridColumnsFocused(false)
                      }}
                      className="w-16 appearance-none [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
                      disabled={saving || minimalList}
                      min={1}
                      max={5}
                      onFocus={() => setGridColumnsFocused(true)}
                    />
                    <div className={`absolute left-1/2 top-full z-50 mt-2 -translate-x-1/2 whitespace-nowrap rounded-lg border border-border bg-popover px-3 py-1.5 text-xs text-popover-foreground shadow-lg transition-all duration-200 ${gridColumnsFocused ? 'translate-y-0 opacity-100' : 'pointer-events-none -translate-y-1 opacity-0'}`}>
                      {minimalList ? t('lora.settings.gridColumnsTooltipMinimal') : t('lora.settings.gridColumnsTooltip')}
                      <div className="absolute bottom-full left-1/2 -translate-x-1/2 border-4 border-transparent border-b-popover"></div>
                    </div>
                  </div>
                </div>
              </div>

              <div className="flex gap-2">
                <div className="relative flex flex-1 items-center gap-3">
                  <label className="whitespace-nowrap text-sm font-medium text-muted-foreground">
                    {t('lora.settings.previewLimit')}
                  </label>
                  <div className="relative">
                    <Input
                      type="number"
                      placeholder="0"
                      value={previewLimit}
                      onChange={(e) => setPreviewLimit(parseInt(e.target.value) || 0)}
                      onBlur={() => {
                        const value = Math.max(0, previewLimit)
                        setPreviewLimit(value)
                        setPreviewLimitFocused(false)
                      }}
                      className="w-16 appearance-none [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
                      disabled={saving}
                      min={0}
                      onFocus={() => setPreviewLimitFocused(true)}
                    />
                    <div className={`absolute left-1/2 top-full z-50 mt-2 -translate-x-1/2 whitespace-nowrap rounded-lg border border-border bg-popover px-3 py-1.5 text-xs text-popover-foreground shadow-lg transition-all duration-200 ${previewLimitFocused ? 'translate-y-0 opacity-100' : 'pointer-events-none -translate-y-1 opacity-0'}`}>
                      {t('lora.settings.previewLimitTooltip')}
                      <div className="absolute bottom-full left-1/2 -translate-x-1/2 border-4 border-transparent border-b-popover"></div>
                    </div>
                  </div>
                </div>

                <div className="relative flex flex-1 items-center gap-3">
                  <label className="whitespace-nowrap text-sm font-medium text-muted-foreground">
                    {t('lora.settings.previewShortEdge')}
                  </label>
                  <div className="relative">
                    <Input
                      type="number"
                      value={previewShortEdge}
                      onChange={(e) => setPreviewShortEdge(parseInt(e.target.value) || 200)}
                      onBlur={() => {
                        const value = Math.max(100, Math.min(400, previewShortEdge))
                        setPreviewShortEdge(value)
                        setPreviewShortEdgeFocused(false)
                      }}
                      className="w-16 appearance-none [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
                      disabled={saving}
                      min={100}
                      max={400}
                      onFocus={() => setPreviewShortEdgeFocused(true)}
                    />
                    <div className={`absolute left-1/2 top-full z-50 mt-2 -translate-x-1/2 whitespace-nowrap rounded-lg border border-border bg-popover px-3 py-1.5 text-xs text-popover-foreground shadow-lg transition-all duration-200 ${previewShortEdgeFocused ? 'translate-y-0 opacity-100' : 'pointer-events-none -translate-y-1 opacity-0'}`}>
                      {t('lora.settings.previewShortEdgeTooltip')}
                      <div className="absolute bottom-full left-1/2 -translate-x-1/2 border-4 border-transparent border-b-popover"></div>
                    </div>
                  </div>
                </div>
              </div>
              
              <div className="flex justify-end gap-2 pt-2">
                <Button variant="ghost" onClick={() => handleOpenChange(false)} disabled={saving}>
                  {t('common.cancel')}
                </Button>
                <Button onClick={handleSave} disabled={saving}>
                  {saving ? (
                    <>
                      <Loader2 className="mr-2 size-4 animate-spin" />
                      {t('common.saving')}
                    </>
                  ) : (
                    t('lora.settings.saveConfig')
                  )}
                </Button>
              </div>
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
