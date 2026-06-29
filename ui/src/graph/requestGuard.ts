export interface RequestGuard {
  begin(): number;
  isLatest(token: number): boolean;
}

export function createRequestGuard(): RequestGuard {
  let latest = 0;
  return {
    begin() {
      latest += 1;
      return latest;
    },
    isLatest(token) {
      return token === latest;
    },
  };
}
