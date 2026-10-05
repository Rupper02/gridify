/** Latest-wins for overlapping loads of the same thing: a slower, older response must never overwrite a
 * newer one (a diff asked mid-run landing after the one asked when the run finished). `begin(key)` starts a
 * load and returns `isLatest()`, true only while no newer load of that key has begun. */
export function latestWins(): (key: string) => () => boolean {
  const seq = new Map<string, number>();
  return (key) => {
    const n = (seq.get(key) ?? 0) + 1;
    seq.set(key, n);
    return () => seq.get(key) === n;
  };
}
