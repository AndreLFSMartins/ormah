import type { MemoryNode } from "../types";

export interface SpaceLegendEntry {
  name: string; // display name; "(no space)" for the null/empty group
  val: string; // value passed to drill/focus ("" for the no-space group)
  count: number; // nodes of this space in the loaded payload
}

export function buildSpaceLegend(
  nodes: MemoryNode[],
  allSpaces: string[],
  hasNoSpace = false, // F1: render "(no space)" even at count 0 when the group exists
): SpaceLegendEntry[] {
  const counts = new Map<string, number>();
  for (const s of allSpaces) counts.set(s, 0);
  let noSpace = 0;
  for (const node of nodes) {
    const key = node.space || "";
    if (key === "") {
      noSpace += 1;
      continue;
    }
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  const entries: SpaceLegendEntry[] = Array.from(counts.entries())
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([name, count]) => ({ name, val: name, count }));
  if (noSpace > 0 || hasNoSpace) entries.push({ name: "(no space)", val: "", count: noSpace });
  return entries;
}
