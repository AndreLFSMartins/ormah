/**
 * Seed-once policy for the space filter (the set of spaces shown un-dimmed in
 * the active view, and checked in the FilterDrawer).
 *
 * On the first load that uses space filtering, seed every space plus "" (the
 * no-space bucket) so the drawer checkboxes start all-checked. On later loads —
 * notably exiting a space drill back to the active view — keep the current set
 * so the user's manual deselections survive the round-trip instead of being
 * silently re-checked.
 */
export function nextSpaceFilter(
  current: Set<string>,
  spaceList: string[],
  seeded: boolean,
): Set<string> {
  if (seeded) return current;
  return new Set<string>([...spaceList, ""]);
}
