/**
 * CreatorRecommendationGrid 组件
 * 展示推荐的 ComfyUI 创作者
 * 
 * 新设计：
 * - 5列布局（Bento Grid 风格）
 * - 2排共10个博主
 * - 优化间距
 */

import React, { useEffect } from 'react'
import { cn } from '@/lib/utils'
import { Creator } from '@/types/home'
import { CreatorCard } from './CreatorCard'

/**
 * CreatorRecommendationGrid 组件属性
 */
export interface CreatorRecommendationGridProps {
  /** 自定义样式类名 */
  className?: string
}

/**
 * 推荐创作者数据
 * 使用现有首页的博主数据，去掉 Replicate 和 RunwayML
 */
const RECOMMENDED_CREATORS: Creator[] = [
  {
    id: 1,
    name: '诶-阿伟哥',
    avatar: '/avatars/weige.jpg',
    description: 'ComfyUI最好用的提示词插件作者',
    link: 'https://space.bilibili.com/520680644',
    platform: 'bilibili'
  },
  {
    id: 2,
    name: '乔巴大战Comfyui',
    avatar: '/avatars/qb.jpg',
    description: 'ComfyUI教程创作者',
    link: 'https://space.bilibili.com/522625412',
    platform: 'bilibili'
  },
  {
    id: 3,
    name: '早点睡觉',
    avatar: '/avatars/hhsj.jpg',
    description: 'ComfyUI教程创作者',
    link: 'https://space.bilibili.com/628353217',
    platform: 'bilibili'
  },
  {
    id: 11,
    name: '小珠光',
    avatar: '/avatars/xzhg.jpg',
    description: 'ComfyUI 化神级插件作者',
    link: 'https://space.bilibili.com/477349877',
    platform: 'bilibili'
  },
  {
    id: 12,
    name: '黑鹤001',
    avatar: '/avatars/hh001.jpg',
    description: 'ComfyUI 教程与工作流分享',
    link: 'https://space.bilibili.com/515231056',
    platform: 'bilibili'
  },
  {
    id: 13,
    name: '机智罗_LX',
    avatar: '/avatars/jzlx.jpg',
    description: '帮助新手玩转 ComfyUI',
    link: 'https://space.bilibili.com/302329373',
    platform: 'bilibili'
  },
  {
    id: 14,
    name: '班长captain',
    avatar: '/avatars/bzcaptain.jpg',
    description: 'ComfyUI 教程创作者',
    link: 'https://space.bilibili.com/15838129',
    platform: 'bilibili'
  },
  {
    id: 15,
    name: '8g显存小黑的折腾日记',
    avatar: '/avatars/8gxh.jpg',
    description: '低显存玩转 AI 绘图的折腾日常',
    link: 'https://space.bilibili.com/96854764',
    platform: 'bilibili'
  },
  {
    id: 16,
    name: '生活作弊码',
    avatar: '/avatars/shzpm.jpg',
    description: '把复杂技术变简单的干货 UP 主',
    link: 'https://space.bilibili.com/3546724018686465',
    platform: 'bilibili'
  },
  {
    id: 17,
    name: '多少会点不精',
    avatar: '/avatars/dshd.jpg',
    description: '本地部署模型 / ComfyUI / 编程杂谈',
    link: 'https://space.bilibili.com/1132964473',
    platform: 'bilibili'
  },
  {
    id: 4,
    name: '六斤 AIGC',
    avatar: '/avatars/z.jpg',
    description: 'AIGC视频创作者',
    link: 'https://www.douyin.com/user/MS4wLjABAAAA4WH_ahqk0gUf-kMv6VSzY4QGWX-UazlNPQYk_gVgik8Bd4_PjOXwVZxBEputZLvP',
    platform: 'douyin'
  },
  {
    id: 5,
    name: '初阳AIAgent',
    avatar: '/avatars/cy.jpg',
    description: 'AIGC视频创作者',
    link: 'https://space.bilibili.com/3546954344696042',
    platform: 'bilibili'
  },
  {
    id: 6,
    name: 'ComfyUI 官方',
    avatar: '/avatars/comfyui-official.jpg',
    description: 'ComfyUI 官方团队',
    link: 'https://github.com/comfyanonymous/ComfyUI',
    platform: 'github'
  },
  {
    id: 7,
    name: 'Civitai',
    avatar: '/avatars/civitai.jpg',
    description: 'AI 模型分享社区',
    link: 'https://civitai.com',
    platform: 'web'
  },
  {
    id: 8,
    name: 'Hugging Face',
    avatar: '/avatars/huggingface.jpg',
    description: 'AI 模型和数据集平台',
    link: 'https://huggingface.co',
    platform: 'web'
  },
  {
    id: 9,
    name: 'Midjourney',
    avatar: '/avatars/midjourney.jpg',
    description: 'AI 图像生成社区',
    link: 'https://www.midjourney.com',
    platform: 'web'
  },
  {
    id: 10,
    name: 'Leonardo.AI',
    avatar: '/avatars/leonardo.jpg',
    description: 'AI 艺术创作平台',
    link: 'https://leonardo.ai',
    platform: 'web'
  },
  {
    id: 101,
    name: 'AIArt.pics',
    avatar: '',
    description: 'AI 图像提示词与作品画廊',
    link: 'https://aiart.pics/',
    platform: 'web'
  },
  {
    id: 102,
    name: 'PromptHub',
    avatar: '',
    description: 'AI 绘画提示词聚合社区',
    link: 'https://prompthub.lilu.org.cn/',
    platform: 'web'
  },
  {
    id: 103,
    name: 'GPT-Image2',
    avatar: '',
    description: 'GPT 图像生成提示词库',
    link: 'https://gpt-image2.canghe.ai/',
    platform: 'web'
  },
  {
    id: 104,
    name: 'OpenNana 提示词画廊',
    avatar: '',
    description: '精选 Awesome 提示词合集',
    link: 'https://opennana.com/awesome-prompt-gallery',
    platform: 'web'
  },
  {
    id: 105,
    name: 'AI 视频提示词库',
    avatar: '',
    description: 'LanShu Awesome AI Video 提示词浏览器',
    link: 'https://lanshu-awesome-ai-video-kit.lank.workers.dev/tools/prompt-browser/',
    platform: 'web'
  },
  {
    id: 106,
    name: 'Awesome AI Video Prompts',
    avatar: '',
    description: 'AI 视频提示词精选清单',
    link: 'https://manallen.github.io/awesome-ai-video-prompts/',
    platform: 'web'
  }
]

