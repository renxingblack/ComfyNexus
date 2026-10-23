/**
 * HuggingFace 镜像加速设置组件
 *
 * 功能：开关、自动(测速选优)/手动模式、手动指定镜像源、一键测速与结果展示。
 * 生效范围：模型管理页的网络模型下载（huggingface.co → 当前镜像）。
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui'
import { Switch } from '@/components/ui/Switch'
import { NativeSelect } from '@/components/ui/NativeSelect'
import { Zap, Gauge, Info } from 'lucide-react'
import { toast } from '@/utils/toast'

interface HFMirrorSettingsData {
  enabled: boolean
  mode: string
  forceSource: string | null
  statusText: string
  currentSource: string | null
  isTesting: boolean
  testResults: Record<string, number> | null
}

const SOURCE_OPTIONS = [
  { value: 'hf-mirror', label: 'HF-Mirror（国内镜像）' },
  { value: 'official', label: 'HuggingFace 官方' },
]

const SOURCE_LABELS: Record<string, string> = {
  'hf-mirror': 'HF-Mirror',
  official: '官方',
}

export function HFMirrorSettings() {
  const { t } = useTranslation()
  const [settings, setSettings] = useState<HFMirrorSettingsData>({
    enabled: false,
    mode: 'auto',
    forceSource: null,
    statusText: '',
    currentSource: null,
    isTesting: false,
    testResults: null,
  })
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const loadSettings = useCallback(async () => {
    if (!window.pywebview?.api) return
    try {
      const result = await window.pywebview.api.get_hf_mirror_settings()
      if (result.success && result.settings) {
        setSettings({
          enabled: result.settings.enabled || false,
          mode: result.settings.mode || 'auto',
          forceSource: result.settings.forceSource || null,
          statusText: result.settings.statusText || '',
          currentSource: result.settings.currentSource || null,
          isTesting: result.settings.isTesting || false,
          testResults: result.settings.testResults || null,
        })
      }
    } catch (e) {
      console.error('[HFMirrorSettings] 加载设置失败:', e)
    }
  }, [])

  useEffect(() => {
    loadSettings()
  }, [loadSettings])

  // 测速进行中时轮询状态
  useEffect(() => {
    if (settings.isTesting && !pollRef.current) {
      pollRef.current = setInterval(async () => {
        if (!window.pywebview?.api) return
        try {
          const st = await window.pywebview.api.get_hf_mirror_speed_test_status()
          if (st.success && !st.isRunning) {
            if (pollRef.current) {
              clearInterval(pollRef.current)
              pollRef.current = null
            }
            loadSettings()
            toast.success(t('settings.hfMirror.testDone'))
          }
        } catch {
          // 轮询失败静默
        }
      }, 1000)
    }
    return () => {
      if (!settings.isTesting && pollRef.current) {
        clearInterval(pollRef.current)
        pollRef.current = null
      }
    }
  }, [settings.isTesting, loadSettings, t])

  const updateSettings = async (updates: Partial<HFMirrorSettingsData>) => {
    if (!window.pywebview?.api) return
    // 乐观更新：先切 UI（开关立即响应），后台保存；失败再回滚
    const prevSettings = settings
    setSettings((prev) => ({ ...prev, ...updates }))
    try {
      const apiUpdates: Record<string, unknown> = {}
      if (updates.enabled !== undefined) apiUpdates.enabled = updates.enabled
      if (updates.mode !== undefined) apiUpdates.mode = updates.mode
      if (updates.forceSource !== undefined) apiUpdates.forceSource = updates.forceSource
      const result = await window.pywebview.api.update_hf_mirror_settings(apiUpdates)
      if (result.success && result.settings) {
        const s = result.settings as { statusText?: string; currentSource?: string | null }
        setSettings((prev) => ({
          ...prev,
          statusText: s.statusText || prev.statusText,
          currentSource: s.currentSource ?? prev.currentSource,
        }))
      } else {
        setSettings(prevSettings)
        toast.error(t('settings.mirror.updateFailed'))
      }
    } catch (e) {
      console.error('[HFMirrorSettings] 更新设置失败:', e)
      setSettings(prevSettings)
      toast.error(t('settings.mirror.updateFailed'))
    }
  }

  const handleSpeedTest = async () => {
    if (!window.pywebview?.api) return
    try {
      const r = await window.pywebview.api.start_hf_mirror_speed_test()
      if (!r.success) {
        toast.error(r.message || t('settings.hfMirror.testFail'))
        return
      }
      setSettings((prev) => ({ ...prev, isTesting: true }))
    } catch (e) {
      toast.error(String(e))
    }
  }

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Zap className="text-primary size-4" />
            <label className="text-sm font-medium">{t('settings.hfMirror.enable')}</label>
          </div>
          <Switch
            checked={settings.enabled}
            onCheckedChange={(checked) => {
              if (checked) {
                updateSettings({ enabled: true })
                toast.success(t('settings.hfMirror.enabled'))
              } else {
                updateSettings({ enabled: false })
                toast.info(t('settings.hfMirror.disabled'))
              }
            }}
          />
        </div>
        <p className="text-muted-foreground text-xs">{t('settings.hfMirror.enableHint')}</p>
      </div>

      {settings.enabled && (
        <>
          {settings.statusText && (
            <div className="flex items-center gap-2 rounded-md bg-primary/10 px-3 py-2">
              <Info className="text-primary size-3.5" />
              <span className="text-primary text-xs">{settings.statusText}</span>
            </div>
          )}

          <div className="space-y-2">
            <label className="text-sm font-medium">{t('settings.hfMirror.mode')}</label>
            <NativeSelect
              value={settings.mode === 'manual' ? 'manual' : 'auto'}
              onValueChange={(value) => {
                if (value === 'auto') {
                  updateSettings({ mode: 'auto' })
                } else {
                  updateSettings({
                    mode: 'manual',
                    forceSource: settings.forceSource || 'hf-mirror',
                  })
                }
              }}
            >
              <option value="auto">{t('settings.hfMirror.modeAuto')}</option>
              <option value="manual">{t('settings.hfMirror.modeManual')}</option>
            </NativeSelect>
            <p className="text-muted-foreground text-xs">{t('settings.hfMirror.modeHint')}</p>
          </div>

          {settings.mode === 'manual' && (
            <div className="space-y-2">
              <label className="text-sm font-medium">{t('settings.hfMirror.forceSource')}</label>
              <NativeSelect
                value={settings.forceSource || 'hf-mirror'}
                onValueChange={(value) => updateSettings({ forceSource: value })}
              >
                {SOURCE_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </NativeSelect>
            </div>
          )}

          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={handleSpeedTest}
              disabled={settings.isTesting}
            >
              <Gauge className="mr-2 size-4" />
              {settings.isTesting
                ? t('settings.mirror.testing')
                : t('settings.hfMirror.speedTest')}
            </Button>
          </div>

          {settings.testResults && (
            <div className="space-y-1 rounded-md border border-border p-3">
              <p className="text-muted-foreground text-xs font-medium">
                {t('settings.hfMirror.results')}
              </p>
              {Object.entries(settings.testResults).map(([name, latency]) => (
                <div key={name} className="flex items-center justify-between text-xs">
                  <span>{SOURCE_LABELS[name] || name}</span>
                  <span
                    className={
                      latency > 0
                        ? latency < 800
                          ? 'text-green-600'
                          : 'text-yellow-600'
                        : 'text-destructive'
                    }
                  >
                    {latency > 0 ? `${latency} ms` : t('settings.hfMirror.unreachable')}
                  </span>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
