import { useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useLocation } from 'react-router-dom'
import { Plus, Monitor, Rocket } from 'lucide-react'
import { useEnvStore } from '@/stores/useEnvStore'
import { useToast } from '@/hooks/useToast'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui'

interface EnvRequiredGuideProps {
  icon?: React.ReactNode
  title?: string
  description?: string
  className?: string
}

export function EnvRequiredGuide({ 
  icon, 
  title, 
  description,
  className 
}: EnvRequiredGuideProps) {
  const { t } = useTranslation()
  const { environments, currentEnvId, createEnvironment } = useEnvStore()
  const { success, error: showError } = useToast()
  const navigate = useNavigate()
  const location = useLocation()

  const noEnvironment = environments.length === 0 || !currentEnvId
  // 标题栏「添加环境」强制进入欢迎选择模式（即使已有环境）
  const forceWelcome = (location.state as { showEnvWelcome?: boolean } | null)?.showEnvWelcome === true
  const welcomeMode = noEnvironment || forceWelcome

  // 显示「0基础安装」入口
  const goZeroInstall = useCallback(() => {
    navigate('/dependency', { state: { tab: 'zero-install' }, replace: true })
  }, [navigate])

  const handleAddEnvironment = useCallback(async () => {
    try {
      let selectedPath: string | undefined

      if (window.pywebview?.api?.select_directory) {
        const response = await window.pywebview.api.select_directory()
        if (!response.success || !response.path) {
          return
        }
        selectedPath = response.path
        await new Promise(resolve => setTimeout(resolve, 300))
      } else {
        const path = prompt(t('titleBar.env.inputPathDev'), 'C:\\ComfyUI-New')
        if (!path) {
          return
        }
        selectedPath = path
      }

      await createEnvironment(selectedPath)
      // 导入环境后默认进入工作台标签页
      navigate('/workspace', { replace: true })
      success(t('env.message.createSuccess'))
    } catch (error) {
      console.error('Failed to create environment:', error)
      const errorMessage = error instanceof Error ? error.message : t('env.message.createFailed')
      showError(errorMessage)
    }
  }, [createEnvironment, t, success, showError])

  // 仅在"既没有环境、也不在强制欢迎模式"时才不渲染。
  // 注意：标题栏「添加环境」带着 showEnvWelcome 进来（此时可能已有环境），
  // 若这里按 noEnvironment 早退 return null，整页会变成空白。
  if (!noEnvironment && !forceWelcome) {
    return null
  }

  const displayTitle = title || (welcomeMode
    ? t('env.guide.addFirst')
    : t('env.guide.selectOne'))

  const displayDescription = description || (welcomeMode
    ? t('env.guide.noEnvDesc')
    : t('env.guide.selectEnvDesc'))

  return (
    <div className={cn("flex h-full flex-col items-center justify-center p-8", className)}>
      <div
        onClick={handleAddEnvironment}
        className="w-full max-w-md rounded-2xl border border-border bg-surface p-10 cursor-pointer hover:border-primary/50 hover:shadow-soft-md transition-all group"
      >
        <div className="flex justify-center mb-8">
          <div className="flex size-16 items-center justify-center rounded-full bg-primary/10 group-hover:bg-primary/20 transition-colors">
            {icon || <Monitor className="size-8 text-primary" />}
          </div>
        </div>

        <h2 className="text-2xl font-bold text-center mb-4">
          {displayTitle}
        </h2>

        <p className="text-muted-foreground text-center mb-8 leading-relaxed">
          {displayDescription}
        </p>

        <div className="flex flex-col items-center gap-3">
          <Button
            size="lg"
            className="gap-2"
          >
            <Plus className="size-5" />
            {welcomeMode ? t('env.guide.addFirstEnv') : t('env.guide.selectEnv')}
          </Button>
          {welcomeMode && (
            <>
              <span className="text-muted-foreground text-xs">{t('env.guide.orDivider')}</span>
              <Button
                size="lg"
                variant="outline"
                className="gap-2 border-primary/40 text-primary hover:bg-primary/10"
                onClick={(e) => {
                  e.stopPropagation()
                  goZeroInstall()
                }}
              >
                <Rocket className="size-5" />
                {t('env.guide.zeroInstall')}
              </Button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

export function useEnvRequiredGuide(options?: EnvRequiredGuideProps) {
  const { environments, currentEnvId } = useEnvStore()
  const location = useLocation()
  const noEnvironment = environments.length === 0 || !currentEnvId
  const forceWelcome = (location.state as { showEnvWelcome?: boolean } | null)?.showEnvWelcome === true

  // 与组件本体保持一致：强制欢迎模式下即使已有环境也要显示
  if (!noEnvironment && !forceWelcome) {
    return null
  }

  return <EnvRequiredGuide {...options} />
}
