import { ArrowRight } from "lucide-react";
import { useEffect, useRef } from "react";
import type { CallEvent } from "../lib/types";

/** A call's timeline: caller and agent turns, with transitions shown inline. */
export default function Transcript({ events, follow = false }: { events: CallEvent[]; follow?: boolean }) {
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (follow) end.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [events.length, follow]);

  return (
    <div className="space-y-2">
      {events.map((e, i) => {
        if (e.type === "transition") {
          const args = Object.entries(e.args ?? {});
          return (
            <div key={i} className="rounded-md border border-emerald-200 bg-emerald-50 px-2.5 py-1.5 text-xs">
              <div className="flex items-center gap-1 font-mono text-emerald-800">
                <span>{e.from_node}</span>
                <ArrowRight size={12} />
                <span className="font-semibold">{e.to_node}</span>
                <span className="ml-auto text-emerald-600">{e.function}</span>
              </div>
              {args.length > 0 && (
                <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-2 text-emerald-900">
                  {args.map(([k, v]) => (
                    <div key={k} className="contents">
                      <dt className="font-mono text-emerald-700">{k}</dt>
                      <dd className="truncate">{typeof v === "string" ? v : JSON.stringify(v)}</dd>
                    </div>
                  ))}
                </dl>
              )}
            </div>
          );
        }
        const isAgent = e.type === "agent";
        return (
          <div key={i} className={`flex ${isAgent ? "justify-start" : "justify-end"}`}>
            <div
              className={`max-w-[85%] rounded-2xl px-3 py-1.5 text-sm ${
                isAgent ? "rounded-bl-sm bg-slate-100 text-slate-800" : "rounded-br-sm bg-indigo-600 text-white"
              }`}
            >
              {e.text}
              {isAgent && e.interrupted && <span className="ml-1 text-xs italic text-slate-400">(interrupted)</span>}
            </div>
          </div>
        );
      })}
      <div ref={end} />
    </div>
  );
}
