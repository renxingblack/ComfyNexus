/**
 * 工作流管理页面
 */

import { useState, useCallback, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { Upload, Search, Loader2, FolderOpen, CheckSquare, FolderSync, Cog } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui'
import { Input } from '@/components/ui/Input'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { WorkflowSidebar, WorkflowDetailDialog, WorkflowDragLayer, WorkflowSelectionBox, WorkflowBatchToolbar, WorkflowGrid, WorkflowFolderManageDialog, WorkflowSettingsModal } from '@/components/workflow'
import { DragProvider, useDragContext } from '@/components/workflow/WorkflowDragContext'
import { useWorkflowStore } from '@/stores/useWorkflowStore'
import { useEnvStore } from '@/stores/useEnvStore'
import { useProcessStore } from '@/stores/useProcessStore'
import { useNavigate } from 'react-router-dom'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import { workflowApi } from '@/api/workflow'
import { toast } from '@/utils/toast'
import { loadNodeTypeMap, loadLocalNodeMap } from '@/utils/workflowParser'
import { EnvRequiredGuide } from '@/components/common/EnvRequiredGuide'
import type { Workflow, WorkflowInfoUpdate } from '@/types/workflow'
import type { WorkflowGridRef } from '@/components/workflow/WorkflowGrid'

function WorkflowManagePageInner() {
  const { t } = useTranslation()
  const currentEnvId = useEnvStore(state => state.currentEnvId)
  const {
    isLoading,
    getFilteredWorkflows,
    refreshWorkflows,
    deleteWorkflow,
    toggleFavorite,
    updateWorkflowInfo,
    addWorkflow,
    selectedWorkflowIds,
    isBatchMode,
    toggleWorkflowSelection,
    clearSelection,
    batchToggleFavorite,
    batchDeleteWorkflows,
    setBatchMode,
    folders,
    addFolder,
    updateFolder,
    deleteFolder,
    filterTags,
    activeFilterTag,
    setActiveFilterTag
  } = useWorkflowStore()

  const { dropTargetId } = useDragContext()

  const [showDetailDialog, setShowDetailDialog] = useState(false)
  const [detailWorkflow, setDetailWorkflow] = useState<Workflow | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [isImporting, setIsImporting] = useState(false)
  
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false)
  const [workflowToDelete, setWorkflowToDelete] = useState<Workflow | null>(null)
  const [batchDeleteConfirmOpen, setBatchDeleteConfirmOpen] = useState(false)
  const [folderManageOpen, setFolderManageOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  
  const [isSelecting, setIsSelecting] = useState(false)
  const [selectionStart, setSelectionStart] = useState<{ x: number; y: number } | null>(null)
  const [selectionEnd, setSelectionEnd] = useState<{ x: number; y: number } | null>(null)
  
  const gridRef = useRef<WorkflowGridRef>(null)
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const selectionStartRef = useRef<{ x: number; y: number } | null>(null)
  const isSelectingRef = useRef(false)

  useEffect(() => {
    if (currentEnvId) {
      refreshWorkflows()
      // 预加载节点映射表（强制检查是否需要重新扫描）
      loadNodeTypeMap().then(() => {
        loadLocalNodeMap(true).catch(() => {})
      }).catch(() => {})
    }
  }, [currentEnvId, refreshWorkflows])

  const filteredWorkflows = getFilteredWorkflows().filter(w =>
    searchQuery === '' ||
    w?.name?.toLowerCase().includes(searchQuery.toLowerCase()) ||
    w?.description?.toLowerCase().includes(searchQuery.toLowerCase()) ||
    (Array.isArray(w?.tags) && w.tags.some(tag => tag?.toLowerCase().includes(searchQuery.toLowerCase())))
  )

  const handleShowDetail = useCallback((workflow: Workflow) => {
    setDetailWorkflow(workflow)
    setShowDetailDialog(true)
  }, [])

  const handleExport = useCallback(async (workflow: Workflow) => {
    const content = await workflowApi.exportWorkflow(workflow.id)
    if (content) {
      const blob = new Blob([content], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${workflow.name}.json`
      a.click()
      URL.revokeObjectURL(url)
      toast.success(t('workflow.toast.exportSuccess'))
    } else {
      toast.error(t('workflow.toast.exportFailed'))
    }
  }, [t])

  // ---- 打开工作流：在检测到的平台（工作台/浏览器）打开 ComfyUI 并加载该工作流 ----
  // 工作台：把工作流 JSON 经桥接插件 postMessage 给 ComfyUI（app.loadGraphData）加载，
  //         兼容前端 1.55.x（无 ?template=）。浏览器：打开 ComfyUI（工作流已暂存到 Open 菜单）。
  const navigate = useNavigate()
  const [openChoiceWorkflow, setOpenChoiceWorkflow] = useState<Workflow | null>(null)

  const getWorkflowJson = useCallback(async (workflow: Workflow): Promise<string | null> => {
    try {
      const content = await workflowApi.exportWorkflow(workflow.id)
      return content || null
    } catch {
      return null
    }
  }, [])

  const doOpenWorkspace = useCallback(async (workflow: Workflow) => {
    const json = await getWorkflowJson(workflow)
    if (!json) {
      toast.error(t('workflow.open.stageFailed'))
      return
    }
    const ps = useProcessStore.getState()
    ps.setWorkspaceLoadWorkflowJson(json)
    ps.setWorkspaceLoadWorkflowName(workflow.name)
    ps.setShowWorkspaceIframe(true)
    navigate('/workspace')
  }, [getWorkflowJson, navigate, t])

  const doOpenBrowser = useCallback(async (workflow: Workflow) => {
    const url = useProcessStore.getState().comfyUIStatus?.url
    if (!url) {
      toast.error(t('workflow.open.noUrl'))
      return
    }
    // 暂存到 ComfyUI 工作流目录，便于在浏览器 ComfyUI 的 Open 菜单找到该工作流
    try {
      const api = (window as any).pywebview?.api
      await api?.stage_workflow_for_comfyui?.(workflow.id)
    } catch { /* 忽略：暂存失败不影响打开 ComfyUI */ }
    try {
      const api = (window as any).pywebview?.api
      if (api?.open_url) {
        await api.open_url(url)
      } else {
        window.open(url, '_blank', 'noopener,noreferrer')
      }
    } catch {
      window.open(url, '_blank', 'noopener,noreferrer')
    }
    toast.success(t('workflow.open.browserOpened', { name: workflow.name }))
  }, [t])

  const handleOpenWorkflow = useCallback(async (workflow: Workflow) => {
    const ps = useProcessStore.getState()
    try { await ps.loadComfyUIStatus() } catch { /* 忽略 */ }
    const st = useProcessStore.getState().comfyUIStatus
    const running = !!(st && (st.isRunning || st.portAvailable))
    if (!running) {
      // 未检测到运行中的 ComfyUI：弹窗让用户选择打开方式
      setOpenChoiceWorkflow(workflow)
      return
    }
    // 已运行：一律在工作台加载（iframe 未显示时 doOpenWorkspace 会挂载并自动加载）
    await doOpenWorkspace(workflow)
  }, [doOpenWorkspace])

  const confirmOpenChoice = useCallback(async (mode: 'workspace' | 'browser') => {
    const workflow = openChoiceWorkflow
    setOpenChoiceWorkflow(null)
    if (!workflow) return
    const ps = useProcessStore.getState()
    const st = ps.comfyUIStatus
    const running = !!(st && (st.isRunning || st.portAvailable))
    if (mode === 'workspace') {
      if (running) {
        await doOpenWorkspace(workflow)
      } else {
        // 未运行：先把工作流 JSON 备好，ComfyUI 启动、工作台 iframe 就绪后自动加载
        const json = await getWorkflowJson(workflow)
        if (json) {
          ps.setWorkspaceLoadWorkflowJson(json)
          ps.setWorkspaceLoadWorkflowName(workflow.name)
        }
        ps.setStartedFromWorkspace(true)
        try { await ps.startComfyUI() } catch { /* 由工作台页处理错误提示 */ }
      }
    } else {
      if (running) {
        await doOpenBrowser(workflow)
      } else {
        try { await ps.startComfyUIAndOpenBrowser() } catch { /* 忽略 */ }
      }
    }
  }, [openChoiceWorkflow, doOpenWorkspace, doOpenBrowser, getWorkflowJson])

  const handleImport = useCallback(() => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = '.json'
    input.onchange = async (e) => {
      const file = (e.target as HTMLInputElement).files?.[0]
      if (file) {
        setIsImporting(true)
        const workflow = await workflowApi.importWorkflow(file)
        if (workflow) {
          addWorkflow(workflow)
          toast.success(t('workflow.toast.importSuccess'))
        } else {
          toast.error(t('workflow.toast.importFailed'))
        }
        setIsImporting(false)
      }
    }
    input.click()
  }, [addWorkflow, t])

  const handleDeleteClick = useCallback((workflow: Workflow) => {
    setWorkflowToDelete(workflow)
    setDeleteConfirmOpen(true)
  }, [])

  const confirmDelete = useCallback(async () => {
    if (workflowToDelete) {
      await deleteWorkflow(workflowToDelete.id)
      toast.success(t('workflow.toast.deleteSuccess'))
      setDeleteConfirmOpen(false)
      setWorkflowToDelete(null)
    }
  }, [workflowToDelete, deleteWorkflow, t])

  const handleToggleFavorite = useCallback(async (workflow: Workflow) => {
    await toggleFavorite(workflow.id)
  }, [toggleFavorite])

  const handleSaveInfo = useCallback(async (info: WorkflowInfoUpdate) => {
    if (detailWorkflow) {
      const updated = await updateWorkflowInfo(detailWorkflow.id, info)
      if (updated) {
        // 从 store 中获取最新的完整 workflow 对象
        const latestWorkflow = useWorkflowStore.getState().workflows.find(w => w.id === detailWorkflow.id)
        if (latestWorkflow) {
          setDetailWorkflow(latestWorkflow)
        }
      }
    }
  }, [detailWorkflow, updateWorkflowInfo])

  const getIntersectingCardIds = useCallback((
    start: { x: number; y: number },
    end: { x: number; y: number }
  ): string[] => {
    const selectionRect = {
      left: Math.min(start.x, end.x),
      right: Math.max(start.x, end.x),
      top: Math.min(start.y, end.y),
      bottom: Math.max(start.y, end.y)
    }

    const intersectingIds: string[] = []
    const cardRefs = gridRef.current?.getCardRefs() ?? new Map()

    cardRefs.forEach((cardEl, workflowId) => {
      const cardRect = cardEl.getBoundingClientRect()

      if (
        cardRect.left < selectionRect.right &&
        cardRect.right > selectionRect.left &&
        cardRect.top < selectionRect.bottom &&
        cardRect.bottom > selectionRect.top
      ) {
        intersectingIds.push(workflowId)
      }
    })

    return intersectingIds
  }, [])

  const handleSelectionMouseDown = useCallback((e: React.MouseEvent) => {
    if (e.button !== 0) return
    if ((e.target as HTMLElement).closest('[data-workflow-card]')) return

    const point = { x: e.clientX, y: e.clientY }
    setIsSelecting(true)
    setSelectionStart(point)
    setSelectionEnd(point)
    selectionStartRef.current = point
    isSelectingRef.current = true
  }, [])

  useEffect(() => {
    if (!isSelecting) return

    const handleMouseMove = (e: MouseEvent) => {
      if (!isSelectingRef.current || !selectionStartRef.current) return

      setSelectionEnd({ x: e.clientX, y: e.clientY })

      const intersectingIds = getIntersectingCardIds(selectionStartRef.current, { x: e.clientX, y: e.clientY })
      
      if (intersectingIds.length > 0 && !isBatchMode) {
        setBatchMode(true)
      }
      
      useWorkflowStore.setState(state => {
        const newIds = new Set(state.selectedWorkflowIds)
        intersectingIds.forEach(id => newIds.add(id))
        return { selectedWorkflowIds: Array.from(newIds) }
      })
    }

    const handleMouseUp = () => {
      setIsSelecting(false)
      setSelectionStart(null)
      setSelectionEnd(null)
      isSelectingRef.current = false
      selectionStartRef.current = null
    }

    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)

    return () => {
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
    }
  }, [isSelecting, getIntersectingCardIds, isBatchMode, setBatchMode])

  useEffect(() => {
    if (!isSelecting) return

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setIsSelecting(false)
        setSelectionStart(null)
        setSelectionEnd(null)
        isSelectingRef.current = false
        selectionStartRef.current = null
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [isSelecting])

  const handleBatchFavorite = useCallback(async () => {
    if (selectedWorkflowIds.length === 0) return
    const success = await batchToggleFavorite(selectedWorkflowIds)
    if (success) {
      toast.success(t('workflow.toast.favoriteSuccess', { count: selectedWorkflowIds.length }))
    } else {
      toast.error(t('workflow.toast.favoriteFailed'))
    }
  }, [selectedWorkflowIds, batchToggleFavorite, t])

  const handleBatchDeleteClick = useCallback(() => {
    setBatchDeleteConfirmOpen(true)
  }, [])

  const handleBatchDeleteConfirm = useCallback(async () => {
    if (selectedWorkflowIds.length === 0) return
    const success = await batchDeleteWorkflows(selectedWorkflowIds)
    if (success) {
      toast.success(t('workflow.toast.batchDeleteSuccess', { count: selectedWorkflowIds.length }))
    } else {
      toast.error(t('workflow.toast.deleteFailed'))
    }
    setBatchDeleteConfirmOpen(false)
  }, [selectedWorkflowIds, batchDeleteWorkflows, t])

  return (
    <div className="flex h-full flex-col bg-background text-foreground">
      <header className="shrink-0 border-b border-border-subtle bg-surface p-4">
        <div className="flex items-center justify-between gap-4">
          <div className="relative max-w-md flex-1">
            <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder={t('workflow.searchPlaceholder')}
              className="w-full border border-border-subtle bg-surface-active py-1.5 pl-9 pr-3 text-sm text-foreground transition-colors placeholder:text-muted-foreground focus:border-primary"
            />
          </div>
          <div className="flex items-center gap-3">
            <Button
              variant={isBatchMode ? 'default' : 'outline'}
              size="sm"
              onClick={() => setBatchMode(!isBatchMode)}
              className={cn(
                isBatchMode && 'bg-success/15 text-success border-success hover:bg-success/20'
              )}
            >
              <CheckSquare className="size-4" />
              {isBatchMode ? t('workflow.batch.done') : t('workflow.batch.mode')}
            </Button>
            
            <Button
              onClick={handleImport}
              disabled={isImporting}
              className="gap-1.5 border border-primary/30 bg-primary/20 text-primary hover:bg-primary/30"
            >
              {isImporting ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Upload className="size-4" />
              )}
              {isImporting ? t('workflow.importing') : t('workflow.import')}
            </Button>

            <Button
              variant="ghost"
              size="sm"
              onClick={() => setSettingsOpen(true)}
              className="text-muted-foreground hover:text-foreground"
            >
              <Cog className="size-4" />
            </Button>
          </div>
        </div>

        {filterTags.length > 0 && (
          <div className="mt-3 flex items-center gap-2">
            <span className="text-xs text-muted-foreground">{t('workflow.quickFilter')}:</span>
            <div className="flex gap-2">
              {filterTags.map((tag) => (
                <Button
                  key={tag.id}
                  variant="ghost"
                  size="sm"
                  onClick={() => setActiveFilterTag(tag.id)}
                  className={cn(
                    'h-auto rounded-full px-3 py-1 text-xs',
                    activeFilterTag === tag.id
                      ? 'bg-primary/15 text-primary hover:bg-primary/20'
                      : 'bg-surface-active text-muted-foreground hover:text-foreground'
                  )}
                >
                  {tag.name}
                </Button>
              ))}
            </div>
          </div>
        )}
      </header>

      <main className="flex flex-1 overflow-hidden">
        <WorkflowSidebar className="z-10" dropTargetId={dropTargetId} onOpenFolderManage={() => setFolderManageOpen(true)} />

        <div 
          ref={scrollContainerRef}
          className="flex-1 overflow-y-auto p-6"
          onMouseDown={handleSelectionMouseDown}
        >
          {isLoading ? (
            <div className="flex h-64 items-center justify-center">
              <Loader2 className="size-8 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <>
              <WorkflowGrid
                ref={gridRef}
                workflows={filteredWorkflows}
                selectedWorkflowIds={selectedWorkflowIds}
                isBatchMode={isBatchMode}
                onSelectWorkflow={toggleWorkflowSelection}
                onAnalyzeWorkflow={handleShowDetail}
                onOpenWorkflow={handleOpenWorkflow}
                onExportWorkflow={handleExport}
                onDeleteWorkflow={handleDeleteClick}
                onToggleFavorite={handleToggleFavorite}
                onPreviewChange={refreshWorkflows}
              />

              {filteredWorkflows.length === 0 && (
                <div className="flex h-64 flex-col items-center justify-center text-muted-foreground">
                  <FolderOpen className="mb-4 size-12" />
                  <p>{searchQuery ? t('workflow.noResults') : t('workflow.empty')}</p>
                </div>
              )}
            </>
          )}
        </div>
      </main>

      <WorkflowDetailDialog
        open={showDetailDialog}
        onOpenChange={setShowDetailDialog}
        name={detailWorkflow?.name || ''}
        description={detailWorkflow?.description || ''}
        tags={detailWorkflow?.tags}
        data={detailWorkflow?.rawData || null}
        onSaveInfo={handleSaveInfo}
      />

      <WorkflowDragLayer getCardRefs={() => gridRef.current?.getCardRefs() ?? new Map()} />

      {isSelecting && selectionStart && selectionEnd && (
        <WorkflowSelectionBox
          startPoint={selectionStart}
          endPoint={selectionEnd}
        />
      )}

      <WorkflowBatchToolbar
        selectedCount={selectedWorkflowIds.length}
        totalCount={filteredWorkflows.length}
        onClearSelection={clearSelection}
        onBatchFavorite={handleBatchFavorite}
        onBatchDelete={handleBatchDeleteClick}
      />

      <AlertDialog open={deleteConfirmOpen} onOpenChange={setDeleteConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('workflow.deleteTitle')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('workflow.deleteConfirm', { name: workflowToDelete?.name || '' })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={confirmDelete}>{t('common.confirm')}</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={batchDeleteConfirmOpen} onOpenChange={setBatchDeleteConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('workflow.batch.deleteTitle')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('workflow.batch.deleteConfirm', { count: selectedWorkflowIds.length })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={handleBatchDeleteConfirm}>{t('common.confirm')}</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <WorkflowFolderManageDialog
        open={folderManageOpen}
        onOpenChange={setFolderManageOpen}
        folders={folders}
        onAddFolder={addFolder}
        onUpdateFolder={updateFolder}
        onDeleteFolder={deleteFolder}
      />

      <WorkflowSettingsModal
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
      />

      {/* 打开工作流：未检测到运行中的 ComfyUI 时，选择打开方式 */}
      <Dialog
        open={!!openChoiceWorkflow}
        onOpenChange={(open) => { if (!open) setOpenChoiceWorkflow(null) }}
      >
        <DialogContent className="sm:max-w-[420px]">
          <DialogHeader>
            <DialogTitle>{t('workflow.open.title')}</DialogTitle>
            <DialogDescription>{t('workflow.open.notRunning')}</DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2 sm:gap-2">
            <Button variant="outline" onClick={() => confirmOpenChoice('browser')}>
              {t('workflow.open.browser')}
            </Button>
            <Button onClick={() => confirmOpenChoice('workspace')}>
              {t('workflow.open.workspace')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function WorkflowManagePageContent() {
  const currentEnvId = useEnvStore(state => state.currentEnvId)
  const environments = useEnvStore(state => state.environments)
  const noEnvironment = environments.length === 0 || !currentEnvId

  if (noEnvironment) {
    return (
      <EnvRequiredGuide 
        icon={<FolderSync className="size-24 text-muted-foreground" />}
      />
    )
  }

  return <WorkflowManagePageInner />
}

export default function WorkflowManagePage() {
  const { t } = useTranslation()
  
  const handleDropToFolder = useCallback(async (folderId: string, workflowIds: string[]) => {
    const { batchMoveToFolder, batchToggleFavorite } = useWorkflowStore.getState()
    const count = workflowIds.length
    
    if (folderId === 'favorites') {
      const success = await batchToggleFavorite(workflowIds)
      if (success) {
        toast.success(t('workflow.toast.favoriteSuccess', { count }))
      }
      return
    }
    
    const success = await batchMoveToFolder(workflowIds, folderId)
    if (success) {
      toast.success(t('workflow.toast.moveSuccess', { count }))
    }
  }, [t])

  return (
    <DragProvider onDrop={handleDropToFolder}>
      <WorkflowManagePageContent />
    </DragProvider>
  )
}
