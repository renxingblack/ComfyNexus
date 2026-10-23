/**
 * 0基础安装向导
 *
 * 步骤：安装位置 → ComfyUI 版本 → 注意力后端 → 模型（仅链接） → 插件 → 确认安装
 * 安装过程实时日志，失败时给出 Watt Toolkit / DevSidecar 代理引导。
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from '@/utils/toast'
import { router } from '@/router'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Switch } from '@/components/ui/Switch'
import { Checkbox } from '@/components/ui/checkbox'
import { Progress } from '@/components/ui/progress'
import { cn } from '@/lib/utils'
import {
  FolderOpen, Download, PackageOpen, Puzzle, CheckCircle2,
  Loader2, ChevronLeft, ChevronRight, ExternalLink, X,
} from 'lucide-react'

interface ReleaseAsset { name: string; url: string; size: number }
interface AttentionOption { id: string; name: string; built_in: boolean; note?: string }
interface PluginItem { name: string; url: string }
interface HfFile { path: string; name: string; size: number; dir: string; url: string; selected: boolean }
interface ModelGroup { name: string; repo: string; files: HfFile[]; loading?: boolean; error?: string }
interface KeyDef { label: string; key: string; default?: string }

/** 大模型名称规范：仅字母、小数点、下划线 */
const sanitizeModelName = (s: string) => s.replace(/[^\w.]/g, '')
/** 仓库标识 → 完整 hf-mirror 浏览地址 */
const fullRepoUrl = (repo: string) => `https://hf-mirror.com/${repo.replace(/^https?:\/\/[^/]+\//, '').replace(/\/(tree|blob|resolve)\/.*$/, '')}/tree/main`

interface WizardState {
  installDir: string
  assets: ReleaseAsset[]
  recommendedUrl: string | null
  gpuName: string
  tag: string
  attentions: AttentionOption[]
  defaultPlugins: PluginItem[]
  defaultModelRepos: Array<{ name: string; repo: string; defaultDir?: string }>
  modelPathKeys: KeyDef[]
  workspaceKeys: KeyDef[]
  workflowFiles: Array<{ name: string; url: string }>
}

const STEPS = ['位置', '版本', '注意力', '模型', '插件', '安装']

// 向导位置跨切页保持（模块级）：切到其他标签页再回来不重置
// 安装进行中（后端线程持续运行）时挂载自动恢复到进度页
let savedWizardStep = 0

