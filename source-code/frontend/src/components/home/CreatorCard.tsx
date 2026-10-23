/**
 * CreatorCard 组件
 * 用于显示推荐创作者信息的卡片
 * 
 * Bento Grid 设计：
 * - 深浅色主题适配
 * - 更紧凑的布局
 * - 优化悬停效果
 */

import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Video, Youtube, Github, Globe, LucideIcon, Music, Clock } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Creator } from '@/types/home'
import { useBilibiliLastUpdate } from '@/hooks/useBilibiliLastUpdate'

/** 毫秒差 → "X天X小时X分钟X秒" */
function formatDuration(ms: number): string {
  if (ms < 0) return '0秒'
  const s = Math.floor(ms / 1000)
  const days = Math.floor(s / 86400)
  const hours = Math.floor((s % 86400) / 3600)
  const minutes = Math.floor((s % 3600) / 60)
  const seconds = s % 60
  if (days > 0) return `${days}天${hours}小时${minutes}分钟${seconds}秒`
  return `${hours}小时${minutes}分钟${seconds}秒`
}

export interface CreatorCardProps {
  creator: Creator
}

const PLATFORM_ICONS: Record<string, LucideIcon> = {
  bilibili: Video,
  youtube: Youtube,
  github: Github,
  web: Globe,
  douyin: Music,
}

const getPlatformIcon = (platform: string): LucideIcon => {
  return PLATFORM_ICONS[platform.toLowerCase()] || Globe
}

const getAvatarColor = (name: string): string => {
  const colors = [
    'bg-primary',
    'bg-success',
    'bg-info',
    'bg-danger',
    'bg-warning',
    'bg-primary/80',
    'bg-info/80',
    'bg-danger/80',
  ]
  const index = name.split('').reduce((acc, char) => acc + char.charCodeAt(0), 0) % colors.length
  return colors[index]
}

const getInitial = (name: string): string => {
  if (!name) return '?'
  if (/[\u4e00-\u9fa5]/.test(name[0])) {
    return name[0]
  }
  return name[0].toUpperCase()
}

export const CreatorCard: React.FC<CreatorCardProps> = ({ creator }) => {
  const { t } = useTranslation()
  const PlatformIcon = getPlatformIcon(creator.platform)
  const [imageError, setImageError] = useState(false)
  const [imageLoaded, setImageLoaded] = useState(false)
  // 所有 bilibili 博主动态查询最新投稿时间（含倒计时 tooltip）；
  // 查询失败（限流）时静默隐藏。官网/GitHub 类博主不显示该功能。
  const { pubdate: biliPubdate } = useBilibiliLastUpdate(
    creator.link,
    creator.platform
  )
  const [biliNow, setBiliNow] = useState(Date.now())
  // 倒计时每分钟刷新一次（秒级跳动意义不大且省渲染）
  useEffect(() => {
    if (!biliPubdate) return
    const id = setInterval(() => setBiliNow(Date.now()), 60000)
    return () => clearInterval(id)
  }, [biliPubdate])
  const biliTimeDiff = biliPubdate
    ? formatDuration(biliNow - biliPubdate * 1000)
    : null

  const showBiliCountdown = creator.platform === 'bilibili' && !!biliTimeDiff

  const handleClick = () => {
    window.open(creator.link, '_blank', 'noopener,noreferrer')
  }

  const handleImageError = () => {
    setImageError(true)
  }

  const handleImageLoad = () => {
    setImageLoaded(true)
  }

  const showPlaceholder = !creator.avatar || imageError

  return (
    <div
      onClick={handleClick}
      className={cn(
        'flex items-center gap-4 p-5 rounded-2xl w-full',
        'bg-surface-hover',
        'border border-border-subtle',
        'hover:bg-surface-hover/80 hover:border-border',
        'transition-all duration-200 cursor-pointer group',
        'hover:-translate-y-1 hover:shadow-lg hover:shadow-border-subtle/50'
      )}
    >
      <div className="relative shrink-0">
        {showPlaceholder ? (
          <div
            className={cn(
              'w-[52px] h-[52px] rounded-full',
              'flex items-center justify-center',
              'text-white font-bold text-lg',
              'ring-2 ring-border-subtle',
              'group-hover:ring-primary',
              'transition-all duration-200',
              getAvatarColor(creator.name)
            )}
          >
            {getInitial(creator.name)}
          </div>
        ) : (
          <img
            src={creator.avatar}
            alt={creator.name}
            loading="lazy"
            onError={handleImageError}
            onLoad={handleImageLoad}
            className={cn(
              'w-[52px] h-[52px] rounded-full object-cover',
              'ring-2 ring-border-subtle',
              'group-hover:ring-primary',
              'transition-all duration-200',
              !imageLoaded && 'opacity-0'
            )}
          />
        )}
        
        <div
          className={cn(
            'absolute -bottom-0.5 -right-0.5',
            'bg-surface rounded-full p-1.5',
            'ring-2 ring-surface'
          )}
        >
          <PlatformIcon className="text-muted-foreground size-3.5" />
        </div>

        {showBiliCountdown && (
          <div
            className={cn(
              'absolute -top-12 left-1/2 -translate-x-1/2 z-10',
              'px-3 py-1.5 rounded-lg',
              'bg-gradient-to-r from-primary to-info',
              'text-white text-xs font-medium whitespace-nowrap',
              'shadow-lg shadow-primary/30',
              'opacity-0 group-hover:opacity-100',
              'transition-opacity duration-200',
              'pointer-events-none'
            )}
          >
            <div className="flex items-center gap-1.5">
              <Clock className="size-3" />
              <span>⏰ {t('home.creatorSince', { timeDiff: biliTimeDiff })}</span>
            </div>
            <div className="absolute bottom-0 left-1/2 size-2 -translate-x-1/2 translate-y-1/2 rotate-45 bg-gradient-to-r from-primary to-info" />
          </div>
        )}
      </div>

      <div className="flex min-w-0 flex-1 flex-col gap-1.5 overflow-hidden">
        <p
          className={cn(
            'font-semibold text-sm',
            'text-foreground',
            'group-hover:text-primary',
            'transition-colors duration-200',
            'truncate'
          )}
        >
          {creator.name}
        </p>
        
        <p
          className={cn(
            'text-xs leading-relaxed',
            'text-muted-foreground',
            'line-clamp-2'
          )}
        >
          {creator.description}
        </p>
      </div>
    </div>
  )
}

export default CreatorCard
