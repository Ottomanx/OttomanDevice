import type { DeviceGroup, InventoryFilters, InventorySort, InventorySortField } from '../types/inventory'

interface InventoryToolbarProps {
  search: string
  filters: InventoryFilters
  sort: InventorySort
  pageSize: number
  groups: DeviceGroup[]
  tags: string[]
  totalItems: number
  onSearchChange: (value: string) => void
  onFiltersChange: (value: InventoryFilters) => void
  onSortChange: (value: InventorySort) => void
  onPageSizeChange: (value: number) => void
}

const sortFields: { value: InventorySortField; label: string }[] = [
  { value: 'name', label: 'Device name' },
  { value: 'status', label: 'Status' },
  { value: 'last_seen', label: 'Last seen' },
  { value: 'firmware', label: 'Firmware' },
  { value: 'os', label: 'OS' },
  { value: 'cpu', label: 'CPU' },
  { value: 'ram', label: 'RAM' },
  { value: 'ip', label: 'IP address' },
  { value: 'group', label: 'Group' },
]

const pageSizeOptions = [10, 25, 50]

export function InventoryToolbar({
  search,
  filters,
  sort,
  pageSize,
  groups,
  tags,
  totalItems,
  onSearchChange,
  onFiltersChange,
  onSortChange,
  onPageSizeChange,
}: InventoryToolbarProps) {
  return (
    <section className="mb-6 space-y-4 rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h2 className="text-lg font-semibold text-white">Fleet inventory</h2>
          <p className="text-sm text-slate-400">{totalItems} devices match current filters</p>
        </div>
        <label className="flex min-w-[240px] flex-col gap-1 text-xs uppercase tracking-wide text-slate-500">
          Search
          <input
            type="search"
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder="Name, IP, OS, tags, group…"
            className="rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm normal-case text-white outline-none focus:border-indigo-400"
          />
        </label>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-5">
        <FilterSelect
          label="Status"
          value={filters.status}
          onChange={(value) => onFiltersChange({ ...filters, status: value as InventoryFilters['status'] })}
          options={[
            { value: 'all', label: 'All statuses' },
            { value: 'online', label: 'Online' },
            { value: 'offline', label: 'Offline' },
            { value: 'unknown', label: 'Unknown' },
          ]}
        />
        <FilterSelect
          label="Group"
          value={filters.groupId}
          onChange={(value) => onFiltersChange({ ...filters, groupId: value })}
          options={[
            { value: 'all', label: 'All groups' },
            ...groups.map((group) => ({ value: group.id, label: group.name })),
          ]}
        />
        <FilterSelect
          label="Tag"
          value={filters.tag}
          onChange={(value) => onFiltersChange({ ...filters, tag: value })}
          options={[
            { value: 'all', label: 'All tags' },
            ...tags.map((tag) => ({ value: tag, label: tag })),
          ]}
        />
        <label className="flex flex-col gap-1 text-xs uppercase tracking-wide text-slate-500">
          Sort by
          <div className="flex gap-2">
            <select
              value={sort.field}
              onChange={(event) =>
                onSortChange({ ...sort, field: event.target.value as InventorySortField })
              }
              className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm normal-case text-white outline-none focus:border-indigo-400"
            >
              {sortFields.map((field) => (
                <option key={field.value} value={field.value}>
                  {field.label}
                </option>
              ))}
            </select>
            <select
              value={sort.direction}
              onChange={(event) =>
                onSortChange({ ...sort, direction: event.target.value as InventorySort['direction'] })
              }
              className="rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm normal-case text-white outline-none focus:border-indigo-400"
            >
              <option value="asc">Asc</option>
              <option value="desc">Desc</option>
            </select>
          </div>
        </label>
        <FilterSelect
          label="Page size"
          value={String(pageSize)}
          onChange={(value) => onPageSizeChange(Number(value))}
          options={pageSizeOptions.map((size) => ({ value: String(size), label: `${size} / page` }))}
        />
      </div>
    </section>
  )
}

interface FilterSelectProps {
  label: string
  value: string
  onChange: (value: string) => void
  options: { value: string; label: string }[]
}

function FilterSelect({ label, value, onChange, options }: FilterSelectProps) {
  return (
    <label className="flex flex-col gap-1 text-xs uppercase tracking-wide text-slate-500">
      {label}
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm normal-case text-white outline-none focus:border-indigo-400"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  )
}
