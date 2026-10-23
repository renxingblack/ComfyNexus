/**
 * 工具箱组件 - 终端和日志管理
 *
 * 功能：
 * - 打开终端（4 种：cmd / PowerShell / Windows Terminal / VS2022 x64 Native Tools）
 * - 清空日志
 */

import { useTranslation } from 'react-i18next'
import { toast } from '@/utils/toast'
import { useDependencyStore } from '@/stores/useDependencyStore'
import { Button } from '@/components/ui/Button'
import {
  Terminal,
  Trash2,
  SquareTerminal,
  AppWindow,
  Hammer,
} from 'lucide-react'

type TerminalKind = 'cmd' | 'powershell' | 'windowsterminal' | 'vs2022'

export default function ToolboxSection() {
  const { t } = useTranslation()
  const {
    isExecuting,
    openTerminalKind,
    clearLogs,
  } = useDependencyStore()

  const terminalItems: Array<{
    kind: TerminalKind
    icon: React.ReactNode
    label: string
  }> = [
    { kind: 'cmd', icon: <SquareTerminal className="size-4" />, label: t('dependency.openCmd') },
    { kind: 'powershell', icon: <Terminal className="size-4" />, label: t('dependency.openPowerShell') },
    { kind: 'windowsterminal', icon: <AppWindow className="size-4" />, label: t('dependency.openWindowsTerminal') },
    { kind: 'vs2022', icon: <Hammer className="size-4" />, label: t('dependency.openVS2022') },
  ]

  const handleOpenTerminal = async (kind: TerminalKind) => {
    try {
      await openTerminalKind(kind)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    }
  }

  const handleClearLogs = () => {
    clearLogs()
  }

  return (
    <div className="dark:border-dark-border dark:bg-dark-secondary border-gray-200 bg-white rounded-lg border p-4">
      <h3 className="dark:text-dark-text-primary text-gray-900 mb-4 font-semibold">{t("dependency.toolbox")}</h3>

      <div className="space-y-2">
        {/* 终端启动器：2×2 网格 */}
        <div className="grid grid-cols-2 gap-2">
          {terminalItems.map((item) => (
            <Button
              key={item.kind}
              variant="outline"
              className="justify-start"
              onClick={() => handleOpenTerminal(item.kind)}
              disabled={isExecuting}
              title={t('dependency.terminalCwdHint')}
            >
              {item.icon}
              <span className="truncate">{item.label}</span>
            </Button>
          ))}
        </div>
        <p className="text-muted-foreground text-xs">{t('dependency.terminalCwdHint')}</p>

        {/* 清空日志按钮 */}
        <Button
          variant="outline"
          className="w-full justify-start"
          onClick={handleClearLogs}
          disabled={isExecuting}
        >
          <Trash2 className="mr-2 size-4" />
          清空日志
        </Button>
      </div>
    </div>
  )
}
