/**
 * 模型管理 - 本地模型文件夹设置模态框
 *
 * 与 LoRA 管理器设置中的「本地模型文件夹」部分对齐：
 * - 支持设置多个本地模型文件夹
 * - 每个文件夹可开启/关闭（Switch）
 * - 可删除当前文件夹（垃圾桶按钮）
 * - 默认路径为空
 * 保存后若路径有变动，会触发页面重新扫描。
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
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/Select'
import { FolderOpen, Loader2, Plus, Trash2 } from 'lucide-react'
import { bridgeService } from '@/services/bridge'

interface ModelPathRow {
  id: string
  path: string
  name: string
  category: string
  enabled: boolean
  isNew: boolean
}

interface ModelSettingsModalProps {
  open: boolean
  onClose: () => void
  onSaved?: (pathsChanged: boolean) => void
}

export function ModelSettingsModal({
  open, onClose, onSaved }: ModelSettingsModalProps) {
  const { t } = useTranslation()
  const [pathRows, setPathRows] = useState<ModelPathRow[]>([])
  const [initialPathsSignature, setInitialPathsSignature] = useState('')
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  // 默认链接源（魔搭 / HuggingFace / 自动）
  const [defaultSource, setDefaultSource] = useState('modelscope')

  useEffect(() => {
    if (open) {
      loadConfig()
    }
  }, [open])

  const loadConfig = async () => {
    setLoading(true)
    try {
      // 默认链接源单独读取（不在 scan_paths 配置里）
      try {
        const ds = await bridgeService.modelGetDefaultSource()
        if (ds.success && ds.source) setDefaultSource(ds.source)
      } catch { /* 忽略，保持默认 */ }
      const result = await bridgeService.modelGetConfig()
      if (result.success && result.config) {
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
      console.error('加载模型配置失败:', error)
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
      console.error('[ModelSettingsModal] 浏览文件夹失败:', error)
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
          name: (r.name.trim() || r.path.trim().split(/[\\/]/).pop() || 'Models'),
          category: r.category || 'uncategorized',
          enabled: r.enabled
        }))

      const newSignature = JSON.stringify(
        builtPaths.map(p => ({ path: p.path, enabled: p.enabled }))
      )
      const pathsChanged = newSignature !== initialPathsSignature

      const updates: Record<string, any> = {
        // 用完整列表整体替换，支持多路径与移除；空列表 = 不扫描任何本地文件夹
        scan_paths: builtPaths,
      }

      await bridgeService.modelUpdateConfig(updates)
      // 默认链接源一并保存
      try {
        await bridgeService.modelSetDefaultSource(defaultSource)
      } catch { /* 保存失败不阻断路径保存结果 */ }
      onClose()

      // 路径有变动时通知页面重新扫描，确保"清空/移除/新增/开关"会立即反映到模型列表
      if (onSaved) {
        onSaved(pathsChanged)
      }
    } catch (error) {
      console.error('保存模型配置失败:', error)
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
          <DialogTitle>{t("common.title.modelSettings")}</DialogTitle>
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
                  {t('modelLib.modelPath')}
                </label>
                <div className="space-y-2">
                  {pathRows.map((row, index) => (
                    <div key={row.id} className="flex items-center gap-2">
                      <Input
                        type="text"
                        placeholder={t("common.placeholder.modelPath")}
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
                        title={t("common.placeholder.modelPath")}
                      >
                        <FolderOpen className="size-4" />
                      </Button>
                      <Switch
                        checked={row.enabled}
                        onCheckedChange={(checked) => handlePathEnabledChange(index, checked)}
                        disabled={saving}
                        title={t('modelLib.pathEnabled')}
                      />
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => handleRemovePath(index)}
                        className="h-9 w-9 shrink-0 text-danger hover:bg-danger/10 hover:text-danger"
                        disabled={saving}
                        title={t('modelLib.removePath')}
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
                  {t('modelLib.addPath')}
                </Button>
                {pathRows.filter(r => r.path.trim() !== '').length === 0 && (
                  <p className="mt-2 text-xs text-muted-foreground">
                    {t('modelLib.noPaths')}
                  </p>
                )}
              </div>

              {/* 默认链接源 */}
              <div>
                <label className="mb-2 block text-sm font-medium text-muted-foreground">
                  {t('modelLib.defaultSource')}
                </label>
                <Select value={defaultSource} onValueChange={setDefaultSource}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="modelscope">{t('modelLib.srcModelscope')}</SelectItem>
                    <SelectItem value="huggingface">{t('modelLib.srcHuggingface')}</SelectItem>
                    <SelectItem value="auto">{t('modelLib.srcAuto')}</SelectItem>
                  </SelectContent>
                </Select>
                <p className="mt-2 text-xs text-muted-foreground">
                  {t('modelLib.defaultSourceHint')}
                </p>
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
                    t('modelLib.saveConfig')
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
