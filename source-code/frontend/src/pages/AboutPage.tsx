import { useTranslation } from 'react-i18next'
import { useAppVersion } from '@/hooks/useAppVersion'
import {
  AboutHeader,
  AboutSection,
  ChangelogSection,
  Disclaimer,
  SponsorSection,
  TelegramSection,
} from '@/components/about'

export default function AboutPage() {
  const { t } = useTranslation()
  const { version } = useAppVersion()

  return (
    /**
     * 关于页有两种布局，由 `roomy` 断点（宽 >=768 且 高 >=720）切换：
     *
     * 【roomy】3 列网格：左列 2/3（关于项目 + 更新日志）、右列 1/3（支持 + TG）。
     *   空间充足时整页不滚动，各板块铺满一屏，视觉最紧凑。
     *
     * 【compact】单列自然排布，每块按内容/固定高度取高，整页滚动。
     *
     * ---- 为什么不靠「压缩」来适配小窗 ----
     * 旧实现在两种模式下都让 flex 无限压缩板块（`min-h-0` + `flex-1` 无下限），
     * 于是窗口一变矮，【更新日志】就被压到 200px 出头、内部滚动区只剩 100px 左右，
     * 看起来「挤在一起、看不到内容、也没法下拉」—— 这正是用户报的问题。
     * 现在给更新日志一个 min-h-[340px] 的可读下限，压到下限就停止，不再继续扁。
     */
    <div className="h-full overflow-y-auto" data-page="about">
      {/*
        内层只给 min-h-full，**roomy 时才补 h-full**：
          · compact：高度 auto + min-h-full → 内容超出一屏时这层自然长高，
            把 footer 一起往下推，根容器的 overflow-y-auto 才有东西可滚。
          · roomy  ：必须回 h-full 锁定一屏。否则下面 ChangelogSection 的 flex-1
            失去「可分配的剩余空间」这个前提，会退化成按内容取高 ——
            实测日志全文 4.9 万像素，卡片直接涨到 49142px（本轮踩到的真实回归）。
      */}
      <div className="flex min-h-full flex-col gap-4 p-6 md:p-8 roomy:h-full">
        {/* 页头：Logo + 标题/版本 + 两个项目地址(上下) + 核心技术栈 + 检查更新 */}
        <div className="shrink-0">
          <AboutHeader version={version} />
        </div>

        {/*
          主体：
            roomy   → 3 列网格（左 2/3 / 右 1/3）。
                      grid-rows 必须用 `[1fr]` 而不是 `grid-rows-1`：
                      后者展开是 repeat(1, minmax(0,1fr))，行高下限是 0，
                      行会被压到 0 而内容溢出到网格外却不产生滚动；
                      `[1fr]` 等价于 minmax(auto,1fr)，下限是内容最小高度，才会正确把父级撑高。
            compact → 单列自然排布。
        */}
        <div className="flex flex-col gap-4 roomy:grid roomy:min-h-0 roomy:flex-1 roomy:grid-cols-3 roomy:grid-rows-[1fr]">
          {/* 左列（roomy）/ 主体流（compact） */}
          <div className="flex flex-col gap-4 roomy:min-h-0 roomy:col-span-2">
            <div className="shrink-0">
              <AboutSection />
            </div>

            {/*
              更新日志（组件内不写高度，必须由这里给）：
                compact：固定 h-[420px] 内部滚动。父级是自然流，不能用 flex-1
                         —— 不定高容器里 flex-1 会塌成内容高度，长日志把整页拖到极长。
                roomy  ：h-auto + flex-1 吃掉左列剩余空间，并用 min-h-[380px] 兜底。
              说明：h-[420px] 与 roomy:h-auto 是「同一属性、不同断点」的合法组合，
              Tailwind 会把带断点的规则排在无断点之后，所以 roomy 下 h-auto 生效。
              （这与 h-full / h-[420px] 两个无断点类互撞的情况不同，那种是不可预期的。）
            */}
            <ChangelogSection className="h-[420px] shrink-0 roomy:h-auto roomy:min-h-[340px] roomy:flex-1" />
          </div>

          {/* 支持项目 / 加入TG群组：roomy 时占右侧整列；compact 时排在更新日志之后。
              roomy 下必须 min-h-0 + overflow-y-auto：右列两张卡总高约 526px，
              小一点的 roomy 窗口装不下，需要自己内部滚动而不是撑破网格行。 */}
          <div className="flex flex-col gap-4 roomy:min-h-0 roomy:overflow-y-auto roomy:col-span-1">
            <SponsorSection />
            <TelegramSection />
          </div>
        </div>

        {/* 页脚：免责声明 + 版权（单行） */}
        <footer className="shrink-0 space-y-2 border-t border-border pt-3 text-center">
          <Disclaimer />
          <p className="text-xs text-muted-foreground">
            {t('about.copyright')} · {t('about.poweredBy')}
          </p>
        </footer>
      </div>
    </div>
  )
}
