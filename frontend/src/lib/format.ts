export function timeAgo(iso: string): string {
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000;
  if (seconds < 60) return "just now";
  const units: [number, string][] = [
    [60, "minute"],
    [3600, "hour"],
    [86400, "day"],
    [2592000, "month"],
  ];
  let [size, label] = units[0];
  for (const unit of units) if (seconds >= unit[0]) [size, label] = unit;
  const n = Math.floor(seconds / size);
  return `${n} ${label}${n === 1 ? "" : "s"} ago`;
}
