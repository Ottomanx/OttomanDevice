import { InventoryPagination } from './InventoryPagination'
import { InventoryTable } from './InventoryTable'
import { InventoryToolbar } from './InventoryToolbar'
import { useInventory } from '../hooks/useInventory'

export function InventoryPage() {
  const {
    pageResult,
    groups,
    tags,
    search,
    filters,
    sort,
    pageSize,
    error,
    isLoading,
    lastUpdated,
    setSearch,
    setFilters,
    setSort,
    setPage,
    setPageSize,
    assignGroup,
    assignTags,
    createGroup,
  } = useInventory()

  return (
    <section>
      <header className="mb-6 border-b border-slate-800 pb-6">
        <p className="text-sm font-semibold uppercase tracking-[0.2em] text-indigo-400">OttomanDevice</p>
        <h1 className="mt-2 text-3xl font-bold tracking-tight text-white sm:text-4xl">Device Inventory</h1>
        <p className="mt-3 max-w-3xl text-sm leading-relaxed text-slate-400 sm:text-base">
          Enterprise fleet inventory with search, filters, sorting, pagination, and group/tag assignment.
          Data refreshes every 5 seconds.
        </p>
        <p className="mt-2 text-xs text-slate-500">
          Last updated: {lastUpdated ? lastUpdated.toLocaleTimeString() : '—'}
        </p>
      </header>

      {error && (
        <div className="mb-6 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
          Failed to load inventory: {error}
        </div>
      )}

      <InventoryToolbar
        search={search}
        filters={filters}
        sort={sort}
        pageSize={pageSize}
        groups={groups}
        tags={tags}
        totalItems={pageResult.totalItems}
        onSearchChange={setSearch}
        onFiltersChange={setFilters}
        onSortChange={setSort}
        onPageSizeChange={setPageSize}
      />

      <InventoryTable
        devices={pageResult.items}
        groups={groups}
        isLoading={isLoading}
        onAssignGroup={assignGroup}
        onAssignTags={assignTags}
        onCreateGroup={createGroup}
      />

      <InventoryPagination
        page={pageResult.page}
        totalPages={pageResult.totalPages}
        totalItems={pageResult.totalItems}
        pageSize={pageResult.pageSize}
        onPageChange={setPage}
      />
    </section>
  )
}
