/**
 * Seed/merge policy for the space filter (the set of spaces shown un-dimmed in
 * the active view, and checked in the FilterDrawer).
 *
 * On the first load that uses space filtering, seed every space plus "" (the
 * no-space bucket) so the drawer checkboxes start all-checked. On later loads —
 * e.g. exiting a space drill, or after the MCP `remember` tool created a memory
 * in a brand-new space mid-session — keep the user's current set so manual
 * deselections survive, but auto-add any space that was never seen before
 * (tracked in `known`). Without that, a freshly created space would land
 * unchecked and its nodes would be silently dimmed off the canvas.
 */
export function nextSpaceFilter(
  current: Set<string>,
  spaceList: string[],
  seeded: boolean,
  known: Set<string>,
): Set<string> {
  if (!seeded) return new Set<string>([...spaceList, ""]);
  const next = new Set(current);
  for (const s of spaceList) {
    if (!known.has(s)) next.add(s); // new space → check it; deselected known spaces stay out
  }
  return next;
}
