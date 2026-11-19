type Save = { error: Error | null; isPending: boolean; isSuccess: boolean }

export function SaveStatus({ save, onSkip }: { save: Save; onSkip?: () => void }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <p className="text-xs text-muted" role="status">
        {save.error ? save.error.message : save.isPending ? 'Saving…' : save.isSuccess ? 'Saved' : ''}
      </p>
      {onSkip && (
        <button type="button" onClick={onSkip} className="text-xs text-muted underline hover:text-secondary">
          Not this one
        </button>
      )}
    </div>
  )
}
