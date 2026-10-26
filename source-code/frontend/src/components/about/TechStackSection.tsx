import { useTranslation } from 'react-i18next'
import { Code2 } from 'lucide-react'
import { Card } from '@/components/ui/Card'

/** 核心技术栈清单（与 source-code/backend/requirements.txt、frontend/package.json 实际依赖同步） */
export const techStackItems = [
  {
    name: 'Python 3.13.x',
    bgColor: 'bg-primary/10',
    borderColor: 'border-primary/30',
    textColor: 'text-primary',
  },
  {
    name: 'Flask 3.x',
    bgColor: 'bg-primary/10',
    borderColor: 'border-primary/30',
    textColor: 'text-primary',
  },
  {
    name: 'pywebview 6.x',
    bgColor: 'bg-primary/10',
    borderColor: 'border-primary/30',
    textColor: 'text-primary',
  },
  {
    name: 'pythonnet 3.x',
    bgColor: 'bg-primary/10',
    borderColor: 'border-primary/30',
    textColor: 'text-primary',
  },
  {
    name: 'PyInstaller 6.x',
    bgColor: 'bg-primary/10',
    borderColor: 'border-primary/30',
    textColor: 'text-primary',
  },
  {
    name: 'React 19.x',
    bgColor: 'bg-info/10',
    borderColor: 'border-info/30',
    textColor: 'text-info',
  },
  {
    name: 'TypeScript 5.9.x',
    bgColor: 'bg-info/10',
    borderColor: 'border-info/30',
    textColor: 'text-info',
  },
  {
    name: 'Vite 7.x',
    bgColor: 'bg-info/10',
    borderColor: 'border-info/30',
    textColor: 'text-info',
  },
  {
    name: 'Zustand 5.x',
    bgColor: 'bg-info/10',
    borderColor: 'border-info/30',
    textColor: 'text-info',
  },
  {
    name: 'Tailwind CSS 3.4.x',
    bgColor: 'bg-success/10',
    borderColor: 'border-success/30',
    textColor: 'text-success',
  },
  {
    name: 'ECharts 6.x',
    bgColor: 'bg-warning/10',
    borderColor: 'border-warning/30',
    textColor: 'text-warning',
  },
  {
    name: 'React Flow 12.x',
    bgColor: 'bg-warning/10',
    borderColor: 'border-warning/30',
    textColor: 'text-warning',
  },
]

export function TechStackSection() {
  const { t } = useTranslation()

  return (
    <Card className="flex h-full flex-col p-5">
      <h2 className="mb-3 flex items-center gap-2 text-base font-semibold text-foreground">
        <Code2 className="size-4 text-success" />
        {t('about.techStack.title')}
      </h2>
      <div className="flex flex-1 flex-wrap content-start gap-2">
        {techStackItems.map((item) => (
          <span
            key={item.name}
            className={`rounded-md px-2.5 py-0.5 ${item.bgColor} ${item.textColor} border ${item.borderColor} font-mono text-xs`}
          >
            {item.name}
          </span>
        ))}
      </div>
    </Card>
  )
}

export default TechStackSection
