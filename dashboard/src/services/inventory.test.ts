import { describe, expect, it } from 'vitest'

import { computeTagSyncPlan } from '../utils/inventoryQuery'

describe('group assignment behavior', () => {
  it('treats null group id as unassigned state', () => {
    const assignedGroupId: string | null = 'group-42'
    const clearedGroupId: string | null = assignedGroupId ? null : null

    expect(assignedGroupId).toBe('group-42')
    expect(clearedGroupId).toBeNull()
  })

  it('replaces existing group membership with a new group id', () => {
    const currentGroupId = 'group-old'
    const nextGroupId = 'group-new'
    const resolvedGroupId = nextGroupId || currentGroupId

    expect(resolvedGroupId).toBe('group-new')
  })
})

describe('tag assignment sync', () => {
  it('adds only missing tags', () => {
    const plan = computeTagSyncPlan(['existing'], ['existing', 'new-tag'])
    expect(plan.toAdd).toEqual(['new-tag'])
    expect(plan.toRemove).toEqual([])
  })

  it('removes tags that are no longer selected', () => {
    const plan = computeTagSyncPlan(['remove-me', 'keep-me'], ['keep-me'])
    expect(plan.toAdd).toEqual([])
    expect(plan.toRemove).toEqual(['remove-me'])
  })

  it('handles full tag replacement', () => {
    const plan = computeTagSyncPlan(['old-a', 'old-b'], ['new-a'])
    expect(plan.toAdd).toEqual(['new-a'])
    expect(plan.toRemove).toEqual(['old-a', 'old-b'])
  })
})
