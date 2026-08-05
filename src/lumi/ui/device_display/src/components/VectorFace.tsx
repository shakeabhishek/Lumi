import { motion } from 'motion/react';
import type { FaceState } from '../state';

/**
 * Vector face — single big emoji, animated per state. Same component the
 * Figma export shipped; the previous pygame implementation used Twemoji
 * PNGs but here we just lean on the system emoji font (the kiosk's
 * Chromium has full emoji coverage out of the box).
 *
 * `sleeping` (2026-07-06, presence-driven, IDLE-only) swaps the idle
 * glyph for 😴 and drops the wiggle — no separate Zzz needed here since
 * the sleeping-face emoji already carries it.
 */
export function VectorFace({ state, sleeping = false }: { state: FaceState; sleeping?: boolean }) {
  const glyph = (() => {
    if (sleeping && state === 'idle') return '😴';
    switch (state) {
      case 'idle':   return '😊';
      case 'listen': return '🤗';
      case 'think':  return '🤔';
      case 'speak':  return '😮';
    }
  })();

  const anim = (() => {
    if (sleeping && state === 'idle') return {};
    if (state === 'idle')   return { rotate: [0, -5, 5, -5, 0] };
    if (state === 'think')  return { rotate: [0, 10, -10, 0] };
    if (state === 'speak')  return { scale: [1, 1.12, 0.95, 1.08, 1] };
    return {};
  })();

  const transition = (() => {
    if (state === 'idle')   return { duration: 2, repeat: Infinity, repeatDelay: 1 };
    if (state === 'think')  return { duration: 1.5, repeat: Infinity };
    if (state === 'speak')  return { duration: 0.5, repeat: Infinity };
    return { duration: 0.3 };
  })();

  return (
    <div className="relative w-56 h-56 flex items-center justify-center">
      <motion.div
        className="text-[8rem] select-none leading-none"
        animate={anim}
        transition={transition}
      >
        {glyph}
      </motion.div>
    </div>
  );
}