export default function ZeroInstallTab() {
  const { t } = useTranslation()
  const [step, setStepState] = useState(savedWizardStep)
  const setStep = (s: number | ((prev: number) => number)) =>
    setStepState((prev) => {
      const next = typeof s === 'function' ? s(prev) : s
      savedWizardStep = next
      return next
    })
  const [wizard, setWizard] = useState<WizardState | null>(null)
  const [loading, setLoading] = useState(true)

  // 步骤数据
  const [installDir, setInstallDir] = useState('D:\\ComfyUI')
  const [assetUrl, setAssetUrl] = useState('')
  const [attSel, setAttSel] = useState<Record<string, { on: boolean; wheelUrl?: string; wheelSize?: number }>>({})
  const [wheelOptions, setWheelOptions] = useState<Record<string, Array<{ name: string; url: string; size?: number }>>>({})
  const [plugins, setPlugins] = useState<PluginItem[]>([])
  const [customPluginUrl, setCustomPluginUrl] = useState('')
  const [modelGroups, setModelGroups] = useState<ModelGroup[]>([])
  const [customRepoUrl, setCustomRepoUrl] = useState('')
  const [sharedModelDir, setSharedModelDir] = useState('')
  const [modelPathMap, setModelPathMap] = useState<Record<string, string>>({})
  const [workspaceMap, setWorkspaceMap] = useState<Record<string, string>>({})
  const [showShared, setShowShared] = useState(true)
  const [workflowOn, setWorkflowOn] = useState(true)
  const [wfGroups, setWfGroups] = useState<Array<{ repo: string; name: string; files: Array<{ name: string; relPath: string; selected: boolean }>; error?: string }>>([])
  const [wfLoading, setWfLoading] = useState(false)
  // 自定义工作流：本地导入文件 + 泛网址
  const [localWfFiles, setLocalWfFiles] = useState<string[]>([])
  const [customWfUrls, setCustomWfUrls] = useState<string[]>([])
  const [customWfUrlInput, setCustomWfUrlInput] = useState('')

  // 推荐工作流：官方固定清单（勾选后以 URL 方式下载，gh-proxy 镜像自动回退）
  // wfGroups 仅用于自定义泛网址解析出的仓库
  // 安装进度
  const [progress, setProgress] = useState<{ running: boolean; step: string; percent: number; logs: string[]; done: boolean; error: string; stepPercent?: number; currentDep?: string; downloadInfo?: { name: string; done: number; total: number; speed: number; groupDone?: number; groupTotal?: number } | null } | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const logEndRef = useRef<HTMLDivElement>(null)

  const loadAssets = useCallback(async () => {
    setLoading(true)
    try {
      const res = await window.pywebview.api.zero_get_release_assets()
      if (!res.success) throw new Error(res.error_message || '获取版本信息失败')
      const w: WizardState = {
        installDir: '',
        assets: res.assets || [],
        recommendedUrl: res.recommendedUrl || null,
        gpuName: res.gpuName || '',
        tag: res.tag || '',
        attentions: res.attentions || [],
        defaultPlugins: res.defaultPlugins || [],
        defaultModelRepos: res.defaultModelRepos || [],
        modelPathKeys: res.modelPathKeys || [],
        workspaceKeys: res.workspaceKeys || [],
        workflowFiles: res.workflowFiles || [],
      }
      setWizard(w)
      setAssetUrl(w.recommendedUrl || w.assets?.[0]?.url || '')
      setPlugins(w.defaultPlugins)
      // 初始化模型仓库组（步骤 4 时再逐仓库拉取文件清单）；repo 存完整浏览地址
      setModelGroups((w.defaultModelRepos || []).map((r) => ({
        name: sanitizeModelName(r.name),
        repo: fullRepoUrl(r.repo),
        files: [],
        loading: false,
      })))
      // 初始化模型/工作区映射默认值（默认位置提示）
      const mp: Record<string, string> = {}
      for (const k of w.modelPathKeys || []) mp[k.key] = ''
      setModelPathMap(mp)
      const ws: Record<string, string> = {}
      for (const k of w.workspaceKeys || []) ws[k.key] = ''
      setWorkspaceMap(ws)
      // 默认勾选 Sage（新架构最常用）+ CK（内置提示）
      const initSel: Record<string, { on: boolean; wheelUrl?: string }> = {}
      for (const a of w.attentions) initSel[a.id] = { on: false }
      initSel.sage = { on: true }
      setAttSel(initSel)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadAssets() }, [loadAssets])

  // 切页返回时恢复：后端安装线程仍在运行 → 直达进度页继续显示实时进度；
  // 安装已结束/未开始 → 回到向导最后一步（绝不渲染空进度页）
  useEffect(() => {
    ;(async () => {
      try {
        const res = await window.pywebview.api.zero_get_progress()
        if (res?.success && res.progress?.running) {
          setProgress(res.progress)
          savedWizardStep = 5
          setStepState(5)
        } else {
          // 无进行中的安装：进度页位置回退到向导最后一步，避免空进度页
          if (savedWizardStep >= 5) {
            savedWizardStep = 4
            setStepState(4)
          }
        }
      } catch {
        if (savedWizardStep >= 5) {
          savedWizardStep = 4
          setStepState(4)
        }
      }
    })()
  }, [])

  // 安装中轮询进度
  useEffect(() => {
    if (!progress?.running) {
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
      return
    }
    if (!pollRef.current) {
      pollRef.current = setInterval(async () => {
        try {
          const res = await window.pywebview.api.zero_get_progress()
          if (res.success && res.progress) setProgress(res.progress)
        } catch { /* 静默 */ }
      }, 1000)
    }
  }, [progress?.running])

  // 依赖安装过程：累积"正在处理的依赖"列表，供前端滚动展示
  const [depFeed, setDepFeed] = useState<string[]>([])
  useEffect(() => {
    const cur = progress?.currentDep
    if (!cur) return
    setDepFeed((prev) => (prev[prev.length - 1] === cur ? prev : [...prev, cur].slice(-60)))
  }, [progress?.currentDep])

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [progress?.logs?.length])

  const pickFolder = async () => {
    try {
      const res = await window.pywebview.api.select_directory()
      if (res?.success && res.path) setInstallDir(res.path)
    } catch { /* 用户取消 */ }
  }

  const toggleAttention = async (id: string) => {
    const next = { ...attSel, [id]: { on: !attSel[id]?.on } }
    setAttSel(next)
    // flash 需要列出可选 whl 版本
    if (id === 'flash' && next[id].on && !wheelOptions.flash) {
      try {
        const res = await window.pywebview.api.zero_list_attention_wheels('flash')
        if (res.success && res.mode === 'wheel' && res.wheels) {
          setWheelOptions((prev) => ({ ...prev, flash: res.wheels! }))
        } else if (res.message) {
          toast.warning(res.message)
        }
      } catch { /* 静默 */ }
    }
  }

  const canNext = () => {
    if (step === 0) return installDir.trim().length > 2
    if (step === 1) return !!assetUrl
    return true
  }

  const startInstall = async () => {
    try {
      const attentions = Object.entries(attSel)
        .filter(([, v]) => v.on)
        .map(([id, v]) => ({ id, wheelUrl: v.wheelUrl, size: v.wheelSize }))
      // 勾选的模型文件（后端按 hf-mirror 下载，官方源自动回退）
      const selectedModels = modelGroups.flatMap((g) =>
        g.files
          .filter((f) => f.selected)
          .map((f) => ({ url: f.url, name: f.name, size: f.size, dir: f.dir, group: g.name }))
      )
      // 模型映射组装：用户填写的优先；未填但设置了根目录 → <根目录>/<key>
      const root = sharedModelDir.trim().replace(/[\\/]+$/, '')
      const modelPaths = Object.fromEntries(
        Object.entries(modelPathMap)
          .map(([k, v]) => [k, v.trim() || (root ? `${root}\\${k}` : '')])
          .filter(([, v]) => v)
      )
      const workspace = Object.fromEntries(Object.entries(workspaceMap).filter(([, v]) => v.trim()))
      const res = await window.pywebview.api.zero_start_install({
        installDir,
        assetUrl,
        assetName: wizard?.assets?.find((a) => a.url === assetUrl)?.name || 'ComfyUI_portable.7z',
        assetSize: wizard?.assets?.find((a) => a.url === assetUrl)?.size || 0,
        attentions,
        plugins: plugins.map((p) => ({ name: p.name, url: p.url })),
        workflowRepos: [],
        // 泛网址解析出的仓库条目（预取于 _wf_tmp）
        workflows: workflowOn
          ? wfGroups.flatMap((g) =>
              g.files
                .filter((f) => f.selected)
                .map((f) => ({ repoName: g.repo, relPath: f.relPath, name: f.name }))
            )
          : [],
        // 推荐工作流（URL 直下，gh-proxy 镜像自动回退）+ 本地导入 + 自定义链接
        customWorkflows: [
          ...(workflowOn
            ? recommendedWfs.filter((w) => w.selected).map((w) => ({ type: 'url', url: w.url, name: w.name }))
            : []),
          ...localWfFiles.map((p) => ({ type: 'file', path: p })),
          ...customWfUrls.map((u) => ({ type: 'url', url: u })),
        ],
        models: selectedModels,
        sharedModelDir: root,
        modelPaths,
        workspace,
      })
      if (!res.success) throw new Error(res.error_message)
      setStep(5)
      const pr = await window.pywebview.api.zero_get_progress()
      if (pr.success && pr.progress) setProgress(pr.progress)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }

  // 启动台：自动把当前安装目录加入环境，再跳转工作台并启动 ComfyUI
  const [addingEnv, setAddingEnv] = useState(false)
  const handleGotoWorkspace = async () => {
    const dir = installDir.trim()
    if (!dir) {
      toast.error(t('zero.noInstallDir'))
      return
    }
    setAddingEnv(true)
    try {
      // 自动加入环境（重名/已存在由后端去重处理），静默、不弹提示
      await window.pywebview.api.add_environment(dir, undefined, 'zh')
      // 强制刷新环境 store，让右上角环境菜单立即出现刚装好的环境
      const { useEnvStore } = await import('@/stores/useEnvStore')
      await useEnvStore.getState().fetchEnvironments(true)
    } catch (e) {
      console.error('[ZeroInstall] 自动加入环境失败', e)
    } finally {
      setAddingEnv(false)
    }
    // 跳转工作台
    router.navigate('/workspace')
    // 自动启动 ComfyUI（幂等：已在运行则直接显示工作台，不弹冲突框）
    try {
      const { useProcessStore } = await import('@/stores/useProcessStore')
      useProcessStore.getState().setStartedFromWorkspace(true)
      await useProcessStore.getState().startComfyUI()
    } catch (e) {
      console.error('[ZeroInstall] 自动启动 ComfyUI 失败', e)
    }
  }

  // 推荐工作流固定清单（官方 10 条），进入步骤 5 时初始化
  const [recommendedWfs, setRecommendedWfs] = useState<Array<{ name: string; url: string; selected: boolean }>>([])
  useEffect(() => {
    if (step === 4 && recommendedWfs.length === 0 && (wizard?.workflowFiles?.length || 0) > 0) {
      setRecommendedWfs((wizard!.workflowFiles).map((w) => ({ ...w, selected: true })))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step])

  // 拉取单个 HF 仓库的文件清单（进入步骤 4 时调用）
  const loadModelGroupFiles = async (idx: number) => {
    const g = modelGroups[idx]
    if (!g || g.files.length > 0 || g.loading) return
    // 该仓库的强制分类目录（如文本编码器仓库 → text_encoders）
    const defaultDir = wizard?.defaultModelRepos?.find(
      (r) => fullRepoUrl(r.repo) === g.repo || r.repo === g.repo
    )?.defaultDir || ''
    setModelGroups((prev) => prev.map((x, i) => i === idx ? { ...x, loading: true, error: undefined } : x))
    try {
      const res = await window.pywebview.api.zero_list_hf_files(g.repo, defaultDir)
      if (res.success && res.files && res.files.length > 0) {
        // 主模型（unet/checkpoints 分类）默认勾选，配套文件默认不勾
        const files = res.files.map((f) => ({ ...f, selected: ['unet', 'checkpoints'].includes(f.dir) }))
        setModelGroups((prev) => prev.map((x, i) => i === idx ? { ...x, files, loading: false, error: undefined } : x))
      } else {
        const msg = res.error_message || t('zero.noFiles')
        setModelGroups((prev) => prev.map((x, i) => i === idx ? { ...x, loading: false, error: msg } : x))
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setModelGroups((prev) => prev.map((x, i) => i === idx ? { ...x, loading: false, error: msg } : x))
    }
  }

  // 进入步骤 4 时拉取全部仓库
  useEffect(() => {
    if (step === 3) {
      modelGroups.forEach((_, idx) => { loadModelGroupFiles(idx) })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step])

  const cancelInstall = async () => {
    try { await window.pywebview.api.zero_cancel_install() } catch { /* 静默 */ }
  }

  if (loading) {
    return <div className="flex items-center justify-center p-20"><Loader2 className="animate-spin" /></div>
  }
  if (!wizard) {
    return <div className="p-8 text-center text-muted-foreground">{t('zero.loadFail')}</div>
  }

  const fmtSize = (n: number) => `${(n / 1073741824).toFixed(2)} GB`

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* 步骤条 */}
      <div className="flex items-center gap-1 border-b border-border bg-surface px-6 py-3">
        {STEPS.map((s, i) => (
          <div key={s} className="flex items-center gap-1">
            <div className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium ${
              i === step ? 'bg-primary text-primary-foreground'
              : i < step ? 'bg-primary/10 text-primary' : 'text-muted-foreground'
            }`}>
              {i < step ? <CheckCircle2 className="size-3.5" /> : <span>{i + 1}</span>}
              {s}
            </div>
            {i < STEPS.length - 1 && <ChevronRight className="text-muted-foreground size-3" />}
          </div>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        {/* ---- 步骤 1：位置 ---- */}
        {step === 0 && (
          <div className="mx-auto max-w-2xl space-y-4">
            <h2 className="text-lg font-semibold">{t('zero.step1Title')}</h2>
            <p className="text-muted-foreground text-sm">{t('zero.step1Hint')}</p>
            <div className="flex gap-2">
              <Input value={installDir} onChange={(e) => setInstallDir(e.target.value)} className="font-mono" />
              <Button variant="outline" onClick={pickFolder}>
                <FolderOpen className="size-4" />
              </Button>
            </div>
            <div className="rounded-md bg-warning/10 px-3 py-2 text-xs text-warning">
              {t('zero.step1Warning')}
            </div>

            {/* 共享文件夹设置（折叠） */}
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowShared(!showShared)}
              className="flex w-full items-center justify-between p-0 hover:bg-transparent"
            >
              <span className="text-sm font-medium">{t('zero.sharedTitle')}</span>
              <span className="text-muted-foreground text-xs">{showShared ? '−' : '+'}</span>
            </Button>
            {showShared && (
              <div className="space-y-4 rounded-md border border-border p-4">
                {/* 共享模型文件夹 */}
                <div className="space-y-2">
                  <p className="text-sm font-medium">{t('zero.sharedModelTitle')}</p>
                  <p className="text-muted-foreground text-xs">{t('zero.sharedModelHint')}</p>
                  {/* 自定义 models 总目录（根目录）：子目录不填时使用它的子目录 */}
                  <div className="flex items-center gap-2">
                    <span className="w-40 shrink-0 text-xs font-medium">{t('zero.sharedModelRoot')}</span>
                    <Input
                      value={sharedModelDir}
                      onChange={(e) => setSharedModelDir(e.target.value)}
                      placeholder="D:\\ComfyUI_Models"
                      className="h-8 font-mono text-xs"
                    />
                  </div>
                  <div className="space-y-1.5">
                    {wizard.modelPathKeys.map((k) => (
                      <div key={k.key} className="flex items-center gap-2">
                        <span className="w-40 shrink-0 truncate text-xs" title={k.label}>{k.label}</span>
                        <Input
                          value={modelPathMap[k.key] || ''}
                          onChange={(e) => setModelPathMap((prev) => ({ ...prev, [k.key]: e.target.value }))}
                          placeholder={sharedModelDir.trim()
                            ? `${sharedModelDir.replace(/[\\/]+$/, '')}\\${k.default?.replace(/^models[\\/]/, '') || k.key}`
                            : (k.default || '')}
                          className="h-8 font-mono text-xs"
                        />
                      </div>
                    ))}
                  </div>
                </div>
                {/* 工作区目录映射 */}
                <div className="space-y-2">
                  <p className="text-sm font-medium">{t('zero.workspaceTitle')}</p>
                  <p className="text-muted-foreground text-xs">{t('zero.workspaceHint')}</p>
                  <div className="space-y-1.5">
                    {wizard.workspaceKeys.map((k) => (
                      <div key={k.key} className="flex items-center gap-2">
                        <span className="w-40 shrink-0 text-xs">{k.label}</span>
                        <Input
                          value={workspaceMap[k.key] || ''}
                          onChange={(e) => setWorkspaceMap((prev) => ({ ...prev, [k.key]: e.target.value }))}
                          className="h-8 font-mono text-xs"
                        />
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* ---- 步骤 2：版本 ---- */}
        {step === 1 && (
          <div className="mx-auto max-w-3xl space-y-3">
            <h2 className="text-lg font-semibold">
              {t('zero.step2Title')} {wizard.tag && <span className="text-muted-foreground text-sm">({wizard.tag})</span>}
            </h2>
            <p className="text-muted-foreground text-sm">
              {wizard.gpuName
                ? t('zero.step2Gpu', { gpu: wizard.gpuName })
                : t('zero.step2NoGpu')}
            </p>
            <div className="space-y-2">
              {wizard.assets.map((a) => (
                <div
                  key={a.url}
                  onClick={() => setAssetUrl(a.url)}
                  className={`flex cursor-pointer items-center justify-between rounded-lg border p-3 transition-colors ${
                    assetUrl === a.url ? 'border-primary bg-primary/5' : 'hover:border-border/80'
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <CheckCircle2 className={`size-4 ${assetUrl === a.url ? 'text-primary' : 'text-muted-foreground/40'}`} />
                    <div>
                      <p className="text-sm font-medium">{a.name}</p>
                      {wizard.recommendedUrl === a.url && (
                        <p className="text-primary text-xs">
                          {t('zero.recommended')} {wizard.gpuName && `(${wizard.gpuName})`}
                        </p>
                      )}
                    </div>
                  </div>
                  <span className="text-muted-foreground text-sm">{fmtSize(a.size)}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ---- 步骤 3：注意力 ---- */}
        {step === 2 && (
          <div className="mx-auto max-w-3xl space-y-3">
            <h2 className="text-lg font-semibold">{t('zero.step3Title')}</h2>
            <p className="text-muted-foreground text-sm">{t('zero.step3Hint')}</p>
            <div className="space-y-2">
              {wizard.attentions.map((a) => (
                <div key={a.id} className="rounded-lg border p-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <Checkbox
                        checked={attSel[a.id]?.on || false}
                        onCheckedChange={() => toggleAttention(a.id)}
                        disabled={a.built_in}
                      />
                      <div>
                        <p className="text-sm font-medium">{a.name}</p>
                        {a.built_in && a.note && (
                          <p className="text-muted-foreground text-xs">{a.note}</p>
                        )}
                        {a.id === 'flash' && attSel[a.id]?.on && !wheelOptions.flash && (
                          <p className="text-muted-foreground text-xs">{t('zero.flashLoading')}</p>
                        )}
                      </div>
                    </div>
                    {a.built_in && (
                      <span className="rounded bg-green-500/10 px-2 py-0.5 text-xs text-green-600">
                        {t('zero.builtIn')}
                      </span>
                    )}
                  </div>
                  {a.id === 'flash' && attSel[a.id]?.on && wheelOptions.flash && (
                    <div className="mt-2 space-y-1 pl-8">
                      <p className="text-muted-foreground text-xs">{t('zero.flashPickVersion')}</p>
                      {wheelOptions.flash.map((w) => (
                        <label key={w.url} className="flex cursor-pointer items-center gap-2 text-xs">
                          <input
                            type="radio"
                            name="flash-wheel"
                            checked={attSel[a.id]?.wheelUrl === w.url}
                            onChange={() => setAttSel((prev) => ({
                              ...prev, flash: { on: true, wheelUrl: w.url, wheelSize: w.size },
                            }))}
                          />
                          <span className="font-mono">{w.name}</span>
                        </label>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
            <p className="text-muted-foreground text-xs">{t('zero.step3Compat')}</p>
          </div>
        )}

        {/* ---- 步骤 4：可选模型下载（按仓库/文件三行格式） ---- */}
        {step === 3 && (
          <div className="mx-auto max-w-4xl space-y-4">
            <h2 className="text-lg font-semibold">{t('zero.step4Title')}</h2>
            <div className="rounded-md bg-warning/10 px-3 py-2 text-sm text-warning">
              {t('zero.step4TooBig')}
            </div>

            {/* 共享模型根目录（优先于便携包 models） */}
            <div className="flex items-center gap-2">
              <span className="w-44 shrink-0 text-sm font-medium">{t('zero.sharedModelDir')}</span>
              <Input
                value={sharedModelDir}
                onChange={(e) => setSharedModelDir(e.target.value)}
                placeholder={t('zero.sharedModelDirHint')}
                className="h-9 font-mono text-xs"
              />
            </div>

            {modelGroups.map((g, gi) => (
              <div key={g.repo} className="rounded-lg border p-3">
                {/* 第一行：名称 + 完整仓库地址 */}
                <div className="flex items-center gap-2">
                  <Input
                    value={g.name}
                    onChange={(e) => setModelGroups((prev) => prev.map((x, i) => i === gi ? { ...x, name: sanitizeModelName(e.target.value) } : x))}
                    className="h-8 w-52 text-sm font-medium"
                    title={t('zero.nameRule')}
                  />
                  <Input
                    value={g.repo}
                    onChange={(e) => setModelGroups((prev) => prev.map((x, i) => i === gi ? { ...x, repo: e.target.value, files: [] } : x))}
                    className="h-8 min-w-0 flex-1 font-mono text-xs"
                    placeholder="https://hf-mirror.com/owner/repo/tree/main"
                  />
                  <a href={fullRepoUrl(g.repo)} target="_blank" rel="noopener noreferrer">
                    <Button variant="ghost" size="icon" title={t('zero.openRepo')}>
                      <ExternalLink className="size-4" />
                    </Button>
                  </a>
                  <Button variant="ghost" size="icon" title={t('zero.reloadFiles')} onClick={() => {
                    setModelGroups((prev) => prev.map((x, i) => i === gi ? { ...x, files: [], loading: false, error: undefined } : x))
                    setTimeout(() => loadModelGroupFiles(gi), 0)
                  }}>
                    <Loader2 className={`size-4 ${g.loading ? 'animate-spin text-primary' : ''}`} />
                  </Button>
                  <Button variant="ghost" size="icon" onClick={() => setModelGroups((prev) => prev.filter((_, i) => i !== gi))}>
                    <X className="size-4" />
                  </Button>
                </div>

                {/* 文件行 */}
                {g.loading && (
                  <p className="text-muted-foreground mt-2 flex items-center gap-2 text-xs">
                    <Loader2 className="size-3 animate-spin" /> {t('zero.loadingFiles')}
                  </p>
                )}
                {!g.loading && g.error && (
                  <p className="mt-2 text-xs text-destructive">{g.error}</p>
                )}
                {!g.loading && !g.error && g.files.length === 0 && (
                  <p className="text-muted-foreground mt-2 text-xs">{t('zero.noFiles')}</p>
                )}
                <div className="mt-2 space-y-2">
                  {g.files.map((f, fi) => {
                    // 保存位置：共享模型根目录优先，否则便携包内置 models
                    const base = sharedModelDir.trim().replace(/[\\/]+$/, '') || 'models'
                    return (
                      <div key={f.path} className="rounded border border-border/60 p-2">
                        <div className="flex items-center gap-2">
                          <Checkbox
                            checked={f.selected}
                            onCheckedChange={(checked) => setModelGroups((prev) => prev.map((x, i) => i === gi ? {
                              ...x, files: x.files.map((ff, j) => j === fi ? { ...ff, selected: !!checked } : ff),
                            } : x))}
                          />
                          <span className="min-w-0 flex-1 truncate font-mono text-xs" title={f.name}>{f.name}</span>
                          <span className="shrink-0 text-xs text-muted-foreground">
                            {f.size >= 1073741824 ? `${(f.size / 1073741824).toFixed(2)} GB` : `${(f.size / 1048576).toFixed(0)} MB`}
                          </span>
                          <a href={f.url.replace('/resolve/main/', '/blob/main/')} target="_blank" rel="noopener noreferrer">
                            <ExternalLink className="text-muted-foreground hover:text-primary size-3.5" />
                          </a>
                          <X
                            className="text-muted-foreground hover:text-destructive size-3.5 cursor-pointer"
                            onClick={() => setModelGroups((prev) => prev.map((x, i) => i === gi ? {
                              ...x, files: x.files.filter((_, j) => j !== fi),
                            } : x))}
                          />
                        </div>
                        <div className="mt-1 flex items-center gap-1.5 pl-6 text-[11px]">
                          <span className="shrink-0 text-muted-foreground">{t('zero.fileSaveTo')}:</span>
                          <span className="shrink-0 font-mono text-muted-foreground">{base}</span>
                          <span className="shrink-0 font-mono text-muted-foreground">\</span>
                          {/* 目录类型可编辑（默认分类不正确时可自定义，如 unet / vae / text_encoders） */}
                          <Input
                            value={f.dir}
                            onChange={(e) => setModelGroups((prev) => prev.map((x, i) => i === gi ? {
                              ...x,
                              files: x.files.map((ff, j) => j === fi ? { ...ff, dir: sanitizeModelName(e.target.value) } : ff),
                            } : x))}
                            className="h-6 w-32 font-mono text-[11px]"
                          />
                          <span className="shrink-0 font-mono text-muted-foreground">\</span>
                          <span className="truncate font-mono text-muted-foreground">{g.name}</span>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            ))}

            {/* 添加自定义仓库（自动识别文件） */}
            <div className="flex gap-2">
              <Input
                value={customRepoUrl}
                onChange={(e) => setCustomRepoUrl(e.target.value)}
                placeholder={t('zero.customRepoPlaceholder')}
                className="font-mono text-sm"
              />
              <Button
                variant="outline"
                onClick={async () => {
                  const repo = fullRepoUrl(customRepoUrl.trim())
                  if (!customRepoUrl.trim()) return
                  setCustomRepoUrl('')
                  // 名称从仓库标识提取并规范化
                  const rawName = repo.replace(/^https?:\/\/[^/]+\//, '').replace(/\/tree\/.*$/, '').split('/').pop() || 'Model'
                  const newItem: ModelGroup = { name: sanitizeModelName(rawName), repo, files: [], loading: false }
                  setModelGroups((prev) => [...prev, newItem])
                  // 立即拉取
                  const idx = modelGroups.length
                  setTimeout(() => loadModelGroupFiles(idx), 0)
                }}
              >
                {t('common.add')}
              </Button>
            </div>
          </div>
        )}

        {/* ---- 步骤 5：插件 ---- */}
        {step === 4 && (
          <div className="mx-auto max-w-3xl space-y-3">
            <h2 className="text-lg font-semibold">{t('zero.step5Title')}</h2>
            <div className="space-y-2">
              {plugins.map((p, idx) => (
                <div key={idx} className="flex items-center gap-2 rounded-lg border p-3">
                  <Puzzle className="text-muted-foreground size-4 shrink-0" />
                  <span className="w-44 truncate text-sm font-medium">{p.name}</span>
                  <span className="text-muted-foreground min-w-0 flex-1 truncate font-mono text-xs">{p.url}</span>
                  <Button variant="ghost" size="icon" onClick={() => setPlugins((prev) => prev.filter((_, i) => i !== idx))}>
                    <X className="size-4" />
                  </Button>
                </div>
              ))}
            </div>
            <div className="flex gap-2">
              <Input
                value={customPluginUrl}
                onChange={(e) => setCustomPluginUrl(e.target.value)}
                placeholder={t('zero.customPluginPlaceholder')}
                className="font-mono text-sm"
              />
              <Button
                variant="outline"
                onClick={() => {
                  const url = customPluginUrl.trim()
                  if (!url || !url.includes('github.com')) { toast.error(t('zero.invalidPluginUrl')); return }
                  const name = url.replace(/\/+$/, '').split('/').pop() || 'plugin'
                  setPlugins((prev) => [...prev, { name, url }])
                  setCustomPluginUrl('')
                }}
              >
                {t('common.add')}
              </Button>
            </div>
            <div className="rounded-lg border p-3">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium">{t('zero.workflowInstall')}</p>
                  <p className="text-muted-foreground text-xs">{t('zero.workflowInstallHint')}</p>
                </div>
                <Switch checked={workflowOn} onCheckedChange={setWorkflowOn} />
              </div>

              {/* 推荐工作流固定清单（官方 10 条，逐条选择） */}
              {workflowOn && (
                <div className="mt-3 space-y-1.5 border-t border-border/60 pt-3">
                  <p className="text-xs font-medium">{t('zero.recommendedWfTitle')}</p>
                  {recommendedWfs.map((w, wi) => (
                    <label key={w.url} className="flex cursor-pointer items-center gap-2 text-xs">
                      <Checkbox
                        checked={w.selected}
                        onCheckedChange={(checked) => setRecommendedWfs((prev) => prev.map((x, i) => i === wi ? { ...x, selected: !!checked } : x))}
                      />
                      <span className="truncate">{w.name}</span>
                      <a href={w.url} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()}>
                        <ExternalLink className="text-muted-foreground hover:text-primary size-3" />
                      </a>
                    </label>
                  ))}
                </div>
              )}

              {/* 自定义泛网址解析出的仓库条目 */}
              {workflowOn && wfGroups.length > 0 && (
                <div className="mt-3 space-y-3 border-t border-border/60 pt-3">
                  {wfGroups.map((g, gi) => (
                    <div key={g.repo}>
                      <div className="flex items-center justify-between">
                        <p className="text-xs font-medium">{g.name}</p>
                        <button
                          className="text-primary text-xs hover:underline"
                          onClick={() => setWfGroups((prev) => prev.map((x, i) => i === gi ? {
                            ...x, files: x.files.map((f) => ({ ...f, selected: true })),
                          } : x))}
                        >
                          {t('zero.wfSelectAll')}
                        </button>
                      </div>
                      <div className="mt-1.5 space-y-1 pl-3">
                        {g.files.map((f, fi) => (
                          <label key={f.relPath} className="flex cursor-pointer items-center gap-2 text-xs">
                            <Checkbox
                              checked={f.selected}
                              onCheckedChange={(checked) => setWfGroups((prev) => prev.map((x, i) => i === gi ? {
                                ...x, files: x.files.map((ff, j) => j === fi ? { ...ff, selected: !!checked } : ff),
                              } : x))}
                            />
                            <span className="truncate">{f.name}</span>
                            <span className="text-muted-foreground hidden truncate font-mono text-[10px] sm:inline">{f.relPath}</span>
                          </label>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* 自定义工作流：本地导入 / 泛网址 */}
              {workflowOn && (
                <div className="mt-3 space-y-2 border-t border-border/60 pt-3">
                  <p className="text-xs font-medium">{t('zero.customWfTitle')}</p>
                  {wfLoading && (
                    <p className="text-muted-foreground flex items-center gap-2 text-xs">
                      <Loader2 className="size-3 animate-spin" /> {t('zero.wfLoading')}
                    </p>
                  )}
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={async () => {
                        try {
                          const res = await window.pywebview.api.select_workflow_files()
                          if (res.success && res.paths) {
                            setLocalWfFiles((prev) => [...prev, ...res.paths!])
                          }
                        } catch { /* 用户取消 */ }
                      }}
                    >
                      {t('zero.importLocalWf')}
                    </Button>
                  </div>
                  <div className="flex gap-2">
                    <Input
                      value={customWfUrlInput}
                      onChange={(e) => setCustomWfUrlInput(e.target.value)}
                      placeholder={t('zero.customWfUrlPlaceholder')}
                      className="h-8 font-mono text-xs"
                    />
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={async () => {
                        const u = customWfUrlInput.trim()
                        if (!u) return
                        setCustomWfUrlInput('')
                        // 直接指向 .json 文件 → 直接下载
                        if (u.toLowerCase().includes('.json')) {
                          setCustomWfUrls((prev) => [...prev, u])
                          return
                        }
                        // 泛网址（仓库页等）：预解析，展开仓库内的工作流让用户选
                        try {
                          setWfLoading(true)
                          const res = await window.pywebview.api.zero_preview_workflows([u], installDir)
                          if (res.success && res.groups?.length) {
                            const g = res.groups[0]
                            if (g.files && g.files.length > 0) {
                              setWfGroups((prev) => [...prev, {
                                repo: g.name,
                                name: `${t('zero.customWfTitle')}: ${g.name}`,
                                files: g.files.map((f) => ({ ...f, selected: true })),
                                error: undefined,
                              }])
                            } else {
                              toast.warning(g.error || t('zero.wfNone'))
                            }
                          } else {
                            toast.warning(res.error_message || t('zero.wfNone'))
                          }
                        } catch (e) {
                          toast.error(e instanceof Error ? e.message : String(e))
                        } finally {
                          setWfLoading(false)
                        }
                      }}
                    >
                      {t('common.add')}
                    </Button>
                  </div>
                  {(localWfFiles.length > 0 || customWfUrls.length > 0) && (
                    <div className="space-y-1">
                      {localWfFiles.map((p) => (
                        <div key={p} className="flex items-center gap-2 text-xs">
                          <span className="min-w-0 flex-1 truncate font-mono">{p}</span>
                          <X className="text-muted-foreground hover:text-destructive size-3.5 cursor-pointer"
                             onClick={() => setLocalWfFiles((prev) => prev.filter((x) => x !== p))} />
                        </div>
                      ))}
                      {customWfUrls.map((u) => (
                        <div key={u} className="flex items-center gap-2 text-xs">
                          <span className="min-w-0 flex-1 truncate font-mono">{u}</span>
                          <X className="text-muted-foreground hover:text-destructive size-3.5 cursor-pointer"
                             onClick={() => setCustomWfUrls((prev) => prev.filter((x) => x !== u))} />
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}

        {/* ---- 步骤 6：安装进度 ---- */}
        {step === 5 && (
          <div className="mx-auto max-w-4xl space-y-3">
            <h2 className="text-lg font-semibold">{t('zero.step6Title')}</h2>
            {progress && (
              <>
                <div className="flex items-center gap-3">
                  {progress.running ? (
                    <Loader2 className="size-5 animate-spin text-primary" />
                  ) : progress.error ? (
                    <X className="text-destructive size-5" />
                  ) : (
                    <CheckCircle2 className="text-green-600 size-5" />
                  )}
                  <span className="font-medium">{progress.step}</span>
                  <span className="text-muted-foreground text-sm">{progress.percent}%</span>
                </div>
                {/* 双行进度：第一行总进度，第二行当前步骤进度 */}
                <div className="space-y-1.5">
                  <div className="flex items-center gap-2 text-xs">
                    <span className="text-muted-foreground w-14 shrink-0">总进度</span>
                    <Progress value={progress.percent} className="h-2" />
                    <span className="text-muted-foreground w-10 shrink-0 text-right">{progress.percent}%</span>
                  </div>
                  <div className="flex items-center gap-2 text-xs">
                    <span className="text-muted-foreground w-14 shrink-0">当前步骤</span>
                    <Progress value={progress.stepPercent ?? 0} className="h-2" />
                    <span className="text-muted-foreground w-10 shrink-0 text-right">{progress.stepPercent ?? 0}%</span>
                  </div>
                </div>
                {/* 当前文件下载详情（5s 刷新）——按组内字节总量展示 */}
                {progress.downloadInfo && (
                  <div className="text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-0.5 font-mono text-[11px]">
                    <span className="break-all">📄 {progress.downloadInfo.name}</span>
                    {(progress.downloadInfo.groupTotal ?? 0) > 0 ? (
                      <span title="已下载总大小 / 总大小">
                        总计 {((progress.downloadInfo.groupDone ?? 0) / 1048576).toFixed(1)} / {((progress.downloadInfo.groupTotal ?? 0) / 1048576).toFixed(1)} MB
                      </span>
                    ) : (
                      <span>{(progress.downloadInfo.done / 1048576).toFixed(1)} / {(progress.downloadInfo.total / 1048576).toFixed(1)} MB</span>
                    )}
                    <span>{(progress.downloadInfo.speed / 1048576).toFixed(2)} MB/s</span>
                  </div>
                )}
                {/* 当前正在安装的依赖（滚动展示） */}
                {depFeed.length > 0 && (
                  <div className="rounded-md border border-primary/30 bg-primary/5">
                    <div className="flex items-center gap-2 border-b border-primary/20 px-2.5 py-1.5 text-xs font-medium">
                      <Loader2 className="size-3.5 shrink-0 animate-spin text-primary" />
                      <span className="text-foreground">正在安装依赖</span>
                      <span className="text-muted-foreground ml-auto text-[11px]">{depFeed.length} 项</span>
                    </div>
                    <div className="max-h-24 overflow-y-auto px-2.5 py-1.5 font-mono text-[11px]">
                      {depFeed.map((d, i) => (
                        <div
                          key={`${d}-${i}`}
                          className={cn(
                            'truncate py-0.5',
                            i === depFeed.length - 1 ? 'text-primary' : 'text-muted-foreground'
                          )}
                        >
                          {d}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                <div className="h-96 overflow-y-auto rounded-lg border bg-muted p-3 font-mono text-xs select-text">
                  {progress.logs.map((l, i) => (
                    <div key={i} className="whitespace-pre-wrap break-all py-0.5">{l}</div>
                  ))}
                  <div ref={logEndRef} />
                </div>
                {progress.error && (
                  <div className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
                    {progress.error}
                  </div>
                )}
                <div className="flex justify-end gap-2">
                  {progress.running && (
                    <Button variant="outline" onClick={cancelInstall}>{t('common.cancel')}</Button>
                  )}
                  {progress.done && !progress.error && (
                    <Button onClick={handleGotoWorkspace} disabled={addingEnv}>
                      {addingEnv ? <Loader2 className="mr-2 size-4 animate-spin" /> : <PackageOpen className="mr-2 size-4" />}
                      {t('zero.gotoWorkspace')}
                    </Button>
                  )}
                </div>
              </>
            )}
          </div>
        )}
      </div>

      {/* 底部导航 */}
      {step < 5 && (
        <div className="flex items-center justify-between border-t border-border bg-surface px-6 py-3">
          <Button variant="outline" onClick={() => setStep((s) => Math.max(0, s - 1))} disabled={step === 0}>
            <ChevronLeft className="mr-1 size-4" />
            {t('zero.prev')}
          </Button>
          {step < 4 ? (
            <div className="flex items-center gap-2">
              {/* 步骤 4 专属：跳过模型下载 */}
              {step === 3 && (
                <Button
                  onClick={() => {
                    // 清空全部勾选，不下载任何模型
                    setModelGroups((prev) => prev.map((g) => ({
                      ...g, files: g.files.map((f) => ({ ...f, selected: false })),
                    })))
                    setStep(4)
                  }}
                >
                  {t('zero.skipModels')}
                </Button>
              )}
              <Button variant="outline" onClick={() => setStep((s) => Math.min(4, s + 1))} disabled={!canNext()}>
                {t('zero.next')}
                <ChevronRight className="ml-1 size-4" />
              </Button>
            </div>
          ) : (
            <Button onClick={startInstall}>
              <Download className="mr-2 size-4" />
              {t('zero.confirmInstall')}
            </Button>
          )}
        </div>
      )}
    </div>
  )
}