/**
 * CreatorRecommendationGrid 组件
 * 显示推荐的 ComfyUI 创作者网格（5列布局，2排）
 */
export const CreatorRecommendationGrid: React.FC<CreatorRecommendationGridProps> = ({
  className
}) => {
  // 自定义创作者（手动添加）
  const [customCreators, setCustomCreators] = React.useState<Creator[]>([])
  const [adding, setAdding] = React.useState(false)
  const [addLink, setAddLink] = React.useState('')
  const [addName, setAddName] = React.useState('')

  // 加载自定义创作者
  React.useEffect(() => {
    if (!window.pywebview?.api) return
    window.pywebview.api.list_custom_creators().then((res) => {
      if (res?.success && res.creators) {
        setCustomCreators(res.creators as Creator[])
      }
    }).catch(() => {})
  }, [])

  const allCreators = React.useMemo(
    () => [...RECOMMENDED_CREATORS, ...customCreators],
    [customCreators]
  )

  // 挂载即触发 B 站博主更新时间后台预取（幂等，缓存持久化）
  useEffect(() => {
    if (!window.pywebview?.api) return
    const mids = allCreators
      .filter((c) => c.platform === 'bilibili')
      .map((c) => (c.link.match(/space\.bilibili\.com\/(\d+)/) || [])[1])
      .filter(Boolean)
    if (mids.length > 0) {
      window.pywebview.api.prefetch_bilibili_updates(mids).catch(() => {})
    }
  }, [allCreators])

  const handleAdd = async () => {
    const link = addLink.trim()
    const name = addName.trim()
    if (!link || !name || !window.pywebview?.api) return
    const res = await window.pywebview.api.add_custom_creator(name, link)
    if (res?.success) {
      // 后端已抓取一次头像/介绍并落盘缓存（后续直接读本地，不再下载）
      setCustomCreators((prev) => [...prev, {
        id: res.id || Date.now(),
        name,
        avatar: res.avatar || '',
        description: res.description || '',
        link,
        platform: link.includes('bilibili') ? 'bilibili' : 'web',
      } as Creator])
      setAddLink('')
      setAddName('')
      setAdding(false)
    }
  }

  return (
    <div className="space-y-3">
      <div
        className={cn(
          'grid grid-cols-5 gap-x-4 gap-y-5',
          className
        )}
      >
        {allCreators.map(creator => (
          <CreatorCard key={creator.id} creator={creator} />
        ))}
      </div>

      {/* 手动添加推荐关注 */}
      <div className="flex items-center gap-2 pt-1">
        {adding ? (
          <>
            <input
              value={addName}
              onChange={(e) => setAddName(e.target.value)}
              placeholder="博主名称"
              className="rounded-lg border border-border-subtle bg-surface px-3 py-1.5 text-sm w-40"
            />
            <input
              value={addLink}
              onChange={(e) => setAddLink(e.target.value)}
              placeholder="主页链接（如 https://space.bilibili.com/15838129）"
              className="rounded-lg border border-border-subtle bg-surface px-3 py-1.5 text-sm flex-1"
            />
            <button
              onClick={handleAdd}
              className="rounded-lg bg-primary px-3 py-1.5 text-sm text-white hover:bg-primary/90"
            >
              确认添加
            </button>
            <button
              onClick={() => setAdding(false)}
              className="rounded-lg border border-border-subtle px-3 py-1.5 text-sm"
            >
              取消
            </button>
          </>
        ) : (
          <button
            onClick={() => setAdding(true)}
            className="flex items-center gap-1 rounded-lg border border-dashed border-border px-3 py-1.5 text-sm text-text-secondary hover:border-primary hover:text-primary transition-colors"
          >
            + 手动添加推荐关注
          </button>
        )}
      </div>
    </div>
  )
}

export default React.memo(CreatorRecommendationGrid)
