import { useTranslation } from 'react-i18next'
import { Info } from 'lucide-react'
import { Card } from '@/components/ui/Card'

export function AboutSection() {
  const { t } = useTranslation()

  return (
    <Card className="flex flex-col p-5">
      {/*
        标题与标语同一行，中间空 12 个字符（用户明确要求）。
        用 gap-x-[12ch] 而不是 ml-[12ch]：两者在同一行时效果一致，
        但空间不足时 gap 会触发 flex-wrap 正常换行，
        而 ml 会把标语直接顶出容器（窄窗下完全看不见）。
        gap-y-1 保证换行后的行间距不至于贴太紧。
      */}
      <div className="mb-2 flex flex-wrap items-baseline gap-x-[12ch] gap-y-1">
        <h2 className="flex items-center gap-2 text-base font-semibold text-foreground">
          <Info className="size-4 text-primary" />
          {t('about.projectIntro.title')}
        </h2>
        <span className="text-sm text-muted-foreground">
          {t('about.projectIntro.slogan')}
        </span>
      </div>
      {/* 去除空行，改用 1.2 倍段后间距 */}
      <div className="text-sm leading-relaxed text-muted-foreground">
        <p className="mb-[1.2em]">{t('about.projectIntro.description1')}</p>
        <p>{t('about.projectIntro.description2')}</p>
      </div>
    </Card>
  )
}

export default AboutSection
