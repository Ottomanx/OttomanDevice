interface InventoryPaginationProps {
  page: number
  totalPages: number
  totalItems: number
  pageSize: number
  onPageChange: (page: number) => void
}

export function InventoryPagination({
  page,
  totalPages,
  totalItems,
  pageSize,
  onPageChange,
}: InventoryPaginationProps) {
  const start = totalItems === 0 ? 0 : (page - 1) * pageSize + 1
  const end = Math.min(page * pageSize, totalItems)

  return (
    <div className="mt-4 flex flex-col gap-3 rounded-2xl border border-slate-800 bg-slate-900/70 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
      <p className="text-sm text-slate-400">
        Showing {start}-{end} of {totalItems}
      </p>
      <div className="flex items-center gap-2">
        <PaginationButton label="Previous" disabled={page <= 1} onClick={() => onPageChange(page - 1)} />
        <span className="min-w-[88px] text-center text-sm text-slate-300">
          Page {page} / {totalPages}
        </span>
        <PaginationButton
          label="Next"
          disabled={page >= totalPages}
          onClick={() => onPageChange(page + 1)}
        />
      </div>
    </div>
  )
}

interface PaginationButtonProps {
  label: string
  disabled: boolean
  onClick: () => void
}

function PaginationButton({ label, disabled, onClick }: PaginationButtonProps) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className="rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200 transition enabled:hover:border-indigo-400 enabled:hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
    >
      {label}
    </button>
  )
}
