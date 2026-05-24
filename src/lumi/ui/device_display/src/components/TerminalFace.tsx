import { motion } from 'motion/react';
import { useEffect, useState } from 'react';
import type { FaceState } from '../state';

/**
 * Terminal face — macOS window chrome (traffic-light dots, monospace
 * green text on dark) wrapping the kawaii bear ʕ♥ᴥ♥ʔ as the kaomoji.
 *
 * Per the user's explicit decision: keep the bear, present it inside
 * a macOS-style terminal. The bear's expression changes per state;
 * the surrounding status lines change too.
 */
export function TerminalFace({ state }: { state: FaceState }) {
  const [cursorOn, setCursorOn] = useState(true);
  useEffect(() => {
    const t = setInterval(() => setCursorOn((v) => !v), 500);
    return () => clearInterval(t);
  }, []);

  const lines = scriptForState(state);

  return (
    <div className="w-[420px] max-w-full bg-zinc-950/95 rounded-xl overflow-hidden shadow-2xl ring-1 ring-emerald-500/30">
      {/* Title bar with traffic-light dots */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-emerald-500/20 bg-zinc-900/70">
        <span className="w-3 h-3 rounded-full bg-rose-500/90" />
        <span className="w-3 h-3 rounded-full bg-amber-400/90" />
        <span className="w-3 h-3 rounded-full bg-emerald-500/90" />
        <span className="text-emerald-300/80 text-[11px] ml-2 font-mono select-none">
          lumi-terminal · v1.0
        </span>
      </div>

      {/* Body */}
      <div className="px-4 py-4 font-mono text-sm leading-relaxed">
        {lines.map((line, i) => (
          <motion.div
            key={`${state}-${i}`}
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: i * 0.08 }}
            className={
              line.startsWith('$') ? 'text-sky-300'
                : line.startsWith('>') ? 'text-emerald-300'
                : 'text-zinc-200'
            }
          >
            {line}
            {i === lines.length - 1 && (
              <span className={cursorOn ? 'opacity-100 ml-1' : 'opacity-0 ml-1'}>█</span>
            )}
          </motion.div>
        ))}

        {state === 'think' && (
          <motion.div
            className="text-amber-300/90 text-xs mt-2"
            animate={{ opacity: [0.4, 1, 0.4] }}
            transition={{ duration: 1.5, repeat: Infinity }}
          >
            ⚡ analyzing…
          </motion.div>
        )}
      </div>
    </div>
  );
}

function scriptForState(state: FaceState): string[] {
  // Bear expressions per state — kawaii bear ʕ•ᴥ•ʔ, with hearts when
  // idle, a coffee-thinking pose when thinking, etc.
  switch (state) {
    case 'idle':
      return [
        '$ lumi --status',
        '> status: IDLE',
        '> mood: content',
        '> ʕ♥ᴥ♥ʔ',
      ];
    case 'listen':
      return [
        '$ lumi --listen',
        '> status: LISTENING',
        '> mic: open',
        '> ʕ◉ᴥ◉ʔ',
      ];
    case 'think':
      return [
        '$ lumi --think',
        '> status: PROCESSING',
        '> [████████░░] 80%',
        '> ʕ •ᴥ• ʔ',
      ];
    case 'speak':
      return [
        '$ lumi --speak',
        '> status: TRANSMITTING',
        '> ♪♫♪ output stream',
        '> ʕ⌐■ᴥ■ʔ',
      ];
  }
}
